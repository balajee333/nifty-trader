"""Tests for StatePersister save/load/clear."""

import os
import time
import pytest
from nifty_trader.core.persister import StatePersister, VenomSnapshot


@pytest.fixture
def tmp_path_str(tmp_path):
    return str(tmp_path / "state.json")


@pytest.fixture
def persister(tmp_path_str):
    return StatePersister(path=tmp_path_str, max_age_seconds=3600)


class TestSaveLoadRoundTrip:
    def test_round_trip(self, persister):
        snap = VenomSnapshot(
            fsm_state="POSITION_OPEN",
            daily_pnl=1500.0,
            trade_count=3,
            consecutive_losses=1,
            position={"strike": 24000, "qty": 50},
            signal={"type": "OEQ_HIGH"},
            trail_state={"sl_price": 95.0},
        )
        persister.save(snap)
        loaded = persister.load()
        assert loaded is not None
        assert loaded.fsm_state == "POSITION_OPEN"
        assert loaded.daily_pnl == 1500.0
        assert loaded.trade_count == 3
        assert loaded.position == {"strike": 24000, "qty": 50}
        assert loaded.trail_state == {"sl_price": 95.0}


class TestMissingFile:
    def test_load_missing_returns_none(self, persister):
        result = persister.load()
        assert result is None


class TestStaleState:
    def test_stale_state_returns_none(self, tmp_path_str):
        persister = StatePersister(path=tmp_path_str, max_age_seconds=1)
        snap = VenomSnapshot(fsm_state="POSITION_OPEN")
        snap.timestamp = time.time() - 10  # 10 seconds ago
        persister.save(snap)
        # Manually patch the timestamp to be old
        import json
        with open(tmp_path_str) as f:
            data = json.load(f)
        data["timestamp"] = time.time() - 10
        with open(tmp_path_str, "w") as f:
            json.dump(data, f)
        result = persister.load()
        assert result is None


class TestClear:
    def test_clear_removes_file(self, persister, tmp_path_str):
        snap = VenomSnapshot()
        persister.save(snap)
        assert os.path.exists(tmp_path_str)
        persister.clear()
        assert not os.path.exists(tmp_path_str)

    def test_clear_nonexistent_is_safe(self, persister):
        persister.clear()  # should not raise


class TestCorruptFile:
    def test_corrupt_json_returns_none(self, tmp_path_str, persister):
        os.makedirs(os.path.dirname(tmp_path_str), exist_ok=True)
        with open(tmp_path_str, "w") as f:
            f.write("{bad json")
        result = persister.load()
        assert result is None
