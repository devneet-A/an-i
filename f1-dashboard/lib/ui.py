"""Look and feel: global CSS, the floating pill navigation, and the HTML pieces
of the TV-style Live page (banner, timing tower, weather strip, race control).

Why HTML instead of st.dataframe for the tower? A broadcast timing tower has
details a data grid can't do: a position box, a thin team-colour bar, purple
for the session's fastest lap, tyre "rings". Streamlit's st.html renders our
markup directly in the page.

Anything that came from the API (names, race control messages) goes through
html.escape() first, so stray "<" characters can't break the page.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from lib.charts import COMPOUND_COLOUR
from lib.timeutils import IST
from lib.timing import FLAG_ICON

# --------------------------------------------------------------------------
# Global CSS. Selectors rely on `st-key-<key>` classes (Streamlit adds one
# for every element given a key) and on data-testid attributes, which are
# more stable across Streamlit versions than its generated class names.
# --------------------------------------------------------------------------
CSS = """
<style>
:root {
  --bg: #0B0B0F; --panel: #14141B; --panel-2: #1B1B24; --line: #262630;
  --ink: #F2F2F2; --muted: #8E8E9A; --red: #E10600;
  --purple: #B35CFF; --green: #2BD46A; --yellow: #FFD12E;
}

/* ---------- floating pill navigation ---------- */
.st-key-pillnav {
  position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
  z-index: 1000001; width: auto !important; flex-wrap: nowrap !important;
  padding: 5px; gap: 2px !important; border-radius: 999px;
  background: rgba(20, 20, 27, 0.82); border: 1px solid var(--line);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}
.st-key-pillnav [data-testid="stPageLink"] a {
  border-radius: 999px; padding: 6px 14px; margin: 0; white-space: nowrap;
}
.st-key-pillnav [data-testid="stPageLink"] a:hover { background: var(--panel-2); }
.st-key-pillnav > div { width: auto !important; }
/* The current page's link is highlighted by a rule pill_nav() adds per run. */

/* Streamlit's own top bar: keep its menu, drop its background. */
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 5.25rem; }

/* Phones: pill moves to the bottom like an app tab bar, labels shrink. */
@media (max-width: 640px) {
  .st-key-pillnav { top: auto; bottom: 14px; }
  .st-key-pillnav [data-testid="stPageLink"] a { padding: 6px 10px; }
  .st-key-pillnav [data-testid="stPageLink"] p { font-size: 0.8rem; }
  [data-testid="stMainBlockContainer"] { padding-top: 3.5rem; padding-bottom: 6rem; }
}

/* ---------- Live page: broadcast banner ---------- */
.f1-banner { display: flex; align-items: stretch; gap: 14px; margin-bottom: 4px; }
.f1-banner .accent { width: 6px; border-radius: 3px; background: var(--red); }
.f1-banner .event { font-weight: 700; font-size: clamp(1.4rem, 4vw, 2.2rem);
  text-transform: uppercase; letter-spacing: -0.01em; line-height: 1.05; color: var(--ink); }
.f1-banner .meta { color: var(--muted); font-size: 0.9rem; margin-top: 4px;
  text-transform: uppercase; letter-spacing: 0.06em; }
.f1-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px;
  border-radius: 4px; font-size: 0.78rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; background: var(--panel-2); color: var(--ink); }
.f1-chip.live { background: var(--red); color: #fff; }
.f1-chip.live::before { content: ""; width: 7px; height: 7px; border-radius: 50%;
  background: #fff; animation: f1-pulse 1.4s ease-in-out infinite; }
@keyframes f1-pulse { 50% { opacity: 0.25; } }
@media (prefers-reduced-motion: reduce) { .f1-chip.live::before { animation: none; } }

/* Countdown to the next session (top right of the banner) */
.f1-next { text-align: right; }
.f1-next small { display: block; color: var(--muted); font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; }
.f1-next b { display: block; font-size: clamp(1.3rem, 3vw, 1.9rem); font-weight: 700;
  font-variant-numeric: tabular-nums; line-height: 1.15; }
.f1-next span { color: var(--muted); font-size: 0.82rem; }
@media (max-width: 640px) { .f1-next { text-align: left; margin-top: 4px; } }

/* Status bar under the banner: lap counter + track status */
.f1-status { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 2px 0 12px; }
.f1-status .lap { font-weight: 700; font-size: 1.05rem; letter-spacing: 0.04em;
  font-variant-numeric: tabular-nums; }
.f1-status .lap span { color: var(--muted); font-weight: 600; font-size: 0.8rem; margin-right: 6px; }
.track-CLEAR { background: #0f3d22 !important; color: var(--green) !important; }
.track-YELLOW, .track-VSC, .track-SC { background: #3d3410 !important; color: var(--yellow) !important; }
.track-RED { background: #4a0f0f !important; color: #ff5a5a !important; }
.track-FINISHED { background: #e9e9ee !important; color: #111 !important; }

/* ---------- timing tower ---------- */
.f1-tower { width: 100%; border-collapse: separate; border-spacing: 0 3px;
  font-variant-numeric: tabular-nums; font-size: 0.92rem; }
.f1-tower th { color: var(--muted); font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; text-align: right; padding: 0 8px 2px; }
.f1-tower th.l, .f1-tower td.l { text-align: left; }
.f1-tower td { background: var(--panel); padding: 6px 8px; text-align: right; white-space: nowrap; }
.f1-tower tr td:first-child { border-radius: 4px 0 0 4px; }
.f1-tower tr td:last-child { border-radius: 0 4px 4px 0; }
.f1-tower td.pos { width: 30px; padding: 0; text-align: center; font-weight: 700;
  background: #F2F2F2; color: #0B0B0F; }
.f1-tower td.bar { width: 4px; padding: 0; }
.f1-tower td.code { font-weight: 700; letter-spacing: 0.04em; }
.f1-tower td.team { color: var(--muted); font-size: 0.8rem; }
.f1-tower .leader { color: var(--muted); font-size: 0.72rem; letter-spacing: 0.08em; }
.f1-tower .best { color: var(--purple); font-weight: 700; }   /* session fastest */
.f1-tower .pb { color: var(--green); }                         /* personal best */
.tyre { display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid; font-size: 0.66rem;
  font-weight: 700; color: var(--ink); background: #0B0B0F; vertical-align: middle; }
.tyre-age { color: var(--muted); font-size: 0.78rem; margin-left: 5px; }
@media (max-width: 640px) {
  .f1-tower { font-size: 0.85rem; }
  .f1-tower .hide-sm { display: none; }
}

/* ---------- side panels ---------- */
.f1-panel-title { color: var(--muted); font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.12em; text-transform: uppercase; margin: 0 0 6px; }
.f1-weather { display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
  gap: 3px; margin-bottom: 18px; }
.f1-weather div { background: var(--panel); padding: 8px 10px; border-radius: 4px; }
.f1-weather b { display: block; font-size: 1.15rem; font-variant-numeric: tabular-nums; }
.f1-weather small { color: var(--muted); font-size: 0.66rem; letter-spacing: 0.1em;
  text-transform: uppercase; }
.f1-weather i { font-style: normal; color: var(--muted); font-size: 0.72rem; margin-left: 4px; }
.f1-rc { max-height: 430px; overflow-y: auto; display: flex; flex-direction: column; gap: 3px;
  padding-right: 4px; }
.f1-rc div { background: var(--panel); border-left: 3px solid var(--line); padding: 7px 10px;
  border-radius: 0 4px 4px 0; font-size: 0.85rem; line-height: 1.3; }
.f1-rc div small { display: block; color: var(--muted); font-size: 0.72rem; margin-top: 2px; }
.f1-rc .flag-GREEN, .f1-rc .flag-CLEAR { border-left-color: var(--green); }
.f1-rc .flag-YELLOW, .f1-rc .flag-DOUBLE-YELLOW, .f1-rc .cat-SafetyCar { border-left-color: var(--yellow); }
.f1-rc .flag-RED { border-left-color: #ff3b3b; }
.f1-rc .flag-BLUE { border-left-color: #3b82f6; }
.f1-rc .flag-CHEQUERED { border-left-color: #fff; }
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def pill_nav(pages: list, current) -> None:
    """Our own navigation: page links inside a container the CSS turns into a
    floating pill (top-centre on desktop, bottom on phones).

    Streamlit doesn't tag the current page's link in a stable way, so each
    link sits in its own keyed container and we add one CSS rule that paints
    the current page's container red.
    """
    with st.container(key="pillnav", horizontal=True, gap=None):
        for i, page in enumerate(pages):
            with st.container(key=f"nav{i}", width="content"):
                st.page_link(page, width="content")
    active = next((i for i, p in enumerate(pages) if p.url_path == current.url_path), 0)
    st.html(f"""<style>
      .st-key-nav{active} a {{ background: var(--red) !important; }}
      .st-key-nav{active} a p {{ color: #fff !important; font-weight: 600; }}
    </style>""")


# --------------------------------------------------------------------------
# Live page HTML builders (pure: data in, HTML string out)
# --------------------------------------------------------------------------

def banner_html(event: str, meta: str, chip: str, live: bool) -> str:
    return (f'<div class="f1-banner"><div class="accent"></div><div>'
            f'<span class="f1-chip{" live" if live else ""}">{escape(chip)}</span>'
            f'<div class="event">{escape(event)}</div>'
            f'<div class="meta">{escape(meta)}</div></div></div>')


def next_session_html(label: str, countdown: str, detail: str) -> str:
    return (f'<div class="f1-next"><small>{escape(label)}</small><b>{escape(countdown)}</b>'
            f'<span>{escape(detail)}</span></div>')


def status_html(lap_label: str, track: str | None) -> str:
    parts = []
    if lap_label:
        parts.append(f'<span class="lap">{lap_label}</span>')
    if track:
        css = track.split()[0]  # "SC", "VSC", "RED", "CLEAR"...
        parts.append(f'<span class="f1-chip track-{css}">{escape(TRACK_LABEL.get(track, track))}</span>')
    return f'<div class="f1-status">{"".join(parts)}</div>' if parts else ""


TRACK_LABEL = {"CLEAR": "Track clear", "YELLOW": "Yellow flag", "SC": "Safety car",
               "VSC": "Virtual safety car", "RED": "Red flag", "FINISHED": "Chequered flag"}


def tower_html(tower: pd.DataFrame) -> str:
    """The timing tower as an HTML table. Columns marked hide-sm disappear on phones."""
    session_best = tower["best_lap_s"].min()
    head = ('<tr><th></th><th></th><th class="l">Driver</th><th>Gap</th><th>Int</th>'
            '<th class="hide-sm">Last</th><th class="hide-sm">Best</th><th class="l">Tyre</th>'
            '<th class="hide-sm">Pit</th><th class="l hide-sm">Team</th></tr>')
    rows = []
    for r in tower.itertuples(index=False):
        pos = "" if pd.isna(r.position) else int(r.position)
        gap = escape(r.gap) or ('<span class="leader">LEADER</span>' if pos == 1 else "")
        # Purple = fastest lap of the session; green = this driver's own best.
        best_cls = "best" if pd.notna(r.best_lap_s) and r.best_lap_s == session_best else ""
        last_cls = ("best" if best_cls and r.last_lap_s == r.best_lap_s
                    else "pb" if pd.notna(r.last_lap_s) and r.last_lap_s == r.best_lap_s else "")
        tyre = ""
        if r.compound:
            colour = COMPOUND_COLOUR.get(r.compound, COMPOUND_COLOUR["UNKNOWN"])
            tyre = (f'<span class="tyre" style="border-color:{colour}">{escape(r.compound[:1])}</span>'
                    f'<span class="tyre-age">{int(r.tyre_age)}</span>')
        rows.append(
            f'<tr><td class="pos">{pos}</td>'
            f'<td class="bar" style="background:{escape(r.team_colour)}"></td>'
            f'<td class="code l">{escape(r.name_acronym)}</td>'
            f'<td>{gap}</td><td>{escape(r.interval)}</td>'
            f'<td class="hide-sm {last_cls}">{escape(r.last_lap)}</td>'
            f'<td class="hide-sm {best_cls}">{escape(r.best_lap)}</td>'
            f'<td class="l">{tyre}</td><td class="hide-sm">{r.pits or ""}</td>'
            f'<td class="team l hide-sm">{escape(r.team_name)}</td></tr>')
    return f'<table class="f1-tower"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def weather_html(weather: pd.DataFrame) -> str:
    if weather.empty:
        return '<p class="f1-panel-title">Weather</p><p>No weather data.</p>'
    w = weather.iloc[-1]
    older = weather[weather["date"] <= w["date"] - pd.Timedelta(minutes=10)]
    prev = older.iloc[-1] if not older.empty else None

    def trend(col: str) -> str:
        if prev is None or pd.isna(prev[col]) or pd.isna(w[col]):
            return ""
        d = float(w[col] - prev[col])
        return f"<i>{'↑' if d > 0 else '↓' if d < 0 else '→'}{abs(d):.1f}</i>" if abs(d) >= 0.1 else ""

    def num(col: str, fmt: str) -> str:
        return format(float(w[col]), fmt) if pd.notna(w[col]) else "–"

    cells = [
        ("Air", f"{num('air_temperature', '.1f')}°{trend('air_temperature')}"),
        ("Track", f"{num('track_temperature', '.1f')}°{trend('track_temperature')}"),
        ("Humidity", f"{num('humidity', '.0f')}%"),
        ("Rain", "Yes" if w["rainfall"] else "No"),
        ("Wind", f"{num('wind_speed', '.1f')} m/s"),
    ]
    body = "".join(f"<div><small>{k}</small><b>{v}</b></div>" for k, v in cells)
    return f'<p class="f1-panel-title">Weather</p><div class="f1-weather">{body}</div>'


def race_control_html(rc: pd.DataFrame, limit: int = 60) -> str:
    title = '<p class="f1-panel-title">Race control</p>'
    if rc.empty:
        return title + "<p>No race control messages.</p>"
    items = []
    for _, m in rc.sort_values("date", ascending=False).head(limit).iterrows():
        flag = str(m.get("flag") or "")
        icon = FLAG_ICON.get(flag) or ("🚗" if m.get("category") == "SafetyCar" else "")
        css = f"flag-{flag.replace(' ', '-')} cat-{m.get('category') or ''}"
        lap = f"Lap {int(m['lap_number'])} · " if pd.notna(m.get("lap_number")) else ""
        t = m["date"].tz_convert(IST).strftime("%H:%M:%S")
        items.append(f'<div class="{escape(css)}">{icon} {escape(str(m["message"]))}'
                     f"<small>{lap}{t} IST</small></div>")
    return title + f'<div class="f1-rc">{"".join(items)}</div>'


def standings_html(df: pd.DataFrame, name_col: str, sub_col: str | None = None) -> str:
    """Championship table in the same broadcast style as the timing tower.
    `df` needs position, colour, points, gap, wins and `name_col` columns."""
    head = ('<tr><th></th><th></th><th class="l">' + ("Driver" if sub_col else "Team") +
            '</th><th>Pts</th><th>Gap</th><th class="hide-sm">Wins</th>' +
            ('<th class="l hide-sm">Team</th>' if sub_col else "") + "</tr>")
    rows = []
    for r in df.itertuples(index=False):
        pos = "" if pd.isna(r.position) else int(r.position)
        gap = '<span class="leader">LEADER</span>' if r.gap == 0 else f"−{r.gap:g}"
        sub = f'<td class="team l hide-sm">{escape(str(getattr(r, sub_col)))}</td>' if sub_col else ""
        rows.append(
            f'<tr><td class="pos">{pos}</td>'
            f'<td class="bar" style="background:{escape(r.colour)}"></td>'
            f'<td class="code l">{escape(str(getattr(r, name_col)))}</td>'
            f'<td><b>{r.points:g}</b></td><td>{gap}</td>'
            f'<td class="hide-sm">{r.wins}</td>{sub}</tr>')
    return f'<table class="f1-tower"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'
