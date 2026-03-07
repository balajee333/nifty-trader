"""Tests for OhlcSignalDetector — O=H/O=L pattern matrix."""

import pytest

from nifty_trader.strategy.ohlc_signal import OhlcSignalDetector, SignalType


@pytest.fixture
def det():
    return OhlcSignalDetector(index_tolerance_pct=0.05, option_tolerance_abs=0.50)


# ── Tolerance helpers ────────────────────────────────────────────────

class TestTolerance:
    def test_index_open_eq_high_within_tolerance(self, det):
        # open=22000, high=22000.10 → diff/open = 0.0000045 < 0.0005
        assert det._is_open_eq_high(22000, 22000.10, is_index=True) is True

    def test_index_open_eq_high_outside_tolerance(self, det):
        # open=22000, high=22020 → diff/open = 0.00091 > 0.0005
        assert det._is_open_eq_high(22000, 22020, is_index=True) is False

    def test_index_open_eq_low_within_tolerance(self, det):
        assert det._is_open_eq_low(22000, 21999.90, is_index=True) is True

    def test_index_open_eq_low_outside_tolerance(self, det):
        assert det._is_open_eq_low(22000, 21980, is_index=True) is False

    def test_option_open_eq_high_within_tolerance(self, det):
        # abs tolerance of 0.50
        assert det._is_open_eq_high(200, 200.40, is_index=False) is True

    def test_option_open_eq_high_outside_tolerance(self, det):
        assert det._is_open_eq_high(200, 201.0, is_index=False) is False

    def test_option_open_eq_low_within_tolerance(self, det):
        assert det._is_open_eq_low(200, 199.60, is_index=False) is True

    def test_option_open_eq_low_outside_tolerance(self, det):
        assert det._is_open_eq_low(200, 198.0, is_index=False) is False


class TestPattern:
    def test_open_eq_high(self, det):
        assert det._pattern(22000, 22000.05, 21950, is_index=True) == "O=H"

    def test_open_eq_low(self, det):
        assert det._pattern(22000, 22050, 22000.05, is_index=True) == "O=L"

    def test_mid(self, det):
        assert det._pattern(22000, 22050, 21950, is_index=True) == "MID"

    def test_option_open_eq_high(self, det):
        assert det._pattern(200, 200.30, 190, is_index=False) == "O=H"

    def test_option_open_eq_low(self, det):
        assert det._pattern(200, 210, 199.80, is_index=False) == "O=L"


# ── Signal matrix ────────────────────────────────────────────────────

class TestStrongBullish:
    """Index O=L, CE O=L, PE O=H → BUY_CE."""

    def test_strong_bullish(self, det):
        sig = det.detect(
            index_open=22000, index_high=22050, index_low=22000,  index_close=22040,
            ce_open=200,     ce_high=220,     ce_low=200,       ce_close=215,
            pe_open=180,     pe_high=180,     pe_low=160,       pe_close=165,
        )
        assert sig.signal_type == SignalType.BUY_CE
        assert sig.index_pattern == "O=L"
        assert sig.ce_pattern == "O=L"
        assert sig.pe_pattern == "O=H"
        assert "bullish" in sig.reason.lower()


class TestStrongBearish:
    """Index O=H, CE O=H, PE O=L → BUY_PE."""

    def test_strong_bearish(self, det):
        sig = det.detect(
            index_open=22000, index_high=22000, index_low=21950,  index_close=21960,
            ce_open=200,     ce_high=200,     ce_low=180,       ce_close=185,
            pe_open=180,     pe_high=200,     pe_low=180,       pe_close=195,
        )
        assert sig.signal_type == SignalType.BUY_PE
        assert sig.index_pattern == "O=H"
        assert sig.ce_pattern == "O=H"
        assert sig.pe_pattern == "O=L"
        assert "bearish" in sig.reason.lower()


class TestPartialBullish:
    """Index O=L + one supporting option → BUY_CE."""

    def test_index_ol_ce_ol(self, det):
        sig = det.detect(
            index_open=22000, index_high=22050, index_low=22000,  index_close=22040,
            ce_open=200,     ce_high=220,     ce_low=200,       ce_close=215,
            pe_open=180,     pe_high=190,     pe_low=170,       pe_close=175,  # MID
        )
        assert sig.signal_type == SignalType.BUY_CE

    def test_index_ol_pe_oh(self, det):
        sig = det.detect(
            index_open=22000, index_high=22050, index_low=22000,  index_close=22040,
            ce_open=200,     ce_high=210,     ce_low=190,       ce_close=205,  # MID
            pe_open=180,     pe_high=180,     pe_low=160,       pe_close=165,
        )
        assert sig.signal_type == SignalType.BUY_CE


class TestPartialBearish:
    """Index O=H + one supporting option → BUY_PE."""

    def test_index_oh_ce_oh(self, det):
        sig = det.detect(
            index_open=22000, index_high=22000, index_low=21950,  index_close=21960,
            ce_open=200,     ce_high=200,     ce_low=180,       ce_close=185,
            pe_open=180,     pe_high=190,     pe_low=170,       pe_close=185,  # MID
        )
        assert sig.signal_type == SignalType.BUY_PE

    def test_index_oh_pe_ol(self, det):
        sig = det.detect(
            index_open=22000, index_high=22000, index_low=21950,  index_close=21960,
            ce_open=200,     ce_high=210,     ce_low=190,       ce_close=195,  # MID
            pe_open=180,     pe_high=200,     pe_low=180,       pe_close=195,
        )
        assert sig.signal_type == SignalType.BUY_PE


class TestChoppy:
    """CE O=H + PE O=H (both sold from open) → NO_TRADE."""

    def test_choppy(self, det):
        sig = det.detect(
            index_open=22000, index_high=22025, index_low=21975,  index_close=22010,  # MID
            ce_open=200,     ce_high=200,     ce_low=185,       ce_close=190,
            pe_open=180,     pe_high=180,     pe_low=165,       pe_close=170,
        )
        assert sig.signal_type == SignalType.NO_TRADE
        assert "choppy" in sig.reason.lower()


class TestWait:
    """No recognizable pattern → WAIT."""

    def test_all_mid(self, det):
        sig = det.detect(
            index_open=22000, index_high=22025, index_low=21975,  index_close=22010,
            ce_open=200,     ce_high=210,     ce_low=190,       ce_close=205,
            pe_open=180,     pe_high=190,     pe_low=170,       pe_close=175,
        )
        assert sig.signal_type == SignalType.WAIT

    def test_index_mid_ce_ol_pe_ol(self, det):
        """Both options at low, index mid → no clear direction."""
        sig = det.detect(
            index_open=22000, index_high=22025, index_low=21975,  index_close=22010,
            ce_open=200,     ce_high=220,     ce_low=200,       ce_close=215,
            pe_open=180,     pe_high=200,     pe_low=180,       pe_close=195,
        )
        assert sig.signal_type == SignalType.WAIT


class TestCustomTolerance:
    """Different tolerance values should shift detection boundaries."""

    def test_tight_tolerance(self):
        det = OhlcSignalDetector(index_tolerance_pct=0.01, option_tolerance_abs=0.10)
        # 0.01 % of 22000 = 2.2 pts → high at 22003 is outside
        assert det._pattern(22000, 22003, 21950, is_index=True) == "MID"
        # But 22002 is inside
        assert det._pattern(22000, 22002, 21950, is_index=True) == "O=H"

    def test_wide_tolerance(self):
        det = OhlcSignalDetector(index_tolerance_pct=0.10, option_tolerance_abs=2.0)
        # 0.10 % of 22000 = 22 pts
        assert det._pattern(22000, 22020, 21950, is_index=True) == "O=H"
        # Option: 2.0 abs tolerance
        assert det._pattern(200, 201.5, 190, is_index=False) == "O=H"
