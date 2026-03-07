"""State persistence for VENOM strategy crash recovery."""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class VenomSnapshot:
    fsm_state: str = "IDLE"
    position: Optional[dict] = None
    daily_pnl: float = 0.0
    trade_count: int = 0
    consecutive_losses: int = 0
    signal: Optional[dict] = None
    trail_state: Optional[dict] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class StatePersister:
    def __init__(self, path: str = "~/.venom/state.json",
                 max_age_seconds: int = 3600):
        self._path = os.path.expanduser(path)
        self._max_age = max_age_seconds

    def save(self, snapshot: VenomSnapshot) -> None:
        snapshot.timestamp = time.time()
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(snapshot), f)
        os.replace(tmp, self._path)

    def load(self) -> Optional[VenomSnapshot]:
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path) as f:
                data = json.load(f)
            snap = VenomSnapshot(**data)
            if time.time() - snap.timestamp > self._max_age:
                return None
            return snap
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def clear(self) -> None:
        if os.path.exists(self._path):
            os.remove(self._path)
