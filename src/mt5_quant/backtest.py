"""本地回测引擎。"""

from __future__ import annotations

from dataclasses import asdict
import logging
from math import inf

import pandas as pd

from mt5_quant.config import AppConfig
from mt5_quant.guardrails import RiskSnapshot, SafetyGuard
from mt5_quant.models import BacktestTrade, Position
from mt5_quant.news_calendar import build_calendar_client
from mt5_quant.strategy.base import Strategy

LOGGER = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, config: AppConfig, strategy: Strategy) -> None:
        self.config = config
        self.strategy = strategy
        self.guard = SafetyGuard(config.safety)
        self.calendar_client = build_calendar_client(
            config.news_calendar,
            config.safety.timezone,
            config.mt5.path,
        )

    def run(self, data: pd.DataFrame) -> dict[str, object]:
        self._load_dynamic_news_windows(data)
        balance = self.config.backtest.initial_balance
        equity_curve: list[dict[str, object]] = []
        trades: list[BacktestTrade] = []
        position: Position | None = None
        pending_entry: dict[str, object] | None = None
        point = self._infer_point(data)
        spread = self.config.backtest.spread_points * point
        current_day: str | None = None
        day_start_balance = balance
        consecutive_losses = 0
        blocked_entries: dict[str, int] = {}
        peak_balance = balance
        max_drawdown_pct = 0.0
        day_direction: str | None = None

        for timestamp, bar in data.iterrows():
            day_key = self.guard.local_day_key(timestamp)
            if day_key != current_day:
                current_day = day_key
                day_start_balance = balance
                consecutive_losses = 0
                day_direction = None

            if pending_entry is not None and position is None:
                position = Position(
                    ticket=len(trades) + 1,
                    symbol=self.config.trading.symbol,
                    side=pending_entry["side"],
                    volume=float(pending_entry["volume"]),
                    price_open=float(pending_entry["entry_price"]),
                    stop_loss=float(pending_entry["stop_loss"]),
                    take_profit=float(pending_entry["take_profit"]),
                    opened_at=str(pending_entry["entry_time"]),
                )
                pending_entry = None

            if position is not None:
                self._apply_trailing_stop(position, bar)
                exit_price, exit_reason = self._check_exit(position, bar)
                if exit_price is not None:
                    pnl = self._calculate_pnl(position, exit_price)
                    pnl -= self.config.backtest.commission_per_lot * position.volume
                    balance += pnl
                    trades.append(
                        BacktestTrade(
                            symbol=position.symbol,
                            side=position.side,
                            entry_time=position.opened_at,
                            exit_time=str(timestamp),
                            entry_price=position.price_open,
                            exit_price=exit_price,
                            volume=position.volume,
                            pnl=pnl,
                            exit_reason=exit_reason,
                        )
                    )
                    position = None
                    consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0

            window = data.loc[:timestamp]
            signal = self.strategy.generate_signal(window, position)

            if position is not None and signal.action == "close":
                exit_price = float(bar["close"])
                pnl = self._calculate_pnl(position, exit_price)
                pnl -= self.config.backtest.commission_per_lot * position.volume
                balance += pnl
                trades.append(
                    BacktestTrade(
                        symbol=position.symbol,
                        side=position.side,
                        entry_time=position.opened_at,
                        exit_time=str(timestamp),
                        entry_price=position.price_open,
                        exit_price=exit_price,
                        volume=position.volume,
                        pnl=pnl,
                        exit_reason=signal.reason,
                    )
                )
                position = None
                consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0

            if position is None and pending_entry is None and signal.action in {"buy", "sell"}:
                risk = RiskSnapshot(
                    realized_pnl=balance - day_start_balance,
                    day_start_balance=day_start_balance,
                    current_balance=balance,
                    consecutive_losses=consecutive_losses,
                )
                can_open, reason = self.guard.can_open_trade(timestamp, risk)
                if can_open:
                    direction_allowed, direction_reason = self.guard.is_direction_allowed(signal.action, day_direction)
                    if not direction_allowed:
                        blocked_entries[direction_reason] = blocked_entries.get(direction_reason, 0) + 1
                        can_open = False

                if can_open:
                    stop_loss = signal.stop_loss or float(bar["close"])
                    distance = abs(float(bar["close"]) - stop_loss)
                    if distance > 0:
                        risk_amount = balance * self.config.strategy.risk_per_trade
                        volume = risk_amount / (distance * self.config.backtest.contract_size)
                        half_spread = spread / 2.0
                        entry_price = (
                            float(bar["close"]) + half_spread
                            if signal.action == "buy"
                            else float(bar["close"]) - half_spread
                        )
                        pending_entry = {
                            "side": signal.action,
                            "volume": volume,
                            "entry_price": entry_price,
                            "stop_loss": signal.stop_loss,
                            "take_profit": signal.take_profit,
                            "entry_time": str(timestamp),
                        }
                        day_direction = signal.action
                else:
                    blocked_entries[reason] = blocked_entries.get(reason, 0) + 1

            peak_balance = max(peak_balance, balance)
            drawdown_pct = 0.0 if peak_balance <= 0 else (peak_balance - balance) / peak_balance
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
            equity_curve.append({"time": str(timestamp), "balance": balance, "drawdown_pct": drawdown_pct})

        wins = sum(1 for trade in trades if trade.pnl > 0)
        total = len(trades)
        win_rate = (wins / total) if total else 0.0
        net_profit = balance - self.config.backtest.initial_balance
        gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
        gross_loss_value = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
        avg_trade = net_profit / total if total else 0.0
        avg_win = gross_profit / wins if wins else 0.0
        loss_count = total - wins
        avg_loss = -(gross_loss_value / loss_count) if loss_count else 0.0
        profit_factor = gross_profit / gross_loss_value if gross_loss_value > 0 else (inf if gross_profit > 0 else 0.0)

        return {
            "final_balance": balance,
            "net_profit": net_profit,
            "total_trades": total,
            "win_rate": win_rate,
            "gross_profit": gross_profit,
            "gross_loss": -gross_loss_value,
            "avg_trade": avg_trade,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "blocked_entries": blocked_entries,
            "trades": [asdict(trade) for trade in trades],
            "equity_curve": equity_curve,
        }

    def _load_dynamic_news_windows(self, data: pd.DataFrame) -> None:
        """回测前按历史区间一次性生成新闻黑窗。"""
        if self.calendar_client is None or data.empty:
            return
        start = data.index.min()
        end = data.index.max()
        try:
            windows = self.calendar_client.fetch_windows(start, end)
            self.guard.set_dynamic_news_windows([(item.start, item.end) for item in windows])
            LOGGER.info("Loaded %s automatic news blackout windows for backtest.", len(windows))
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to load automatic news windows for backtest: %s", exc)

    def _check_exit(self, position: Position, bar: pd.Series) -> tuple[float | None, str]:
        high = float(bar["high"])
        low = float(bar["low"])
        stop_loss = position.stop_loss
        take_profit = position.take_profit

        if position.side == "buy":
            if stop_loss is not None and low <= stop_loss:
                return float(stop_loss), "stop_loss"
            if take_profit is not None and high >= take_profit:
                return float(take_profit), "take_profit"
        else:
            if stop_loss is not None and high >= stop_loss:
                return float(stop_loss), "stop_loss"
            if take_profit is not None and low <= take_profit:
                return float(take_profit), "take_profit"

        return None, ""

    def _calculate_pnl(self, position: Position, exit_price: float) -> float:
        multiplier = self.config.backtest.contract_size
        if position.side == "buy":
            return (exit_price - position.price_open) * position.volume * multiplier
        return (position.price_open - exit_price) * position.volume * multiplier

    def _apply_trailing_stop(self, position: Position, bar: pd.Series) -> None:
        if not self.config.safety.trailing_stop_enabled:
            return

        current_price = float(bar["close"])
        entry_price = position.price_open

        if position.side == "buy":
            move_pct = (current_price - entry_price) / entry_price
            if move_pct < self.config.safety.trailing_trigger_pct:
                return
            candidate_sl = current_price * (1 - self.config.safety.trailing_distance_pct)
            current_sl = position.stop_loss or 0.0
            if candidate_sl > current_sl:
                position.stop_loss = candidate_sl
            return

        move_pct = (entry_price - current_price) / entry_price
        if move_pct < self.config.safety.trailing_trigger_pct:
            return
        candidate_sl = current_price * (1 + self.config.safety.trailing_distance_pct)
        current_sl = position.stop_loss or float("inf")
        if candidate_sl < current_sl:
            position.stop_loss = candidate_sl

    @staticmethod
    def _infer_point(data: pd.DataFrame) -> float:
        decimals = 0
        sample = data.head(min(len(data), 200))
        for column in ("open", "high", "low", "close"):
            for value in sample[column]:
                text = f"{float(value):.10f}".rstrip("0")
                if "." in text:
                    decimals = max(decimals, len(text.split(".")[1]))
        return 10 ** (-decimals) if decimals > 0 else 1.0
