"""
history.py — Local history manager for portfolio snapshots.

Snapshots are stored in history.json as a list of daily records.
Note: On Streamlit Cloud, the filesystem is ephemeral (resets on redeploy).
For persistent history, commit history.json to your GitHub repo periodically,
or use an external store (e.g., GitHub Gist via API, or Streamlit's st.session_state
to maintain in-memory history within a session).
"""

import json
import os
import pandas as pd
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")


def save_snapshot(data: dict) -> None:
    """
    Append (or update) a daily snapshot to history.json.

    Expected data keys:
        date (str YYYY-MM-DD),
        total_usd (float),
        fintual_clp (float),
        falabella_clp (float),
        ibkr_usd (float or None),
        clp_usd_rate (float),
        eur_usd_rate (float),
    """
    today = data.get("date") or datetime.today().strftime("%Y-%m-%d")
    data["date"] = today

    # Load existing history
    history = _load_raw_history()

    # Check if today's entry already exists — update it
    updated = False
    for i, entry in enumerate(history):
        if entry.get("date") == today:
            history[i] = data
            updated = True
            break

    if not updated:
        history.append(data)

    # Keep only the last 365 entries to avoid unbounded growth
    history = sorted(history, key=lambda x: x.get("date", ""))[-365:]

    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # Non-fatal — just log to stderr; app continues
        print(f"Warning: could not save history snapshot: {e}")


def load_history() -> pd.DataFrame:
    """
    Load historical snapshots as a DataFrame.
    Columns: date, total_usd, fintual_clp, falabella_clp, ibkr_usd
    Returns empty DataFrame if file doesn't exist or is empty.
    """
    history = _load_raw_history()
    if not history:
        return pd.DataFrame(
            columns=["date", "total_usd", "fintual_clp", "falabella_clp", "ibkr_usd"]
        )

    df = pd.DataFrame(history)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)

    return df


def _load_raw_history() -> list:
    """Internal helper — load raw list from history.json."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []
