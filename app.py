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


def buysell(net: pd.Series) -> go.Figure:
    """Horizontal bar chart of the 8 largest net buyers and 8 largest net sellers."""
    show = pd.concat([net.head(8), net.tail(8)])
    show = show[~show.index.duplicated()].sort_values()
    fig = go.Figure(go.Bar(x=show.values, y=show.index, orientation="h",
                           marker=dict(color=[BUY if v >= 0 else SELL for v in show.values], line=dict(width=0)),
                           hovertemplate="%{y}: %{x:$,.1f}bn<extra></extra>"))
    fig = style(fig, 460)
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(tickformat="$,.0f", ticksuffix="bn", gridcolor=GRID, showgrid=True)
    fig.update_yaxes(ticksuffix="", tickformat="", tickfont=dict(color=INK2), showgrid=False)
    return fig


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

tab_own, tab_for, tab_jp, tab_hf, tab_src = st.tabs(
    ["Ownership", "US foreign holders", "Japan flows", "Hedge funds", "Sources"])

# ------------------------------------------------------------------ ownership
MARKETS = {"US": "US Treasuries", "Japan": "Japanese government bonds", "UK": "UK gilts",
           "France": "French government bonds", "Italy": "Italian government bonds",
           "Germany": "German government bonds", "Spain": "Spanish government bonds"}
# one colour per holder type, shared across every country
HOLDER_ORDER = ["Foreign", "Central bank", "Central bank & banks", "Banks", "Insurers", "Insurers & pension funds",
                "Pension funds", "Investment funds", "Money market funds", "Other financial (incl. hedge funds)",
                "Households (incl. hedge funds)", "Households", "Other"]
HOLDER_COLOR = {"Foreign": 0, "Central bank": 1, "Central bank & banks": 1, "Money market funds": 2,
                "Other financial (incl. hedge funds)": 2, "Households (incl. hedge funds)": 3, "Households": 3,
                "Investment funds": 4, "Banks": 5, "Pension funds": 6, "Insurers": 7,
                "Insurers & pension funds": 7}
MARKET_NOTES = {
    "US Treasuries": ("Fed Financial Accounts of the US (Z.1), quarterly",
                      "The Fed doesn't track hedge funds as their own group; they're folded into Households, which "
                      "the Fed calculates as whatever is left after every other holder is counted. Other = state and "
                      "local governments, broker-dealers, government-sponsored enterprises, companies. The Fed's own "
                      "holdings show about $400bn below its weekly balance sheet because of an accounting difference."),
    "Japanese government bonds": ("Bank of Japan Flow of Funds, quarterly",
                                  "Includes Treasury bills and FILP agency bonds. Pension funds include public "
                                  "pensions such as the GPIF (Government Pension Investment Fund). Hedge funds are "
                                  "not broken out and sit mostly within Foreign."),
    "UK gilts": ("ONS UK Economic Accounts, quarterly",
                 "Conventional and index-linked gilts, excluding Treasury bills. The ONS puts the Bank of England's "
                 "QE holdings and commercial banks in one group. Hedge funds sit in Other financial or, if based "
                 "abroad, in Foreign."),
    "euro": ("ECB Securities Holdings Statistics plus ECB government debt totals, quarterly",
             "Central bank = the Eurosystem (the ECB plus national central banks such as the Banque de France). "
             "Foreign = investors outside the euro area, calculated as total debt minus everything euro-area "
             "investors hold. Domestic and other euro-area investors are combined in each group. ECB publishes "
             "this data from 2021."),
}

with tab_own:
    pick_m = st.segmented_control("Market", list(MARKETS), default="US", key="mkt",
                                  label_visibility="collapsed") or "US"
    market = MARKETS[pick_m]
    src_name, note = MARKET_NOTES.get(market, MARKET_NOTES["euro"])
    st.subheader(f"Who owns {market}")
    z = (df[(df.market == market) & (df.measure == "holdings") & ~df.source.str.contains("TIC|H.4.1")]
         .pivot(index="date", columns="holder", values="amount").dropna())
    z = z[[h for h in HOLDER_ORDER if h in z.columns]]
    total = z.sum(axis=1)
    c1, c2 = st.columns([3, 1])
    with c1:
        start = window("own", "10Y")
    with c2:
        mode = st.segmented_control("Show", ["$ value", "% share"], default="% share", key="ownmode",
                                    label_visibility="collapsed") or "% share"
    zz = cut(z, start)
    pct = mode == "% share"
    plot = zz.div(zz.sum(axis=1), axis=0) * 100 if pct else zz
    fig = go.Figure()
    for h in z.columns:
        fig.add_trace(go.Scatter(x=plot.index, y=plot[h], name=h, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE),
                                 fillcolor=SERIES[HOLDER_COLOR[h]] if h in HOLDER_COLOR else OTHER,
                                 hovertemplate="%{y:.1f}%" if pct else "%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 460, ".0f" if pct else "$,.0f", "%" if pct else "bn"), width="stretch")
    fx_note = "" if market == "US Treasuries" else " · converted to USD at each quarter-end exchange rate, so % share is the cleaner view"
    asof(f"As of {z.index[-1]:%d %b %Y} · {src_name}{fx_note}")

    last = z.iloc[-1]
    share = z.div(total, axis=0) * 100
    yago = share[share.index <= z.index[-1] - pd.DateOffset(years=1)]
    tbl = pd.DataFrame({"Holding ($bn)": last.round(0), "Share": share.iloc[-1].round(1),
                        "1Y change in share (pts)": (share.iloc[-1] - yago.iloc[-1]).round(1) if len(yago) else None})
    tbl = tbl.sort_values("Holding ($bn)", ascending=False)
    tbl.index.name = "Holder"
    st.dataframe(tbl, width="stretch",
                 column_config={"Holding ($bn)": st.column_config.NumberColumn(format="$%,d"),
                                "Share": st.column_config.NumberColumn(format="%.1f%%"),
                                "1Y change in share (pts)": st.column_config.NumberColumn(format="%+.1f")})
    st.caption(note)

# ------------------------------------------------------------------ US foreign holders
AGGREGATE = ("Total", "Memo", "Foreign", "All Countries", "International", "All Other")
with tab_for:
    tic_all = df[df.source.str.contains("TIC")]
    hold = tic_all[tic_all.measure == "holdings"]
    latest_m = hold.date.max()
    countries = (hold[(hold.date == latest_m) & ~hold.holder.str.startswith(AGGREGATE)]
                 .sort_values("amount", ascending=False).holder.tolist())
    fa = series("US Treasuries", "Foreign (all)", "TIC")

    st.subheader("Who's buying and selling")
    months = sorted(tic_all[tic_all.measure == "net purchases"].date.unique())
    n = st.segmented_control("Window", ["Latest month", "3 months", "6 months", "12 months"],
                             default="3 months", key="netwin", label_visibility="collapsed") or "3 months"
    k = {"Latest month": 1, "3 months": 3, "6 months": 6, "12 months": 12}[n]
    win = months[-k:]
    net = (tic_all[(tic_all.measure == "net purchases") & tic_all.date.isin(win) & tic_all.holder.isin(countries)]
           .groupby("holder").amount.sum().sort_values())
    st.plotly_chart(buysell(net), width="stretch")
    asof(f"Net purchases {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · blue = net buyer, "
         f"red = net seller · US Treasury International Capital data (TIC), monthly, about 6 weeks behind")

    st.subheader("Holdings by country")
    pick = st.multiselect("Countries (up to 8)", countries, default=countries[:8], max_selections=8,
                          label_visibility="collapsed")
    start = window("for", "10Y")
    fig = go.Figure()
    for i, c in enumerate(pick):
        line(fig, cut(series("US Treasuries", c, "TIC"), start), c, SERIES[i])
    fig.add_trace(go.Scatter(x=cut(fa, start).index, y=cut(fa, start).values, name="Total, all countries",
                             mode="lines", line=dict(color=MUTED, width=2, dash="dot"),
                             hovertemplate="%{y:$,.0f}bn"))
    fig = style(fig, 460)
    fig.update_yaxes(type="log", tickvals=[25, 50, 100, 250, 500, 1000, 2500, 5000, 10000])  # log scale keeps the total and individual countries readable together
    st.plotly_chart(fig, width="stretch")
    asof(f"As of {latest_m:%b %Y} · US Treasury TIC, monthly · defaults to the 8 largest holders · "
         f"log scale, so equal distances mean equal % changes")
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
         f"latest weekly custody reading ${cust.iloc[-1]:,.0f}bn on {cust.index[-1]:%d %b %Y}")
    st.caption("Official = foreign central banks and governments. Private = everyone else abroad (banks, funds, "
               "insurers, hedge funds). Central banks keep most of their Treasuries in custody at the New York Fed, "
               "which reports weekly, so a drop there is the earliest sign of central bank selling.")

# ------------------------------------------------------------------ Japan flows
with tab_jp:
    jp = df[df.source.str.contains("BoJ balance of payments")]
    out_ = jp[(jp.market == "Japanese investors abroad") & (jp.holder != "All countries")]
    jmonths = sorted(out_.date.unique())

    st.subheader("Where Japanese investors are buying and selling foreign bonds")
    n = st.segmented_control("Window", ["Latest month", "3 months", "6 months", "12 months"],
                             default="3 months", key="jpwin", label_visibility="collapsed") or "3 months"
    k = {"Latest month": 1, "3 months": 3, "6 months": 6, "12 months": 12}[n]
    win = jmonths[-k:]
    net = out_[out_.date.isin(win)].groupby("holder").amount.sum().sort_values()
    st.plotly_chart(buysell(net), width="stretch")
    asof(f"Net purchases {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · blue = net buyer, "
         f"red = net seller · Japan balance of payments via Bank of Japan, monthly, about 5 weeks behind")

    st.subheader("Cumulative buying and selling by country")
    jc = out_.pivot(index="date", columns="holder", values="amount").fillna(0)
    jdefault = ["United States", "France", "United Kingdom", "Germany", "Italy"]
    jpick = st.multiselect("Countries", sorted(jc.columns), default=jdefault, max_selections=8,
                           label_visibility="collapsed")
    start = window("jp", "3Y")
    fig = go.Figure()
    for i, c in enumerate(jpick):
        line(fig, cut(jc[c], start).cumsum(), c, SERIES[i])
    st.plotly_chart(style(fig, 420), width="stretch")
    asof("Running total of monthly net purchases from the start of the selected range · a falling line = "
         "steady selling")

    st.subheader("Foreign investors in Japanese bonds")
    fj = series("Japanese government bonds", "Foreign", "BoJ balance of payments", "net purchases")
    start = window("jpf", "3Y")
    fjc = cut(fj, start)
    fig = go.Figure(go.Bar(x=fjc.index, y=fjc.values, marker=dict(color=[BUY if v >= 0 else SELL for v in fjc.values],
                                                                  line=dict(width=0)),
                           hovertemplate="%{y:$,.1f}bn<extra></extra>"))
    fig = style(fig, 360)
    fig.update_layout(showlegend=False)
    st.plotly_chart(fig, width="stretch")
    asof(f"Monthly through {fj.index[-1]:%b %Y} · foreign net purchases of Japanese long-term bonds · "
         f"Japan balance of payments via Bank of Japan")
    st.caption("Flows cover all long-term bonds issued in each country, government and corporate, but government "
               "bonds are the bulk for the large markets. These are mostly private investors (life insurers, banks, "
               "pension funds); Japan's own reserves are run separately by the Ministry of Finance. Converted to USD "
               "at each month's average exchange rate.")

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
        "BoJ Flow of Funds (quarterly)": "https://www.boj.or.jp/en/statistics/sj/index.htm",
        "BoJ balance of payments (monthly)": "https://www.boj.or.jp/en/statistics/br/index.htm",
        "ONS UK Economic Accounts (quarterly)": "https://www.ons.gov.uk/economy/nationalaccounts/uksectoraccounts",
        "ECB securities holdings (quarterly)": "https://data.ecb.europa.eu/data/datasets/SHSS",
    })
    st.dataframe(fresh, width="stretch", column_config={"Link": st.column_config.LinkColumn(display_text="Open")})
    st.caption("Data refreshes daily via GitHub Actions; each source keeps its last good copy if a download fails.")
    st.download_button("Download master table (CSV)", DATA.read_bytes(), "holdings.csv", "text/csv")
