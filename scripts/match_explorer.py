import sys
import os

# 1. Dynamically add the root directory
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import streamlit as st
import pandas as pd
import json
from src.config import LOL_DB_PATH, DATA_DIR
from src.static_data import load_static_map

# --- App Config ---
st.set_page_config(page_title="LoL Data Miner", layout="wide")
st.title("League of Legends Deep Data Miner 💎")

# --- Constants & Helpers ---
PATCH = "16.5.1"  # Default fallback
DDRAGON_URL = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/img"

@st.cache_data
def load_queue_map():
    """Loads queue mapping from static cache."""
    # Try current patch
    static_queues = load_static_map(PATCH, "queues")
    if static_queues:
        # Riot's queues.json is a list of dicts. 
        # Use 'or' to handle keys that exist but are explicitly None
        return {
            q["queueId"]: (q.get("description") or f"Mode {q['queueId']}").replace(" games", "") 
            for q in static_queues if "queueId" in q
        }
    
    # Fallback to standard hardcoded map if sync hasn't run
    return {
        0: "Custom", 400: "Normal Draft", 420: "Ranked Solo", 430: "Normal Blind", 440: "Ranked Flex",
        450: "ARAM", 490: "Normal Quickplay", 700: "Clash", 720: "ARAM Clash"
    }

QUEUE_MAP = load_queue_map()

def get_queue_name(qid):
    name = QUEUE_MAP.get(qid, f"Special Mode ({qid})")
    # Clean up Riot's verbose descriptions
    return name.replace("5v5 ", "").replace("Summoner's Rift ", "")

@st.cache_data
def load_accounts():
    if os.path.exists(LOL_DB_PATH):
        with open(LOL_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("lol_accounts", [])
    return []

# --- Initialize Session State for Persistence ---
if "selected_queues" not in st.session_state:
    st.session_state.selected_queues = []
if "selected_champs" not in st.session_state:
    st.session_state.selected_champs = []

# --- Data Loading ---
accounts = load_accounts()
account_options = {f"{acc['account_name']}#{acc['riot_tagline']}": acc.get('puuid') for acc in accounts if acc.get('puuid')}

if not account_options:
    st.warning("No accounts with a PUUID found. Run the main updater first!")
    st.stop()

# Add "ALL Accounts" option
selector_options = ["ALL Accounts"] + list(account_options.keys())
selected_account = st.sidebar.selectbox("Select Account", selector_options)

matches_dir = os.path.join(os.path.dirname(LOL_DB_PATH), "matches")

all_parsed_matches = []

# Logic to load matches (Single or All)
targets = account_options.items() if selected_account == "ALL Accounts" else [(selected_account, account_options[selected_account])]

for acc_name, target_puuid in targets:
    match_file = os.path.join(matches_dir, f"{target_puuid}.json")
    if os.path.exists(match_file):
        with open(match_file, "r", encoding="utf-8") as f:
            raw_matches_list = json.load(f)
            
        for m in raw_matches_list:
            info = m.get("info", {})
            player = next((p for p in info.get("participants", []) if p.get("puuid") == target_puuid), None)
            if not player: continue

            challenges = player.get("challenges", {})
            game_duration = info.get("gameDuration", 1)
            minutes = game_duration / 60.0
            
            kills = player.get("kills", 0)
            deaths = player.get("deaths", 0)
            assists = player.get("assists", 0)

            all_parsed_matches.append({
                "Match ID": m.get("metadata", {}).get("matchId"),
                "Account": acc_name,
                "puuid": target_puuid, # Critical for Raw Data Tab
                "Date": pd.to_datetime(info.get("gameCreation"), unit='ms'),
                "Queue": get_queue_name(info.get("queueId")),
                "Champion": player.get("championName"),
                "ChampIcon": f"{DDRAGON_URL}/champion/{player.get('championName')}.png",
                "Result": "Win" if player.get("win") else "Loss",
                "Role": player.get("individualPosition"),
                "K": kills,
                "D": deaths,
                "A": assists,
                "K/D/A": f"{kills}/{deaths}/{assists}",
                "KDA Ratio": round((kills + assists) / max(1, deaths), 2),
                "Solo Kills": int(challenges.get("soloKills", 0)),
                "Multi Kills": player.get("largestMultiKill", 0),
                "CS/min": round((player.get("totalMinionsKilled", 0) + player.get("neutralMinionsKilled", 0)) / max(1, minutes), 1),
                "Dmg/min": int(challenges.get("damagePerMinute", player.get("totalDamageDealtToChampions", 0) / max(1, minutes))),
                "Gold/min": int(challenges.get("goldPerMinute", player.get("goldEarned", 0) / max(1, minutes))),
                "Vision": player.get("visionScore", 0)
            })

if all_parsed_matches:
    df = pd.DataFrame(all_parsed_matches)
    # Deduplicate matches if multiple accounts are in the same game
    if selected_account == "ALL Accounts":
        df = df.drop_duplicates(subset=["Match ID", "puuid"])

    # --- Sidebar Filtering ---
    st.sidebar.markdown("---")
    
    # Persistent filter logic with Ranked-only defaults
    available_queues = sorted(df["Queue"].unique())
    default_queues = [q for q in ["Ranked Solo", "Ranked Flex"] if q in available_queues]
    
    if not st.session_state.selected_queues:
        st.session_state.selected_queues = default_queues
        
    with st.sidebar.expander("🔍 Filter Matches", expanded=True):
        queues = st.multiselect("Game Modes", available_queues, default=st.session_state.selected_queues)
        st.session_state.selected_queues = queues
        
        available_champs = sorted(df["Champion"].unique())
        champs = st.multiselect("Champions", available_champs, default=[c for c in st.session_state.selected_champs if c in available_champs])
        st.session_state.selected_champs = champs
        
        if st.button("Reset to Ranked Only"):
            st.session_state.selected_queues = default_queues
            st.session_state.selected_champs = []
            st.rerun()
    
    filtered_df = df[df["Queue"].isin(queues)]
    if champs:
        filtered_df = filtered_df[filtered_df["Champion"].isin(champs)]

    if filtered_df.empty:
        st.warning("No matches match the selected filters.")
        st.stop()

    # --- Header Metrics ---
    m1, m2, m3, m4 = st.columns(4)
    winrate = (filtered_df["Result"] == "Win").mean() * 100
    m1.metric("Winrate", f"{winrate:.1f}%")
    m2.metric("Avg KDA", f"{filtered_df['KDA Ratio'].mean():.2f}")
    m3.metric("Avg Dmg/min", f"{int(filtered_df['Dmg/min'].mean())}")
    m4.metric("Avg Gold/min", f"{int(filtered_df['Gold/min'].mean())}")

    # --- Dashboard Tabs ---
    tab_history, tab_champs, tab_roles, tab_raw = st.tabs(["🕒 Match History", "🏆 Champion Analytics", "🛡️ Positional Data", "🔍 Raw Data Explorer"])

    with tab_history:
        st.subheader("Match History Details")
        display_cols = ["Date", "ChampIcon", "Champion", "Result", "K", "D", "A", "KDA Ratio", "Solo Kills", "CS/min", "Dmg/min", "Gold/min", "Queue"]
        if selected_account == "ALL Accounts":
            display_cols.insert(1, "Account")
            
        st.dataframe(
            filtered_df[display_cols].sort_values("Date", ascending=False),
            column_config={
                "ChampIcon": st.column_config.ImageColumn("Icon"),
                "Date": st.column_config.DatetimeColumn(format="D MMM, YY - HH:mm"),
                "Result": st.column_config.TextColumn("Result"),
            },
            use_container_width=True,
            hide_index=True
        )

    with tab_champs:
        st.subheader("Performance by Champion")
        champ_stats = filtered_df.groupby("Champion").agg({
            "Result": lambda x: f"{(x == 'Win').mean()*100:.1f}%",
            "Match ID": "count",
            "K": "mean",
            "D": "mean",
            "A": "mean",
            "KDA Ratio": "mean",
            "Dmg/min": "mean",
            "Solo Kills": "sum"
        }).rename(columns={"Result": "Winrate", "Match ID": "Games", "K": "Avg K", "D": "Avg D", "A": "Avg A", "KDA Ratio": "Avg KDA", "Dmg/min": "Avg Dmg/min", "Solo Kills": "Total Solo Kills"})
        
        # Format means to 1 decimal place
        for col in ["Avg K", "Avg D", "Avg A", "Avg KDA", "Avg Dmg/min"]:
            champ_stats[col] = champ_stats[col].round(1)
            
        st.dataframe(champ_stats.sort_values("Games", ascending=False), use_container_width=True)

    with tab_roles:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Games per Role")
            role_counts = filtered_df["Role"].value_counts()
            st.bar_chart(role_counts)
        with c2:
            st.subheader("Winrate per Role")
            role_wr = filtered_df.groupby("Role")["Result"].apply(lambda x: (x == 'Win').mean() * 100)
            st.bar_chart(role_wr)

    with tab_raw:
        st.subheader("JSON Inspection (Idea Gathering)")
        st.write("Select a match to see every single field Riot provides in the match-v5 JSON.")
        
        # Create a selectbox for recent matches to inspect
        match_options_df = filtered_df.sort_values("Date", ascending=False)
        match_labels = match_options_df.apply(lambda x: f"{x['Date'].strftime('%Y-%m-%d')} - {x['Champion']} ({x['Result']}) [{x['Account']}]", axis=1).tolist()
        
        selected_match_label = st.selectbox("Select Match to Inspect", match_labels)
        selected_idx = match_labels.index(selected_match_label)
        selected_row = match_options_df.iloc[selected_idx]
        
        selected_match_id = selected_row["Match ID"]
        selected_puuid = selected_row["puuid"]
        
        # Reload the specific file for this match's account
        target_file = os.path.join(matches_dir, f"{selected_puuid}.json")
        with open(target_file, "r", encoding="utf-8") as f:
            search_matches = json.load(f)
            
        target_raw = next((m for m in search_matches if m.get("metadata", {}).get("matchId") == selected_match_id), None)
        
        if target_raw:
            col_json, col_player = st.columns(2)
            
            with col_json:
                st.markdown("**Full Match JSON**")
                st.json(target_raw, expanded=False)
                
            with col_player:
                st.markdown("**Your Specific Participant Data**")
                p_data = next((p for p in target_raw.get("info", {}).get("participants", []) if p.get("puuid") == selected_puuid), {})
                st.json(p_data, expanded=True)
        else:
            st.error("Could not find raw data for the selected match.")

else:
    st.info("No match history found for the selected account(s).")
