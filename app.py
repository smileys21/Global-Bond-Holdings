"""Global Bond Tool — who owns, buys and sells government bonds."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Global Bond Tool", layout="wide")

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
    .asof {color: #898781; font-size: 0.8rem; margin-top: -0.6rem; margin-bottom: 1rem;}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600)
def load(version: float) -> pd.DataFrame:  # version = file timestamp, so new data never hits a stale cache
    return pd.read_csv(DATA, parse_dates=["date"])


df = load(DATA.stat().st_mtime)


def series(market: str, holder: str, src: str, measure: str = "holdings") -> pd.Series:
    x = df[(df.market == market) & (df.holder == holder) & (df.measure == measure)
           & df.source.str.contains(src, regex=False)]
    return x.set_index("date")["amount"].sort_index()


def asof(text: str) -> None:
    st.markdown(f"<div class='asof'>{text}</div>", unsafe_allow_html=True)


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


def line(fig: go.Figure, s: pd.Series, name: str, color: str, width: float = 2) -> None:
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                             line=dict(color=color, width=width), hovertemplate="%{y:$,.0f}bn"))


RANGES = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "20Y": 20, "Max": None}


def window(key: str, default: str = "5Y") -> pd.Timestamp | None:
    pick = st.segmented_control("Range", list(RANGES), default=default, key=key,
                                label_visibility="collapsed") or default
    yrs = RANGES[pick]
    return None if yrs is None else pd.Timestamp.today() - pd.DateOffset(years=yrs)


def cut(s, start):
    return s if start is None else s[s.index >= start]


# ------------------------------------------------------------------ header
st.title("Global Bond Tool")
st.caption("Who owns, buys and sells government bonds. All figures in US dollars.")

tab_own, tab_for, tab_hf, tab_src = st.tabs(["Ownership", "Foreign holders", "Hedge funds", "Sources"])

# ------------------------------------------------------------------ ownership
Z1_ORDER = ["Foreign (all)", "Federal Reserve", "Money market funds", "Households (incl. hedge funds)",
            "Mutual funds & ETFs", "Banks", "Pension funds", "Insurers", "Other"]
with tab_own:
    st.subheader("Who owns US Treasuries")
    z = df[df.source.str.contains("Z.1")].pivot(index="date", columns="holder", values="amount")[Z1_ORDER]
    total = z.sum(axis=1)
    c1, c2 = st.columns([3, 1])
    with c1:
        start = window("own", "20Y")
    with c2:
        mode = st.segmented_control("Show", ["$ value", "% share"], default="% share", key="ownmode",
                                    label_visibility="collapsed") or "% share"
    zz = cut(z, start)
    pct = mode == "% share"
    plot = zz.div(zz.sum(axis=1), axis=0) * 100 if pct else zz
    fig = go.Figure()
    for i, h in enumerate(Z1_ORDER):
        fig.add_trace(go.Scatter(x=plot.index, y=plot[h], name=h, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE),
                                 fillcolor=OTHER if h == "Other" else SERIES[i],
                                 hovertemplate="%{y:.1f}%" if pct else "%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 460, ".0f" if pct else "$,.0f", "%" if pct else "bn"), width="stretch")
    asof(f"As of {z.index[-1]:%d %b %Y} · Fed Financial Accounts of the US (Z.1), quarterly")

    last, yago = z.iloc[-1], z[: z.index[-1] - pd.DateOffset(years=1)].iloc[-1]
    tbl = pd.DataFrame({"Holding ($bn)": last.round(0), "Share": (last / total.iloc[-1] * 100).round(1),
                        "1Y change ($bn)": (last - yago).round(0)}).sort_values("Holding ($bn)", ascending=False)
    tbl.index.name = "Holder"
    st.dataframe(tbl, width="stretch",
                 column_config={"Holding ($bn)": st.column_config.NumberColumn(format="$%,d"),
                                "Share": st.column_config.NumberColumn(format="%.1f%%"),
                                "1Y change ($bn)": st.column_config.NumberColumn(format="%+,d")})
    st.caption("The Fed doesn't track hedge funds as their own group here; they're folded into Households, which the "
               "Fed calculates as whatever is left after every other holder is counted. Other = state and local "
               "governments, broker-dealers, government-sponsored enterprises, companies. The Fed's own holdings show "
               "about $400bn below its weekly balance sheet because of an accounting difference in this report.")

# ------------------------------------------------------------------ foreign holders
AGGREGATE = ("Total", "Memo", "Foreign", "All Countries", "International", "All Other")
with tab_for:
    tic_all = df[df.source.str.contains("TIC")]
    hold = tic_all[tic_all.measure == "holdings"]
    latest_m = hold.date.max()
    countries = (hold[(hold.date == latest_m) & ~hold.holder.str.startswith(AGGREGATE)]
                 .sort_values("amount", ascending=False).holder.tolist())

    st.subheader("Who's buying and selling")
    months = sorted(tic_all[tic_all.measure == "net purchases"].date.unique())
    n = st.segmented_control("Window", ["Latest month", "3 months", "6 months", "12 months"],
                             default="3 months", key="netwin", label_visibility="collapsed") or "3 months"
    k = {"Latest month": 1, "3 months": 3, "6 months": 6, "12 months": 12}[n]
    win = months[-k:]
    net = (tic_all[(tic_all.measure == "net purchases") & tic_all.date.isin(win) & tic_all.holder.isin(countries)]
           .groupby("holder").amount.sum().sort_values())
    show = pd.concat([net.head(8), net.tail(8)])
    show = show[~show.index.duplicated()].sort_values()
    fig = go.Figure(go.Bar(x=show.values, y=show.index, orientation="h",
                           marker=dict(color=[BUY if v >= 0 else SELL for v in show.values], line=dict(width=0)),
                           hovertemplate="%{y}: %{x:$,.1f}bn<extra></extra>"))
    fig = style(fig, 460)
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(tickformat="$,.0f", ticksuffix="bn", gridcolor=GRID, showgrid=True)
    fig.update_yaxes(ticksuffix="", tickformat="", tickfont=dict(color=INK2), showgrid=False)
    st.plotly_chart(fig, width="stretch")
    asof(f"Net purchases {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · blue = net buyer, "
         f"red = net seller · US Treasury International Capital data (TIC), monthly, about 6 weeks behind")

    st.subheader("Holdings by country")
    core = ["Japan", "United Kingdom", "China, Mainland", "Cayman Islands", "Belgium", "Switzerland"]
    all_on = st.toggle("Show all countries", key="allc")
    pick = countries if all_on else st.multiselect("Countries", countries, default=core,
                                                   label_visibility="collapsed")
    start = window("for", "10Y")
    fig = go.Figure()
    free = iter([i for i in range(8) if i >= len(core) or core[i] not in pick])
    for c in pick:
        slot = core.index(c) if c in core else next(free, None)
        color, width = (SERIES[slot], 2) if slot is not None else (OTHER, 1)
        line(fig, cut(series("US Treasuries", c, "TIC"), start), c, color, width)
    if len(pick) > 8:
        fig.update_layout(showlegend=False)
    st.plotly_chart(style(fig, 440), width="stretch")
    asof(f"As of {latest_m:%b %Y} · US Treasury TIC, monthly"
         + (" · beyond 8 countries the extra lines are grey; hover to see each one" if len(pick) > 8 else ""))

    # sortable table of every country
    h = hold[hold.holder.isin(countries)].pivot(index="date", columns="holder", values="amount")

    def chg(months_back: int) -> pd.Series:
        past = h[h.index <= latest_m - pd.DateOffset(months=months_back)]
        return h.iloc[-1] - past.iloc[-1] if len(past) else pd.Series(dtype=float)

    fa = series("US Treasuries", "Foreign (all)", "TIC")
    tbl = pd.DataFrame({"Holding ($bn)": h.iloc[-1], "Share of foreign": h.iloc[-1] / fa.iloc[-1] * 100,
                        "1M change": chg(1), "3M change": chg(3), "12M change": chg(12)}).round(1)
    tbl = tbl.sort_values("Holding ($bn)", ascending=False)
    tbl.index.name = "Country"
    with st.expander(f"All {len(tbl)} countries, latest month ({latest_m:%b %Y})"):
        st.dataframe(tbl, width="stretch", height=420,
                     column_config={"Holding ($bn)": st.column_config.NumberColumn(format="$%,.1f"),
                                    "Share of foreign": st.column_config.NumberColumn(format="%.1f%%"),
                                    "1M change": st.column_config.NumberColumn(format="%+,.1f"),
                                    "3M change": st.column_config.NumberColumn(format="%+,.1f"),
                                    "12M change": st.column_config.NumberColumn(format="%+,.1f")})
    st.caption("Holdings are recorded by where they sit, not who owns them. Belgium and Luxembourg host big "
               "custodians (China is widely thought to hold some there). The Cayman Islands is where most hedge "
               "funds are legally based, so it's the standard stand-in for hedge fund holdings.")

    st.subheader("Foreign holders: official vs private")
    fo = series("US Treasuries", "Foreign official (all)", "TIC")
    cust = series("US Treasuries", "Foreign central banks (Fed custody)", "H.4.1")
    cust_m = cust.resample("ME").last()
    stack = pd.DataFrame({"Central banks, held at the Fed": cust_m,
                          "Central banks, held elsewhere": fo - cust_m,
                          "Private investors": fa - fo}).dropna()
    start2 = window("off", "10Y")
    st2 = cut(stack, start2)
    fig = go.Figure()
    for i, c in enumerate(stack.columns):
        fig.add_trace(go.Scatter(x=st2.index, y=st2[c], name=c, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                 hovertemplate="%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 400), width="stretch")
    asof(f"Monthly through {stack.index[-1]:%b %Y} · the three layers add up to total foreign holdings · "
         f"latest weekly custody reading {cust.iloc[-1]:,.0f}bn on {cust.index[-1]:%d %b %Y}")

# ------------------------------------------------------------------ hedge funds
TENORS = ["2-year", "5-year", "10-year", "Ultra 10-year", "Bond", "Ultra bond"]
with tab_hf:
    fut = df[df.source.str.startswith("CFTC")]
    lev = fut[fut.holder == "Leveraged funds"].pivot(index="date", columns="market", values="amount")
    lev.columns = [c.replace("UST futures ", "") for c in lev.columns]
    lev = lev[[t for t in TENORS if t in lev.columns]]
    tot = fut.groupby(["date", "holder"]).amount.sum().unstack()
    cay = series("US Treasuries", "Cayman Islands", "TIC")
    start = window("hf", "5Y")

    st.subheader("Hedge fund net futures by maturity")
    lv = cut(lev, start)
    fig = go.Figure()
    for i, t in enumerate(lv.columns):
        fig.add_trace(go.Bar(x=lv.index, y=lv[t], name=t, marker=dict(color=SERIES[i], line=dict(width=0)),
                             hovertemplate="%{y:$,.0f}bn"))
    fig.update_layout(barmode="relative", bargap=0.1)
    st.plotly_chart(style(fig, 400), width="stretch")
    asof(f"As of {lev.index[-1]:%d %b %Y} · CFTC Traders in Financial Futures, weekly · 'leveraged funds' "
         f"category · face value of contracts · below zero = net short")

    st.subheader("The basis trade")
    fig = go.Figure()
    t2 = cut(tot, start)
    line(fig, -t2["Leveraged funds"], "Hedge funds: futures short", SERIES[0])
    line(fig, t2["Asset managers"], "Asset managers: futures long", SERIES[1])
    line(fig, cut(cay, start), "Cayman Islands: cash Treasuries", SERIES[2])
    st.plotly_chart(style(fig, 400), width="stretch")
    asof(f"Futures as of {tot.index[-1]:%d %b %Y} (weekly) · Cayman as of {cay.index[-1]:%b %Y} (monthly, TIC)")
    st.caption("Asset managers (pension and bond funds) buy futures as a cheap way to own Treasuries. Hedge funds "
               "take the other side, selling the futures and buying the actual bonds with borrowed money, pocketing "
               "the small price gap between the two. That's why the two futures lines mirror each other, and why "
               "hedge fund cash holdings (proxied by Cayman) rise as the short grows. Not every hedge fund is in "
               "Cayman, so the cash line understates the true long.")

# ------------------------------------------------------------------ sources
with tab_src:
    fresh = (df.groupby("source").date.max().rename("Latest data").dt.strftime("%d %b %Y").to_frame())
    fresh["Link"] = fresh.index.map({
        "Fed H.4.1 (weekly)": "https://www.federalreserve.gov/releases/h41/",
        "Fed Z.1 Financial Accounts (quarterly)": "https://www.federalreserve.gov/releases/z1/",
        "US Treasury TIC (monthly)": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "CFTC Traders in Financial Futures (weekly)": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/",
    })
    st.dataframe(fresh, width="stretch", column_config={"Link": st.column_config.LinkColumn(display_text="Open")})
    st.caption("Data refreshes daily via GitHub Actions; each source keeps its last good copy if a download fails.")
    st.download_button("Download master table (CSV)", DATA.read_bytes(), "holdings.csv", "text/csv")
