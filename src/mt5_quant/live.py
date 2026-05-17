"""实盘轮询与风控执行引擎。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway
from mt5_quant.execution import ExecutionEngine
from mt5_quant.guardrails import RiskSnapshot, SafetyGuard
from mt5_quant.models import Position
from mt5_quant.news_calendar import build_calendar_client
from mt5_quant.risk import RiskManager
from mt5_quant.strategy.base import Strategy

LOGGER = logging.getLogger(__name__)


class LiveTradingEngine:
    def __init__(self, config: AppConfig, strategy: Strategy) -> None:
        self.config = config
        self.gateway = Mt5Gateway(config)
        self.execution = ExecutionEngine(config, self.gateway)
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
                    self._apply_trailing_stop(active_position)
                signal = self.strategy.generate_signal(closed, active_position)
                self._handle_signal(signal, active_position, latest_bar_time)
                last_processed_bar = latest_bar_time
                time.sleep(self.config.trading.poll_interval_seconds)
        finally:
            self.gateway.shutdown()

    def _handle_signal(self, signal, active_position: Position | None, signal_time) -> None:
        if signal.action == "hold":
            LOGGER.info("No action: %s", signal.reason)
            return

        if signal.action == "close" and active_position is not None:
            LOGGER.info("Closing position because %s", signal.reason)
            self.execution.close_position(active_position)
            return

        if active_position is not None:
            LOGGER.info("Signal %s ignored because a position is already open.", signal.action)
            return

        risk = self._get_risk_snapshot()
        can_open, reason = self.guard.can_open_trade(signal_time, risk)
        if not can_open:
            LOGGER.info(
                "New trade blocked: %s | daily_loss_pct=%.4f consecutive_losses=%s",
                reason,
                risk.daily_loss_pct,
                risk.consecutive_losses,
            )
            return

        day_direction = self._get_day_direction(active_position)
        direction_allowed, direction_reason = self.guard.is_direction_allowed(signal.action, day_direction)
        if not direction_allowed:
            LOGGER.info("New trade blocked: %s | existing_day_direction=%s", direction_reason, day_direction)
            return

        tick = self.gateway.get_tick()
        entry = tick.ask if signal.action == "buy" else tick.bid
        stop_loss = signal.stop_loss
        if stop_loss is None:
            LOGGER.warning("Signal %s has no stop loss and will be ignored.", signal.action)
            return

        volume = self.risk.calculate_volume(side=signal.action, entry=entry, stop_loss=stop_loss)
        if volume <= 0:
            LOGGER.warning("Calculated volume is zero; signal skipped.")
            return

        LOGGER.info("Opening %s position because %s", signal.action, signal.reason)
        self.execution.open_market_position(
            side=signal.action,
            volume=volume,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
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

    def _apply_trailing_stop(self, position: Position) -> None:
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

        self.execution.update_position_stops(position, stop_loss=rounded_sl, take_profit=position.take_profit)

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
            LOGGER.info("Loaded %s automatic news blackout windows.", len(windows))
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to refresh automatic news windows: %s", exc)
