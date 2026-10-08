# F1 Live Dashboard

A Streamlit dashboard for following Formula 1 sessions on a second screen.
It uses [OpenF1](https://openf1.org) for timing, telemetry and race control, and
[Jolpica](https://github.com/jolpica/jolpica-f1) (Ergast-compatible) for the
calendar and championship standings.

> Work in progress. Full setup and deployment steps are added in build step 7.

## Run locally

```bash
cd f1-dashboard
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/check_apis.py      # quick API smoke test, no UI
streamlit run app.py              # opens http://localhost:8501
```

Live (real-time) OpenF1 data is optional and needs a paid OpenF1 account:
copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in.

## Layout

```
app.py              entry point + page navigation
pages/              one file per page (UI only, no HTTP calls)
lib/http.py         shared requests.Session: timeouts, retries, rate-limit throttle
lib/openf1.py       OpenF1 client -> pandas DataFrames, cached
lib/jolpica.py      Jolpica client -> pandas DataFrames, cached
scripts/            command-line helpers
.streamlit/         theme (config.toml) and secrets template
```
