"""Tests for the TV-style Live page pieces: track status, lap label, HTML."""

import pandas as pd

from lib import timing, ui
from tests.fake_race import race, ts


def rc(*rows):
    return pd.DataFrame([{"date": ts(i), "category": c, "flag": f, "message": m, "scope": sc,
                          "qualifying_phase": q}
                         for i, (c, f, m, sc, q) in enumerate(rows)])


def test_track_status_sequence():
    msgs = [("Flag", "GREEN", "GREEN LIGHT - PIT EXIT OPEN", "Track", None)]
    assert timing.track_status(rc(*msgs)) == "CLEAR"
    msgs.append(("Flag", "YELLOW", "YELLOW IN TRACK SECTOR 7", "Sector", None))
    assert timing.track_status(rc(*msgs)) == "CLEAR"          # sector yellow only
    msgs.append(("SafetyCar", None, "SAFETY CAR DEPLOYED", "Track", None))
    assert timing.track_status(rc(*msgs)) == "SC"
    msgs.append(("SafetyCar", None, "SAFETY CAR IN THIS LAP", "Track", None))
    assert timing.track_status(rc(*msgs)) == "SC"             # still out until green
    msgs.append(("Flag", "GREEN", "TRACK CLEAR", "Track", None))
    assert timing.track_status(rc(*msgs)) == "CLEAR"
    msgs.append(("SafetyCar", None, "VIRTUAL SAFETY CAR DEPLOYED", "Track", None))
    assert timing.track_status(rc(*msgs)) == "VSC"
    msgs.append(("Flag", "RED", "RED FLAG", "Track", None))
    assert timing.track_status(rc(*msgs)) == "RED"
    msgs.append(("Flag", "CHEQUERED", "CHEQUERED FLAG", "Track", None))
    assert timing.track_status(rc(*msgs)) == "FINISHED"
    assert timing.track_status(pd.DataFrame()) is None


def test_lap_label():
    d = race(laps_done=10)
    assert timing.lap_label(d["laps"], pd.DataFrame(), "Race") == "<span>LAP</span>11"
    q = rc(("Flag", "GREEN", "x", "Track", 1), ("Flag", "GREEN", "y", "Track", 3))
    assert timing.lap_label(d["laps"], q, "Qualifying") == "<span>SESSION</span>Q3"
    assert timing.lap_label(d["laps"], q, "Sprint Qualifying").endswith("SQ3")
    assert timing.lap_label(d["laps"], q, "Practice") == ""


def test_tower_html_marks_and_escapes():
    d = race(laps_done=10)
    d["drivers"].loc[0, "team_name"] = "<script>x</script>"
    tower = timing.build_tower(d["drivers"], d["positions"], d["intervals"],
                               d["laps"], d["stints"], d["pit"])
    html = ui.tower_html(tower)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "LEADER" in html and 'class="hide-sm best"' in html   # VER has the fastest lap
    assert html.count("<tr>") == 7                                # header + 6 drivers


def test_race_control_html_escapes_messages():
    html = ui.race_control_html(rc(("Other", None, "CAR 1 <b>NOTED</b>", "Driver", None)))
    assert "&lt;b&gt;" in html and "<b>NOTED" not in html
