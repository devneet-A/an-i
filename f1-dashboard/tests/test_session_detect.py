"""Tests for session detection. Run with:  pip install pytest && pytest -q

No network: we build small fake tables and fake the API functions.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from lib import session_detect as sd
from lib.http import APIError

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)  # FP1 start in our fake weekend


def fake_sessions() -> pd.DataFrame:
    rows = [
        # (key, name, type, start offset hours, length hours)
        (1, "Practice 1", "Practice", 0, 1),
        (2, "Practice 2", "Practice", 4, 1),
        (3, "Qualifying", "Qualifying", 24, 1),
        (4, "Race", "Race", 48, 2),
    ]
    return pd.DataFrame([{
        "session_key": k, "meeting_key": 100, "session_name": n, "session_type": t,
        "date_start": pd.Timestamp(T0 + timedelta(hours=s)),
        "date_end": pd.Timestamp(T0 + timedelta(hours=s + d)),
        "circuit_short_name": "Marina Bay", "country_name": "Singapore",
        "location": "Marina Bay", "is_cancelled": False,
    } for k, n, t, s, d in rows])


def keys(*rows):
    return tuple(None if r is None else int(r["session_key"]) for r in rows)


@pytest.mark.parametrize("hours, expected", [
    (-1, (None, None, 1)),        # before the weekend: nothing live, FP1 next
    (0.5, (1, None, 2)),          # during FP1
    (1.5, (1, 1, 2)),             # FP1 finished 30 min ago: still in overrun window
    (2, (None, 1, 2)),            # FP1 well finished
    (49, (4, 3, None)),           # during the race, nothing after it
    (51, (None, 4, None)),        # 1h after scheduled race end
])
def test_pick_sessions(hours, expected):
    now = T0 + timedelta(hours=hours)
    assert keys(*sd.pick_sessions(fake_sessions(), now)) == expected


def test_cancelled_sessions_are_ignored():
    df = fake_sessions()
    df.loc[df["session_key"] == 2, "is_cancelled"] = True
    _, _, nxt = sd.pick_sessions(df, T0 + timedelta(hours=2))
    assert int(nxt["session_key"]) == 3


def test_chequered_flag_rules():
    rc = pd.DataFrame({"flag": ["GREEN", "CHEQUERED"], "qualifying_phase": [None, 1]})
    assert sd.chequered_flag_shown(rc, "Race")
    assert not sd.chequered_flag_shown(rc, "Qualifying")  # only Q1 finished
    rc.loc[2] = ["CHEQUERED", 3]
    assert sd.chequered_flag_shown(rc, "Qualifying")
    assert not sd.chequered_flag_shown(pd.DataFrame(), "Race")


@pytest.fixture
def fake_openf1(monkeypatch):
    def install(access: bool, race_control: pd.DataFrame | None = None):
        sessions = fake_sessions()
        monkeypatch.setattr(sd.openf1, "get_sessions",
                            lambda year: sessions if year == 2026 else pd.DataFrame())
        monkeypatch.setattr(sd.openf1, "get_meetings", lambda year: pd.DataFrame(
            {"meeting_key": [100], "meeting_name": ["Singapore Grand Prix"]}))
        monkeypatch.setattr(sd.openf1, "has_live_access", lambda: access)
        monkeypatch.setattr(sd.openf1, "get_race_control",
                            lambda key, live: race_control if race_control is not None else pd.DataFrame())
    return install


def test_detect_live_without_credentials_shows_latest(fake_openf1):
    fake_openf1(access=False)
    st = sd.detect(T0 + timedelta(hours=24.5))  # during qualifying
    assert st.is_live and st.live.session_name == "Qualifying"
    assert not st.can_stream
    assert st.data_session.session_name == "Practice 2"
    assert st.next_session.session_name == "Race"
    assert st.live.meeting_name == "Singapore Grand Prix"
    assert st.note


def test_detect_live_with_credentials_streams(fake_openf1):
    fake_openf1(access=True)
    st = sd.detect(T0 + timedelta(hours=24.5))
    assert st.can_stream and st.data_session.session_name == "Qualifying"


def test_chequered_flag_ends_overrun(fake_openf1):
    fake_openf1(access=True, race_control=pd.DataFrame({"flag": ["CHEQUERED"]}))
    st = sd.detect(T0 + timedelta(hours=50, minutes=10))  # race overrunning
    assert not st.is_live and st.data_session.session_name == "Race"


def test_falls_back_to_jolpica(monkeypatch):
    def boom(year):
        raise APIError("down")
    monkeypatch.setattr(sd.openf1, "get_sessions", boom)
    sched = pd.DataFrame({
        "race_name": ["Singapore Grand Prix"] * 2, "circuit_name": ["Marina Bay"] * 2,
        "country": ["Singapore"] * 2, "session": ["Qualifying", "Race"],
        "start_utc": [pd.Timestamp(T0), pd.Timestamp(T0 + timedelta(days=1))],
    })
    monkeypatch.setattr(sd.jolpica, "get_schedule", lambda y: sched if y == 2026 else pd.DataFrame())
    st = sd.detect(T0 + timedelta(minutes=30))
    assert st.source == "jolpica" and st.is_live and st.live.session_name == "Qualifying"
    assert st.next_session.session_name == "Race" and st.data_session is None
