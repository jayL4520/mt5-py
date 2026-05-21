"""实盘轮询与风控执行引擎。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway
from mt5_quant.execution import ExecutionEngine
from mt5_quant.guardrails import RiskSnapshot, SafetyGuard
from mt5_quant.models import Position
from mt5_quant.news_calendar import build_calendar_client
from mt5_quant.risk import RiskManager
from mt5_quant.risk_overrides import get_cleared_consecutive_losses, is_blocked_reason_cleared
from mt5_quant.runtime_events import RuntimeEventWriter, generate_session_id
from mt5_quant.strategy.base import Strategy

LOGGER = logging.getLogger(__name__)

BLOCKED_REASON_LABELS = {
    "outside_trading_window": "不在允许交易时段内",
    "news_blackout_window": "当前处于新闻黑窗",
    "daily_loss_limit_reached": "已触发日内最大亏损限制",
    "consecutive_loss_limit_reached": "连续亏损已超过允许次数",
    "one_direction_per_day": "已触发日内单方向限制",
    "missing_stop_loss": "信号未提供止损，已跳过",
    "zero_volume": "计算出的下单手数为 0，已跳过",
}

SIGNAL_REASON_LABELS = {
    "no_signal": "当前无有效信号",
    "insufficient_bars": "K 线数量不足，指标未准备好",
    "indicator_not_ready": "指标尚未准备好",
}


class LiveTradingEngine:
    """实盘或模拟盘运行主循环。"""

    def __init__(self, config: AppConfig, strategy: Strategy, session_id: str | None = None) -> None:
        self.config = config
        self.session_id = session_id or generate_session_id()
        self.event_writer = RuntimeEventWriter(
            session_id=self.session_id,
            symbol=config.trading.symbol,
            timeframe=config.trading.timeframe,
            strategy=config.strategy.name,
            timezone_name=config.safety.timezone,
        )
        self.gateway = Mt5Gateway(config)
        self.execution = ExecutionEngine(
            config,
            self.gateway,
            event_writer=self.event_writer,
            session_id=self.session_id,
        )
        self.risk = RiskManager(config, self.gateway)
        self.strategy = strategy
        self.guard = SafetyGuard(config.safety)
        self.calendar_client = build_calendar_client(
            config.news_calendar,
            config.safety.timezone,
            config.mt5.path,
        )
        self.news_cache_expires_at = None

    def run(self) -> None:
        """持续轮询最新已收盘 K 线并处理策略信号。"""
        LOGGER.info("[session_id=%s] Live trading loop started.", self.session_id)
        self.gateway.connect()
        last_processed_bar = None
        try:
            while True:
                frame = self.gateway.get_rates()
                if len(frame) < 3:
                    time.sleep(self.config.trading.poll_interval_seconds)
                    continue

                closed = frame.iloc[:-1]
                latest_bar_time = closed.index[-1]
                if latest_bar_time == last_processed_bar:
                    time.sleep(self.config.trading.poll_interval_seconds)
                    continue

                self._refresh_dynamic_news_windows(latest_bar_time)
                positions = self.gateway.get_positions()
                active_position: Position | None = positions[0] if positions else None
                if active_position is not None:
                    self._apply_trailing_stop(active_position, latest_bar_time)
                signal = self.strategy.generate_signal(closed, active_position)
                self._handle_signal(signal, active_position, latest_bar_time)
                last_processed_bar = latest_bar_time
                time.sleep(self.config.trading.poll_interval_seconds)
        except Exception as exc:
            self.event_writer.emit(
                "runtime_error",
                f"运行异常：{exc}",
                extra={"error": str(exc)},
            )
            raise
        finally:
            self.gateway.shutdown()

    def _handle_signal(self, signal, active_position: Position | None, signal_time) -> None:
        """处理策略信号，并把所有阻断原因写成结构化事件。"""
        bar_time = str(signal_time)
        if signal.action == "hold":
            LOGGER.info("[session_id=%s] No action: %s", self.session_id, signal.reason)
            self.event_writer.emit(
                "signal_hold",
                f"策略无动作：{self._describe_signal_reason(signal.reason)}",
                signal_action=signal.action,
                signal_reason=signal.reason,
                bar_time=bar_time,
                position_side=active_position.side if active_position is not None else "",
            )
            return

        if signal.action == "close" and active_position is not None:
            LOGGER.info("[session_id=%s] Closing position because %s", self.session_id, signal.reason)
            self.execution.close_position(active_position, signal_reason=signal.reason, bar_time=bar_time)
            return

        if active_position is not None:
            LOGGER.info("[session_id=%s] Signal %s ignored because a position is already open.", self.session_id, signal.action)
            self.event_writer.emit(
                "signal_ignored",
                "已有持仓，当前信号被忽略",
                signal_action=signal.action,
                signal_reason=signal.reason,
                bar_time=bar_time,
                position_side=active_position.side,
            )
            return

        risk = self._get_risk_snapshot()
        can_open, reason, override_info = self._can_open_trade_with_overrides(signal_time, risk)
        if not can_open:
            LOGGER.info(
                "[session_id=%s] New trade blocked: %s | daily_loss_pct=%.4f consecutive_losses=%s",
                self.session_id,
                reason,
                risk.daily_loss_pct,
                risk.consecutive_losses,
            )
            self._emit_blocked_event(signal, reason, bar_time, risk, override_info)
            return

        day_direction = self._get_day_direction(active_position)
        direction_allowed, direction_reason = self.guard.is_direction_allowed(signal.action, day_direction)
        if not direction_allowed:
            if self._is_blocked_reason_manually_cleared(direction_reason, signal_time, risk):
                LOGGER.info(
                    "[session_id=%s] Manual override skipped block: %s | existing_day_direction=%s",
                    self.session_id,
                    direction_reason,
                    day_direction,
                )
            else:
                LOGGER.info(
                    "[session_id=%s] New trade blocked: %s | existing_day_direction=%s",
                    self.session_id,
                    direction_reason,
                    day_direction,
                )
                self.event_writer.emit(
                    "signal_blocked",
                    f"信号被拦截：{self._describe_blocked_reason(direction_reason)}",
                    signal_action=signal.action,
                    signal_reason=signal.reason,
                    blocked_reason=direction_reason,
                    bar_time=bar_time,
                    extra={
                        "existing_day_direction": day_direction or "",
                        "magic_number": self.config.trading.magic_number,
                    },
                )
                return

        tick = self.gateway.get_tick()
        entry = tick.ask if signal.action == "buy" else tick.bid
        stop_loss = signal.stop_loss
        if stop_loss is None:
            LOGGER.warning("[session_id=%s] Signal %s has no stop loss and will be ignored.", self.session_id, signal.action)
            self.event_writer.emit(
                "signal_blocked",
                f"信号被拦截：{self._describe_blocked_reason('missing_stop_loss')}",
                signal_action=signal.action,
                signal_reason=signal.reason,
                blocked_reason="missing_stop_loss",
                bar_time=bar_time,
                extra={"magic_number": self.config.trading.magic_number},
            )
            return

        volume = self.risk.calculate_volume(side=signal.action, entry=entry, stop_loss=stop_loss)
        if volume <= 0:
            LOGGER.warning("[session_id=%s] Calculated volume is zero; signal skipped.", self.session_id)
            self.event_writer.emit(
                "signal_blocked",
                f"信号被拦截：{self._describe_blocked_reason('zero_volume')}",
                signal_action=signal.action,
                signal_reason=signal.reason,
                blocked_reason="zero_volume",
                bar_time=bar_time,
                extra={
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "magic_number": self.config.trading.magic_number,
                },
            )
            return

        LOGGER.info("[session_id=%s] Opening %s position because %s", self.session_id, signal.action, signal.reason)
        self.event_writer.emit(
            "signal_open_attempt",
            f"准备开仓：{signal.action}",
            signal_action=signal.action,
            signal_reason=signal.reason,
            bar_time=bar_time,
            position_side=signal.action,
            extra={"entry": entry, "volume": volume},
        )
        self.execution.open_market_position(
            side=signal.action,
            volume=volume,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            signal_reason=signal.reason,
            bar_time=bar_time,
        )

    def _can_open_trade_with_overrides(
        self,
        signal_time,
        risk: RiskSnapshot,
    ) -> tuple[bool, str, dict[str, Any]]:
        """按固定顺序检查开仓风控，并跳过已被 GUI 手动解除的本日限制。"""
        skipped: list[str] = []
        checks = [
            ("outside_trading_window", not self.guard.is_trading_time(signal_time)),
            ("news_blackout_window", self.guard.is_news_blackout(signal_time)),
            ("daily_loss_limit_reached", risk.daily_loss_pct >= self.config.safety.max_daily_loss_pct),
            ("consecutive_loss_limit_reached", risk.consecutive_losses > self.config.safety.max_consecutive_losses),
        ]
        for reason, blocked in checks:
            if not blocked:
                continue
            if self._is_blocked_reason_manually_cleared(reason, signal_time, risk):
                skipped.append(reason)
                continue
            return False, reason, {"manually_cleared_blocked_reasons": skipped}
        return True, "ok", {"manually_cleared_blocked_reasons": skipped}

    def _is_blocked_reason_manually_cleared(
        self,
        blocked_reason: str,
        signal_time,
        risk: RiskSnapshot,
    ) -> bool:
        """判断某个风控拦截是否已被 GUI 手动解除。"""
        day_key = self.guard.local_day_key(signal_time)
        if blocked_reason == "consecutive_loss_limit_reached":
            cleared_losses = get_cleared_consecutive_losses(
                symbol=self.config.trading.symbol,
                magic_number=self.config.trading.magic_number,
                day_key=day_key,
            )
            return cleared_losses > 0 and risk.consecutive_losses <= cleared_losses

        return is_blocked_reason_cleared(
            symbol=self.config.trading.symbol,
            magic_number=self.config.trading.magic_number,
            day_key=day_key,
            blocked_reason=blocked_reason,
        )

    def _emit_blocked_event(
        self,
        signal,
        reason: str,
        bar_time: str,
        risk: RiskSnapshot,
        override_info: dict[str, Any],
    ) -> None:
        """统一写入开仓前风控拦截事件。"""
        self.event_writer.emit(
            "signal_blocked",
            f"信号被拦截：{self._describe_blocked_reason(reason)}",
            signal_action=signal.action,
            signal_reason=signal.reason,
            blocked_reason=reason,
            bar_time=bar_time,
            extra={
                "daily_loss_pct": round(risk.daily_loss_pct, 6),
                "consecutive_losses": risk.consecutive_losses,
                "max_consecutive_losses": self.config.safety.max_consecutive_losses,
                "magic_number": self.config.trading.magic_number,
                **override_info,
            },
        )

    def _get_risk_snapshot(self) -> RiskSnapshot:
        now = datetime.now(timezone.utc)
        date_from, date_to = self.guard.current_day_bounds_utc(now)
        deals = self.gateway.get_deals_range(date_from, date_to)
        lib = self.gateway._require_mt5()

        realized_pnl = 0.0
        exit_deals: list[dict[str, float | int | str]] = []
        for deal in deals:
            if int(deal["entry"]) != lib.DEAL_ENTRY_OUT:
                continue
            realized_pnl += float(deal["pnl"])
            exit_deals.append(deal)

        consecutive_losses = 0
        for deal in reversed(exit_deals):
            if float(deal["pnl"]) <= 0:
                consecutive_losses += 1
                continue
            break

        account = self.gateway.get_account_info()
        current_balance = float(account.balance)
        day_start_balance = current_balance - realized_pnl
        return RiskSnapshot(
            realized_pnl=realized_pnl,
            day_start_balance=day_start_balance,
            current_balance=current_balance,
            consecutive_losses=consecutive_losses,
        )

    def _get_day_direction(self, active_position: Position | None) -> str | None:
        if active_position is not None:
            return active_position.side

        now = datetime.now(timezone.utc)
        date_from, date_to = self.guard.current_day_bounds_utc(now)
        deals = self.gateway.get_deals_range(date_from, date_to)
        lib = self.gateway._require_mt5()
        for deal in deals:
            if int(deal["entry"]) == lib.DEAL_ENTRY_IN and str(deal["side"]) in {"buy", "sell"}:
                return str(deal["side"])
        return None

    def _apply_trailing_stop(self, position: Position, bar_time) -> None:
        if not self.config.safety.trailing_stop_enabled:
            return

        tick = self.gateway.get_tick()
        symbol_info = self.gateway.get_symbol_info()
        current_price = tick.bid if position.side == "buy" else tick.ask
        entry_price = position.price_open

        if position.side == "buy":
            move_pct = (current_price - entry_price) / entry_price
            if move_pct < self.config.safety.trailing_trigger_pct:
                return
            candidate_sl = current_price * (1 - self.config.safety.trailing_distance_pct)
            current_sl = position.stop_loss or 0.0
            if candidate_sl <= current_sl:
                return
        else:
            move_pct = (entry_price - current_price) / entry_price
            if move_pct < self.config.safety.trailing_trigger_pct:
                return
            candidate_sl = current_price * (1 + self.config.safety.trailing_distance_pct)
            current_sl = position.stop_loss or float("inf")
            if candidate_sl >= current_sl:
                return

        rounded_sl = round(candidate_sl, symbol_info.digits)
        if position.stop_loss is not None and round(position.stop_loss, symbol_info.digits) == rounded_sl:
            return

        self.execution.update_position_stops(
            position,
            stop_loss=rounded_sl,
            take_profit=position.take_profit,
            bar_time=str(bar_time),
        )

    def _refresh_dynamic_news_windows(self, reference_time) -> None:
        """按缓存周期刷新自动财经日历。"""
        if self.calendar_client is None:
            return

        reference_ts = pd.Timestamp(reference_time)
        if reference_ts.tzinfo is None:
            reference_ts = reference_ts.tz_localize("UTC")
        if self.news_cache_expires_at is not None and reference_ts < self.news_cache_expires_at:
            return

        end_time = reference_ts + pd.Timedelta(days=self.config.news_calendar.lookahead_days)
        try:
            windows = self.calendar_client.fetch_windows(reference_ts, end_time)
            self.guard.set_dynamic_news_windows([(item.start, item.end) for item in windows])
            self.news_cache_expires_at = reference_ts + pd.Timedelta(minutes=self.config.news_calendar.cache_minutes)
            LOGGER.info("[session_id=%s] Loaded %s automatic news blackout windows.", self.session_id, len(windows))
            self.event_writer.emit(
                "news_windows_refreshed",
                f"已刷新自动新闻黑窗，共 {len(windows)} 个窗口",
                bar_time=str(reference_ts),
                extra={"window_count": len(windows)},
                timestamp=reference_ts,
            )
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("[session_id=%s] Failed to refresh automatic news windows: %s", self.session_id, exc)
            self.event_writer.emit(
                "runtime_warning",
                f"刷新自动新闻黑窗失败：{exc}",
                bar_time=str(reference_ts),
                extra={"error": str(exc)},
                timestamp=reference_ts,
            )

    @staticmethod
    def _describe_signal_reason(reason: str) -> str:
        return SIGNAL_REASON_LABELS.get(reason, reason or "未知原因")

    @staticmethod
    def _describe_blocked_reason(reason: str) -> str:
        return BLOCKED_REASON_LABELS.get(reason, reason or "未知拦截原因")
