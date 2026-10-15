"""Streamlit dashboard on top of the dbt marts.  Run: streamlit run dashboard/app.py"""
import math
import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DB = Path(os.getenv("DUCKDB_PATH", Path(__file__).resolve().parents[1] / "data" / "warehouse" / "dota.duckdb"))

st.set_page_config(page_title="Dota 2 Meta", page_icon="🎮", layout="wide")
st.title("🎮 Dota 2 public match meta")

if not DB.exists():
    st.error(f"Database not found at {DB}. Run the pipeline first (see README).")
    st.stop()


@st.cache_data(ttl=60)
def q(sql: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def wilson(wins: pd.Series, games: pd.Series, z: float = 1.96) -> tuple[pd.Series, pd.Series]:
    p = wins / games
    centre = p + z * z / (2 * games)
    margin = z * ((p * (1 - p) + z * z / (4 * games)) / games).map(math.sqrt)
    denom = 1 + z * z / games
    return (centre - margin) / denom, (centre + margin) / denom


daily = q("select * from marts.mart_daily_matches")
ranks = q("select rank_medal_id, rank_medal_name from reference.rank_tiers order by 1")

with st.sidebar:
    st.header("Filters")
    rank_choice = st.selectbox("Rank", ["All ranks"] + ranks.rank_medal_name.tolist())
    min_games = st.slider("Minimum games per hero", 0, 500, 50, step=10)

if rank_choice == "All ranks":
    heroes = q("select hero_name, games, wins, pick_rate from marts.mart_hero_winrate")
else:
    heroes = q(
        f"select hero_name, games, wins, pick_rate from marts.mart_hero_winrate_by_rank "
        f"where rank_medal_name = '{rank_choice}'"
    )
heroes = heroes[heroes.games >= min_games].copy()
heroes["win_rate"] = heroes.wins / heroes.games
heroes["ci_low"], heroes["ci_high"] = wilson(heroes.wins, heroes.games)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Matches analysed", f"{int(daily.matches.sum()):,}")
c2.metric("Heroes shown", len(heroes))
c3.metric("Avg duration", f"{(daily.avg_duration_min * daily.matches).sum() / daily.matches.sum():.1f} min")
c4.metric("Radiant win rate", f"{(daily.radiant_win_rate * daily.matches).sum() / daily.matches.sum() * 100:.1f}%")

left, right = st.columns([3, 2])
with left:
    st.subheader(f"Hero win rates: {rank_choice}")
    st.caption("Sorted by the LOWER bound of the 95% Wilson interval, so heroes with few games don't top the list.")
    table = heroes.sort_values("ci_low", ascending=False)[
        ["hero_name", "games", "win_rate", "ci_low", "ci_high", "pick_rate"]
    ].copy()
    for col in ["win_rate", "ci_low", "ci_high", "pick_rate"]:
        table[col] = table[col] * 100
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "hero_name": "Hero",
            "games": st.column_config.NumberColumn("Games", format="%d"),
            "win_rate": st.column_config.NumberColumn("Win %", format="%.1f"),
            "ci_low": st.column_config.NumberColumn("CI low", format="%.1f"),
            "ci_high": st.column_config.NumberColumn("CI high", format="%.1f"),
            "pick_rate": st.column_config.NumberColumn("Pick %", format="%.1f"),
        },
    )
with right:
    st.subheader("Pick rate vs win rate")
    plot = heroes.assign(win_pct=heroes.win_rate * 100, pick_pct=heroes.pick_rate * 100)
    st.scatter_chart(plot, x="pick_pct", y="win_pct", size="games")

st.subheader("Best hero pairs on the same team")
pairs = q(
    "select hero_a_name as hero_a, hero_b_name as hero_b, games, win_rate * 100 as win_pct "
    "from marts.mart_hero_pairs order by win_rate desc limit 15"
)
st.dataframe(pairs, hide_index=True, width="stretch")

st.subheader("Matches per day")
st.line_chart(daily, x="started_date", y="matches")

st.subheader("Data quality: rejected matches")
st.caption("Matches removed before reaching the fact tables, by rule and ingestion day.")
st.dataframe(q("select * from marts.dq_summary"), hide_index=True, width="stretch")
