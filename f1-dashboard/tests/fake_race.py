"""Small deterministic fake race in OpenF1's shape, for tests and screenshots."""

from datetime import datetime, timedelta, timezone

import pandas as pd

START = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
DRIVERS = [  # number, code, team, colour, pace offset (s/lap)
    (1, "VER", "Red Bull Racing", "#3671C6", 0.00), (4, "NOR", "McLaren", "#FF8000", 0.05),
    (16, "LEC", "Ferrari", "#E80020", 0.12), (81, "PIA", "McLaren", "#FF8000", 0.15),
    (44, "HAM", "Ferrari", "#E80020", 0.30), (63, "RUS", "Mercedes", "#27F4D2", 0.35),
]


def ts(seconds: float) -> pd.Timestamp:
    return pd.Timestamp(START + timedelta(seconds=seconds))


def race(laps_done: int = 10):
    drivers = pd.DataFrame([{"driver_number": n, "name_acronym": c, "team_name": t,
                             "team_colour": col} for n, c, t, col, _ in DRIVERS])
    lap_rows, ivl_rows, pos_rows = [], [], []
    for i, (n, *_rest, pace) in enumerate(DRIVERS):
        t = 0.0
        for lap in range(1, laps_done + 2):  # last lap is in progress (no time yet)
            dur = 92 + pace + (0.4 if lap == 5 and n == 44 else 0)
            lap_rows.append({"driver_number": n, "lap_number": lap, "date_start": ts(t),
                             "lap_duration": None if lap == laps_done + 1 else dur})
            t += dur
        gap = round(pace * laps_done, 3)
        ivl_rows += [{"driver_number": n, "date": ts(t - 30), "gap_to_leader": gap + 1,
                      "interval": 0.1},
                     {"driver_number": n, "date": ts(t), "gap_to_leader": gap if i else None,
                      "interval": round(gap - DRIVERS[i - 1][4] * laps_done, 3) if i else None}]
        pos_rows += [{"driver_number": n, "date": ts(0), "position": len(DRIVERS) - i},
                     {"driver_number": n, "date": ts(60), "position": i + 1}]
    ivl_rows[-1]["gap_to_leader"] = "+1 LAP"  # backmarker lapped, as OpenF1 sends it
    stints = pd.DataFrame([{"driver_number": n, "stint_number": 1, "compound": "MEDIUM",
                            "lap_start": 1, "lap_end": None, "tyre_age_at_start": 3}
                           for n, *_ in DRIVERS]
                          + [{"driver_number": 44, "stint_number": 0, "compound": "SOFT",
                              "lap_start": 1, "lap_end": 1, "tyre_age_at_start": 0}])
    stints.loc[stints["driver_number"] == 63, "compound"] = "HARD"
    pit = pd.DataFrame([{"driver_number": 63, "lap_number": 4, "date": ts(400)}])
    rc = pd.DataFrame([
        {"date": ts(0), "category": "Flag", "flag": "GREEN", "message": "GREEN LIGHT - PIT EXIT OPEN", "lap_number": 1, "qualifying_phase": None},
        {"date": ts(300), "category": "Flag", "flag": "YELLOW", "message": "YELLOW IN TRACK SECTOR 7", "lap_number": 4, "qualifying_phase": None},
        {"date": ts(320), "category": "SafetyCar", "flag": None, "message": "VIRTUAL SAFETY CAR DEPLOYED", "lap_number": 4, "qualifying_phase": None},
        {"date": ts(500), "category": "Other", "flag": None, "message": "CAR 44 (HAM) TIME 1:33.012 DELETED - TRACK LIMITS AT TURN 4", "lap_number": 6, "qualifying_phase": None},
    ])
    weather = pd.DataFrame([{"date": ts(m * 60), "air_temperature": 29.0 + m * 0.05,
                             "track_temperature": 36.0 + m * 0.1, "humidity": 74.0,
                             "rainfall": 0, "wind_speed": 1.2, "wind_direction": 210}
                            for m in range(0, 20)])
    return dict(drivers=drivers, positions=pd.DataFrame(pos_rows),
                intervals=pd.DataFrame(ivl_rows), laps=pd.DataFrame(lap_rows),
                stints=stints, pit=pit, race_control=rc, weather=weather)
