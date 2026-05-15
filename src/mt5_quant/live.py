from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from mt5_quant.config import AppConfig
from mt5_quant.data import Mt5Gateway
from mt5_quant.execution import ExecutionEngine
from mt5_quant.guardrails import RiskSnapshot, SafetyGuard
from mt5_quant.models import Position
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

                positions = self.gateway.get_positions()
                active_position: Position | None = positions[0] if positions else None
                signal = self.strategy.generate_signal(closed, active_position)
                self._handle_signal(signal, active_position)
                last_processed_bar = latest_bar_time
                time.sleep(self.config.trading.poll_interval_seconds)
        finally:
            self.gateway.shutdown()

    def _handle_signal(self, signal, active_position: Position | None) -> None:
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
        can_open, reason = self.guard.can_open_trade(datetime.now(timezone.utc), risk)
        if not can_open:
            LOGGER.info(
                "New trade blocked: %s | daily_loss_pct=%.4f consecutive_losses=%s",
                reason,
                risk.daily_loss_pct,
                risk.consecutive_losses,
            )
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
        exit_deals: list[dict[str, float | int]] = []
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
