"""Tests for VixGate — VIX regime classification and trade gating."""

import pytest

from nifty_trader.strategy.vix_gate import VixGate, VixMode


@pytest.fixture
def gate():
    return VixGate()


# ── Mode classification ──────────────────────────────────────────────

class TestGetMode:
    def test_full_mode(self, gate):
        assert gate.get_mode(10.0) == VixMode.FULL
        assert gate.get_mode(12.9) == VixMode.FULL

    def test_selective_mode(self, gate):
        assert gate.get_mode(13.0) == VixMode.SELECTIVE
        assert gate.get_mode(17.9) == VixMode.SELECTIVE

    def test_caution_mode(self, gate):
        assert gate.get_mode(18.0) == VixMode.CAUTION
        assert gate.get_mode(22.9) == VixMode.CAUTION

    def test_restricted_mode(self, gate):
        assert gate.get_mode(23.0) == VixMode.RESTRICTED
        assert gate.get_mode(29.9) == VixMode.RESTRICTED

    def test_blocked_mode(self, gate):
        assert gate.get_mode(30.0) == VixMode.BLOCKED
        assert gate.get_mode(50.0) == VixMode.BLOCKED

    def test_boundary_full_selective(self, gate):
        assert gate.get_mode(12.99) == VixMode.FULL
        assert gate.get_mode(13.0) == VixMode.SELECTIVE

    def test_boundary_blocked(self, gate):
        assert gate.get_mode(29.99) == VixMode.RESTRICTED
        assert gate.get_mode(30.0) == VixMode.BLOCKED


# ── Can trade ─────────────────────────────────────────────────────────

class TestCanTrade:
    def test_allowed_in_all_modes_except_blocked(self, gate):
        assert gate.can_trade(10.0) is True
        assert gate.can_trade(15.0) is True
        assert gate.can_trade(20.0) is True
        assert gate.can_trade(25.0) is True

    def test_blocked(self, gate):
        assert gate.can_trade(30.0) is False
        assert gate.can_trade(40.0) is False


# ── Size multiplier ──────────────────────────────────────────────────

class TestSizeMultiplier:
    def test_full_size(self, gate):
        assert gate.size_multiplier(10.0) == 1.0
        assert gate.size_multiplier(15.0) == 1.0

    def test_half_size(self, gate):
        assert gate.size_multiplier(20.0) == 0.5  # caution
        assert gate.size_multiplier(25.0) == 0.5  # restricted

    def test_zero_size(self, gate):
        assert gate.size_multiplier(30.0) == 0.0
        assert gate.size_multiplier(45.0) == 0.0


# ── Confirmations ────────────────────────────────────────────────────

class TestMinConfirmations:
    def test_standard_confirmations(self, gate):
        assert gate.min_confirmations(10.0) == 3  # FULL
        assert gate.min_confirmations(20.0) == 3  # CAUTION
        assert gate.min_confirmations(30.0) == 3  # BLOCKED

    def test_elevated_confirmations(self, gate):
        assert gate.min_confirmations(15.0) == 4  # SELECTIVE
        assert gate.min_confirmations(25.0) == 4  # RESTRICTED


# ── Target delta ─────────────────────────────────────────────────────

class TestTargetDelta:
    def test_low_vix_delta(self, gate):
        assert gate.target_delta(10.0) == 0.50

    def test_high_vix_delta(self, gate):
        assert gate.target_delta(18.0) == 0.65
        assert gate.target_delta(25.0) == 0.65

    def test_boundary(self, gate):
        assert gate.target_delta(12.99) == 0.50
        assert gate.target_delta(13.0) == 0.50  # selective starts at 13
        # selective threshold is used for delta boundary
        assert gate.target_delta(17.99) == 0.50
        assert gate.target_delta(18.0) == 0.65


# ── Custom thresholds ────────────────────────────────────────────────

class TestCustomThresholds:
    def test_custom_gate(self):
        gate = VixGate(full=10.0, selective=15.0, caution=20.0, blocked=25.0)
        assert gate.get_mode(9.0) == VixMode.FULL
        assert gate.get_mode(12.0) == VixMode.SELECTIVE
        assert gate.get_mode(18.0) == VixMode.CAUTION
        assert gate.get_mode(22.0) == VixMode.RESTRICTED
        assert gate.get_mode(25.0) == VixMode.BLOCKED

    def test_custom_deltas(self):
        gate = VixGate(delta_low=0.40, delta_high=0.70)
        assert gate.target_delta(10.0) == 0.40
        assert gate.target_delta(20.0) == 0.70
