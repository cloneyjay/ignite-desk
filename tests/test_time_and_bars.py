from datetime import datetime, timedelta, timezone

import pandas as pd

from backend.ignite.market.bars import future_timestamps
from backend.ignite.market.time import Clock


def test_server_and_utc_are_inverse():
    clock = Clock(offset=timedelta(hours=2), utc_at_read=datetime.now(timezone.utc))
    assert clock.server_to_utc(datetime(2026, 11, 12, 10, 0)) == datetime(2026, 11, 12, 8, 0)
    assert clock.utc_to_server(datetime(2026, 11, 12, 8, 0)) == datetime(2026, 11, 12, 10, 0)


def test_utc_to_server_accepts_aware_datetimes():
    clock = Clock(offset=timedelta(hours=3), utc_at_read=datetime.now(timezone.utc))
    aware = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert clock.utc_to_server(aware) == datetime(2026, 11, 12, 11, 0)


def test_future_timestamps_skip_the_weekend():
    friday = pd.Timestamp("2026-11-13 23:45:00")
    stamps = future_timestamps(friday, "M15", 12)
    assert len(stamps) == 12
    assert all(t.day_of_week < 5 for t in stamps)
    assert stamps[0] == pd.Timestamp("2026-11-16 00:00:00")
    assert stamps[-1] == pd.Timestamp("2026-11-16 02:45:00")
