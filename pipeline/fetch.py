"""Pull every source and write one master table: data/holdings.csv

Columns: date, market, holder, measure, amount (USD bn), source
Run: python pipeline/fetch.py
"""
from __future__ import annotations

import csv
import io
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "holdings.csv"
UA = {"User-Agent": "bond-holders-dashboard (github.com/smileys21)"}

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
TIC = "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/"
CFTC = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"


def get(url: str, tries: int = 3) -> str:
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            return r.text
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def fred(series_id: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(get(FRED.format(series_id))))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna().set_index("date")["value"]


def rows(s: pd.Series, market: str, holder: str, measure: str, source: str) -> pd.DataFrame:
    return pd.DataFrame({"date": s.index, "market": market, "holder": holder,
                         "measure": measure, "amount": s.values, "source": source})


# ---------------------------------------------------------------- Fed (H.4.1)
def fed_custody() -> list[pd.DataFrame]:
    src = "Fed H.4.1 (weekly)"
    # Treasuries the Fed holds in custody for foreign central banks
    return [rows(fred("WMTSECL1") / 1e3, "US Treasuries", "Foreign central banks (Fed custody)",
                 "holdings", src)]


# ------------------------------------------------------- Z.1 holders by sector
# FRED codes, millions USD, quarterly. Grouped into 8 holder groups + Other.
Z1_GROUPS = {
    "Federal Reserve": ["BOGZ1FL713061103Q"],
    "Foreign (all)": ["BOGZ1LM263061105Q"],
    "Households (incl. hedge funds)": ["BOGZ1LM153061105Q"],
    "Money market funds": ["BOGZ1FL633061105Q"],
    "Banks": ["BOGZ1FL763061100Q", "BOGZ1FL753061103Q", "BOGZ1FL473061105Q",
              "BOGZ1FL733061103Q"],
    "Mutual funds & ETFs": ["BOGZ1FL653061105Q", "BOGZ1FL563061103Q"],
    "Pension funds": ["BOGZ1FL573061105Q", "BOGZ1FL223061143Q", "BOGZ1FL343061105Q"],
    "Insurers": ["BOGZ1FL543061105Q", "BOGZ1FL513061105Q"],
}
Z1_TOTAL = "BOGZ1FL893061105Q"


def z1_holders() -> list[pd.DataFrame]:
    src = "Fed Z.1 Financial Accounts (quarterly)"
    total = fred(Z1_TOTAL)
    groups = {}
    for name, ids in Z1_GROUPS.items():
        parts = [fred(i) for i in ids]
        groups[name] = pd.concat(parts, axis=1).sum(axis=1, min_count=1)
    df = pd.DataFrame(groups).reindex(total.index)
    other = total - df.fillna(0).sum(axis=1)
    df["Other"] = other
    df.index = df.index + pd.offsets.QuarterEnd(0)  # FRED dates quarters by first day
    df = df.dropna(how="all") / 1e3
    return [rows(df[c].dropna(), "US Treasuries", c, "holdings", src) for c in df.columns]


# ------------------------------------------------------------------ TIC
def tic_table3() -> pd.DataFrame:
    """All countries, monthly since 2020: holdings and net purchases."""
    txt = get(TIC + "slt_table3.txt")
    lines = txt.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("country\tcountry_code"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep="\t")
    df = df[df["date"].astype(str).str.match(r"\d{4}-\d{2}$")]
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    for c in ["for_treas_pos", "for_treas_net"]:
        df[c] = pd.to_numeric(df[c], errors="coerce") / 1e3  # millions -> billions
    df["country"] = df["country"].str.strip().replace(
        {"Of Which: Foreign Official": "Foreign official (all)",
         "Of Which: Foreign Non-Official": "Foreign private (all)",
         "Grand Total": "Foreign (all)"})
    return df


def tic_history() -> pd.DataFrame:
    """Major holders history 2000 onward (billions), used before Table 3 starts."""
    txt = get(TIC + "mfhhis01.txt")
    recs, months = [], None
    mmap = {m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
    years = None
    for raw in csv.reader(io.StringIO(txt), delimiter="\t"):
        cells = [c.strip() for c in raw]
        nonempty = [c for c in cells if c]
        if not nonempty:
            continue
        if all(c in mmap for c in nonempty):
            months = [mmap[c] for c in nonempty]
            continue
        if nonempty[0] == "Country" and months:
            years = [int(y) for y in nonempty[1:]]
            continue
        if years is None or nonempty[0].startswith("-"):
            continue
        name = re.sub(r"\s*\d+/$", "", nonempty[0]).strip()
        name = {"Grand Total": "Foreign (all)", "For. Official": "Foreign official (all)"}.get(name, name)
        vals = cells[1:1 + len(years)]
        for m, y, v in zip(months, years, vals):
            try:
                recs.append((pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0), name, float(v)))
            except ValueError:
                pass
        if name == "Foreign official (all)":
            years = None  # end of block
    return pd.DataFrame(recs, columns=["date", "country", "for_treas_pos"]).drop_duplicates(
        ["date", "country"], keep="first")


def tic() -> list[pd.DataFrame]:
    src = "US Treasury TIC (monthly)"
    t3 = tic_table3()
    hist = tic_history()
    cutoff = t3["date"].min()
    hist = hist[hist["date"] < cutoff]
    pos = pd.concat([hist[["date", "country", "for_treas_pos"]],
                     t3[["date", "country", "for_treas_pos"]]]).dropna()
    net = t3[["date", "country", "for_treas_net"]].dropna()
    out = [pd.DataFrame({"date": pos["date"], "market": "US Treasuries", "holder": pos["country"],
                         "measure": "holdings", "amount": pos["for_treas_pos"], "source": src}),
           pd.DataFrame({"date": net["date"], "market": "US Treasuries", "holder": net["country"],
                         "measure": "net purchases", "amount": net["for_treas_net"], "source": src})]
    return out


# ------------------------------------------------------------------ CFTC
CFTC_CONTRACTS = {"042601": ("2-year", 0.2), "044601": ("5-year", 0.1), "043602": ("10-year", 0.1),
                  "043607": ("Ultra 10-year", 0.1), "020601": ("Bond", 0.1),
                  "020604": ("Ultra bond", 0.1)}  # face value per contract, $mn
CFTC_GROUPS = {"Leveraged funds": "lev_money_positions", "Asset managers": "asset_mgr_positions",
               "Dealers": "dealer_positions"}


def cftc() -> list[pd.DataFrame]:
    src = "CFTC Traders in Financial Futures (weekly)"
    fields = ["report_date_as_yyyy_mm_dd", "cftc_contract_market_code",
              "lev_money_positions_long", "lev_money_positions_short",
              "asset_mgr_positions_long", "asset_mgr_positions_short",
              "dealer_positions_long_all", "dealer_positions_short_all"]
    codes = ",".join(f"'{c}'" for c in CFTC_CONTRACTS)
    params = {"$select": ",".join(fields), "$where": f"cftc_contract_market_code in ({codes})",
              "$limit": 50000, "$order": "report_date_as_yyyy_mm_dd"}
    r = requests.get(CFTC, params=params, headers=UA, timeout=120)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
    out = []
    for code, (tenor, face_mn) in CFTC_CONTRACTS.items():
        d = df[df["cftc_contract_market_code"] == code]
        for grp, f in CFTC_GROUPS.items():
            lng = f + ("_long_all" if grp == "Dealers" else "_long")
            sht = f + ("_short_all" if grp == "Dealers" else "_short")
            net = (pd.to_numeric(d[lng]) - pd.to_numeric(d[sht])) * face_mn / 1e3  # -> $bn
            s = pd.Series(net.values, index=d["date"]).groupby(level=0).sum()
            out.append(rows(s, f"UST futures {tenor}", grp, "futures net (face $bn)", src))
    return out


# ------------------------------------------------------------------ main
def main() -> int:
    jobs = {"Fed H.4.1": fed_custody, "Z.1": z1_holders, "TIC": tic, "CFTC": cftc}
    frames, failed = [], []
    old = pd.read_csv(OUT, parse_dates=["date"]) if OUT.exists() else None
    for name, fn in jobs.items():
        try:
            got = fn()
            frames += got
            print(f"ok   {name}: {sum(len(g) for g in got):,} rows")
        except Exception as e:  # keep last good copy of a failed source
            failed.append(name)
            print(f"FAIL {name}: {e}", file=sys.stderr)
            if old is not None:
                keep = old[old["source"].str.contains(name, regex=False)]
                frames.append(keep)
    df = pd.concat(frames, ignore_index=True)
    df["amount"] = df["amount"].round(3)
    df = df.sort_values(["market", "holder", "measure", "date"])
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False, date_format="%Y-%m-%d")
    print(f"wrote {len(df):,} rows -> {OUT}")
    return 1 if len(failed) == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
