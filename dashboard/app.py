"""
dashboard/app.py
----------------
Production Streamlit dashboard for the E-Commerce Intelligence Pipeline.

Features:
  • Run the full pipeline directly from the UI (no terminal needed)
  • Live KPI cards: total books, avg price, avg rating, top genre
  • 4 Plotly charts: genre bar, rating dist, price-vs-rating scatter, sentiment donut
  • Sidebar filters: genre, rating, price range, search
  • Book Spotlight: highest-value-score book with AI summary
  • Sortable, searchable data table
  • One-click CSV download

Run:  streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path regardless of how streamlit is invoked
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import settings
from data.database import load_all_books, get_stats


# ── Page config (must be first Streamlit call) ────────────────────────────────

st.set_page_config(
    page_title=settings.APP_TITLE,
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Theme constants ───────────────────────────────────────────────────────────

COLORS = {
    "primary":   "#7C6AF7",
    "secondary": "#E8A838",
    "success":   "#22C55E",
    "danger":    "#EF4444",
    "neutral":   "#8B8B8B",
    "genres":    px.colors.qualitative.Pastel,
}

SENTIMENT_COLORS = {
    "Positive": COLORS["success"],
    "Neutral":  COLORS["neutral"],
    "Negative": COLORS["danger"],
}

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font_color="#CCCCCC",
    margin=dict(t=40, b=20, l=10, r=10),
)


# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* Tighten default padding */
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

/* KPI section label */
.section-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #888;
    margin-bottom: 0.5rem;
}

/* Spotlight card */
.spotlight-card {
    background: linear-gradient(135deg, #1e1b4b, #312e81);
    border: 1px solid #4f46e5;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
}
.spotlight-title { font-size: 1.1rem; font-weight: 600; color: #e0e7ff; }
.spotlight-meta  { font-size: 0.8rem; color: #a5b4fc; margin: 0.4rem 0; }
.spotlight-summary { font-size: 0.85rem; color: #c7d2fe; line-height: 1.6; }

/* Value badge */
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
}
.badge-great   { background: #166534; color: #86efac; }
.badge-fair    { background: #713f12; color: #fcd34d; }
.badge-overpriced { background: #7f1d1d; color: #fca5a5; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _load_data() -> pd.DataFrame:
    return load_all_books()


@st.cache_data(ttl=30)
def _load_stats() -> dict:
    return get_stats()


def _value_label(score: float) -> str:
    if score >= 7.0:
        return "Great Deal"
    elif score >= 4.0:
        return "Fair"
    return "Overpriced"


def _badge_html(label: str) -> str:
    cls = {
        "Great Deal": "badge-great",
        "Fair":       "badge-fair",
        "Overpriced": "badge-overpriced",
    }.get(label, "badge-fair")
    return f'<span class="badge {cls}">{label}</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.image(
        "https://books.toscrape.com/static/oscar/images/logo_1.png",
        use_column_width=True,
    )
    st.sidebar.markdown("## 📚 E-Commerce Intel")
    st.sidebar.markdown("---")

    # ── Pipeline runner ───────────────────────────────────────────────────────
    st.sidebar.markdown("### ⚙️ Run Pipeline")
    pages = st.sidebar.slider("Pages to scrape", min_value=1, max_value=10, value=3)
    skip_ai = st.sidebar.checkbox("Skip AI enrichment (fast test)")

    if st.sidebar.button("🚀 Run Pipeline", use_container_width=True, type="primary"):
        cmd = [sys.executable, "pipeline.py", f"--pages={pages}"]
        if skip_ai:
            cmd.append("--skip-ai")

        with st.sidebar:
            with st.status("Running pipeline…", expanded=True) as status:
                st.write(f"Scraping {pages} pages (~{pages * 20} books)…")
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=str(settings.BASE_DIR),
                    )
                    if result.returncode == 0:
                        st.write("✅ Scraping complete")
                        if not skip_ai:
                            st.write("✅ AI enrichment complete")
                        st.write("✅ Database updated")
                        status.update(label="Pipeline complete!", state="complete")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(f"Pipeline error:\n{result.stderr[-800:]}")
                        status.update(label="Pipeline failed", state="error")
                except FileNotFoundError:
                    st.error("Could not find pipeline.py — run from project root.")
                    status.update(label="Pipeline failed", state="error")

    st.sidebar.markdown("---")

    # ── Filters ───────────────────────────────────────────────────────────────
    if df.empty:
        return df

    st.sidebar.markdown("### 🔎 Filters")

    # Search
    search = st.sidebar.text_input("Search title", placeholder="e.g. Mystery…")
    if search:
        df = df[df["title"].str.contains(search, case=False, na=False)]

    # Genre
    if "genre" in df.columns:
        genres = sorted(df["genre"].dropna().unique().tolist())
        selected_genres = st.sidebar.multiselect("Genre", genres, default=genres)
        df = df[df["genre"].isin(selected_genres)]

    # Minimum rating
    min_rating = st.sidebar.slider("Minimum rating ⭐", 1, 5, 1)
    df = df[df["rating"] >= min_rating]

    # Price range
    if not df.empty:
        min_p, max_p = float(df["price"].min()), float(df["price"].max())
        price_range = st.sidebar.slider(
            "Price range (£)",
            min_value=min_p,
            max_value=max_p,
            value=(min_p, max_p),
        )
        df = df[(df["price"] >= price_range[0]) & (df["price"] <= price_range[1])]

    # Sentiment
    if "sentiment" in df.columns:
        sentiments = ["All"] + sorted(df["sentiment"].dropna().unique().tolist())
        sel_sent = st.sidebar.selectbox("Sentiment", sentiments)
        if sel_sent != "All":
            df = df[df["sentiment"] == sel_sent]

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Showing **{len(df)}** books after filters")

    return df


# ── Charts ────────────────────────────────────────────────────────────────────

def _chart_genre_bar(df: pd.DataFrame):
    if "genre" not in df.columns or df.empty:
        return
    counts = (
        df["genre"]
        .value_counts()
        .reset_index()
        .rename(columns={"genre": "Genre", "count": "Books"})
    )
    fig = px.bar(
        counts, x="Books", y="Genre", orientation="h",
        color="Books", color_continuous_scale="purples",
        title="Books per Genre",
    )
    fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False, height=350)
    fig.update_traces(hovertemplate="<b>%{y}</b>: %{x} books")
    st.plotly_chart(fig, use_container_width=True)


def _chart_rating_dist(df: pd.DataFrame):
    if "rating" not in df.columns or df.empty:
        return
    counts = (
        df["rating"]
        .value_counts()
        .sort_index()
        .reset_index()
        .rename(columns={"rating": "Stars", "count": "Books"})
    )
    star_labels = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}
    counts["Label"] = counts["Stars"].map(star_labels)
    fig = px.bar(
        counts, x="Label", y="Books",
        color="Stars",
        color_continuous_scale=["#ef4444", "#f97316", "#eab308", "#84cc16", "#22c55e"],
        title="Rating Distribution",
    )
    fig.update_layout(**PLOTLY_LAYOUT, coloraxis_showscale=False, height=350)
    st.plotly_chart(fig, use_container_width=True)


def _chart_price_rating_scatter(df: pd.DataFrame):
    if df.empty or "price" not in df.columns:
        return

    plot_df = df.copy()
    if "value_score" in plot_df.columns:
        plot_df["Value Label"] = plot_df["value_score"].apply(_value_label)
    else:
        plot_df["Value Label"] = "Unknown"

    fig = px.scatter(
        plot_df,
        x="price", y="rating",
        color="value_score" if "value_score" in plot_df.columns else None,
        color_continuous_scale="RdYlGn",
        hover_name="title",
        hover_data={"price": ":.2f", "rating": True, "genre": True},
        labels={"price": "Price (£)", "rating": "Rating (stars)", "value_score": "Value"},
        title="Price vs Rating",
        opacity=0.75,
    )
    fig.update_traces(marker_size=8)
    fig.update_layout(**PLOTLY_LAYOUT, height=350)
    st.plotly_chart(fig, use_container_width=True)


def _chart_sentiment_donut(df: pd.DataFrame):
    if "sentiment" not in df.columns or df.empty:
        return
    counts = df["sentiment"].value_counts().reset_index()
    counts.columns = ["Sentiment", "Count"]
    colors = [SENTIMENT_COLORS.get(s, "#888") for s in counts["Sentiment"]]
    fig = go.Figure(
        go.Pie(
            labels=counts["Sentiment"],
            values=counts["Count"],
            hole=0.5,
            marker_colors=colors,
            textinfo="percent+label",
        )
    )
    fig.update_layout(**PLOTLY_LAYOUT, title="Sentiment Distribution", height=350)
    st.plotly_chart(fig, use_container_width=True)


# ── Spotlight ─────────────────────────────────────────────────────────────────

def _render_spotlight(df: pd.DataFrame) -> None:
    if df.empty or "value_score" not in df.columns:
        return

    best = df.loc[df["value_score"].idxmax()]
    label = _value_label(best["value_score"])
    badge = _badge_html(label)
    stars = "⭐" * int(best.get("rating", 0))

    st.markdown(f"""
<div class="spotlight-card">
    <div class="spotlight-title">📖 {best['title']}</div>
    <div class="spotlight-meta">
        {stars} &nbsp;|&nbsp; £{best['price']:.2f}
        &nbsp;|&nbsp; {best.get('genre', 'Unknown')}
        &nbsp;|&nbsp; {badge}
        &nbsp;|&nbsp; Value score: <b>{best['value_score']:.1f}/10</b>
    </div>
    <div class="spotlight-summary">{best.get('summary', 'No summary available.')}</div>
</div>
""", unsafe_allow_html=True)


# ── Data table ────────────────────────────────────────────────────────────────

def _render_table(df: pd.DataFrame) -> None:
    display_cols = [c for c in
        ["title", "genre", "rating", "price", "sentiment", "value_score", "availability", "url"]
        if c in df.columns]

    tbl = df[display_cols].copy()

    if "value_score" in tbl.columns:
        tbl["value_score"] = tbl["value_score"].round(1)

    col_config = {
        "title":       st.column_config.TextColumn("Title",        width="large"),
        "genre":       st.column_config.TextColumn("Genre"),
        "rating":      st.column_config.NumberColumn("Rating ⭐",   format="%d ⭐"),
        "price":       st.column_config.NumberColumn("Price (£)",  format="£%.2f"),
        "sentiment":   st.column_config.TextColumn("Sentiment"),
        "value_score": st.column_config.ProgressColumn(
                            "Value Score", min_value=0, max_value=10, format="%.1f"
                       ),
        "url":         st.column_config.LinkColumn("Link"),
    }

    st.dataframe(
        tbl,
        use_container_width=True,
        height=400,
        column_config=col_config,
        hide_index=True,
    )

    # Download
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️  Download CSV",
        data=csv,
        file_name="ecom_intelligence.csv",
        mime="text/csv",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    raw_df = _load_data()
    stats  = _load_stats()

    # Sidebar (also applies filters and returns filtered df)
    filtered_df = _render_sidebar(raw_df.copy() if not raw_df.empty else pd.DataFrame())

    # ── Header ────────────────────────────────────────────────────────────────
    col_title, col_refresh = st.columns([5, 1])
    with col_title:
        st.title("📚 E-Commerce Intelligence Dashboard")
        if stats:
            last = stats.get("last_scraped", "N/A")
            st.caption(
                f"**{stats.get('total', 0)}** books in database &nbsp;|&nbsp; "
                f"Last scraped: {str(last)[:16]}"
            )
    with col_refresh:
        if st.button("🔄 Refresh", help="Reload data from database"):
            st.cache_data.clear()
            st.rerun()

    # ── Empty state ───────────────────────────────────────────────────────────
    if raw_df.empty:
        st.warning(
            "No data yet. Click **🚀 Run Pipeline** in the sidebar to get started.",
            icon="⚠️",
        )
        st.code(
            "# Or run from terminal:\n"
            "python pipeline.py --pages 3",
            language="bash",
        )
        return

    # ── Book Spotlight ────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">🏆 Top Value Pick</div>', unsafe_allow_html=True)
    _render_spotlight(raw_df)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── KPI Cards ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">📊 Key Metrics</div>', unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)

    k1.metric(
        "Total Books",
        value=stats.get("total", 0),
        delta=f"{stats.get('enriched_count', 0)} AI enriched",
    )
    k2.metric(
        "Avg Price",
        value=f"£{stats.get('avg_price', 0):.2f}",
    )
    k3.metric(
        "Avg Rating",
        value=f"{stats.get('avg_rating', 0):.1f} ⭐",
    )
    k4.metric(
        "Top Genre",
        value=stats.get("top_genre", "N/A"),
    )

    st.markdown("---")

    # ── Charts row 1 ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">📈 Analytics</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        _chart_genre_bar(filtered_df)
    with c2:
        _chart_rating_dist(filtered_df)

    # ── Charts row 2 ─────────────────────────────────────────────────────────
    c3, c4 = st.columns(2)
    with c3:
        _chart_price_rating_scatter(filtered_df)
    with c4:
        _chart_sentiment_donut(filtered_df)

    st.markdown("---")

    # ── Data Table ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="section-label">📋 Full Dataset — {len(filtered_df)} books</div>',
        unsafe_allow_html=True,
    )
    _render_table(filtered_df)


if __name__ == "__main__":
    main()
