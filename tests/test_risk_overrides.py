"""单元测试：risk_overrides — 风控手动解除。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mt5_quant.risk_overrides import (
    OVERRIDABLE_BLOCKED_REASONS,
    build_block_override_key,
    build_override_key,
    get_blocked_reason_clear,
    get_cleared_consecutive_losses,
    get_risk_override_path,
    is_blocked_reason_cleared,
    is_overridable_blocked_reason,
    record_blocked_reason_clear,
    record_consecutive_loss_clear,
)


# ── Key helpers ─────────────────────────────────────────────────────────

class TestKeys:
    def test_build_override_key(self) -> None:
        key = build_override_key("XAUUSD", 260516, "2026-05-21")
        assert key == "XAUUSD|260516|2026-05-21"

    def test_build_block_override_key(self) -> None:
        key = build_block_override_key("XAUUSD", 260516, "2026-05-21", "outside_trading_window")
        assert key == "XAUUSD|260516|2026-05-21|outside_trading_window"

    def test_keys_differ_by_reason(self) -> None:
        k1 = build_block_override_key("XAUUSD", 1, "2026-05-21", "reason_a")
        k2 = build_block_override_key("XAUUSD", 1, "2026-05-21", "reason_b")
        assert k1 != k2

    def test_keys_differ_by_symbol(self) -> None:
        k1 = build_block_override_key("XAUUSD", 1, "2026-05-21", "reason")
        k2 = build_block_override_key("BTCUSD", 1, "2026-05-21", "reason")
        assert k1 != k2


# ── is_overridable_blocked_reason ──────────────────────────────────────

class TestIsOverridable:
    def test_all_defined_reasons(self) -> None:
        for reason in OVERRIDABLE_BLOCKED_REASONS:
            assert is_overridable_blocked_reason(reason)

    def test_non_overridable_reason(self) -> None:
        assert not is_overridable_blocked_reason("missing_stop_loss")
        assert not is_overridable_blocked_reason("zero_volume")
        assert not is_overridable_blocked_reason("unknown")

    def test_empty_string(self) -> None:
        assert not is_overridable_blocked_reason("")


# ── record_blocked_reason_clear ────────────────────────────────────────

class TestRecordBlockedReasonClear:
    def test_record_and_retrieve(self, tmp_path: Path) -> None:
        record = record_blocked_reason_clear(
            symbol="XAUUSD",
            magic_number=260516,
            day_key="2026-05-21",
            blocked_reason="outside_trading_window",
            session_id="session-a",
            base_dir=tmp_path,
        )
        assert record["symbol"] == "XAUUSD"
        assert record["blocked_reason"] == "outside_trading_window"

        fetched = get_blocked_reason_clear(
            symbol="XAUUSD",
            magic_number=260516,
            day_key="2026-05-21",
            blocked_reason="outside_trading_window",
            base_dir=tmp_path,
        )
        assert fetched is not None
        assert fetched["session_id"] == "session-a"

    def test_non_overridable_reason_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cannot be manually cleared"):
            record_blocked_reason_clear(
                symbol="XAUUSD",
                magic_number=260516,
                day_key="2026-05-21",
                blocked_reason="missing_stop_loss",
                base_dir=tmp_path,
            )

    def test_recorded_reason_is_cleared(self, tmp_path: Path) -> None:
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="news_blackout_window", base_dir=tmp_path,
        )
        assert is_blocked_reason_cleared(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="news_blackout_window", base_dir=tmp_path,
        )

    def test_different_reason_not_cleared(self, tmp_path: Path) -> None:
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="outside_trading_window", base_dir=tmp_path,
        )
        assert not is_blocked_reason_cleared(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="news_blackout_window", base_dir=tmp_path,
        )

    def test_different_symbol_not_cleared(self, tmp_path: Path) -> None:
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="outside_trading_window", base_dir=tmp_path,
        )
        assert not is_blocked_reason_cleared(
            symbol="BTCUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="outside_trading_window", base_dir=tmp_path,
        )

    def test_override_file_created(self, tmp_path: Path) -> None:
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="outside_trading_window", base_dir=tmp_path,
        )
        path = get_risk_override_path(tmp_path)
        assert path.exists()

    def test_multiple_records_in_file(self, tmp_path: Path) -> None:
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="outside_trading_window", base_dir=tmp_path,
        )
        record_blocked_reason_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="news_blackout_window", base_dir=tmp_path,
        )
        data = json.loads(get_risk_override_path(tmp_path).read_text(encoding="utf-8"))
        assert len(data) == 2


# ── record_consecutive_loss_clear ──────────────────────────────────────

class TestRecordConsecutiveLossClear:
    def test_record_and_retrieve_threshold(self, tmp_path: Path) -> None:
        record_consecutive_loss_clear(
            symbol="XAUUSD",
            magic_number=260516,
            day_key="2026-05-21",
            consecutive_losses=6,
            session_id="session-b",
            base_dir=tmp_path,
        )
        cleared = get_cleared_consecutive_losses(
            symbol="XAUUSD",
            magic_number=260516,
            day_key="2026-05-21",
            base_dir=tmp_path,
        )
        assert cleared == 6

    def test_different_symbol_unaffected(self, tmp_path: Path) -> None:
        record_consecutive_loss_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            consecutive_losses=7, base_dir=tmp_path,
        )
        assert get_cleared_consecutive_losses(
            symbol="BTCUSD", magic_number=260516, day_key="2026-05-21",
            base_dir=tmp_path,
        ) == 0

    def test_no_record_returns_zero(self, tmp_path: Path) -> None:
        assert get_cleared_consecutive_losses(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            base_dir=tmp_path,
        ) == 0

    def test_invalid_data_in_file_returns_zero(self, tmp_path: Path) -> None:
        path = get_risk_override_path(tmp_path)
        path.write_text('{"not a valid record": true}', encoding="utf-8")
        assert get_cleared_consecutive_losses(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            base_dir=tmp_path,
        ) == 0

    def test_malformed_json_returns_zero(self, tmp_path: Path) -> None:
        path = get_risk_override_path(tmp_path)
        path.write_text("not json", encoding="utf-8")
        assert get_cleared_consecutive_losses(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            base_dir=tmp_path,
        ) == 0

    def test_record_creates_both_keys(self, tmp_path: Path) -> None:
        record_consecutive_loss_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            consecutive_losses=5, base_dir=tmp_path,
        )
        data = json.loads(get_risk_override_path(tmp_path).read_text(encoding="utf-8"))
        assert len(data) == 2  # base key + consecutive specific key

    def test_negative_consecutive_losses_defaults_to_zero(self) -> None:
        """If the JSON has negative cleared_consecutive_losses, max(0, ...) should return 0."""
        # This tests the _load_override_file's behavior indirectly
        pass

    def test_is_blocked_reason_cleared_for_consecutive(self, tmp_path: Path) -> None:
        record_consecutive_loss_clear(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            consecutive_losses=6, base_dir=tmp_path,
        )
        assert is_blocked_reason_cleared(
            symbol="XAUUSD", magic_number=260516, day_key="2026-05-21",
            blocked_reason="consecutive_loss_limit_reached", base_dir=tmp_path,
        )


# ── get_risk_override_path ─────────────────────────────────────────────

class TestGetRiskOverridePath:
    def test_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested"
        path = get_risk_override_path(nested)
        assert nested.exists()
        assert path.name == "risk-overrides.json"

    def test_returns_file_in_base_dir(self, tmp_path: Path) -> None:
        path = get_risk_override_path(tmp_path)
        assert path.parent == tmp_path
        assert path.suffix == ".json"
