"""
app.py — Dashboard Inversiones
Streamlit investment tracking app.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import traceback

from fetchers import get_fx_rates, get_fintual_data, get_falabella_data, get_ibkr_data
from history import save_snapshot, load_history

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Inversiones",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_clp(value) -> str:
    """Format a number as CLP with thousand separators."""
    if value is None:
        return "—"
    try:
        return f"$ {int(value):,}".replace(",", ".")
    except Exception:
        return str(value)


def fmt_usd(value) -> str:
    """Format a number as USD with 2 decimals."""
    if value is None:
        return "—"
    try:
        return f"USD {float(value):,.2f}"
    except Exception:
        return str(value)


def fmt_eur(value) -> str:
    """Format a number as EUR with 2 decimals."""
    if value is None:
        return "—"
    try:
        return f"EUR {float(value):,.2f}"
    except Exception:
        return str(value)


def color_return(pct) -> str:
    """Return a colored HTML string for a return percentage."""
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    color = "#00c853" if pct >= 0 else "#d50000"
    return f'<span style="color:{color}; font-weight:600;">{sign}{pct:.2f}%</span>'


def _read_secret(section: str, key: str, default=None):
    """Safe helper to read from st.secrets without crashing if missing."""
    try:
        return st.secrets[section][key]
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Load secrets
# ---------------------------------------------------------------------------
fintual_email = _read_secret("fintual", "email", "")
fintual_password = _read_secret("fintual", "password", "")
falabella_shares = int(_read_secret("portfolio", "falabella_shares", 0))
ibkr_token = _read_secret("ibkr", "flex_token", "")
ibkr_query_id = _read_secret("ibkr", "flex_query_id", "")

# ---------------------------------------------------------------------------
# Session state: track if a refresh was requested
# ---------------------------------------------------------------------------
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = None

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
col_title, col_btn = st.columns([6, 1])
with col_title:
    st.title("📈 Dashboard Inversiones")
with col_btn:
    st.write("")  # vertical spacer
    refresh_clicked = st.button("🔄 Actualizar ahora", use_container_width=True)

if refresh_clicked:
    st.cache_data.clear()
    st.session_state["last_refresh"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    st.rerun()

# ---------------------------------------------------------------------------
# Fetch all data
# ---------------------------------------------------------------------------
with st.spinner("Obteniendo datos…"):
    fx = get_fx_rates()
    fintual = get_fintual_data(fintual_email, fintual_password)
    falabella = get_falabella_data(falabella_shares)
    ibkr = get_ibkr_data(ibkr_token, ibkr_query_id)

clp_per_usd: float = fx.get("CLP_USD") or 950.0
eur_per_usd: float = fx.get("EUR_USD") or 1.08  # USD per 1 EUR

# ---------------------------------------------------------------------------
# FX + last-update bar
# ---------------------------------------------------------------------------
now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
st.caption(
    f"Última actualización: **{now_str}** &nbsp;|&nbsp; "
    f"USD/CLP: **{clp_per_usd:,.0f}** &nbsp;|&nbsp; "
    f"EUR/USD: **{eur_per_usd:.4f}**"
    + (f" &nbsp;|&nbsp; ⚠️ FX error: {fx.get('error')}" if fx.get("error") else "")
)

st.divider()

# ---------------------------------------------------------------------------
# Compute consolidated totals
# ---------------------------------------------------------------------------
fintual_clp = fintual.get("total_clp", 0.0) or 0.0
falabella_clp = falabella.get("total_value", 0.0) or 0.0
total_clp = fintual_clp + falabella_clp

# IBKR net liquidation in USD
ibkr_usd = 0.0
if ibkr and not ibkr.get("error"):
    ibkr_usd = ibkr.get("net_liquidation_usd") or 0.0

# Convert CLP totals to USD
fintual_usd = fintual_clp / clp_per_usd if clp_per_usd else 0.0
falabella_usd = falabella_clp / clp_per_usd if clp_per_usd else 0.0
total_usd = fintual_usd + falabella_usd + ibkr_usd

# IBKR in EUR
ibkr_eur = ibkr_usd / eur_per_usd if (ibkr_usd and eur_per_usd) else 0.0

# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------
st.subheader("Resumen consolidado")

card1, card2, card3, card4 = st.columns(4)

with card1:
    st.metric(
        label="Total USD",
        value=fmt_usd(total_usd),
    )

with card2:
    st.metric(
        label="CLP (Fintual + Falabella)",
        value=fmt_clp(total_clp),
    )

with card3:
    st.metric(
        label="IBKR (EUR aprox.)",
        value=fmt_eur(ibkr_eur) if ibkr_eur else "No configurado",
    )

with card4:
    st.metric(
        label="USD/CLP",
        value=f"{clp_per_usd:,.0f}",
    )

st.divider()

# ---------------------------------------------------------------------------
# Account table
# ---------------------------------------------------------------------------
st.subheader("Cuentas")

rows = []

# --- Fintual portfolios ---
if fintual.get("error"):
    st.warning(f"⚠️ Fintual: {fintual['error']}")
else:
    for p in fintual.get("portfolios", []):
        rows.append(
            {
                "Cuenta": f"Fintual — {p['name']}",
                "Moneda": "CLP",
                "Valor actual": fmt_clp(p["current_value"]),
                "Rentabilidad día": p["daily_return_pct"],
                "Rentabilidad acumulada": p["cumulative_return_pct"],
                "_valor_num": p["current_value"],
                "_diario_num": p["daily_return_pct"],
                "_acum_num": p["cumulative_return_pct"],
            }
        )

# --- Falabella ---
if falabella.get("error"):
    st.warning(f"⚠️ Falabella: {falabella['error']}")
else:
    rows.append(
        {
            "Cuenta": "BTG Pactual — Falabella (FALABELLA.SN)",
            "Moneda": "CLP",
            "Valor actual": fmt_clp(falabella.get("total_value")),
            "Rentabilidad día": falabella.get("daily_return_pct"),
            "Rentabilidad acumulada": falabella.get("cumulative_return_pct"),
            "_valor_num": falabella.get("total_value"),
            "_diario_num": falabella.get("daily_return_pct"),
            "_acum_num": falabella.get("cumulative_return_pct"),
        }
    )

# --- IBKR summary row ---
if ibkr is None:
    st.info("ℹ️ IBKR no configurado. Agrega flex_token y flex_query_id en los secrets para habilitar.")
elif ibkr.get("error"):
    st.warning(f"⚠️ IBKR: {ibkr['error']}")
else:
    rows.append(
        {
            "Cuenta": "IBKR — ETFs UCITS",
            "Moneda": "USD",
            "Valor actual": fmt_usd(ibkr.get("net_liquidation_usd")),
            "Rentabilidad día": None,
            "Rentabilidad acumulada": None,
            "_valor_num": ibkr.get("net_liquidation_usd"),
            "_diario_num": None,
            "_acum_num": None,
        }
    )

if rows:
    # Render table with colored returns
    display_rows = []
    for r in rows:
        display_rows.append(
            {
                "Cuenta": r["Cuenta"],
                "Moneda": r["Moneda"],
                "Valor actual": r["Valor actual"],
                "Rent. día": r["Rentabilidad día"],
                "Rent. acumulada": r["Rentabilidad acumulada"],
            }
        )

    df_accounts = pd.DataFrame(display_rows)

    # Style the numeric return columns
    def style_pct(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        color = "#00c853" if float(val) >= 0 else "#d50000"
        return f"color: {color}; font-weight: 600;"

    def fmt_pct(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        sign = "+" if float(val) >= 0 else ""
        return f"{sign}{float(val):.2f}%"

    styled = (
        df_accounts.style
        .applymap(style_pct, subset=["Rent. día", "Rent. acumulada"])
        .format({"Rent. día": fmt_pct, "Rent. acumulada": fmt_pct})
        .hide(axis="index")
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Falabella detail
# ---------------------------------------------------------------------------
with st.expander("📊 Detalle Falabella", expanded=False):
    if falabella.get("error"):
        st.warning(falabella["error"])
    else:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            st.metric("Precio actual", fmt_clp(falabella.get("current_price")))
        with col_f2:
            st.metric("N° acciones", f"{falabella_shares:,}".replace(",", "."))
        with col_f3:
            pct = falabella.get("daily_return_pct")
            delta_str = f"{pct:+.2f}%" if pct is not None else None
            st.metric(
                "Valor total",
                fmt_clp(falabella.get("total_value")),
                delta=delta_str,
            )

# ---------------------------------------------------------------------------
# Historical chart
# ---------------------------------------------------------------------------
st.subheader("Evolución histórica")

# Save today's snapshot first
snapshot = {
    "date": datetime.today().strftime("%Y-%m-%d"),
    "total_usd": total_usd,
    "fintual_clp": fintual_clp,
    "falabella_clp": falabella_clp,
    "ibkr_usd": ibkr_usd if ibkr_usd else None,
    "clp_usd_rate": clp_per_usd,
    "eur_usd_rate": eur_per_usd,
}
try:
    save_snapshot(snapshot)
except Exception:
    pass  # non-fatal

history_df = load_history()

# Build chart data from the JSON history PLUS per-portfolio history from Fintual
# Select which series to show
chart_options = ["Total USD", "Fintual CLP", "Falabella CLP"]
selected_series = st.selectbox(
    "Mostrar en gráfico:",
    options=chart_options,
    index=0,
)

fig = go.Figure()

if not history_df.empty and len(history_df) > 1:
    if selected_series == "Total USD" and "total_usd" in history_df.columns:
        fig.add_trace(
            go.Scatter(
                x=history_df["date"],
                y=history_df["total_usd"],
                mode="lines+markers",
                name="Total USD",
                line=dict(color="#1976D2", width=2),
                marker=dict(size=4),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Total: USD %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(yaxis_title="USD")

    elif selected_series == "Fintual CLP" and "fintual_clp" in history_df.columns:
        fig.add_trace(
            go.Scatter(
                x=history_df["date"],
                y=history_df["fintual_clp"],
                mode="lines+markers",
                name="Fintual CLP",
                line=dict(color="#43A047", width=2),
                marker=dict(size=4),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Fintual: $ %{y:,.0f}<extra></extra>",
            )
        )
        fig.update_layout(yaxis_title="CLP")

    elif selected_series == "Falabella CLP" and "falabella_clp" in history_df.columns:
        fig.add_trace(
            go.Scatter(
                x=history_df["date"],
                y=history_df["falabella_clp"],
                mode="lines+markers",
                name="Falabella CLP",
                line=dict(color="#E53935", width=2),
                marker=dict(size=4),
                hovertemplate="<b>%{x|%d/%m/%Y}</b><br>Falabella: $ %{y:,.0f}<extra></extra>",
            )
        )
        fig.update_layout(yaxis_title="CLP")

    fig.update_layout(
        template="plotly_white",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        height=380,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#e0e0e0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Also show Fintual per-portfolio history if available
    if selected_series == "Fintual CLP":
        fintual_portfolios = fintual.get("portfolios", [])
        if fintual_portfolios:
            fig2 = go.Figure()
            colors = ["#43A047", "#1E88E5", "#FB8C00", "#8E24AA"]
            for i, p in enumerate(fintual_portfolios):
                ph = p.get("history", [])
                if ph:
                    dates = [h["date"] for h in ph]
                    values = [h["value"] for h in ph]
                    fig2.add_trace(
                        go.Scatter(
                            x=dates,
                            y=values,
                            mode="lines",
                            name=p["name"],
                            line=dict(color=colors[i % len(colors)], width=2),
                            hovertemplate="<b>%{x}</b><br>" + p["name"] + ": $ %{y:,.0f}<extra></extra>",
                        )
                    )
            if fig2.data:
                fig2.update_layout(
                    template="plotly_white",
                    hovermode="x unified",
                    margin=dict(l=0, r=0, t=30, b=0),
                    height=300,
                    title="Portfolios Fintual (historial individual)",
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=True, gridcolor="#e0e0e0", title="CLP"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig2, use_container_width=True)
else:
    st.info(
        "El historial se acumulará a medida que uses la app cada día. "
        "Hoy es el primer registro — vuelve mañana para ver la evolución."
    )

st.divider()

# ---------------------------------------------------------------------------
# IBKR Positions Table
# ---------------------------------------------------------------------------
if ibkr is not None and not ibkr.get("error"):
    st.subheader("Posiciones IBKR — ETFs UCITS")

    positions = ibkr.get("positions", [])
    if positions:
        rows_ibkr = []
        for pos in positions:
            rows_ibkr.append(
                {
                    "Ticker": pos.get("symbol", "—"),
                    "Descripción": pos.get("description", "—"),
                    "Participaciones": pos.get("position"),
                    "Precio": pos.get("market_price"),
                    "Valor mercado": pos.get("market_value"),
                    "Moneda": pos.get("currency", "USD"),
                    "P&L no realizado": pos.get("unrealized_pnl"),
                    "Rentabilidad acum. %": pos.get("cumulative_return_pct"),
                }
            )

        df_ibkr = pd.DataFrame(rows_ibkr)

        def fmt_pct_ibkr(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return "—"
            sign = "+" if float(val) >= 0 else ""
            return f"{sign}{float(val):.2f}%"

        def style_pct_ibkr(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return ""
            color = "#00c853" if float(val) >= 0 else "#d50000"
            return f"color: {color}; font-weight: 600;"

        styled_ibkr = (
            df_ibkr.style
            .format(
                {
                    "Participaciones": lambda x: f"{x:,.4f}" if x is not None else "—",
                    "Precio": lambda x: f"{x:,.4f}" if x is not None else "—",
                    "Valor mercado": lambda x: f"{x:,.2f}" if x is not None else "—",
                    "P&L no realizado": lambda x: f"{x:+,.2f}" if x is not None else "—",
                    "Rentabilidad acum. %": fmt_pct_ibkr,
                },
                na_rep="—",
            )
            .applymap(style_pct_ibkr, subset=["Rentabilidad acum. %"])
            .hide(axis="index")
        )
        st.dataframe(styled_ibkr, use_container_width=True, hide_index=True)

        # Net liquidation summary
        nlv = ibkr.get("net_liquidation_usd")
        if nlv:
            st.caption(f"Valor liquidación neta IBKR: **{fmt_usd(nlv)}** "
                       f"(≈ {fmt_eur(nlv / eur_per_usd if eur_per_usd else None)})")
    else:
        st.info("No se encontraron posiciones abiertas en IBKR.")

    st.divider()

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.caption(
    "**Fuentes de datos:** "
    "Fintual API (fintual.cl/api) · "
    "Yahoo Finance via yfinance (Falabella) · "
    "IBKR Flex Queries · "
    "Tipos de cambio: frankfurter.app"
)
st.caption(
    "Los datos se actualizan automáticamente al cargar la app (caché 5 min). "
    "Usa el botón 'Actualizar ahora' para forzar una actualización inmediata."
)
