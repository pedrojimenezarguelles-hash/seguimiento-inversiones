"""
fetchers.py — All API calls for the investment dashboard.
"""

import requests
import yfinance as yf
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import streamlit as st
import time


# ---------------------------------------------------------------------------
# FX Rates
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_fx_rates() -> dict:
    """
    Fetch CLP/USD and EUR/USD rates from frankfurter.app.
    Returns dict with keys: CLP_USD (how many CLP per 1 USD),
    EUR_USD (how many USD per 1 EUR).
    """
    result = {"CLP_USD": None, "EUR_USD": None, "error": None}
    try:
        # Get EUR and CLP quoted against USD
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "USD", "to": "CLP,EUR"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})

        clp_per_usd = rates.get("CLP")
        eur_per_usd = rates.get("EUR")

        if clp_per_usd:
            result["CLP_USD"] = clp_per_usd  # CLP per 1 USD
        if eur_per_usd and eur_per_usd != 0:
            result["EUR_USD"] = 1 / eur_per_usd  # USD per 1 EUR

    except Exception as e:
        result["error"] = f"Error fetching FX rates: {e}"
        # Fallback approximate values so app doesn't crash
        result["CLP_USD"] = 950.0
        result["EUR_USD"] = 1.08

    return result


# ---------------------------------------------------------------------------
# Fintual
# ---------------------------------------------------------------------------

def _fintual_auth(email: str, password: str) -> str | None:
    """
    Authenticate with Fintual API.
    Returns Bearer token or None on failure.
    """
    try:
        resp = requests.post(
            "https://fintual.cl/api/user_token",
            json={"user": {"email": email, "password": password}},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("data", {}).get("attributes", {}).get("access_token")
        return token
    except Exception:
        return None


def _fintual_get_portfolios(token: str) -> list:
    """Fetch all portfolios for the authenticated user."""
    try:
        resp = requests.get(
            "https://fintual.cl/api/portfolios",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception:
        return []


def _fintual_portfolio_history(token: str, portfolio_id: int, days: int = 90) -> list:
    """
    Fetch daily portfolio history for a given portfolio.
    Returns list of {date, nav} dicts.
    """
    to_date = datetime.today().strftime("%Y-%m-%d")
    from_date = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"https://fintual.cl/api/portfolios/{portfolio_id}/portfolio_days",
            headers={"Authorization": f"Bearer {token}"},
            params={"from_date": from_date, "to_date": to_date},
            timeout=20,
        )
        resp.raise_for_status()
        days_data = resp.json().get("data", [])
        history = []
        for item in days_data:
            attrs = item.get("attributes", {})
            date_str = attrs.get("date") or attrs.get("created_at", "")[:10]
            value = attrs.get("net_asset_value") or attrs.get("current_value")
            if date_str and value is not None:
                history.append({"date": date_str, "value": float(value)})
        return sorted(history, key=lambda x: x["date"])
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_fintual_data(email: str, password: str) -> dict:
    """
    Fetch Fintual portfolio data.

    Returns dict:
        portfolios: list of {name, id, current_value, deposits, profit_sum,
                              daily_return_pct, cumulative_return_pct, history}
        total_clp: sum of all portfolio values
        error: None or error message
    """
    result = {"portfolios": [], "total_clp": 0.0, "error": None}

    if not email or not password:
        result["error"] = "Fintual credentials not configured."
        return result

    token = _fintual_auth(email, password)
    if not token:
        result["error"] = "Could not authenticate with Fintual. Check credentials."
        return result

    portfolios = _fintual_get_portfolios(token)
    if not portfolios:
        result["error"] = "No portfolios found on Fintual account."
        return result

    total = 0.0
    parsed = []
    for p in portfolios:
        attrs = p.get("attributes", {})
        pid = p.get("id")

        name = attrs.get("name", f"Portfolio {pid}")
        current_value = float(attrs.get("net_asset_value") or attrs.get("current_value") or 0)
        deposits = float(attrs.get("deposits_sum") or attrs.get("invested_sum") or 0)
        profit_sum = float(attrs.get("profit_sum") or 0)

        # Daily return: compare last two days in history
        history = _fintual_portfolio_history(token, pid, days=90)

        daily_return_pct = None
        if len(history) >= 2:
            prev_val = history[-2]["value"]
            curr_val = history[-1]["value"]
            if prev_val and prev_val != 0:
                daily_return_pct = ((curr_val - prev_val) / prev_val) * 100

        # Cumulative return
        cumulative_return_pct = None
        if deposits and deposits != 0:
            cumulative_return_pct = (profit_sum / deposits) * 100

        total += current_value
        parsed.append(
            {
                "name": name,
                "id": pid,
                "current_value": current_value,
                "deposits": deposits,
                "profit_sum": profit_sum,
                "daily_return_pct": daily_return_pct,
                "cumulative_return_pct": cumulative_return_pct,
                "history": history,
            }
        )

    result["portfolios"] = parsed
    result["total_clp"] = total
    return result


# ---------------------------------------------------------------------------
# Falabella (BTG)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def get_falabella_data(num_shares: int) -> dict:
    """
    Fetch Falabella stock data from Yahoo Finance.

    Returns dict:
        current_price: float (CLP)
        total_value: float (CLP)
        daily_return_pct: float or None
        cumulative_return_pct: None (no cost basis available)
        history: list of {date, value}  (60-day total portfolio value history)
        error: None or message
    """
    result = {
        "current_price": None,
        "total_value": None,
        "daily_return_pct": None,
        "cumulative_return_pct": None,
        "history": [],
        "error": None,
    }

    if not num_shares or num_shares <= 0:
        result["error"] = "Number of Falabella shares not configured."
        return result

    try:
        ticker = yf.Ticker("FALABELLA.SN")
        # Fetch 65 days to ensure 60 trading days
        hist = ticker.history(period="65d", interval="1d")

        if hist.empty:
            result["error"] = "No data returned for FALABELLA.SN from Yahoo Finance."
            return result

        latest = hist.iloc[-1]
        current_price = float(latest["Close"])
        total_value = current_price * num_shares

        # Daily return
        if len(hist) >= 2:
            prev_close = float(hist.iloc[-2]["Close"])
            if prev_close != 0:
                result["daily_return_pct"] = ((current_price - prev_close) / prev_close) * 100

        result["current_price"] = current_price
        result["total_value"] = total_value

        # Build 60-day history as portfolio value
        history = []
        for date_idx, row in hist.iterrows():
            date_str = date_idx.strftime("%Y-%m-%d")
            portfolio_val = float(row["Close"]) * num_shares
            history.append({"date": date_str, "value": portfolio_val})

        result["history"] = history

    except Exception as e:
        result["error"] = f"Error fetching Falabella data: {e}"

    return result


# ---------------------------------------------------------------------------
# IBKR Flex Queries
# ---------------------------------------------------------------------------

def _ibkr_send_request(token: str, query_id: str) -> str | None:
    """
    Step 1 of IBKR Flex Query: submit request and get ReferenceCode.
    """
    url = (
        "https://gdcdyn.interactivebrokers.com/Universal/servlet/"
        f"FlexStatementService.SendRequest?t={token}&q={query_id}&v=3"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        status = root.findtext("Status")
        if status == "Success":
            return root.findtext("ReferenceCode")
        error_msg = root.findtext("ErrorMessage") or "Unknown IBKR error"
        return None
    except Exception:
        return None


def _ibkr_get_statement(reference_code: str, token: str) -> str | None:
    """
    Step 2 of IBKR Flex Query: retrieve the XML statement using ReferenceCode.
    Polls up to 5 times with 3-second delays (IBKR may take a few seconds to generate).
    """
    url = (
        "https://gdcdyn.interactivebrokers.com/Universal/servlet/"
        f"FlexStatementService.GetStatement?q={reference_code}&t={token}&v=3"
    )
    for attempt in range(5):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            status = root.findtext("Status")
            if status == "Success":
                return resp.text
            if status in ("Processing", "Pending"):
                time.sleep(3)
                continue
            # Error state
            return None
        except Exception:
            if attempt < 4:
                time.sleep(3)
    return None


def _parse_ibkr_xml(xml_text: str) -> dict:
    """
    Parse IBKR Flex Query XML to extract positions and net liquidation value.
    Returns dict with positions list and net_liquidation_value.
    """
    result = {"positions": [], "net_liquidation_eur": None, "net_liquidation_usd": None}
    try:
        root = ET.fromstring(xml_text)

        # Net Liquidation value from EquitySummaryByReportDateInBase or AccountInformation
        for summary in root.iter("EquitySummaryByReportDateInBase"):
            total = summary.get("total")
            if total:
                result["net_liquidation_usd"] = float(total)
                break

        # Also try CashReportCurrency or PortfolioModelAllocation
        if result["net_liquidation_usd"] is None:
            for acc in root.iter("AccountInformation"):
                nlv = acc.get("netLiquidation")
                if nlv:
                    result["net_liquidation_usd"] = float(nlv)
                    break

        # Open positions
        for pos in root.iter("OpenPosition"):
            symbol = pos.get("symbol", "")
            position_size = pos.get("position")
            market_price = pos.get("markPrice") or pos.get("closePrice")
            market_value = pos.get("positionValue") or pos.get("value")
            currency = pos.get("currency", "USD")
            description = pos.get("description") or pos.get("securityID") or symbol
            unrealized_pnl = pos.get("unrealizedPnl") or pos.get("fifoPnlUnrealized")
            cost_basis_price = pos.get("costBasisPrice")
            pct_return = None
            if market_price and cost_basis_price:
                try:
                    mp = float(market_price)
                    cbp = float(cost_basis_price)
                    if cbp != 0:
                        pct_return = ((mp - cbp) / cbp) * 100
                except Exception:
                    pass

            result["positions"].append(
                {
                    "symbol": symbol,
                    "description": description,
                    "position": float(position_size) if position_size else None,
                    "market_price": float(market_price) if market_price else None,
                    "market_value": float(market_value) if market_value else None,
                    "currency": currency,
                    "unrealized_pnl": float(unrealized_pnl) if unrealized_pnl else None,
                    "cumulative_return_pct": pct_return,
                }
            )

    except Exception:
        pass

    return result


@st.cache_data(ttl=300)
def get_ibkr_data(token: str, query_id: str) -> dict | None:
    """
    Fetch IBKR portfolio data via Flex Query.

    Returns None if IBKR not configured.
    Returns dict:
        positions: list of position dicts
        net_liquidation_usd: float or None
        net_liquidation_eur: float or None
        error: None or message
    """
    if not token or not query_id:
        return None  # IBKR not configured — caller should handle gracefully

    result = {
        "positions": [],
        "net_liquidation_usd": None,
        "net_liquidation_eur": None,
        "error": None,
    }

    ref_code = _ibkr_send_request(token, query_id)
    if not ref_code:
        result["error"] = (
            "Could not initiate IBKR Flex Query. "
            "Check your token and query_id in secrets."
        )
        return result

    # IBKR needs a moment to generate the report
    time.sleep(3)

    xml_text = _ibkr_get_statement(ref_code, token)
    if not xml_text:
        result["error"] = "IBKR Flex Query timed out or returned an error."
        return result

    parsed = _parse_ibkr_xml(xml_text)
    result["positions"] = parsed["positions"]
    result["net_liquidation_usd"] = parsed["net_liquidation_usd"]
    result["net_liquidation_eur"] = parsed["net_liquidation_eur"]
    return result
