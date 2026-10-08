"""Tests for the timing tower and the live feed's incremental merging."""

import pandas as pd

from lib import live_feed, timing
from tests.fake_race import race, ts


def test_tower_order_gaps_tyres_pits():
    d = race(laps_done=10)
    tower = timing.build_tower(d["drivers"], d["positions"], d["intervals"],
                               d["laps"], d["stints"], d["pit"])
    assert list(tower["name_acronym"]) == ["VER", "NOR", "LEC", "PIA", "HAM", "RUS"]
    assert list(tower["position"]) == [1, 2, 3, 4, 5, 6]
    assert tower.loc[0, "gap"] == ""             # leader
    assert tower.loc[1, "gap"] == "+0.500"       # latest interval row wins, not older one
    assert tower.loc[5, "gap"] == "+1 LAP"       # text gaps pass through
    assert tower.loc[0, "last_lap"] == "1:32.000"
    # Medium fitted with 3 laps on it at lap 1, now on lap 11 -> 13 laps old.
    assert tower.loc[0, "tyre"] == "🟡 M · 13"
    assert tower.loc[5, "tyre"].startswith("⚪ H")
    assert tower.loc[5, "pits"] == 1 and tower.loc[0, "pits"] == 0


def test_tower_without_intervals_uses_best_lap_gap():
    d = race(laps_done=3)
    tower = timing.build_tower(d["drivers"], d["positions"], pd.DataFrame(),
                               d["laps"], pd.DataFrame(), pd.DataFrame())
    assert tower.loc[1, "gap"] == "+0.050"
    assert (tower["tyre"] == "").all()


def test_tower_handles_missing_everything():
    d = race()
    assert timing.build_tower(pd.DataFrame(), *[pd.DataFrame()] * 5).empty
    tower = timing.build_tower(d["drivers"], *[pd.DataFrame()] * 5)
    assert len(tower) == 6 and tower["position"].isna().all()


def test_feed_fetches_incrementally(monkeypatch):
    d = race()
    calls = []

    def fake(name, frame):
        def fn(key, live=False, since=None):
            calls.append((name, since))
            if since is None:
                return frame
            col = "date_start" if name == "laps" else "date"
            return frame[frame[col] > since]
        return fn

    o = live_feed.openf1
    monkeypatch.setattr(o, "get_drivers", lambda key, live=False: d["drivers"])
    for name in ("positions", "intervals", "laps", "race_control"):
        monkeypatch.setattr(o, f"get_{name}", fake(name, d[name]))
    for name in ("stints", "pit", "weather"):
        monkeypatch.setattr(o, f"get_{name}", lambda key, live=False, _f=d[name]: _f)

    feed = live_feed.LiveFeed(123)
    snap = feed.refresh()
    assert not snap.errors and len(snap.positions) == 6  # one row per driver kept
    assert len(snap.race_control) == 4

    # Second refresh straight away: nothing is due yet, so no API calls.
    calls.clear()
    feed.refresh()
    assert calls == []

    # Pretend time passed; a new race control message arrives.
    feed._last_fetch = {}
    new = pd.DataFrame([{"date": ts(900), "category": "Flag", "flag": "CHEQUERED",
                         "message": "CHEQUERED FLAG", "lap_number": 11, "qualifying_phase": None}])
    d["race_control"] = pd.concat([d["race_control"], new], ignore_index=True)
    monkeypatch.setattr(o, "get_race_control", fake("race_control", d["race_control"]))
    snap = feed.refresh()
    rc_since = [s for n, s in calls if n == "race_control"][0]
    assert rc_since == ts(500) - live_feed.OVERLAP     # asked only for recent rows
    assert len(snap.race_control) == 5                 # overlap rows de-duplicated
