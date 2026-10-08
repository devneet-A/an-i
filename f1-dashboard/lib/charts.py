"""Plotly figures for the Analysis page. Data in, figure out; no Streamlit here.

Shared look (applied by `_style`):
- transparent background so charts sit on the app's dark theme
- thin solid gridlines one step off the background, never dashed
- 2px lines, markers >= 8px with a ring in the background colour
- text (labels, legend, axes) in neutral greys, never in the team colour
- one y-axis per chart; different measures get their own panel
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from lib.timeutils import format_laptime

SURFACE = "#0B0B0F"     # app background (.streamlit/config.toml)
GRID = "#24242C"        # one step lighter than the surface
INK = "#E6E6EA"         # primary text
INK_MUTED = "#9A9AA6"   # axis text

# Pirelli's own tyre colours: fans read these instantly.
COMPOUND_COLOUR: dict[str, str] = {
    "SOFT": "#DA291C", "MEDIUM": "#FFD12E", "HARD": "#F0F0EC",
    "INTERMEDIATE": "#43B02A", "WET": "#0067AD", "UNKNOWN": "#6B6B76",
}

Styles = dict[int, dict[str, str]]


def _style(fig: go.Figure, height: int, y_title: str, x_title: str = "Lap") -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Titillium Web, sans-serif", color=INK_MUTED, size=12),
        margin=dict(l=8, r=8, t=8, b=8),
        # Legend across the top: on a phone a side legend eats half the width.
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK),
                    bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="#16161D", bordercolor=GRID, font=dict(color=INK)),
    )
    axis = dict(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=GRID,
                tickfont=dict(color=INK_MUTED))
    fig.update_xaxes(title_text=x_title, **axis)
    fig.update_yaxes(title_text=y_title, **axis)
    return fig


def _line(df: pd.DataFrame, x: str, y: str, style: dict[str, str], **kwargs) -> go.Scatter:
    """A 2px line in the driver's colour/dash. kwargs can override any default."""
    props = dict(x=df[x], y=df[y], mode="lines", name=style["code"],
                 line=dict(color=style["colour"], width=2, dash=style["dash"]),
                 legendgroup=style["code"])
    return go.Scatter(**(props | kwargs))


def lap_time_chart(laps: pd.DataFrame, styles: Styles, drivers: list[int]) -> go.Figure:
    fig = go.Figure()
    for n in drivers:
        d = laps[laps["driver_number"] == n]
        if d.empty:
            continue
        fig.add_trace(_line(
            d, "lap_number", "lap_duration", styles[n],
            mode="lines+markers",
            marker=dict(size=8, color=styles[n]["colour"], line=dict(color=SURFACE, width=2)),
            customdata=d["lap_duration"].map(format_laptime),
            hovertemplate=f"{styles[n]['code']} %{{customdata}}<extra></extra>",
        ))
    fig.update_layout(hovermode="x unified")
    _style(fig, 440, "Lap time (s)")
    return fig


def position_chart(positions: pd.DataFrame, styles: Styles, drivers: list[int]) -> go.Figure:
    fig = go.Figure()
    for n in drivers:
        d = positions[positions["driver_number"] == n]
        if d.empty:
            continue
        fig.add_trace(_line(d, "lap_number", "position", styles[n],
                            hovertemplate=f"{styles[n]['code']} P%{{y}}<extra></extra>"))
        # Direct label at the end of each line: final positions never collide.
        last = d.iloc[-1]
        fig.add_annotation(x=last["lap_number"], y=last["position"], text=styles[n]["code"],
                           xanchor="left", xshift=6, showarrow=False, font=dict(color=INK, size=11))
    fig.update_layout(hovermode="x unified")
    _style(fig, 480, "Position")
    # P1 at the top, every position labelled.
    fig.update_yaxes(autorange="reversed", dtick=1)
    return fig


def gap_chart(gaps: pd.DataFrame, styles: Styles, drivers: list[int]) -> go.Figure:
    fig = go.Figure()
    for n in drivers:
        d = gaps[gaps["driver_number"] == n]
        if d.empty:
            continue
        fig.add_trace(_line(d, "lap_number", "gap_s", styles[n],
                            hovertemplate=f"{styles[n]['code']} +%{{y:.1f}}s<extra></extra>"))
    fig.update_layout(hovermode="x unified")
    _style(fig, 440, "Gap to leader (s)")
    fig.update_yaxes(autorange="reversed")  # leader (0s) at the top, like a timing tower
    return fig


def stint_chart(stints: pd.DataFrame, styles: Styles, drivers: list[int]) -> go.Figure:
    """Horizontal bars: one row per driver, one segment per stint."""
    fig = go.Figure()
    order = [styles[n]["code"] for n in drivers if n in styles]
    shown: set[str] = set()
    for _, s in stints[stints["driver_number"].isin(drivers)].iterrows():
        compound = s["compound"] if s["compound"] in COMPOUND_COLOUR else "UNKNOWN"
        fig.add_trace(go.Bar(
            y=[styles[s["driver_number"]]["code"]], x=[s["laps"]], base=[s["lap_start"] - 1],
            orientation="h", name=compound.title(), legendgroup=compound,
            showlegend=compound not in shown,
            # 2px line in the background colour = the gap between touching stints.
            marker=dict(color=COMPOUND_COLOUR[compound], line=dict(color=SURFACE, width=2)),
            # Only label stints long enough for the letter to fit inside.
            text=[compound[0] if s["laps"] >= 4 else ""], textposition="inside",
            insidetextanchor="middle", textangle=0,  # keep letters upright
            legendrank=list(COMPOUND_COLOUR).index(compound),  # legend: soft -> wet
            textfont=dict(color="#111111" if compound in ("MEDIUM", "HARD") else "#FFFFFF"),
            hovertemplate=(f"{styles[s['driver_number']]['code']} · {compound.title()}<br>"
                           f"Laps {int(s['lap_start'])}–{int(s['lap_end'])} "
                           f"({int(s['laps'])} laps, tyre {int(s['tyre_age_at_start']) if pd.notna(s['tyre_age_at_start']) else '?'} laps old at fitting)"
                           "<extra></extra>"),
        ))
        shown.add(compound)
    # ~34px per driver with a 0.35 gap gives ~20px bars: under the 24px cap,
    # with air between rows, and tall enough for the compound letter.
    _style(fig, 70 + 34 * max(len(order), 1), "", "Lap")
    fig.update_layout(barmode="overlay", bargap=0.35,
                      uniformtext=dict(minsize=11, mode="show"))
    fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], showgrid=False)
    return fig


def telemetry_chart(laps: dict[int, pd.DataFrame], styles: Styles) -> go.Figure:
    """Speed, throttle, brake and gear vs distance as four stacked panels
    sharing the distance axis (instead of one chart with several y-axes)."""
    panels = [("speed", "Speed (km/h)"), ("throttle", "Throttle (%)"),
              ("brake", "Brake"), ("n_gear", "Gear")]
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.4, 0.22, 0.14, 0.24])
    for n, df in laps.items():
        for row, (col, _) in enumerate(panels, start=1):
            fig.add_trace(_line(df, "distance_m", col, styles[n], showlegend=row == 1,
                                hovertemplate=f"{styles[n]['code']} %{{y}}<extra></extra>"),
                          row=row, col=1)
    _style(fig, 640, "", "Distance (m)")
    for row, (_, title) in enumerate(panels, start=1):
        fig.update_yaxes(title_text=title, row=row, col=1)
        if row < len(panels):
            fig.update_xaxes(title_text="", row=row, col=1)
    fig.update_layout(hovermode="x unified")
    return fig


def progression_chart(totals: pd.DataFrame, by: str, colours: dict[str, str],
                      dashes: dict[str, str]) -> go.Figure:
    """Championship points after each round, one line per driver or team."""
    fig = go.Figure()
    # Draw the leader last so their line sits on top.
    final = totals[totals["round"] == totals["round"].max()].sort_values("total")
    for name in final[by]:
        d = totals[totals[by] == name]
        fig.add_trace(go.Scatter(
            x=d["round"], y=d["total"], mode="lines+markers", name=str(name),
            line=dict(color=colours.get(name, "#888888"), width=2, dash=dashes.get(name, "solid")),
            marker=dict(size=8, color=colours.get(name, "#888888"), line=dict(color=SURFACE, width=2)),
            hovertemplate=f"{name} %{{y:.0f}} pts<extra></extra>",
        ))
    # Legend in championship order (leader first) instead of drawing order.
    for rank, trace in enumerate(reversed(fig.data)):
        trace.legendrank = rank
    fig.update_layout(hovermode="x unified")
    _style(fig, 460, "Points", "Round")
    fig.update_xaxes(dtick=1)
    return fig
