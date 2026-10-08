"""Tests for the Analysis page calculations and chart builders."""

from datetime import timedelta

import pandas as pd

from lib import analysis, charts
from tests.fake_race import DRIVERS, START, race


def test_styles_dash_second_teammate():
    styles = analysis.driver_styles(race()["drivers"])
    assert styles[4]["dash"] == "solid" and styles[81]["dash"] == "dash"   # McLaren pair
    assert styles[4]["colour"] == styles[81]["colour"] == "#FF8000"
    assert styles[1]["dash"] == "solid"


def test_positions_and_gaps_from_lap_ends():
    d = race(laps_done=10)
    pos = analysis.positions_by_lap(d["laps"])
    lap10 = pos[pos["lap_number"] == 10].sort_values("position")
    assert list(lap10["driver_number"]) == [n for n, *_ in DRIVERS]
    gaps = analysis.gaps_by_lap(d["laps"])
    nor10 = gaps[(gaps["driver_number"] == 4) & (gaps["lap_number"] == 10)]["gap_s"].iloc[0]
    assert abs(nor10 - 0.5) < 1e-6           # 0.05s/lap slower x 10 laps
    assert gaps[gaps["driver_number"] == 1]["gap_s"].eq(0).all()


def test_missing_duration_uses_next_lap_start():
    laps = race(laps_done=3)["laps"]
    laps.loc[(laps["driver_number"] == 1) & (laps["lap_number"] == 2), "lap_duration"] = None
    ends = analysis.lap_end_times(laps)
    row = ends[(ends["driver_number"] == 1) & (ends["lap_number"] == 2)].iloc[0]
    assert row["lap_end"] == pd.Timestamp(START + timedelta(seconds=184))


def test_hide_slow_laps():
    laps = race(laps_done=6)["laps"]
    laps.loc[(laps["driver_number"] == 1) & (laps["lap_number"] == 3), "lap_duration"] = 130.0
    laps["is_pit_out_lap"] = laps["lap_number"] == 2
    kept = analysis.lap_times(laps, hide_slow=True)
    ver = kept[kept["driver_number"] == 1]["lap_number"].tolist()
    assert 2 not in ver and 3 not in ver and 4 in ver
    assert len(analysis.lap_times(laps, hide_slow=False)) > len(kept)


def test_stints_open_stint_ends_at_latest_lap():
    d = race(laps_done=10)
    bars = analysis.stint_bars(d["stints"], d["laps"])
    ver = bars[bars["driver_number"] == 1].iloc[0]
    assert ver["lap_end"] == 11 and ver["laps"] == 11


def test_orders():
    laps = race(laps_done=5)["laps"]
    assert analysis.finishing_order(laps)[:2] == [1, 4]
    # A retirement (fewer laps) drops to the back.
    short = laps[~((laps["driver_number"] == 4) & (laps["lap_number"] > 2))]
    assert analysis.finishing_order(short)[-1] == 4
    assert analysis.best_lap_order(laps)[0] == 1


def test_distance_integration():
    t = [pd.Timestamp(START + timedelta(seconds=s)) for s in range(5)]
    car = pd.DataFrame({"date": t, "speed": [360] * 5})  # 100 m/s
    assert analysis.add_distance(car)["distance_m"].tolist() == [0, 100, 200, 300, 400]


def test_charts_build():
    d = race(laps_done=10)
    styles = analysis.driver_styles(d["drivers"])
    sel = [1, 4, 81]
    assert len(charts.lap_time_chart(analysis.lap_times(d["laps"], True), styles, sel).data) == 3
    fig = charts.position_chart(analysis.positions_by_lap(d["laps"]), styles, sel)
    assert len(fig.layout.annotations) == 3 and fig.layout.yaxis.autorange == "reversed"
    stint_fig = charts.stint_chart(analysis.stint_bars(d["stints"], d["laps"]), styles, sel)
    assert {t.name for t in stint_fig.data if t.showlegend} == {"Medium"}
    car = analysis.add_distance(pd.DataFrame({
        "date": [pd.Timestamp(START + timedelta(seconds=s)) for s in range(3)],
        "speed": [300, 310, 320], "throttle": [100, 100, 0], "brake": [0, 0, 100], "n_gear": [7, 8, 8]}))
    tel = charts.telemetry_chart({1: car, 4: car}, styles)
    assert len(tel.data) == 8 and sum(bool(t.showlegend) for t in tel.data) == 2
