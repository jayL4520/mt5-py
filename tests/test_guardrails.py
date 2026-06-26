"""单元测试：guardrails — 风控守卫。"""

from __future__ import annotations

import pytest
import pandas as pd

from mt5_quant.config import SafetyConfig
from mt5_quant.guardrails import LossStreakGuardrail, RiskSnapshot, SafetyGuard


# ── RiskSnapshot ─────────────────────────────────────────────────────────

class TestRiskSnapshot:
    def test_daily_loss_pct_with_no_loss(self) -> None:
        risk = RiskSnapshot(realized_pnl=0.0, day_start_balance=100000.0, current_balance=100000.0, consecutive_losses=0)
        assert risk.daily_loss_pct == 0.0

    def test_daily_loss_pct_with_loss(self) -> None:
        risk = RiskSnapshot(realized_pnl=-500.0, day_start_balance=100000.0, current_balance=99500.0, consecutive_losses=2)
        assert risk.daily_loss_pct == pytest.approx(0.005)

    def test_daily_loss_pct_with_zero_balance(self) -> None:
        risk = RiskSnapshot(realized_pnl=0.0, day_start_balance=0.0, current_balance=0.0, consecutive_losses=0)
        assert risk.daily_loss_pct == 0.0

    def test_daily_loss_pct_with_profit(self) -> None:
        risk = RiskSnapshot(realized_pnl=1000.0, day_start_balance=100000.0, current_balance=101000.0, consecutive_losses=0)
        assert risk.daily_loss_pct == 0.0  # profit, not loss

    def test_consecutive_losses_tracked(self) -> None:
        risk = RiskSnapshot(realized_pnl=-200.0, day_start_balance=100000.0, current_balance=99800.0, consecutive_losses=5)
        assert risk.consecutive_losses == 5


# ── SafetyGuard — window parsing ────────────────────────────────────────

class TestWindowParsing:
    def test_parse_simple_window(self) -> None:
        start, end = SafetyGuard._parse_window("14:00-23:00")
        assert start == 14 * 60
        assert end == 23 * 60

    def test_parse_overnight_window(self) -> None:
        start, end = SafetyGuard._parse_window("22:00-06:00")
        assert start == 22 * 60
        assert end == 6 * 60

    def test_parse_all_day_window(self) -> None:
        start, end = SafetyGuard._parse_window("00:00-24:00")
        assert start == 0
        assert end == 24 * 60

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid trading window"):
            SafetyGuard._parse_window("14:00")

    def test_invalid_hour(self) -> None:
        with pytest.raises(ValueError, match="Invalid clock time"):
            SafetyGuard._parse_window("25:00-06:00")

    def test_invalid_minute(self) -> None:
        with pytest.raises(ValueError, match="Invalid clock time"):
            SafetyGuard._parse_window("14:60-16:00")


class TestWindowContains:
    def test_within_simple_window(self) -> None:
        assert SafetyGuard._window_contains(14 * 60, 23 * 60, 15 * 60 + 30) is True

    def test_before_simple_window(self) -> None:
        assert SafetyGuard._window_contains(14 * 60, 23 * 60, 10 * 60) is False

    def test_after_simple_window(self) -> None:
        assert SafetyGuard._window_contains(14 * 60, 23 * 60, 23 * 60 + 1) is False

    def test_within_overnight_window(self) -> None:
        assert SafetyGuard._window_contains(22 * 60, 6 * 60, 2 * 60) is True

    def test_before_overnight_window(self) -> None:
        assert SafetyGuard._window_contains(22 * 60, 6 * 60, 19 * 60) is False

    def test_start_boundary(self) -> None:
        assert SafetyGuard._window_contains(14 * 60, 23 * 60, 14 * 60) is True

    def test_end_boundary_exclusive(self) -> None:
        assert SafetyGuard._window_contains(14 * 60, 23 * 60, 23 * 60) is False

    def test_full_day(self) -> None:
        assert SafetyGuard._window_contains(0, 24 * 60, 0) is True
        assert SafetyGuard._window_contains(0, 24 * 60, 12 * 60) is True
        assert SafetyGuard._window_contains(0, 24 * 60, 23 * 60 + 59) is True

    def test_start_equals_end(self) -> None:
        assert SafetyGuard._window_contains(10 * 60, 10 * 60, 10 * 60) is True
        assert SafetyGuard._window_contains(10 * 60, 10 * 60, 12 * 60) is True


# ── SafetyGuard — trading windows ───────────────────────────────────────

class TestIsTradingTime:
    def test_in_window(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 15:30:00", tz="Asia/Shanghai")
        assert guard.is_trading_time(ts) is True

    def test_outside_window(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 12:00:00", tz="Asia/Shanghai")
        assert guard.is_trading_time(ts) is False

    def test_utc_input_converted_correctly(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        # UTC 06:00 = Shanghai 14:00 — should be in window
        ts = pd.Timestamp("2026-05-20 06:00:00", tz="UTC")
        assert guard.is_trading_time(ts) is True

    def test_no_timezone_input_treated_as_utc(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 06:00:00")
        assert guard.is_trading_time(ts) is True  # treated as UTC


# ── SafetyGuard — news blackout ─────────────────────────────────────────

class TestNewsBlackout:
    def test_static_blackout_hit(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=["2026-05-20 14:00/2026-05-20 14:30"],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 14:15:00", tz="Asia/Shanghai")
        assert guard.is_news_blackout(ts) is True

    def test_static_blackout_miss(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=["2026-05-20 14:00/2026-05-20 14:30"],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 15:00:00", tz="Asia/Shanghai")
        assert guard.is_news_blackout(ts) is False

    def test_dynamic_blackout(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        guard.set_dynamic_news_windows([
            (pd.Timestamp("2026-05-20 20:00", tz="Asia/Shanghai"),
             pd.Timestamp("2026-05-20 20:05", tz="Asia/Shanghai")),
        ])
        ts = pd.Timestamp("2026-05-20 20:02", tz="Asia/Shanghai")
        assert guard.is_news_blackout(ts) is True

    def test_dynamic_blackout_cleared(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        guard.set_dynamic_news_windows([])
        ts = pd.Timestamp("2026-05-20 20:02", tz="Asia/Shanghai")
        assert guard.is_news_blackout(ts) is False

    def test_no_news_windows(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai")
        assert guard.is_news_blackout(ts) is False

    def test_invalid_news_window_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid news blackout window"):
            guard = SafetyGuard(SafetyConfig(
                timezone="Asia/Shanghai",
                trading_windows=["00:00-24:00"],
                max_daily_loss_pct=0.02,
                max_consecutive_losses=3,
                one_direction_per_day=False,
                news_blackout_windows=["2026-05-20 14:00"],
                trailing_stop_enabled=True,
                trailing_trigger_pct=0.0015,
                trailing_distance_pct=0.0012,
            ))

    def test_invalid_news_window_end_before_start(self) -> None:
        with pytest.raises(ValueError, match="Invalid news blackout range"):
            guard = SafetyGuard(SafetyConfig(
                timezone="Asia/Shanghai",
                trading_windows=["00:00-24:00"],
                max_daily_loss_pct=0.02,
                max_consecutive_losses=3,
                one_direction_per_day=False,
                news_blackout_windows=["2026-05-20 14:30/2026-05-20 14:00"],
                trailing_stop_enabled=True,
                trailing_trigger_pct=0.0015,
                trailing_distance_pct=0.0012,
            ))


# ── SafetyGuard — can_open_trade ────────────────────────────────────────

class TestCanOpenTrade:
    def test_all_conditions_ok(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        risk = RiskSnapshot(realized_pnl=0.0, day_start_balance=100000.0, current_balance=100000.0, consecutive_losses=0)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai"), risk)
        assert allowed is True
        assert reason == "ok"

    def test_blocked_outside_window(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["14:00-23:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        risk = RiskSnapshot(realized_pnl=0.0, day_start_balance=100000.0, current_balance=100000.0, consecutive_losses=0)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 12:00", tz="Asia/Shanghai"), risk)
        assert allowed is False
        assert reason == "outside_trading_window"

    def test_blocked_news_blackout(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=["2026-05-20 14:00/2026-05-20 14:30"],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        risk = RiskSnapshot(realized_pnl=0.0, day_start_balance=100000.0, current_balance=100000.0, consecutive_losses=0)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 14:15", tz="Asia/Shanghai"), risk)
        assert allowed is False
        assert reason == "news_blackout_window"

    def test_blocked_daily_loss_limit(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        # 3% loss exceeds the 2% max
        risk = RiskSnapshot(realized_pnl=-3000.0, day_start_balance=100000.0, current_balance=97000.0, consecutive_losses=3)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai"), risk)
        assert allowed is False
        assert reason == "daily_loss_limit_reached"

    def test_blocked_consecutive_losses(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        # consecutive_losses=4 means 4 in a row; limit is 3, so 4 > 3 triggers block
        risk = RiskSnapshot(realized_pnl=-600.0, day_start_balance=100000.0, current_balance=99400.0, consecutive_losses=4)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai"), risk)
        assert allowed is False
        assert reason == "consecutive_loss_limit_reached"

    def test_at_limit_not_blocked_consecutive(self) -> None:
        """Only when consecutive_losses > max_consecutive_losses should it block."""
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=3,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        # consecutive_losses=3 equals limit, should NOT block
        risk = RiskSnapshot(realized_pnl=-100.0, day_start_balance=100000.0, current_balance=99900.0, consecutive_losses=3)
        allowed, reason = guard.can_open_trade(pd.Timestamp("2026-05-20 14:00", tz="Asia/Shanghai"), risk)
        assert allowed is True
        assert reason == "ok"


# ── SafetyGuard — direction check ───────────────────────────────────────

class TestDirectionAllowed:
    def test_no_direction_limit(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        allowed, reason = guard.is_direction_allowed("buy", "sell")
        assert allowed is True
        assert reason == "ok"

    def test_first_trade_allowed(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=True,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        allowed, reason = guard.is_direction_allowed("buy", None)
        assert allowed is True

    def test_same_direction_allowed(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=True,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        allowed, reason = guard.is_direction_allowed("buy", "buy")
        assert allowed is True

    def test_opposite_direction_blocked(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=True,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        allowed, reason = guard.is_direction_allowed("sell", "buy")
        assert allowed is False
        assert reason == "one_direction_per_day"

    def test_normalize_direction_preserves_lowercase(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=True,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        assert guard.normalize_direction("buy") == "buy"
        assert guard.normalize_direction("sell") == "sell"


# ── SafetyGuard — local day key ─────────────────────────────────────────

class TestLocalDayKey:
    def test_local_day_key(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        ts = pd.Timestamp("2026-05-20 23:30:00", tz="Asia/Shanghai")
        assert guard.local_day_key(ts) == "2026-05-20"

    def test_utc_crosses_local_midnight(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        # UTC 18:00 = next day Shanghai 02:00
        ts = pd.Timestamp("2026-05-20 18:00:00", tz="UTC")
        assert guard.local_day_key(ts) == "2026-05-21"


# ── SafetyGuard — day bounds ────────────────────────────────────────────

class TestDayBounds:
    def test_current_day_bounds_utc(self) -> None:
        guard = SafetyGuard(SafetyConfig(
            timezone="Asia/Shanghai",
            trading_windows=["00:00-24:00"],
            max_daily_loss_pct=0.02,
            max_consecutive_losses=6,
            one_direction_per_day=False,
            news_blackout_windows=[],
            trailing_stop_enabled=True,
            trailing_trigger_pct=0.0015,
            trailing_distance_pct=0.0012,
        ))
        from datetime import timezone, datetime
        # Use a fixed time for testing
        fixed = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
        date_from, date_to = guard.current_day_bounds_utc(fixed)
        # Asia/Shanghai is UTC+8, so UTC 10:00 = Shanghai 18:00 on same day
        assert date_from <= fixed < date_to


# ── LossStreakGuardrail ─────────────────────────────────────────────────

class TestLossStreakGuardrail:
    def test_normal_mode_allows_trading(self) -> None:
        guardrail = LossStreakGuardrail({"max_loss_streak_3": 3, "max_loss_streak_5": 5})
        assert guardrail.can_trade() is True

    def test_profit_resets_streak(self) -> None:
        guardrail = LossStreakGuardrail({"max_loss_streak_3": 3, "max_loss_streak_5": 5})
        guardrail.on_trade_result(is_profit=False)
        guardrail.on_trade_result(is_profit=False)
        assert guardrail.loss_streak == 2
        guardrail.on_trade_result(is_profit=True)
        assert guardrail.loss_streak == 0

    def test_three_losses_triggers_15m_cooldown(self) -> None:
        guardrail = LossStreakGuardrail({"max_loss_streak_3": 3, "max_loss_streak_5": 5})
        guardrail.on_trade_result(is_profit=False)  # 1
        guardrail.on_trade_result(is_profit=False)  # 2
        guardrail.on_trade_result(is_profit=False)  # 3 → cooldown_15m
        assert guardrail.mode == "cooldown_15m"
        assert guardrail.can_trade() is False

    def test_five_losses_triggers_1h_cooldown(self) -> None:
        guardrail = LossStreakGuardrail({"max_loss_streak_3": 3, "max_loss_streak_5": 5})
        for _ in range(5):
            guardrail.on_trade_result(is_profit=False)
        assert guardrail.mode == "cooldown_1h"
        assert guardrail.can_trade() is False
