#!/usr/bin/env python3
import os
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from analytics_store import connect


DB_PATH = Path(os.getenv("ANALYTICS_DB", "/data/state/analytics.sqlite"))

GREEN = "#17803d"
BLUE = "#2563eb"
AMBER = "#d97706"
TEXT = "#111827"
MUTED = "#6b7280"
BORDER = "#d7dde5"


st.set_page_config(
    page_title="Plant Analytics",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_styles() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --plant-green: {GREEN};
            --coverage-blue: {BLUE};
            --activity-amber: {AMBER};
            --text-main: {TEXT};
            --text-muted: {MUTED};
            --border-soft: {BORDER};
        }}
        .stApp {{
            background: #f7f8fa;
            color: var(--text-main);
        }}
        h1, h2, h3, label, .stMarkdown, .stDataFrame {{
            color: var(--text-main);
        }}
        .page-title {{
            font-size: 2rem;
            line-height: 1.15;
            font-weight: 760;
            margin: 0 0 0.25rem 0;
            color: var(--text-main);
        }}
        .page-subtitle {{
            color: var(--text-muted);
            font-size: 1rem;
            margin-bottom: 1.25rem;
        }}
        .metric-card {{
            background: #ffffff;
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            min-height: 118px;
            box-shadow: 0 1px 2px rgba(17, 24, 39, 0.04);
        }}
        .metric-label {{
            color: var(--text-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.55rem;
        }}
        .metric-value {{
            color: var(--text-main);
            font-size: 1.55rem;
            font-weight: 760;
            line-height: 1.2;
            word-break: break-word;
        }}
        .metric-note {{
            color: var(--text-muted);
            font-size: 0.86rem;
            margin-top: 0.45rem;
        }}
        .section-title {{
            color: var(--text-main);
            font-size: 1.15rem;
            font-weight: 730;
            margin: 1.2rem 0 0.6rem 0;
        }}
        .detail-path {{
            color: var(--text-muted);
            font-size: 0.86rem;
            overflow-wrap: anywhere;
        }}
        .empty-state {{
            background: #ffffff;
            border: 1px solid var(--border-soft);
            border-radius: 8px;
            padding: 2rem;
            color: var(--text-main);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=10)
def load_analytics(db_path: str) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()

    try:
        with connect(path) as conn:
            df = pd.read_sql_query(
                """
                SELECT
                    source_path,
                    output_path,
                    processed_at,
                    foreground_pixels,
                    total_pixels,
                    foreground_ratio,
                    mask_count,
                    source_mtime_ns,
                    source_size_bytes
                FROM image_analytics
                ORDER BY processed_at DESC
                """,
                conn,
            )
    except sqlite3.Error as exc:
        st.error(f"Could not read analytics database: {exc}")
        return pd.DataFrame()

    if df.empty:
        return df

    df["processed_at"] = pd.to_datetime(df["processed_at"], errors="coerce", utc=True)
    df["filename"] = df["source_path"].apply(lambda p: Path(str(p)).name)
    df["coverage_percent"] = df["foreground_ratio"] * 100
    return df.dropna(subset=["processed_at"]).sort_values("processed_at", ascending=False)


def metric_card(label: str, value: str, note: str = "", accent: str = GREEN) -> None:
    st.markdown(
        f"""
        <div class="metric-card" style="border-top: 4px solid {accent};">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_int(value: int | float) -> str:
    return f"{int(value):,}"


def filter_data(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    st.sidebar.header("Controls")
    search = st.sidebar.text_input("Search filename", placeholder="capture_20260601")

    min_day = df["processed_at"].min().date()
    max_day = df["processed_at"].max().date()
    selected_days = st.sidebar.date_input(
        "Processed date range",
        value=(min_day, max_day),
        min_value=min_day,
        max_value=max_day,
    )
    metric_focus = st.sidebar.radio(
        "Chart focus",
        ["Plant pixels", "Coverage ratio", "Mask count"],
        index=0,
    )

    filtered = df.copy()
    if search:
        needle = search.strip().lower()
        filtered = filtered[filtered["filename"].str.lower().str.contains(needle, na=False)]

    if isinstance(selected_days, tuple) and len(selected_days) == 2:
        start_day, end_day = selected_days
    elif isinstance(selected_days, date):
        start_day = end_day = selected_days
    else:
        start_day, end_day = min_day, max_day

    start_ts = pd.Timestamp(start_day, tz="UTC")
    end_ts = pd.Timestamp(end_day, tz="UTC") + pd.Timedelta(days=1)
    filtered = filtered[
        (filtered["processed_at"] >= start_ts) & (filtered["processed_at"] < end_ts)
    ]

    return filtered, metric_focus


def chart_layout(title: str, y_title: str) -> dict:
    return {
        "title": {"text": title, "font": {"size": 18, "color": TEXT}},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "font": {"color": TEXT, "size": 13},
        "height": 390,
        "margin": {"l": 48, "r": 28, "t": 58, "b": 48},
        "hovermode": "x unified",
        "xaxis": {
            "title": "Processed time",
            "showgrid": True,
            "gridcolor": "#eef1f5",
            "linecolor": BORDER,
        },
        "yaxis": {
            "title": y_title,
            "showgrid": True,
            "gridcolor": "#eef1f5",
            "linecolor": BORDER,
        },
        "legend": {"orientation": "h", "y": 1.08, "x": 0},
    }


def render_charts(df: pd.DataFrame, metric_focus: str) -> None:
    chart_df = df.sort_values("processed_at")
    st.markdown('<div class="section-title">Growth Trends</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Focused metric", "All metrics"])

    focus_map = {
        "Plant pixels": ("foreground_pixels", "Plant pixels", GREEN, "pixels"),
        "Coverage ratio": ("coverage_percent", "Coverage ratio", BLUE, "percent"),
        "Mask count": ("mask_count", "Mask count", AMBER, "masks"),
    }
    col_name, label, color, y_title = focus_map[metric_focus]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["processed_at"],
            y=chart_df[col_name],
            mode="lines+markers",
            name=label,
            line={"color": color, "width": 3},
            marker={"size": 8, "color": color},
            customdata=chart_df["filename"],
            hovertemplate="%{customdata}<br>%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(**chart_layout(label, y_title))
    tabs[0].plotly_chart(fig, use_container_width=True)

    combined = go.Figure()
    combined.add_trace(
        go.Scatter(
            x=chart_df["processed_at"],
            y=chart_df["foreground_pixels"],
            mode="lines+markers",
            name="Plant pixels",
            line={"color": GREEN, "width": 3},
            marker={"size": 7},
            yaxis="y",
        )
    )
    combined.add_trace(
        go.Scatter(
            x=chart_df["processed_at"],
            y=chart_df["coverage_percent"],
            mode="lines+markers",
            name="Coverage %",
            line={"color": BLUE, "width": 3},
            marker={"size": 7},
            yaxis="y2",
        )
    )
    combined.add_trace(
        go.Scatter(
            x=chart_df["processed_at"],
            y=chart_df["mask_count"],
            mode="lines+markers",
            name="Mask count",
            line={"color": AMBER, "width": 2},
            marker={"size": 7},
            yaxis="y3",
            visible="legendonly",
        )
    )
    combined.update_layout(**chart_layout("Plant Pixels And Coverage", "Plant pixels"))
    combined.update_layout(
        yaxis2={
            "title": "Coverage %",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "linecolor": BORDER,
        },
        yaxis3={
            "title": "Masks",
            "overlaying": "y",
            "side": "right",
            "position": 0.95,
            "showgrid": False,
            "visible": False,
        },
    )
    tabs[1].plotly_chart(combined, use_container_width=True)


def render_table(df: pd.DataFrame) -> pd.DataFrame | None:
    st.markdown('<div class="section-title">Processed Images</div>', unsafe_allow_html=True)

    table = df[
        [
            "filename",
            "processed_at",
            "foreground_pixels",
            "coverage_percent",
            "mask_count",
            "source_path",
        ]
    ].copy()
    table["processed_at"] = table["processed_at"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    table["coverage_percent"] = table["coverage_percent"].map(lambda v: f"{v:.2f}%")
    table["foreground_pixels"] = table["foreground_pixels"].map(lambda v: f"{int(v):,}")
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "filename": "File",
            "processed_at": "Processed",
            "foreground_pixels": "Plant pixels",
            "coverage_percent": "Coverage",
            "mask_count": "Masks",
            "source_path": "Source path",
        },
    )

    choices = df["source_path"].tolist()
    if not choices:
        return None
    selected = st.selectbox(
        "Select image to review",
        choices,
        format_func=lambda p: Path(str(p)).name,
    )
    return df[df["source_path"] == selected].iloc[0]


def render_image(path_value: str, caption: str) -> None:
    path = Path(str(path_value))
    if not path.exists():
        st.info(f"{caption} is unavailable at this path.")
        st.markdown(f'<div class="detail-path">{path}</div>', unsafe_allow_html=True)
        return
    try:
        st.image(Image.open(path), caption=caption, use_container_width=True)
        st.markdown(f'<div class="detail-path">{path}</div>', unsafe_allow_html=True)
    except Exception as exc:
        st.warning(f"Could not open {caption.lower()}: {exc}")
        st.markdown(f'<div class="detail-path">{path}</div>', unsafe_allow_html=True)


def render_review(row: pd.Series | None) -> None:
    if row is None:
        return

    st.markdown('<div class="section-title">Image Review</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="detail-path">
        <strong>{row["filename"]}</strong><br>
        Processed {row["processed_at"].strftime("%Y-%m-%d %H:%M:%S UTC")} |
        {format_int(row["foreground_pixels"])} plant pixels |
        {row["coverage_percent"]:.2f}% coverage
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns(2)
    with left:
        render_image(row["output_path"], "Masked output")
    with right:
        render_image(row["source_path"], "Source image")


def main() -> None:
    apply_styles()
    st.markdown('<div class="page-title">Plant Analytics</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Interactive SAM3 growth metrics and image review.</div>',
        unsafe_allow_html=True,
    )

    df = load_analytics(str(DB_PATH))
    if df.empty:
        st.markdown(
            """
            <div class="empty-state">
                <h3>No processed images yet</h3>
                <p>Once the SAM3 pipeline processes an image, analytics will appear here.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"Analytics database: {DB_PATH}")
        return

    filtered, metric_focus = filter_data(df)
    if filtered.empty:
        st.info("No processed images match the current filters.")
        return

    latest = filtered.sort_values("processed_at", ascending=False).iloc[0]
    cols = st.columns(4)
    with cols[0]:
        metric_card("Processed Images", format_int(len(filtered)), "Matching current filters", GREEN)
    with cols[1]:
        metric_card(
            "Latest Plant Pixels",
            format_int(latest["foreground_pixels"]),
            latest["filename"],
            GREEN,
        )
    with cols[2]:
        metric_card(
            "Latest Coverage",
            f"{latest['coverage_percent']:.2f}%",
            f"{format_int(latest['total_pixels'])} total pixels",
            BLUE,
        )
    with cols[3]:
        metric_card(
            "Latest Activity",
            latest["processed_at"].strftime("%b %d, %H:%M"),
            "UTC",
            AMBER,
        )

    render_charts(filtered, metric_focus)
    selected_row = render_table(filtered)
    render_review(selected_row)


if __name__ == "__main__":
    main()
