"""Command-line smoke test: `python scripts/check_apis.py`

Calls each API once without starting Streamlit, so you can tell an API/network
problem apart from a UI problem. (Streamlit prints a harmless "No runtime
found" warning because caching is designed to run inside an app.)
"""

import sys
from pathlib import Path

# Make `import lib` work when this file is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import jolpica, openf1  # noqa: E402
from lib.http import APIError  # noqa: E402


def main() -> int:
    ok = True
    try:
        s = openf1.get_session("latest")
        print("OpenF1 latest session:", s[["session_key", "session_name", "location", "date_start"]].to_dict("records"))
        drivers = openf1.get_drivers(int(s.iloc[0]["session_key"]))
        print(f"OpenF1 drivers in that session: {len(drivers)}")
    except (APIError, IndexError, KeyError) as exc:
        ok = False
        print("OpenF1 FAILED:", exc)
    try:
        sched = jolpica.get_schedule("current")
        print(f"Jolpica calendar: {sched['round'].nunique()} rounds, first: {sched.iloc[0]['race_name']}")
    except (APIError, IndexError, KeyError) as exc:
        ok = False
        print("Jolpica FAILED:", exc)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
