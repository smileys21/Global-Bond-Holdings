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
    st.markdown(f"<div class='asof'>{text.replace('$', '&#36;')}</div>", unsafe_allow_html=True)


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


def buysell(net: pd.Series, pin: tuple = ()) -> go.Figure:
    """Horizontal bar chart of the 8 largest net buyers and 8 largest net sellers, plus any pinned names."""
    show = pd.concat([net.head(8), net.tail(8), net[net.index.isin(pin)]])
    show = show[~show.index.duplicated()].sort_values()
    fig = go.Figure(go.Bar(x=show.values, y=show.index, orientation="h",
                           marker=dict(color=[BUY if v >= 0 else SELL for v in show.values], line=dict(width=0)),
                           hovertemplate="%{y}: %{x:$,.1f}bn<extra></extra>"))
    fig = style(fig, 460)
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(tickformat="$,.0f", ticksuffix="bn", gridcolor=GRID, showgrid=True)
    fig.update_yaxes(ticksuffix="", tickformat="", tickfont=dict(color=INK2), showgrid=False)
    return fig


RANGES = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "20Y": 20, "All": None}


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

tab_us, tab_jp, tab_oth, tab_hf, tab_auc, tab_chk, tab_src = st.tabs(
    ["United States", "Japan", "Other countries", "Hedge funds (US Treasuries)", "Auctions",
     "Data checks", "Sources"])

# ------------------------------------------------------------------ shared pieces
HOLDER_ORDER = ["Foreign", "Central bank", "Central bank & banks", "Banks", "Insurers", "Insurers & pension funds",
                "Pension funds", "Investment funds", "Money market funds", "Other financial (incl. hedge funds)",
                "Households (incl. hedge funds)", "Households", "Other"]
HOLDER_COLOR = {"Foreign": 0, "Central bank": 1, "Central bank & banks": 1, "Money market funds": 2,
                "Other financial (incl. hedge funds)": 2, "Households (incl. hedge funds)": 3, "Households": 3,
                "Investment funds": 4, "Banks": 5, "Pension funds": 6, "Insurers": 7,
                "Insurers & pension funds": 7}
EURO = ("French government bonds", "Italian government bonds", "German government bonds", "Spanish government bonds")
MARKET_NOTES = {
    "US Treasuries": ("Fed Financial Accounts of the US (Z.1), quarterly",
                      "The Fed doesn't track hedge funds as their own group; they're folded into Households, which "
                      "the Fed calculates as whatever is left after every other holder is counted. Other = state and "
                      "local governments, broker-dealers, government-sponsored enterprises, companies. The Fed's own "
                      "holdings here run about $400bn below its weekly balance sheet (see Data checks)."),
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
             "investors hold. ECB publishes this data from 2021."),
}
AGGREGATE = ("Total", "Memo", "Foreign", "All Countries", "All countries", "International", "All Other", "Of Which")
WINDOWS = {"Latest month": 1, "3 months": 3, "6 months": 6, "12 months": 12}


def window_pick(key: str) -> int:
    n = st.segmented_control("Window", list(WINDOWS), default="3 months", key=key,
                             label_visibility="collapsed") or "3 months"
    return WINDOWS[n]


def section(n: int, title: str) -> None:
    st.markdown("---")
    st.header(f"{n}. {title}")


def not_published(text: str) -> None:
    st.caption(f"Not published: {text}")


def holders(market: str) -> pd.DataFrame:
    z = (df[(df.market == market) & (df.measure == "holdings") & ~df.source.str.contains("TIC|H.4.1")]
         .pivot(index="date", columns="holder", values="amount").dropna())
    return z[[h for h in HOLDER_ORDER if h in z.columns]]


def ownership(market: str, key: str) -> None:
    src_name, note = MARKET_NOTES.get(market, MARKET_NOTES["euro"])
    z = holders(market)
    c1, c2 = st.columns([3, 1])
    with c1:
        start = window(f"{key}_own", "10Y")
    with c2:
        mode = st.segmented_control("Show", ["$ value", "% share"], default="% share", key=f"{key}_ownmode",
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
    fig = style(fig, 440, ".0f" if pct else "$,.0f", "%" if pct else "bn")
    if len(z.columns) > 8:  # long legends wrap to two rows; give them room
        fig.update_layout(margin=dict(t=90))
    st.plotly_chart(fig, width="stretch", key=f"{key}_ownchart")
    fx_note = "" if market == "US Treasuries" else " · converted to USD at each quarter-end exchange rate, so % share is the cleaner view"
    asof(f"As of {z.index[-1]:%d %b %Y} · {src_name}{fx_note}")
    if market in EURO:
        asof("Note: 'Foreign' here means investors outside the euro area. A French bank holding Italian bonds "
             "counts as Banks, not Foreign.")
    last, total = z.iloc[-1], z.sum(axis=1)
    share = z.div(total, axis=0) * 100
    ago = z.index <= z.index[-1] - pd.DateOffset(years=1)
    tbl = pd.DataFrame({"Holding ($bn)": last.round(0), "Share": share.iloc[-1].round(1),
                        "1Y change ($bn)": (last - z[ago].iloc[-1]).round(0) if ago.any() else None,
                        "1Y change in share (pts)": (share.iloc[-1] - share[ago].iloc[-1]).round(1) if ago.any() else None})
    tbl = tbl.sort_values("Holding ($bn)", ascending=False)
    tbl.index.name = "Holder"
    st.dataframe(tbl, width="stretch",
                 column_config={"Holding ($bn)": st.column_config.NumberColumn(format="$%,d"),
                                "Share": st.column_config.NumberColumn(format="%.1f%%"),
                                "1Y change ($bn)": st.column_config.NumberColumn(format="%+,d"),
                                "1Y change in share (pts)": st.column_config.NumberColumn(format="%+.1f")})
    st.caption(note)


def running_total(wide: pd.DataFrame, default: list, key: str, note: str) -> None:
    pick = st.multiselect("Countries", sorted(wide.columns), default=[c for c in default if c in wide.columns],
                          max_selections=8, key=f"{key}_pick", label_visibility="collapsed")
    start = window(f"{key}_rt", "3Y")
    fig = go.Figure()
    for i, c in enumerate(pick):
        line(fig, cut(wide[c].fillna(0), start).cumsum(), c, SERIES[i])
    st.plotly_chart(style(fig, 400), width="stretch")
    asof(note)


TIC3 = "US Treasury TIC (monthly)"
TIC1 = "US Treasury TIC long-term securities (monthly)"
TIC2 = "US Treasury TIC US holdings abroad (monthly)"
US_ASSETS = {"Treasuries (incl. bills)": (TIC3, "US Treasuries"),
             "Treasury notes & bonds": (TIC1, "US Treasury notes & bonds"),
             "Agency bonds": (TIC1, "US agency bonds"), "Corporate bonds": (TIC1, "US corporate bonds"),
             "Stocks": (TIC1, "US stocks")}
PORTFOLIO = ["US stocks", "US corporate bonds", "US agency bonds", "US Treasury notes & bonds"]


def tic_countries(src: str) -> list:
    h = df[(df.source == src) & (df.measure == "holdings")]
    last = h[h.date == h.date.max()].groupby("holder").amount.sum()
    return last[~last.index.str.startswith(AGGREGATE)].sort_values(ascending=False).index.tolist()


def us_portfolio(who: str, key: str) -> None:
    """One country's holdings of, and monthly net purchases of, US long-term securities."""
    lt = df[(df.source == TIC1) & (df.holder == who)]
    if lt.empty:
        not_published(f"no US securities data for {who}.")
        return
    start = window(f"{key}_pf", "5Y")
    h = cut(lt[lt.measure == "holdings"].pivot(index="date", columns="market", values="amount")[PORTFOLIO], start)
    n_ = cut(lt[lt.measure == "net purchases"].pivot(index="date", columns="market", values="amount")[PORTFOLIO], start)
    left, right = st.columns(2, gap="large")
    with left:
        fig = go.Figure()
        for i, a in enumerate(PORTFOLIO):
            fig.add_trace(go.Scatter(x=h.index, y=h[a], name=a.replace("US ", ""), stackgroup="one", mode="lines",
                                     line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                     hovertemplate="%{y:$,.0f}bn"))
        st.markdown("**Holdings**")
        st.plotly_chart(style(fig, 340), width="stretch", key=f"{key}_pfh")
    with right:
        fig = go.Figure()
        for i, a in enumerate(PORTFOLIO):
            fig.add_trace(go.Bar(x=n_.index, y=n_[a], name=a.replace("US ", ""),
                                 marker=dict(color=SERIES[i], line=dict(width=0)), hovertemplate="%{y:$,.1f}bn"))
        fig.update_layout(barmode="relative", bargap=0.15)
        st.markdown("**Monthly net purchases**")
        st.plotly_chart(style(fig, 340), width="stretch", key=f"{key}_pfn")
    asof(f"As of {lt.date.max():%b %Y} · US Treasury TIC, monthly · holdings also move with prices, the bars are "
         f"actual buying and selling · Treasury bills excluded")


# ================================================================== UNITED STATES
with tab_us:
    st.caption("Same four sections as the Japan tab: who owns the bonds, foreign buying and selling, the country's "
               "own investors abroad, and the central bank.")

    section(1, "Who owns US Treasuries")
    ownership("US Treasuries", "us")

    section(2, "Foreign investors: who's buying and selling US securities")
    st.subheader("Ranking")
    asset = st.segmented_control("Asset", list(US_ASSETS), default="Treasuries (incl. bills)", key="us_asset",
                                 label_visibility="collapsed") or "Treasuries (incl. bills)"
    src, mkt = US_ASSETS[asset]
    k = window_pick("us_win")
    flows = df[(df.source == src) & (df.market == mkt) & (df.measure == "net purchases")]
    win = sorted(flows.date.unique())[-k:]
    countries3 = tic_countries(TIC3)
    net = flows[flows.date.isin(win) & flows.holder.isin(countries3)].groupby("holder").amount.sum().sort_values()
    st.plotly_chart(buysell(net), width="stretch")
    asof(f"Net purchases of {asset.lower()}, {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · "
         f"blue = net buyer, red = net seller · US Treasury TIC, monthly, about 6 weeks behind")

    st.subheader("Over time: Treasury holdings by country")
    fa = series("US Treasuries", "Foreign (all)", TIC3)
    pick = st.multiselect("Countries (up to 8)", countries3, default=countries3[:8], max_selections=8, key="us_hold",
                          label_visibility="collapsed")
    c1, c2 = st.columns([3, 1])
    with c1:
        start = window("us_holdwin", "10Y")
    with c2:
        show_total = st.toggle("Add total, all countries", key="us_tot")
    fig = go.Figure()
    for i, c in enumerate(pick):
        line(fig, cut(series("US Treasuries", c, TIC3), start), c, SERIES[i])
    if show_total:
        fig.add_trace(go.Scatter(x=cut(fa, start).index, y=cut(fa, start).values, name="Total, all countries",
                                 mode="lines", line=dict(color=MUTED, width=2, dash="dot"),
                                 hovertemplate="%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 420), width="stretch")
    asof(f"As of {fa.index[-1]:%b %Y} · Treasuries including bills · defaults to the 8 largest holders")
    st.caption("Holdings are recorded by where bonds are held, not who owns them. The UK, Belgium and Luxembourg "
               "host big custodians (China is widely thought to hold some via Belgium; the UK figure includes "
               "foreign central banks and funds holding through London). The Cayman Islands is where most hedge "
               "funds are registered.")

    st.subheader("Over time: one country's US portfolio")
    countries1 = tic_countries(TIC1)
    who = st.selectbox("Country", countries1, index=countries1.index("Japan") if "Japan" in countries1 else 0,
                       key="us_pfwho")
    us_portfolio(who, "us")

    section(3, "US investors abroad")
    ab_assets = ["Foreign government bonds", "Foreign corporate bonds", "Foreign stocks"]
    st.subheader("Ranking")
    asset = st.segmented_control("Asset", ab_assets, default="Foreign government bonds", key="ab_asset",
                                 label_visibility="collapsed") or "Foreign government bonds"
    k = window_pick("ab_win")
    ab = df[df.source == TIC2]
    abc = tic_countries(TIC2)
    sel = ab[(ab.measure == "net purchases") & (ab.market == f"US investors abroad: {asset}")]
    win = sorted(sel.date.unique())[-k:]
    st.plotly_chart(buysell(sel[sel.date.isin(win) & sel.holder.isin(abc)].groupby("holder").amount.sum()
                            .sort_values()), width="stretch")
    asof(f"US investors' net purchases of {asset.lower()}, {pd.Timestamp(win[0]):%b %Y} to "
         f"{pd.Timestamp(win[-1]):%b %Y} · by the issuer's country · US Treasury TIC, monthly")

    st.subheader("Over time: US holdings in one country")
    who = st.selectbox("Country", abc, index=abc.index("Japan") if "Japan" in abc else 0, key="ab_who")
    c = ab[ab.holder == who]
    start = window("ab_pf", "5Y")
    cols = [f"US investors abroad: {a}" for a in ab_assets]
    h = cut(c[c.measure == "holdings"].pivot(index="date", columns="market", values="amount")[cols], start)
    n_ = cut(c[c.measure == "net purchases"].pivot(index="date", columns="market", values="amount")[cols], start)
    left, right = st.columns(2, gap="large")
    with left:
        fig = go.Figure()
        for i, a in enumerate(cols):
            fig.add_trace(go.Scatter(x=h.index, y=h[a], name=a.split(": ")[1], stackgroup="one", mode="lines",
                                     line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                     hovertemplate="%{y:$,.0f}bn"))
        st.markdown("**Holdings**")
        st.plotly_chart(style(fig, 340), width="stretch")
    with right:
        fig = go.Figure()
        for i, a in enumerate(cols):
            fig.add_trace(go.Bar(x=n_.index, y=n_[a], name=a.split(": ")[1],
                                 marker=dict(color=SERIES[i], line=dict(width=0)), hovertemplate="%{y:$,.1f}bn"))
        fig.update_layout(barmode="relative", bargap=0.15)
        st.markdown("**Monthly net purchases**")
        st.plotly_chart(style(fig, 340), width="stretch")
    asof(f"As of {ab.date.max():%b %Y} · US Treasury TIC, monthly · long-term securities only · stocks bought on a "
         f"London or Dublin listing may show up under those countries")

    section(4, "Central banks: who abroad holds US Treasuries")
    fo = series("US Treasuries", "Foreign official (all)", TIC3)
    cust = series("US Treasuries", "Foreign central banks (Fed custody)", "H.4.1")
    cust_m = cust.resample("ME").last()
    stack = pd.DataFrame({"Central banks, held at the Fed": cust_m, "Central banks, held elsewhere": fo - cust_m,
                          "Private investors": fa - fo}).dropna()
    st2 = cut(stack, window("us_off", "10Y"))
    fig = go.Figure()
    for i, c in enumerate(stack.columns):
        fig.add_trace(go.Scatter(x=st2.index, y=st2[c], name=c, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                 hovertemplate="%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 400), width="stretch")
    asof(f"Monthly through {stack.index[-1]:%b %Y} · the three layers add up to total foreign holdings · latest "
         f"weekly custody reading ${cust.iloc[-1]:,.0f}bn on {cust.index[-1]:%d %b %Y}")
    st.caption("Covers all US Treasuries held abroad: bills, notes and bonds. "
               "Official = foreign central banks and governments. Private = everyone else abroad (banks, funds, "
               "insurers, hedge funds). Central banks keep most of their Treasuries at the New York Fed, which "
               "reports weekly, so a drop there is the earliest sign of central bank selling.")

# ================================================================== JAPAN
with tab_jp:
    st.caption("Same four sections as the United States tab. Flows are Japan's balance of payments via the Bank of "
               "Japan, monthly, about 5 weeks behind, converted to USD at each month's average exchange rate.")
    jp = df[df.source.str.contains("BoJ balance of payments")]

    section(1, "Who owns Japanese government bonds")
    ownership("Japanese government bonds", "jp")

    section(2, "Foreign investors: who's buying and selling Japanese bonds")
    jb = df[df.market == "Japanese bonds by buyer"]
    st.subheader("Ranking")
    k = window_pick("jb_win")
    bm = sorted(jb.date.unique())[-k:]
    st.plotly_chart(buysell(jb[jb.date.isin(bm)].groupby("holder").amount.sum().sort_values(),
                            pin=("United States",)), width="stretch")
    asof(f"Net purchases {pd.Timestamp(bm[0]):%b %Y} to {pd.Timestamp(bm[-1]):%b %Y} · all Japanese long-term bonds "
         f"(government and corporate) · country = where the other side of the trade sits, so financial hubs "
         f"(US, UK) include investors from elsewhere trading through New York and London · the United States bar "
         f"has run about 2x actual US buying (see Data checks)")
    st.subheader("Over time")
    view = st.segmented_control("View", ["By country (running total)", "All foreign investors (monthly)"],
                                default="By country (running total)", key="jb_view",
                                label_visibility="collapsed") or "By country (running total)"
    if view.startswith("By country"):
        running_total(jb.pivot(index="date", columns="holder", values="amount"),
                      ["United States", "United Kingdom", "France", "Cayman Islands", "China"], "jb",
                      "Running total of each country's net purchases from the start of the range · Japan publishes "
                      "buying and selling by country, not holdings, so this stands in for the US holdings chart")
    else:
        fall = series("Japanese bonds (all long-term)", "Foreign", "BoJ balance of payments", "net purchases")
        fgov = series("Japanese government bonds", "Foreign", "BoJ balance of payments", "net purchases")
        start = window("jb_tot", "3Y")
        mo = cut(pd.DataFrame({"Government bonds": fgov, "Other bonds": fall - fgov}).dropna(), start)
        fig = go.Figure()
        for i, c in enumerate(mo.columns):
            fig.add_trace(go.Bar(x=mo.index, y=mo[c], name=c, marker=dict(color=SERIES[i * 3], line=dict(width=0)),
                                 hovertemplate="%{y:$,.1f}bn"))
        fig.update_layout(barmode="relative", bargap=0.15)
        st.plotly_chart(style(fig, 380), width="stretch")
        asof(f"Monthly through {mo.index[-1]:%b %Y} · all foreign investors' net purchases of Japanese long-term "
             f"bonds · each month's bars add up to the country ranking for that month")
    not_published("Japan does not publish foreign holdings of its bonds by country.")

    section(3, "Japanese investors abroad")
    st.info("These are Japanese private investors and pension funds. The Ministry of Finance's intervention "
            "selling (mostly US Treasury bills) is not included here; it shows in section 4 and in the United "
            "States tab, section 2.")
    scope = st.segmented_control("Bonds", ["Government bonds (12 countries itemized)", "All bonds (38 countries)"],
                                 default="Government bonds (12 countries itemized)", key="jo_scope",
                                 label_visibility="collapsed") or "Government bonds (12 countries itemized)"
    gov_only = scope.startswith("Government")
    if gov_only:
        out_ = jp[(jp.market == "Japanese investors abroad") & (jp.holder != "All countries")].copy()
        out_["holder"] = out_.holder.replace({"Other countries": "All other countries (not itemized)"})
    else:
        out_ = jp[jp.market == "Japanese investors abroad (all bonds)"]
    st.subheader("Ranking: where Japanese investors are buying and selling bonds")
    k = window_pick("jo_win")
    win = sorted(out_.date.unique())[-k:]
    st.plotly_chart(buysell(out_[out_.date.isin(win)].groupby("holder").amount.sum().sort_values(),
                            pin=("United States",)), width="stretch")
    asof(f"Net purchases {pd.Timestamp(win[0]):%b %Y} to {pd.Timestamp(win[-1]):%b %Y} · United States always "
         f"shown · long-term "
         + ("government bonds; Japan only itemizes 12 issuers, everything else is one 'other' bar · switch to "
            "All bonds to see which countries are likely inside it (Japan doesn't break it out)"
            if gov_only else "bonds of all kinds (government and corporate) by the issuer's country"))
    st.subheader("Over time: running total by country")
    running_total(out_.pivot(index="date", columns="holder", values="amount"),
                  ["United States", "France", "United Kingdom", "Germany", "Italy"]
                  + ([] if gov_only else ["South Korea"]), "jo_" + ("g" if gov_only else "a"),
                  "Running total of Japanese investors' net purchases by issuing country · a falling line = "
                  "steady selling")

    st.subheader("Repatriation: are Japanese investors bringing money home?")
    ja = df[df.market == "Japanese investors abroad (all securities)"].pivot(
        index="date", columns="holder", values="amount")
    ja = ja[["Foreign stocks & funds", "Foreign bonds (long-term)", "Foreign bonds (short-term)"]]
    c1, c2 = st.columns([3, 1])
    with c1:
        ja = cut(ja, window("jp_rep", "3Y"))
    with c2:
        rmode = st.segmented_control("Show", ["Monthly", "Running total"], default="Monthly", key="jp_repmode",
                                     label_visibility="collapsed") or "Monthly"
    fig = go.Figure()
    if rmode == "Monthly":
        for i, c in enumerate(ja.columns):
            fig.add_trace(go.Bar(x=ja.index, y=ja[c], name=c, marker=dict(color=SERIES[i], line=dict(width=0)),
                                 hovertemplate="%{y:$,.1f}bn"))
        fig.update_layout(barmode="relative", bargap=0.15)
    else:
        for i, c in enumerate(ja.columns):
            line(fig, ja[c].cumsum(), c, SERIES[i])
        line(fig, ja.sum(axis=1).cumsum(), "Total", INK, 2.5)
    st.plotly_chart(style(fig, 380), width="stretch")
    asof(f"Monthly through {ja.index[-1]:%b %Y} · Japanese investors' net purchases of all foreign stocks and "
         f"bonds · below zero = selling foreign securities (repatriation)")
    st.caption("This records Japanese investors selling foreign securities. It doesn't show whether they converted "
               "the proceeds into yen or what they bought at home; section 1 shows who is adding Japanese "
               "government bonds each quarter.")

    section(4, "Central bank: Ministry of Finance reserves vs Japanese investors")
    res = series("Japan official reserves", "Ministry of Finance", "BoJ balance of payments")
    priv = jp[(jp.market == "Japanese investors abroad") & (jp.holder == "All countries")].set_index("date").amount
    pv = cut(pd.DataFrame({"Japanese investors (excl. reserves): net purchases of foreign government bonds": priv,
                           "Ministry of Finance: change in FX reserves": res.diff()}), window("jp_pv", "3Y"))
    fig = go.Figure()
    for i, c in enumerate(pv.columns):
        fig.add_trace(go.Bar(x=pv.index, y=pv[c], name=c, marker=dict(color=SERIES[i], line=dict(width=0)),
                             hovertemplate="%{y:$,.1f}bn"))
    fig.update_layout(barmode="group", bargap=0.2)
    st.plotly_chart(style(fig, 380), width="stretch")
    asof(f"Reserves monthly through {res.index[-1]:%b %Y} (IMF via FRED) · investor flows through "
         f"{priv.index.max():%b %Y} · reserve changes also include currency and price moves")
    st.caption("Both bars are Japanese residents. The first is life insurers, banks, pension funds (including the "
               "GPIF) and households; the second is the Ministry of Finance's reserves, which it sells to intervene. "
               "A big drop in reserves with no matching investor selling is intervention, and it shows up in the "
               "United States tab as Japan selling Treasuries (mostly bills).")

# ================================================================== OTHER COUNTRIES
with tab_oth:
    st.header("Foreign share of each government bond market")
    MK = {"US": "US Treasuries", "Japan": "Japanese government bonds", "UK": "UK gilts",
          "France": "French government bonds", "Italy": "Italian government bonds",
          "Germany": "German government bonds", "Spain": "Spanish government bonds"}
    rows_ = []
    for name, m in MK.items():
        z = holders(m)
        rows_.append((f"{name} ({z.index[-1]:%b %Y})", z["Foreign"].iloc[-1] / z.iloc[-1].sum() * 100))
    fs = pd.Series(dict(rows_)).sort_values()
    fig = go.Figure(go.Bar(x=fs.values, y=fs.index, orientation="h", marker=dict(color=SERIES[0], line=dict(width=0)),
                           text=[f"{v:.0f}%" for v in fs.values], textposition="outside",
                           hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
    fig = style(fig, 320, ".0f", "%")
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(tickformat=".0f", ticksuffix="%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(ticksuffix="", tickformat="", tickfont=dict(color=INK2), showgrid=False)
    st.plotly_chart(fig, width="stretch")
    asof("Latest quarter for each market · for euro countries 'foreign' means outside the euro area, so their "
         "shares understate how much is held outside each country")

    section(1, "Who owns European government bonds")
    pick_m = st.segmented_control("Market", ["UK", "France", "Italy", "Germany", "Spain"], default="France",
                                  key="oth_mkt", label_visibility="collapsed") or "France"
    st.subheader(f"Who owns {MK[pick_m]}")
    ownership(MK[pick_m], "oth")
    not_published("these countries don't publish buying and selling by investor country.")

    section(2, "Where countries keep their foreign savings")
    fa_ = df[df.market == "Foreign assets"].copy()
    fa_[["country", "group"]] = fa_.holder.str.split("|", expand=True)
    sav = list(dict.fromkeys(fa_.country))
    who = st.segmented_control("Country", sav, default="South Korea", key="sav_c",
                               label_visibility="collapsed") or "South Korea"
    c = fa_[fa_.country == who].pivot(index="date", columns="group", values="amount")
    latest = c.index.max()
    order = ["Reserves (central bank)", "Government (incl. state pension & wealth funds)",
             "Insurers, pensions & funds", "Households & companies", "Banks", "Portfolio investments (all)"]
    live = [g for g in order if g in c.columns and c[g].last_valid_index() == latest]
    c = cut(c[live].dropna(), window("sav", "20Y"))
    fig = go.Figure()
    for i, g in enumerate(live):
        fig.add_trace(go.Scatter(x=c.index, y=c[g], name=g, stackgroup="one", mode="lines",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                 hovertemplate="%{y:$,.0f}bn"))
    st.plotly_chart(style(fig, 420), width="stretch")
    asof(f"As of {latest:%d %b %Y} · IMF international investment position data, quarterly · foreign stocks and "
         f"bonds at market value, by who holds them at home, plus central bank reserves")
    with st.expander("How to read this chart"):
        st.markdown(
            "- A country that sells more abroad than it buys (like Korea with chip exports) earns dollars. Those "
            "dollars end up in one of two places.\n"
            "- **Bottom layer (blue)**: the central bank keeps them as official reserves, mostly safe government "
            "bonds, largely US Treasuries.\n"
            "- **Other layers**: pension funds, insurers, households and companies buy foreign stocks and bonds "
            "themselves.\n"
            "- When the blue layer is flat and the others grow, the country is recycling its dollars privately, "
            "which keeps money flowing out and the currency weaker than its trade surplus alone would suggest.\n"
            "- Values are at market prices, so stock market moves change the size too. For Korea, the government "
            "layer is mostly the National Pension Service and the Korea Investment Corporation.\n"
            "- China, Switzerland and the UK don't say who holds their foreign portfolio, so it shows as one "
            "layer.")

    st.caption("To see how much of this lands in US markets, use United States tab → section 2 → "
               "Over time: one country's US portfolio.")

# ================================================================== HEDGE FUNDS
TENORS = ["2-year", "5-year", "10-year", "Ultra 10-year", "Bond", "Ultra bond"]
TENOR_LABELS = {"Ultra 10-year": "Ultra 10-year (~10Y)", "Bond": "Bond (15–25Y)", "Ultra bond": "Ultra bond (25–30Y)"}
with tab_hf:
    fut = df[df.source.str.startswith("CFTC")]
    tot = fut.groupby(["date", "holder"]).amount.sum().unstack()
    hf_short = -tot["Leveraged funds"].iloc[-1]
    with st.expander("Why this matters", expanded=True):
        st.markdown(
            "- Hedge funds run a trade called the **basis trade**: they buy Treasury bonds with borrowed money and "
            "sell Treasury futures against them, pocketing the small price gap between the two. Their net futures "
            f"short, a rough gauge of its size, is \\${hf_short:,.0f}bn as of {tot.index[-1]:%d %b %Y}.\n"
            "- It's very leveraged. When it unwinds in a hurry (March 2020, April 2025), hedge funds dump bonds all "
            "at once, Treasury yields jump, and in 2020 the Fed had to step in.\n"
            "- So the size of their futures short, and whether it's shrinking, is a read on how fragile the "
            "Treasury market is.")
    st.header("Treasury futures positioning")
    c1, c2 = st.columns([1, 1])
    with c1:
        start = window("hf", "5Y")
    with c2:
        hview = st.segmented_control("View", ["Hedge funds by maturity", "Who's on each side"],
                                     default="Hedge funds by maturity", key="hf_view",
                                     label_visibility="collapsed") or "Hedge funds by maturity"
    fig = go.Figure()
    if hview == "Hedge funds by maturity":
        lev = fut[fut.holder == "Leveraged funds"].pivot(index="date", columns="market", values="amount")
        lev.columns = [c.replace("UST futures ", "") for c in lev.columns]
        lv = cut(lev[[t for t in TENORS if t in lev.columns]], start).rename(columns=TENOR_LABELS)
        for i, t in enumerate(lv.columns):
            fig.add_trace(go.Bar(x=lv.index, y=lv[t], name=t, marker=dict(color=SERIES[i], line=dict(width=0)),
                                 hovertemplate="%{y:$,.0f}bn"))
        fig.update_layout(barmode="relative", bargap=0.1)
        note = "hedge funds' ('leveraged funds') net futures position by contract · below zero = net short"
    else:
        t2 = cut(tot, start)
        line(fig, t2["Asset managers"], "Asset managers (long)", SERIES[1])
        line(fig, -t2["Leveraged funds"], "Hedge funds (short)", SERIES[0])
        line(fig, -t2["Dealers"], "Dealers (short)", SERIES[2])
        note = ("shorts shown as positive so the sides can be compared · asset managers buy futures as a cheap way "
                "to own Treasuries; when the hedge fund line falls and theirs doesn't, dealers (big banks) take up "
                "the selling side")
    st.plotly_chart(style(fig, 420), width="stretch")
    asof(f"As of {tot.index[-1]:%d %b %Y} · CFTC Traders in Financial Futures, weekly · face value of contracts · "
         f"{note}")


# ================================================================== AUCTIONS
AUCTIONS = Path(__file__).parent / "data" / "auctions.csv"
TAILS = Path(__file__).parent / "data" / "tails.csv"
JGB_AUCTIONS = Path(__file__).parent / "data" / "jgb_auctions.csv"
ALLOT = Path(__file__).parent / "data" / "allotments.csv"
TENORS_A = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]
TENORS_J = ["2-Year", "5-Year", "10-Year", "20-Year", "30-Year", "40-Year"]
METRICS = {"Tail (bp)": ("tail_bp", "bp"),
           "Bid-to-cover": ("bid_to_cover", "x"),
           "Dealer takedown (%)": ("dealer_pct", "%"),
           "Indirect bidders, mostly foreign (%)": ("indirect_pct", "%"),
           "Direct bidders, mostly US funds (%)": ("direct_pct", "%"),
           "High yield (%)": ("high_yield", "%"),
           "Size ($bn)": ("size_bn", "bn")}
METRICS_J = {"Tail (bp)": ("tail_bp", "bp"), "Tail (yen)": ("tail_yen", "yen"), "Bid-to-cover": ("bid_to_cover", "x"),
             "Yield (%)": ("yield", "%"), "Size (¥bn)": ("size_bn_jpy", "bn")}
FMT = {"x": (".2f", "x"), "%": (".2f", "%"), "bp": (".1f", "bp"), "bn": (",.0f", "bn"), "yen": (".2f", " yen")}


@st.cache_data(ttl=3600)
def load_csv(path: str, version: float) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["date"] = pd.to_datetime(d["date"] if "date" in d else d["issue_date"])
    return d


def history_chart(a: pd.DataFrame, col: str, unit: str, key: str, label_col: str | None = None) -> None:
    fig = go.Figure()
    if col == "tail_bp" and "tail_src" in a:
        for i, (src, name) in enumerate([("Helious", "Reported tail (Helious)"),
                                         ("Estimate", "Estimated tail (reopenings)")]):
            s = a[a.tail_src == src]
            fig.add_trace(go.Scatter(x=s.index, y=s[col], name=name, mode="markers",
                                     marker=dict(size=8, color=SERIES[0] if i == 0 else SERIES[1],
                                                 symbol="circle" if i == 0 else "diamond"),
                                     hovertemplate="%{x|%d %b %Y}: %{y:+.1f}bp<extra></extra>"))
    else:
        cd = a[[label_col]].values if label_col else None
        fig.add_trace(go.Scatter(x=a.index, y=a[col], name="Each auction", mode="lines+markers",
                                 line=dict(color=SERIES[0], width=1.5), marker=dict(size=7), customdata=cd,
                                 hovertemplate="%{x|%d %b %Y}" + (" · %{customdata[0]}" if label_col else "")
                                 + "<br>%{y:.2f}<extra></extra>"))
    avg = a[col].dropna().rolling(6, min_periods=3).mean()
    fig.add_trace(go.Scatter(x=avg.index, y=avg.values, name="6-auction average", mode="lines",
                             line=dict(color=MUTED, width=2, dash="dot"), hovertemplate="%{y:.2f}"))
    yfmt, ysuf = FMT[unit]
    fig = style(fig, 400, yfmt, ysuf)
    fig.update_layout(hovermode="closest")
    st.plotly_chart(fig, width="stretch", key=key)


def verdict(score: int) -> str:
    return {3: "Strong", 2: "Solid", 1: "Soft", 0: "Weak"}[int(score)]


with tab_auc:
    mkt = st.segmented_control("Market", ["US Treasuries", "Japanese government bonds"], default="US Treasuries",
                               key="au_mkt", label_visibility="collapsed") or "US Treasuries"
    with st.expander("How to read auction results", expanded=False):
        st.markdown(
            "- **Tail**: how far the auction's cut-off yield landed above the market yield just before bidding "
            "closed. Positive = the Treasury had to pay up to sell the bonds (weak). Negative ('stopped through') "
            "= buyers paid more than the market (strong). The single most-watched number.\n"
            "- **Bid-to-cover**: dollars bid for every dollar sold. Higher = more demand.\n"
            "- **Dealer takedown**: share left with the primary dealers, the banks obliged to bid. They're the "
            "buyer of last resort, so a high share means end investors stepped back.\n"
            "- **Indirect bidders**: bids placed through dealers, mostly foreign central banks and big asset "
            "managers. **Direct bidders**: bids placed straight with the Treasury, mostly US funds.\n"
            "- **Japan's tail** is official: the gap between the average and lowest accepted price (or yield). "
            "Japan doesn't publish who bought.\n"
            "- Strong/weak is judged against the average of that maturity's previous 6 auctions.")

    if mkt == "US Treasuries":
        if not AUCTIONS.exists():
            st.warning("Auction data arrives with the next daily refresh.")
        else:
            au = load_csv(str(AUCTIONS), AUCTIONS.stat().st_mtime)
            au["dkey"] = au.date.dt.strftime("%Y-%m-%d")
            if TAILS.exists():
                tl = load_csv(str(TAILS), TAILS.stat().st_mtime)
                tl["dkey"] = tl.date.dt.strftime("%Y-%m-%d")
                tl["rank"] = tl.source.map({"Helious": 0, "Estimate": 1})
                tl = tl.sort_values("rank").drop_duplicates(["dkey", "tenor"])  # reported beats estimated
                au = au.merge(tl[["dkey", "tenor", "tail_bp", "source"]].rename(columns={"source": "tail_src"}),
                              on=["dkey", "tenor"], how="left")
            else:
                au["tail_bp"], au["tail_src"] = float("nan"), None

            st.header("Latest auction for each maturity")
            rows_ = []
            for t in TENORS_A:
                a = au[au.tenor == t].sort_values("date")
                if len(a) < 7:
                    continue
                last, prev = a.iloc[-1], a.iloc[-7:-1]
                btc_d = last.bid_to_cover - prev.bid_to_cover.mean()
                dlr_d = last.dealer_pct - prev.dealer_pct.mean()
                ind_d = last.indirect_pct - prev.indirect_pct.mean()
                tail = ("n/a" if pd.isna(last.tail_bp) else
                        f"{'≈' if last.tail_src == 'Estimate' else ''}{last.tail_bp:+.1f}")
                score = int(btc_d > 0) + int(dlr_d < 0) + int(ind_d > 0)
                rows_.append({"Maturity": t, "Date": f"{last.date:%d %b %Y}",
                              "Type": "Reopening" if last.reopening else "New",
                              "Size ($bn)": f"{last.size_bn:,.0f}", "High yield (%)": f"{last.high_yield:.3f}",
                              "Tail (bp)": tail,
                              "Bid-to-cover": f"{last.bid_to_cover:.2f} ({btc_d:+.2f})",
                              "Dealers (%)": f"{last.dealer_pct:.1f} ({dlr_d:+.1f})",
                              "Indirect (%)": f"{last.indirect_pct:.1f} ({ind_d:+.1f})",
                              "Direct (%)": f"{last.direct_pct:.1f}", "Read": verdict(score)})
            st.table(pd.DataFrame(rows_).set_index("Maturity"))
            asof("Brackets = change vs the average of that maturity's previous 6 auctions · Read counts how many of "
                 "bid-to-cover (up), dealers (down) and indirect (up) beat that average · Tail: positive = tailed "
                 "(weak), negative = stopped through (strong); reported by Helious from July 2026, ≈ = our estimate "
                 "for reopenings · TreasuryDirect auction results")

            st.header("History by maturity")
            tenor = st.segmented_control("Maturity", TENORS_A, default="10-Year", key="au_tenor") or "10-Year"
            metric = st.segmented_control("Metric", list(METRICS), default="Tail (bp)", key="au_metric") \
                or "Tail (bp)"
            col, unit = METRICS[metric]
            a = cut(au[au.tenor == tenor].set_index("date").sort_index(), window("au_win", "5Y"))
            history_chart(a, col, unit, "au_chart", "term")
            if col == "tail_bp":
                asof("Reported tails (circles) cover every auction from July 2026. Estimated tails (diamonds) cover "
                     "reopenings back to 2010: the market yield of the same bond from Treasury's FedInvest daytime "
                     "price on auction day, which matched reported tails within about 0.5bp on average. Estimates get "
                     "noisier on days with big market moves (inflation data, March 2020), when prices can shift "
                     "between Treasury's price snapshot and the 1pm deadline. New-issue tails before July 2026 can't "
                     "be estimated reliably from free data, so they're left blank.")
            else:
                asof(f"{len(a)} {tenor} auctions in range, new issues and reopenings · TreasuryDirect")

            st.header("Who bought")
            mix = st.segmented_control("View", ["By bidder type (auction day)", "By investor type (allotments)"],
                                       default="By bidder type (auction day)", key="au_mixview",
                                       label_visibility="collapsed") or "By bidder type (auction day)"
            start = window("au_mix", "5Y")
            fig = go.Figure()
            if mix.startswith("By bidder"):
                a2 = cut(au[au.tenor == tenor].set_index("date").sort_index(), start)
                for i, (c, n) in enumerate([("indirect_pct", "Indirect (via dealers: foreign, big funds)"),
                                            ("direct_pct", "Direct (straight to Treasury)"),
                                            ("dealer_pct", "Dealers (left over)")]):
                    fig.add_trace(go.Bar(x=a2.index, y=a2[c], name=n,
                                         marker=dict(color=SERIES[[0, 2, 7][i]], line=dict(width=0)),
                                         hovertemplate="%{y:.1f}%"))
                note = (f"Share of the competitive auction won through each bidding channel, {tenor} · published the "
                        f"day of the auction · TreasuryDirect")
            else:
                al = load_csv(str(ALLOT), ALLOT.stat().st_mtime) if ALLOT.exists() else None
                if al is None:
                    st.warning("Allotment data arrives with the next daily refresh.")
                    note = ""
                else:
                    a3 = cut(al[al.tenor == tenor].set_index("date").sort_index(), start)
                    groups = ["Investment funds", "Foreign", "Pensions & insurers", "Banks", "Individuals", "Dealers",
                              "Other"]
                    colors = [SERIES[2], SERIES[0], SERIES[6], SERIES[5], SERIES[4], SERIES[7], OTHER]
                    for g, c in zip(groups, colors):
                        fig.add_trace(go.Bar(x=a3.index, y=a3[g], name=g, marker=dict(color=c, line=dict(width=0)),
                                             hovertemplate="%{y:.1f}%"))
                    note = (f"Share of each {tenor} auction allotted to each investor type, excluding the Fed's own "
                            f"add-on purchases · dated by issue date, published about twice a month · Treasury "
                            f"investor-class allotments, October 2009 onward")
            fig.update_layout(barmode="stack", bargap=0.15)
            st.plotly_chart(style(fig, 380, ".0f", "%"), width="stretch", key="au_mixchart")
            if note:
                asof(note)
            st.caption("The two views cut the same auctions differently. Bidder type is how bids came in: "
                       "'indirect' bids go through a dealer and mostly come from foreign central banks and large "
                       "asset managers, so indirect roughly equals Foreign + Investment funds. Investor type is who "
                       "actually ended up owning the bonds, with funds, foreign buyers, pensions and banks split out.")

    else:
        if not JGB_AUCTIONS.exists():
            st.warning("JGB auction data arrives with the next daily refresh.")
        else:
            jg = load_csv(str(JGB_AUCTIONS), JGB_AUCTIONS.stat().st_mtime)
            st.header("Latest auction for each maturity")
            rows_ = []
            for t in TENORS_J:
                a = jg[jg.tenor == t].sort_values("date")
                if len(a) < 7:
                    continue
                last, prev = a.iloc[-1], a.iloc[-7:-1]
                btc_d = last.bid_to_cover - prev.bid_to_cover.mean()
                has_tail = pd.notna(last.tail_bp)
                tail_d = last.tail_bp - prev.tail_bp.mean() if has_tail else float("nan")
                score = int(btc_d > 0) + (int(tail_d < 0) * 2 if has_tail else int(btc_d > 0))
                rows_.append({"Maturity": t, "Date": f"{last.date:%d %b %Y}",
                              "Size (¥bn)": f"{last.size_bn_jpy:,.0f}", "Yield (%)": f"{last['yield']:.3f}",
                              "Tail (bp)": f"{last.tail_bp:.1f} ({tail_d:+.1f})" if has_tail else "n/a",
                              "Tail (yen)": f"{last.tail_yen:.2f}" if has_tail else "n/a",
                              "Bid-to-cover": f"{last.bid_to_cover:.2f} ({btc_d:+.2f})",
                              "Read": verdict(min(score, 3))})
            st.table(pd.DataFrame(rows_).set_index("Maturity"))
            asof(f"Brackets = change vs the average of that maturity's previous 6 auctions · Read weighs the tail "
                 f"(smaller = better, counts double) and bid-to-cover (higher = better) · the 40-year is sold on "
                 f"yield, so it has no tail · Japan Ministry of Finance, file updated about monthly, latest auction "
                 f"{jg.date.max():%d %b %Y}")

            st.header("History by maturity")
            tenor = st.segmented_control("Maturity", TENORS_J, default="30-Year", key="jg_tenor") or "30-Year"
            metric = st.segmented_control("Metric", list(METRICS_J), default="Tail (bp)", key="jg_metric") \
                or "Tail (bp)"
            col, unit = METRICS_J[metric]
            a = cut(jg[jg.tenor == tenor].set_index("date").sort_index(), window("jg_win", "5Y"))
            history_chart(a, col, unit, "jg_chart")
            asof(f"{len(a)} {tenor} JGB auctions in range · Japan Ministry of Finance · tail = gap between the "
                 f"average and lowest accepted price, shown in bp of yield or in yen per ¥100")


# ------------------------------------------------------------------ data checks
def _s(market: str, holder: str, src: str, measure: str = "holdings") -> pd.Series:
    x = df[(df.market == market) & (df.holder == holder) & (df.measure == measure)
           & df.source.str.contains(src, regex=False)]
    return x.set_index("date")["amount"].sort_index()


def run_checks() -> pd.DataFrame:
    out = []

    def add(name, a_label, a, b_label, b, tol_pct, why):
        diff = a - b
        pct = abs(diff) / max(abs(a), abs(b), 1e-9) * 100
        status = "Agrees" if pct <= tol_pct else "Explained gap" if why.startswith("Expected") else "Doesn't reconcile"
        out.append({"Check": name, "Source A": f"{a_label}: {a:,.1f}", "Source B": f"{b_label}: {b:,.1f}",
                    "Gap ($bn)": f"{diff:+,.1f}", "Status": status, "Why": why})

    try:  # 1. foreign holdings, TIC vs Z.1
        z = _s("US Treasuries", "Foreign", "Z.1")
        t = _s("US Treasuries", "Foreign (all)", "TIC (monthly)")
        q = z.index[-1]
        add(f"Foreign holdings of Treasuries, {q:%b %Y}", "Treasury TIC", t[:q].iloc[-1], "Fed Z.1", z.iloc[-1], 1.0,
            "Z.1 builds its foreign number from TIC, so these should be within a fraction of a percent.")
    except Exception:
        pass
    try:  # 2. Fed holdings, H.4.1 vs Z.1
        z = _s("US Treasuries", "Central bank", "Z.1")
        h = _s("US Treasuries", "Federal Reserve (weekly balance sheet)", "H.4.1")
        q = z.index[-1]
        add(f"Fed's Treasury holdings, {q:%b %Y}", "Fed weekly balance sheet", h[:q].iloc[-1], "Fed Z.1", z.iloc[-1],
            1.0, "Expected: the two Fed releases measure the holdings on different bases. The gap has held "
                 "between about $340bn and $490bn every quarter for two years, so changes are comparable even if "
                 "levels aren't.")
    except Exception:
        pass
    try:  # 3. Fed custody vs foreign official
        fo = _s("US Treasuries", "Foreign official (all)", "TIC (monthly)")
        cu = _s("US Treasuries", "Foreign central banks (Fed custody)", "H.4.1").resample("ME").last()
        m = fo.index[-1]
        add(f"Central bank Treasuries, {m:%b %Y}", "All foreign official (TIC)", fo.iloc[-1],
            "Held at the NY Fed", cu[m], 0.0, "Expected: custody at the Fed is a subset, about 70% of the total. "
                                              "The rest sits with private custodians like Euroclear.")
    except Exception:
        pass
    try:  # 4. Japan: TIC selling vs reserves + private
        jn = _s("US Treasuries", "Japan", "TIC (monthly)", "net purchases")
        ms = jn.index[-3:]
        res = _s("Japan official reserves", "Ministry of Finance", "BoJ")
        r_chg = res[ms[-1]] - res[:ms[0] - pd.offsets.MonthEnd(1)].iloc[-1]
        pv = df[(df.market == "Japanese investors abroad") & (df.holder == "United States")].set_index("date").amount
        add(f"Japan's Treasury selling, {ms[0]:%b}–{ms[-1]:%b %Y}", "TIC: all of Japan", jn[ms].sum(),
            "Reserves change + Japanese investors' US govt bonds", r_chg + pv[ms].sum(), 10.0,
            "Expected to be close, not exact: reserve changes include non-US assets, deposits and price moves.")
    except Exception:
        pass
    try:  # 5. Japan BoP: countries sum to total
        jb = df[df.market == "Japanese bonds by buyer"]
        tot = _s("Japanese bonds (all long-term)", "Foreign", "BoJ balance", "net purchases")
        m = tot.index[-1]
        add(f"Foreign buying of Japanese bonds, {m:%b %Y}", "Sum of the country bars",
            jb[jb.date == m].amount.sum(), "Japan's reported total", tot.iloc[-1], 30.0,
            "Expected: the app shows 23 main countries; the rest sit in smaller regions not charted.")
    except Exception:
        pass
    try:  # 6. Japan JGB: BoJ holdings change vs BoP flows
        h = _s("Japanese government bonds", "Foreign", "BoJ Flow")
        f = _s("Japanese government bonds", "Foreign", "BoJ balance", "net purchases")
        q, p = h.index[-1], h.index[-2]
        add(f"Foreign holdings of Japanese govt bonds, change in Q{q.quarter} {q.year}", "BoJ holdings change",
            h.iloc[-1] - h.iloc[-2], "Sum of monthly foreign buying", f[(f.index > p) & (f.index <= q)].sum(), 40.0,
            "Expected to point the same way: holdings also move with bond prices and the yen-dollar rate.")
    except Exception:
        pass
    try:  # 7. TIC tables agree with each other
        a = _s("US Treasury notes & bonds", "Cayman Islands", "long-term securities")
        b = _s("US Treasury notes & bonds (Cayman)", "Cayman Islands", "TIC (monthly)")
        add(f"Cayman notes & bonds, {a.index[-1]:%b %Y}", "TIC table 1", a.iloc[-1], "TIC table 3", b.iloc[-1], 0.5,
            "Same Treasury survey published two ways; should match exactly.")
    except Exception:
        pass
    try:  # 8. US buying Japanese bonds, like for like (all bonds), 12 months
        g = _s("US investors abroad: Foreign government bonds", "Japan", "abroad", "net purchases")
        c = _s("US investors abroad: Foreign corporate bonds", "Japan", "abroad", "net purchases")
        jp_us = df[(df.market == "Japanese bonds by buyer") & (df.holder == "United States")].set_index("date").amount
        ms = (g + c).dropna().index[-12:]
        add(f"US buying of Japanese bonds, {ms[0]:%b %Y}–{ms[-1]:%b %Y}", "US data (all bonds)",
            (g + c)[ms].sum(), "Japan's data (all bonds)", jp_us.reindex(ms).sum(), 25.0,
            "Expected: Japan books each trade by where the other side sits, so New York dealers and custodians "
            "acting for investors elsewhere count as 'United States'. The US data counts what US residents end up "
            "owning. Japan's figure has run about 2x the US figure in every period over the last two years, while "
            "both move in the same direction.")
    except Exception:
        pass
    try:  # 9. Hedge funds: futures vs filings direction
        lev = df[df.source.str.startswith("CFTC") & (df.holder == "Leveraged funds")].groupby("date").amount.sum()
        o = df[df.source.str.startswith("OFR")].pivot(index="date", columns="holder", values="amount")
        q, p = o.index[-1], o.index[-2]
        add(f"Hedge fund short, change in Q{q.quarter} {q.year}", "CFTC futures short",
            -(lev[:q].iloc[-1] - lev[:p].iloc[-1]), "Form PF short exposure",
            o.loc[q, "Short Treasury exposure"] - o.loc[p, "Short Treasury exposure"], 50.0,
            "Expected to point the same way: Form PF covers all short positions and is 10-year-equivalent, "
            "while CFTC is face value of futures only.")
    except Exception:
        pass
    return pd.DataFrame(out)


with tab_chk:
    st.subheader("Do the overlapping sources agree?")
    st.caption("Several sources measure the same thing from different angles. These checks run on every data "
               "refresh. Agrees = within normal rounding. Explained gap = a known difference in how the sources "
               "count. Doesn't reconcile = a gap worth keeping in mind when reading the charts.")
    chk = run_checks()
    if len(chk):
        st.table(chk.set_index("Check"))

# ------------------------------------------------------------------ sources
with tab_src:
    fresh = (df.groupby("source").date.max().rename("Latest data").dt.strftime("%d %b %Y").to_frame())
    for name, path in [("TreasuryDirect auction results (per auction)", AUCTIONS),
                       ("Japan Ministry of Finance JGB auction results", JGB_AUCTIONS),
                       ("Auction tails: Helious (reported) + FedInvest (estimated)", TAILS),
                       ("Treasury investor-class allotments", ALLOT)]:
        if path.exists():
            fresh.loc[name, "Latest data"] = f"{load_csv(str(path), path.stat().st_mtime).date.max():%d %b %Y}"
    fresh["Link"] = fresh.index.map({
        "Fed H.4.1 (weekly)": "https://www.federalreserve.gov/releases/h41/",
        "Fed Z.1 Financial Accounts (quarterly)": "https://www.federalreserve.gov/releases/z1/",
        "US Treasury TIC (monthly)": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "CFTC Traders in Financial Futures (weekly)": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/",
        "BoJ Flow of Funds (quarterly)": "https://www.boj.or.jp/en/statistics/sj/index.htm",
        "BoJ balance of payments (monthly)": "https://www.boj.or.jp/en/statistics/br/index.htm",
        "ONS UK Economic Accounts (quarterly)": "https://www.ons.gov.uk/economy/nationalaccounts/uksectoraccounts",
        "ECB securities holdings (quarterly)": "https://data.ecb.europa.eu/data/datasets/SHSS",
        "US Treasury TIC long-term securities (monthly)": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "IMF international investment position (quarterly)": "https://data.imf.org/",
        "US Treasury TIC US holdings abroad (monthly)": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "OFR Hedge Fund Monitor, SEC Form PF (quarterly)": "https://www.financialresearch.gov/hedge-fund-monitor/",
        "TreasuryDirect auction results (per auction)": "https://www.treasurydirect.gov/auctions/auction-query/",
        "Japan Ministry of Finance JGB auction results": "https://www.mof.go.jp/english/policy/jgbs/auction/past_auction_results/index.html",
        "Auction tails: Helious (reported) + FedInvest (estimated)": "https://helious.io/auctions",
        "Treasury investor-class allotments": "https://home.treasury.gov/data/investor-class-auction-allotments",
    })
    st.dataframe(fresh, width="stretch", column_config={"Link": st.column_config.LinkColumn(display_text="Open")})
    st.caption("Data refreshes daily via GitHub Actions; each source keeps its last good copy if a download fails.")
    st.download_button("Download master table (CSV)", DATA.read_bytes(), "holdings.csv", "text/csv")
