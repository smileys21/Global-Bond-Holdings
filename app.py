"""Who Owns Government Bonds — Streamlit dashboard (Phase 1: US Treasuries, Fed, SNB)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Who Owns Government Bonds", layout="wide")

DATA = Path(__file__).parent / "data" / "holdings.csv"

# Palette (validated categorical order) and chart chrome
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
OTHER = "#b5b3ab"
BUY, SELL = "#2a78d6", "#e34948"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

st.markdown(
    """<style>
    .block-container {padding-top: 2rem; max-width: 1400px;}
    [data-testid="stMetricValue"] {font-size: 1.6rem;}
    [data-testid="stMetricLabel"] p {color: #52514e;}
    .asof {color: #898781; font-size: 0.8rem; margin-top: -0.6rem;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600)
def load() -> pd.DataFrame:
    return pd.read_csv(DATA, parse_dates=["date"])


df = load()


def series(market: str, holder: str, src: str, measure: str = "holdings") -> pd.Series:
    x = df[(df.market == market) & (df.holder == holder) & (df.measure == measure)
           & df.source.str.contains(src, regex=False)]
    return x.set_index("date")["amount"].sort_index()


def fmt_bn(v: float) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    return sign + (f"${v / 1e3:,.2f}tn" if v >= 1e3 else f"${v:,.0f}bn")


def fmt_delta(v: float) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.0f}bn"


def asof(d: pd.Timestamp, src: str) -> None:
    st.markdown(f"<div class='asof'>As of {d:%d %b %Y} · {src}</div>", unsafe_allow_html=True)


def change(s: pd.Series, periods_back: pd.DateOffset) -> float:
    past = s[: s.index[-1] - periods_back]
    return s.iloc[-1] - past.iloc[-1] if len(past) else float("nan")


def style(fig: go.Figure, height: int = 380, yfmt: str = "$,.0f", ysuffix: str = "bn") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=56, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=INK2, size=12), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, traceorder="normal", font=dict(color=INK2)),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, color=INK)),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor=AXIS, tickfont=dict(color=MUTED),
                     tickformat=yfmt, ticksuffix=ysuffix)
    return fig


def line(fig: go.Figure, s: pd.Series, name: str, color: str, fill: str | None = None) -> None:
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                             line=dict(color=color, width=2), fill=fill,
                             hovertemplate="%{y:$,.0f}bn"))


RANGES = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "20Y": 20, "Max": None}


def window(key: str, default: str = "5Y") -> pd.Timestamp | None:
    pick = st.segmented_control("Range", list(RANGES), default=default, key=key,
                                label_visibility="collapsed") or default
    yrs = RANGES[pick]
    return None if yrs is None else pd.Timestamp.today() - pd.DateOffset(years=yrs)


def cut(s: pd.Series | pd.DataFrame, start):
    return s if start is None else s[s.index >= start]


# ------------------------------------------------------------------ header
st.title("Who Owns Government Bonds")
st.caption("Central bank balance sheets, holders of US Treasuries by type and country, and hedge fund positioning. "
           "All figures in US dollars.")

tab_cb, tab_ust, tab_for, tab_hf, tab_src = st.tabs(
    ["Central banks", "Who owns Treasuries", "Foreign holders", "Hedge funds", "Sources"])

# ------------------------------------------------------------------ central banks
with tab_cb:
    fed_tot, fed_ust, fed_mbs = (series("All assets", "Federal Reserve", "H.4.1"),
                                 series("US Treasuries", "Federal Reserve", "H.4.1"),
                                 series("US MBS", "Federal Reserve", "H.4.1"))
    snb_tot, snb_fx, snb_gold, snb_chf = (series(m, "Swiss National Bank", "SNB") for m in
                                          ["All assets", "Foreign currency investments", "Gold",
                                           "CHF securities"])
    start = window("cb", "10Y")
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Federal Reserve")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total assets", fmt_bn(fed_tot.iloc[-1]), fmt_delta(change(fed_tot, pd.DateOffset(years=1))) + " 1Y")
        c2.metric("Treasuries", fmt_bn(fed_ust.iloc[-1]), fmt_delta(change(fed_ust, pd.DateOffset(weeks=4))) + " 4W")
        c3.metric("Mortgage bonds (MBS)", fmt_bn(fed_mbs.iloc[-1]), fmt_delta(change(fed_mbs, pd.DateOffset(weeks=4))) + " 4W")
        asof(fed_tot.index[-1], "Fed H.4.1, weekly")
        fig = go.Figure()
        line(fig, cut(fed_tot, start), "Total assets", SERIES[0])
        line(fig, cut(fed_ust, start), "Treasuries", SERIES[1])
        line(fig, cut(fed_mbs, start), "Mortgage bonds", SERIES[2])
        st.plotly_chart(style(fig), width="stretch")
    with right:
        st.subheader("Swiss National Bank")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total assets", fmt_bn(snb_tot.iloc[-1]), fmt_delta(change(snb_tot, pd.DateOffset(years=1))) + " 1Y")
        c2.metric("Foreign currency investments", fmt_bn(snb_fx.iloc[-1]),
                  fmt_delta(change(snb_fx, pd.DateOffset(months=1))) + " 1M")
        c3.metric("Gold", fmt_bn(snb_gold.iloc[-1]), fmt_delta(change(snb_gold, pd.DateOffset(months=1))) + " 1M")
        asof(snb_tot.index[-1], "SNB, monthly, converted at month-end USD/CHF")
        fig = go.Figure()
        line(fig, cut(snb_tot, start), "Total assets", SERIES[0])
        line(fig, cut(snb_fx, start), "Foreign currency investments", SERIES[1])
        line(fig, cut(snb_gold, start), "Gold", SERIES[2])
        st.plotly_chart(style(fig), width="stretch")
        st.caption("SNB reserve mix at 30 Jun 2026 (quarterly, snb.ch): currencies USD 37%, EUR 39%, JPY 7%, "
                   "GBP 6%, CAD 3%, other 8% · assets government bonds 61%, other bonds 11%, equities 28%. "
                   "Dollar moves change the USD value of SNB holdings even without trading.")

# ------------------------------------------------------------------ who owns treasuries
Z1_ORDER = ["Foreign (all)", "Federal Reserve", "Money market funds", "Households & hedge funds",
            "Mutual funds & ETFs", "Banks", "Pension funds", "Insurers", "Other"]
with tab_ust:
    z = df[df.source.str.contains("Z.1")].pivot(index="date", columns="holder", values="amount")[Z1_ORDER]
    total = z.sum(axis=1)
    c1, c2 = st.columns([3, 1])
    with c1:
        start = window("ust", "20Y")
    with c2:
        mode = st.segmented_control("Show", ["$ value", "% share"], default="% share", key="ustmode",
                                    label_visibility="collapsed") or "% share"
    zz = cut(z, start)
    plot = zz.div(zz.sum(axis=1), axis=0) * 100 if mode == "% share" else zz
    fig = go.Figure()
    for i, h in enumerate(Z1_ORDER):
        color = OTHER if h == "Other" else SERIES[i]
        fig.add_trace(go.Scatter(x=plot.index, y=plot[h], name=h, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=color,
                                 hovertemplate=("%{y:.1f}%" if mode == "% share" else "%{y:$,.0f}bn")))
    pct = mode == "% share"
    st.plotly_chart(style(fig, 460, ".0f" if pct else "$,.0f", "%" if pct else "bn"), width="stretch")
    asof(z.index[-1], "Fed Z.1 Financial Accounts, quarterly")

    last, yago = z.iloc[-1], z[: z.index[-1] - pd.DateOffset(years=1)].iloc[-1]
    tbl = pd.DataFrame({"Holding ($bn)": last.round(0), "Share": (last / total.iloc[-1] * 100).round(1),
                        "1Y change ($bn)": (last - yago).round(0)}).sort_values("Holding ($bn)", ascending=False)
    tbl.index.name = "Holder"
    st.dataframe(tbl, width="stretch",
                 column_config={"Holding ($bn)": st.column_config.NumberColumn(format="$%,d"),
                                "Share": st.column_config.NumberColumn(format="%.1f%%"),
                                "1Y change ($bn)": st.column_config.NumberColumn(format="%+,d")})
    st.caption("Hedge funds have no line of their own in Z.1; they sit inside 'Households & hedge funds'. "
               "Other = state and local governments, broker-dealers, government-sponsored enterprises, companies. "
               "Z.1 runs the Fed about $400bn below the weekly H.4.1 figure (a definitional difference); "
               "use the Central banks tab for the Fed's level.")

# ------------------------------------------------------------------ foreign holders
COUNTRIES = ["Japan", "United Kingdom", "China, Mainland", "Belgium", "Cayman Islands", "Luxembourg",
             "Canada", "Ireland", "France", "Taiwan", "Switzerland", "Singapore", "Hong Kong", "Norway",
             "India", "Brazil", "Saudi Arabia", "Korea, South", "United Arab Emirates", "Germany"]
with tab_for:
    tic_all = df[(df.source.str.contains("TIC"))]
    fa, fo = series("US Treasuries", "Foreign (all)", "TIC"), series("US Treasuries", "Foreign official (all)", "TIC")
    cust = series("US Treasuries", "Foreign central banks (Fed custody)", "H.4.1")
    c1, c2, c3 = st.columns(3)
    c1.metric("Foreign holdings", fmt_bn(fa.iloc[-1]), fmt_delta(change(fa, pd.DateOffset(years=1))) + " 1Y")
    c2.metric("of which foreign official", fmt_bn(fo.iloc[-1]), fmt_delta(change(fo, pd.DateOffset(years=1))) + " 1Y")
    c3.metric("Central bank custody at the Fed", fmt_bn(cust.iloc[-1]),
              fmt_delta(change(cust, pd.DateOffset(weeks=4))) + " 4W")
    st.markdown(f"<div class='asof'>TIC as of {fa.index[-1]:%b %Y} (monthly, ~6 week lag) · "
                f"Fed custody as of {cust.index[-1]:%d %b %Y} (weekly, the fastest read on central bank selling)</div>",
                unsafe_allow_html=True)

    st.subheader("Who's buying and selling")
    months = sorted(tic_all[tic_all.measure == "net purchases"].date.unique())
    n = st.segmented_control("Window", ["Latest month", "3 months", "6 months", "12 months"],
                             default="3 months", key="netwin", label_visibility="collapsed") or "3 months"
    k = {"Latest month": 1, "3 months": 3, "6 months": 6, "12 months": 12}[n]
    win = months[-k:]
    net = (tic_all[(tic_all.measure == "net purchases") & tic_all.date.isin(win) & tic_all.holder.isin(COUNTRIES)]
           .groupby("holder").amount.sum().sort_values())
    show = pd.concat([net.head(8), net.tail(8)]).drop_duplicates()
    show = show[~show.index.duplicated()].sort_values()
    fig = go.Figure(go.Bar(x=show.values, y=show.index, orientation="h",
                           marker=dict(color=[BUY if v >= 0 else SELL for v in show.values], line=dict(width=0)),
                           hovertemplate="%{y}: %{x:$,.1f}bn<extra></extra>"))
    fig = style(fig, 460)
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(tickformat="$,.0f", ticksuffix="bn", gridcolor=GRID, showgrid=True)
    fig.update_yaxes(ticksuffix="", tickformat="", tickfont=dict(color=INK2), showgrid=False)
    st.plotly_chart(fig, width="stretch")
    st.markdown(f"<div class='asof'>Net purchases {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · "
                f"blue = net buyer, red = net seller · US Treasury TIC</div>", unsafe_allow_html=True)

    st.subheader("Holdings by country")
    pick = st.multiselect("Countries (up to 8)", COUNTRIES, max_selections=8,
                          default=["Japan", "United Kingdom", "China, Mainland", "Cayman Islands",
                                   "Belgium", "Switzerland"])  # keep in sync with `core` below
    start = window("for", "10Y")
    fig = go.Figure()
    # default countries keep fixed colours; extra picks take the remaining slots in pick order
    core = ["Japan", "United Kingdom", "China, Mainland", "Cayman Islands", "Belgium", "Switzerland"]
    free = iter([i for i in range(8) if i >= len(core) or core[i] not in pick])
    for c in pick:
        slot = core.index(c) if c in core else next(free)
        line(fig, cut(series("US Treasuries", c, "TIC"), start), c, SERIES[slot])
    st.plotly_chart(style(fig), width="stretch")
    st.caption("Belgium, Luxembourg and the Cayman Islands are custody locations: holdings booked there often "
               "belong to others (China is widely thought to hold some via Belgium; hedge funds via Cayman). "
               "TIC also has series breaks from annual benchmark surveys.")

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Official vs private")
        fig = go.Figure()
        line(fig, cut(fo, start), "Foreign official", SERIES[0])
        line(fig, cut((fa - fo).dropna(), start), "Foreign private", SERIES[1])
        st.plotly_chart(style(fig, 340), width="stretch")
    with right:
        st.subheader("Central bank custody at the Fed")
        fig = go.Figure()
        line(fig, cut(cust, start), "Custody holdings", SERIES[0])
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, 340), width="stretch")

# ------------------------------------------------------------------ hedge funds
TENORS = ["2-year", "5-year", "10-year", "Ultra 10-year", "Bond", "Ultra bond"]
with tab_hf:
    fut = df[df.source.str.startswith("CFTC")]
    lev = fut[fut.holder == "Leveraged funds"].pivot(index="date", columns="market", values="amount")
    lev.columns = [c.replace("UST futures ", "") for c in lev.columns]
    lev = lev[[t for t in TENORS if t in lev.columns]]
    tot = fut.groupby(["date", "holder"]).amount.sum().unstack()
    cay = series("US Treasuries", "Cayman Islands", "TIC")
    c1, c2, c3 = st.columns(3)
    c1.metric("Leveraged funds net futures", fmt_bn(tot["Leveraged funds"].iloc[-1]),
              fmt_delta(change(tot["Leveraged funds"], pd.DateOffset(weeks=4))) + " 4W")
    c2.metric("Asset managers net futures", fmt_bn(tot["Asset managers"].iloc[-1]),
              fmt_delta(change(tot["Asset managers"], pd.DateOffset(weeks=4))) + " 4W")
    c3.metric("Cayman Islands cash Treasuries", fmt_bn(cay.iloc[-1]),
              fmt_delta(change(cay, pd.DateOffset(years=1))) + " 1Y")
    st.markdown(f"<div class='asof'>CFTC as of {tot.index[-1]:%d %b %Y} (weekly) · TIC Cayman as of "
                f"{cay.index[-1]:%b %Y} (monthly) · futures shown at face value</div>", unsafe_allow_html=True)
    start = window("hf", "5Y")

    st.subheader("Leveraged funds net futures by maturity")
    lv = cut(lev, start)
    fig = go.Figure()
    for i, t in enumerate(lv.columns):
        fig.add_trace(go.Bar(x=lv.index, y=lv[t], name=t, marker=dict(color=SERIES[i], line=dict(width=0)),
                             hovertemplate="%{y:$,.0f}bn"))
    fig.update_layout(barmode="relative", bargap=0.1)
    st.plotly_chart(style(fig, 400), width="stretch")

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Hedge funds vs asset managers")
        fig = go.Figure()
        t2 = cut(tot, start)
        line(fig, t2["Leveraged funds"], "Leveraged funds", SERIES[0])
        line(fig, t2["Asset managers"], "Asset managers", SERIES[1])
        st.plotly_chart(style(fig, 340), width="stretch")
    with right:
        st.subheader("Cayman Islands cash Treasuries")
        fig = go.Figure()
        line(fig, cut(cay, start), "Cayman Islands", SERIES[0])
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, 340), width="stretch")
    st.caption("Leveraged funds short futures while holding cash Treasuries (the basis trade); asset managers are "
               "the mirror image, long futures. Cayman holdings are the usual proxy for hedge fund cash bonds.")

# ------------------------------------------------------------------ sources
with tab_src:
    fresh = (df.groupby("source").date.max().rename("Latest data").dt.strftime("%d %b %Y").to_frame())
    fresh["Link"] = fresh.index.map({
        "Fed H.4.1 (weekly)": "https://www.federalreserve.gov/releases/h41/",
        "Fed Z.1 Financial Accounts (quarterly)": "https://www.federalreserve.gov/releases/z1/",
        "US Treasury TIC (monthly)": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "CFTC Traders in Financial Futures (weekly)": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/",
        "SNB balance sheet (monthly, converted to USD)": "https://data.snb.ch/en/topics/snb#!/cube/snbbipo",
    })
    st.dataframe(fresh, width="stretch",
                 column_config={"Link": st.column_config.LinkColumn(display_text="Open")})
    st.caption("Data refreshes daily via GitHub Actions; each source keeps its last good copy if a download fails.")
    st.download_button("Download master table (CSV)", DATA.read_bytes(), "holdings.csv", "text/csv")
