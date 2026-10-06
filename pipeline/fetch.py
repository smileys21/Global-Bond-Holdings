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
    "Central bank": ["BOGZ1FL713061103Q"],
    "Foreign": ["BOGZ1LM263061105Q"],
    "Households (incl. hedge funds)": ["BOGZ1LM153061105Q"],
    "Money market funds": ["BOGZ1FL633061105Q"],
    "Banks": ["BOGZ1FL763061100Q", "BOGZ1FL753061103Q", "BOGZ1FL473061105Q",
              "BOGZ1FL733061103Q"],
    "Investment funds": ["BOGZ1FL653061105Q", "BOGZ1FL563061103Q"],
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


# ------------------------------------------------------------------ FX helpers
def fx_usd_per(ccy: str) -> pd.Series:
    """Daily USD per unit of local currency (FRED H.10)."""
    if ccy == "JPY":
        return 1 / fred("DEXJPUS")
    if ccy == "GBP":
        return fred("DEXUSUK")
    if ccy == "EUR":
        return fred("DEXUSEU")
    raise ValueError(ccy)


def to_usd_bn(s: pd.Series, ccy: str, local_unit: float) -> pd.Series:
    """Convert local-currency values to USD bn at the period-end rate. local_unit = size of 1 unit in LC."""
    fx = fx_usd_per(ccy).sort_index()
    rate = fx.reindex(fx.index.union(s.index)).ffill().reindex(s.index)
    return (s * local_unit * rate / 1e9).dropna()


# ------------------------------------------------------------------ Japan (BoJ)
BOJ = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"


def boj(db: str, codes: list[str], start: str) -> pd.DataFrame:
    out = {}
    for i in range(0, len(codes), 50):  # API takes up to 250 codes; stay well under
        r = requests.get(BOJ, params={"format": "json", "lang": "en", "db": db,
                                      "code": ",".join(codes[i:i + 50]), "startDate": start},
                         headers=UA, timeout=120)
        r.raise_for_status()
        j = r.json()
        if str(j.get("STATUS")) != "200":
            raise RuntimeError(j.get("MESSAGE"))
        for s in j["RESULTSET"]:
            v = s["VALUES"]
            out[s["SERIES_CODE"]] = pd.Series(pd.to_numeric(v["VALUES"], errors="coerce"),
                                              index=[str(d) for d in v["SURVEY_DATES"]])
    return pd.DataFrame(out)


JGB_GROUPS = {  # BoJ Flow of Funds sector codes, holdings of JGBs and FILP bonds
    "Central bank": ["110"], "Banks": ["120"], "Insurers": ["131"], "Pension funds": ["140", "424"],
    "Investment funds": ["160"], "Households": ["430"], "Foreign": ["500"],
}


def japan_holders() -> list[pd.DataFrame]:
    src = "BoJ Flow of Funds (quarterly)"
    codes = [f"FOF_FFAS{c}A311" for g in JGB_GROUPS.values() for c in g] + ["FOF_FFAS700A311"]
    d = boj("FF", codes, "199704")
    # survey dates are YYYYQQ (e.g. 202602 = Q2 2026)
    d.index = [pd.Period(f"{i[:4]}Q{int(i[4:])}", "Q").end_time.normalize() for i in d.index]
    groups = pd.DataFrame({g: d[[f"FOF_FFAS{c}A311" for c in cs]].sum(axis=1, min_count=1)
                           for g, cs in JGB_GROUPS.items()})
    groups["Other"] = d["FOF_FFAS700A311"] - groups.sum(axis=1)
    out = []
    for g in groups.columns:
        usd = to_usd_bn(groups[g].dropna(), "JPY", 1e8)  # units of 100 million yen
        out.append(rows(usd, "Japanese government bonds", g, "holdings", src))
    return out


BOP_COUNTRIES = {"US": "United States", "FR": "France", "GB": "United Kingdom", "DE": "Germany",
                 "IT": "Italy", "ES": "Spain", "NL": "Netherlands", "BE": "Belgium", "AU": "Australia",
                 "CA": "Canada", "CI": "Cayman Islands", "LX": "Luxembourg", "IE": "Ireland",
                 "CN": "China", "CH": "Switzerland", "SE": "Sweden", "AT": "Austria", "FI": "Finland",
                 "NO": "Norway", "DK": "Denmark", "PT": "Portugal", "KR": "South Korea", "SG": "Singapore",
                 "NZ": "New Zealand", "MX": "Mexico", "BR": "Brazil", "IN": "India", "ID": "Indonesia"}


def japan_flows() -> list[pd.DataFrame]:
    """Monthly: Japanese investors' net purchases of long-term foreign bonds by issuer country,
    and foreign investors' net purchases of Japanese long-term bonds."""
    src = "BoJ balance of payments (monthly)"
    codes = [f"BPPI6D3N9{c}" for c in BOP_COUNTRIES] + ["BPBP6JYNFA221", "BPBP6JYNFL221"]
    d = boj("BP01", codes, "201401")
    d.index = [pd.Period(f"{i[:4]}-{i[4:]}", "M").end_time.normalize() for i in d.index]
    fx = 1 / fred("EXJPUS")  # monthly average USD per JPY
    fx.index = fx.index + pd.offsets.MonthEnd(0)
    conv = lambda s: (s * 1e8 * fx.reindex(s.index) / 1e9).dropna()  # noqa: E731
    out = [rows(conv(d[f"BPPI6D3N9{c}"].dropna()), "Japanese investors abroad", name, "net purchases", src)
           for c, name in BOP_COUNTRIES.items() if f"BPPI6D3N9{c}" in d]
    out.append(rows(conv(d["BPBP6JYNFA221"].dropna()), "Japanese investors abroad", "All countries",
                    "net purchases", src))
    out.append(rows(conv(d["BPBP6JYNFL221"].dropna()), "Japanese government bonds", "Foreign",
                    "net purchases", src))
    return out


# ------------------------------------------------------------------ UK (ONS)
ONS = "https://www.ons.gov.uk/generator?format=csv&uri=/economy/grossdomesticproductgdp/timeseries/{}/ukea"
GILT_GROUPS = {  # ONS CDIDs, long-term gilts (AF.32N1) held by each sector, GBP mn
    "Foreign": "NLDT", "Central bank & banks": "NNTV", "Insurers & pension funds": "NIZB",
    "Other financial (incl. hedge funds)": "NLQJ", "Households": "NNNN",
}
GILT_TOTAL = "NYXQ"  # total issued (liability of UK sector)


def ons(cdid: str) -> pd.Series:
    txt = get(ONS.format(cdid.lower()))
    recs = []
    for line in csv.reader(io.StringIO(txt)):
        if len(line) == 2 and re.match(r"^\d{4} Q[1-4]$", line[0]):
            recs.append((pd.Period(line[0].replace(" ", ""), "Q").end_time.normalize(), float(line[1])))
    return pd.Series(dict(recs)).sort_index()


def uk_holders() -> list[pd.DataFrame]:
    src = "ONS UK Economic Accounts (quarterly)"
    groups = pd.DataFrame({g: ons(c) for g, c in GILT_GROUPS.items()})
    total = ons(GILT_TOTAL)
    groups = groups.reindex(total.index)
    groups["Other"] = total - groups.sum(axis=1)
    return [rows(to_usd_bn(groups[g].dropna(), "GBP", 1e6), "UK gilts", g, "holdings", src)
            for g in groups.columns]


# ------------------------------------------------------------------ Euro area (ECB)
ECB = "https://data-api.ecb.europa.eu/service/data/{}/{}"
EURO = {"FR": "French government bonds", "IT": "Italian government bonds",
        "DE": "German government bonds", "ES": "Spanish government bonds"}
SHS_SECTORS = ["S1", "S12", "S121", "S12P", "S12Q", "S123", "S124", "S128", "S129", "S11", "S13", "S1M"]


def ecb(flow: str, key: str) -> pd.DataFrame:
    r = requests.get(ECB.format(flow, key), headers={**UA, "Accept": "text/csv"}, timeout=180)
    r.raise_for_status()
    d = pd.read_csv(io.StringIO(r.text))
    d["date"] = [pd.Period(p, "Q").end_time.normalize() for p in d["TIME_PERIOD"]]
    return d


def euro_holders() -> list[pd.DataFrame]:
    src = "ECB securities holdings (quarterly)"
    out = []
    for cc, market in EURO.items():
        shs = ecb("SHSS", f"Q.N.U2.{cc}.{'+'.join(SHS_SECTORS)}.S13.N.A.LE.F3.T._Z.XDC._T.F.V.N._T")
        h = shs.pivot(index="date", columns="REF_SECTOR", values="OBS_VALUE")  # EUR mn, face value
        gfs = ecb("GFS", f"Q.N.{cc}.W0.S13.S1.C.L.LE.F3.T._Z.XDC._T.F.V.N._T").set_index("date")["OBS_VALUE"]
        g = pd.DataFrame(index=h.index)
        g["Central bank"] = h["S121"]
        g["Banks"] = h["S12"] - h["S121"] - h["S12P"] - h["S12Q"] - h["S123"]
        g["Insurers"] = h["S128"]
        g["Pension funds"] = h["S129"]
        g["Investment funds"] = h["S124"] + h["S123"]
        g["Other financial (incl. hedge funds)"] = h["S12P"] - h["S124"]
        g["Households"] = h["S1M"]
        g["Other"] = h["S11"]
        # holders outside the euro area = total debt (consolidated, face value) minus euro-area holders
        g["Foreign"] = gfs.reindex(g.index) - (h["S1"] - h["S13"])
        for col in g.columns:
            out.append(rows(to_usd_bn(g[col].dropna(), "EUR", 1e6), market, col, "holdings", src))
    return out


# ------------------------------------------------------------------ main
def main() -> int:
    jobs = {"Fed H.4.1": fed_custody, "Z.1": z1_holders, "TIC": tic, "CFTC": cftc,
            "BoJ Flow of Funds": japan_holders, "BoJ balance of payments": japan_flows,
            "ONS": uk_holders, "ECB": euro_holders}
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
