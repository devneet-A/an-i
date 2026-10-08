"""Tests for standings helpers and calendar status labels."""

from datetime import timedelta

import pandas as pd

from lib import schedule, standings
from tests.fake_race import START


def points_table():
    rows = [  # round, race, code, team, points
        (1, "Bahrain GP", "VER", "Red Bull", 25), (1, "Bahrain GP", "NOR", "McLaren", 18),
        (2, "Saudi GP", "NOR", "McLaren", 25), (2, "Saudi GP", "PIA", "McLaren", 18),
        (3, "Aus GP", "VER", "Red Bull", 26), (3, "Aus GP", "NOR", "McLaren", 0),
    ]
    return pd.DataFrame(rows, columns=["round", "race_name", "code", "team", "points"])


def test_cumulative_points_fills_rounds_without_points():
    t = standings.cumulative_points(points_table(), "code")
    ver = t[t["code"] == "VER"].set_index("round")["total"].tolist()
    assert ver == [25, 25, 51]                    # round 2 = no score, line continues
    pia = t[t["code"] == "PIA"].set_index("round")["total"].tolist()
    assert pia == [0, 18, 18]
    teams = standings.cumulative_points(points_table(), "team")
    assert teams[(teams["team"] == "McLaren") & (teams["round"] == 3)]["total"].iloc[0] == 61
    assert t[t["round"] == 2]["race_name"].unique().tolist() == ["Saudi GP"]


def test_colours_fall_back_through_team_then_grey():
    by_driver = {"VER": "#3671C6", "NOR": "#FF8000"}
    by_team = standings.team_colours(points_table(), by_driver)
    assert by_team == {"Red Bull": "#3671C6", "McLaren": "#FF8000"}
    assert standings.colour_for_driver("PIA", "McLaren", by_driver, by_team) == "#FF8000"
    assert standings.colour_for_driver("XXX", "Nobody", by_driver, by_team) == standings.FALLBACK_COLOUR


def test_gap_to_leader():
    df = pd.DataFrame({"position": [2, 1], "points": [90.0, 120.0]})
    assert standings.with_gap(df)["gap"].tolist() == [0.0, 30.0]


def fake_schedule():
    rows = []
    for rnd, days in ((1, 0), (2, 14)):
        for i, name in enumerate(["Practice 1", "Qualifying", "Race"]):
            rows.append({"round": rnd, "race_name": f"GP {rnd}", "session": name,
                         "start_utc": pd.Timestamp(START + timedelta(days=days + i))})
    return pd.DataFrame(rows)


def test_calendar_status_mid_weekend():
    now = START + timedelta(days=1, hours=3)       # after round 1 qualifying
    df = schedule.add_status(fake_schedule(), now)
    assert df["status"].tolist()[:3] == ["done", "done", "next"]
    assert (df[df["round"] == 1]["round_status"] == "next").all()   # race still to come
    assert (df[df["round"] == 2]["round_status"] == "upcoming").all()


def test_calendar_status_between_rounds_and_season_end():
    df = schedule.add_status(fake_schedule(), START + timedelta(days=5))
    assert (df[df["round"] == 1]["round_status"] == "done").all()
    assert (df[df["round"] == 2]["round_status"] == "next").all()
    end = schedule.add_status(fake_schedule(), START + timedelta(days=40))
    assert (end["status"] == "done").all() and (end["round_status"] == "done").all()


def test_weekend_label():
    s = pd.DataFrame({"start_utc": [pd.Timestamp("2026-10-30 10:00Z"), pd.Timestamp("2026-11-01 19:00Z")]})
    assert schedule.weekend_label(s) == "30 Oct – 2 Nov"   # Sunday 19:00 UTC = Monday IST
    s2 = pd.DataFrame({"start_utc": [pd.Timestamp("2026-10-09 08:00Z"), pd.Timestamp("2026-10-11 08:00Z")]})
    assert schedule.weekend_label(s2) == "9–11 Oct"
