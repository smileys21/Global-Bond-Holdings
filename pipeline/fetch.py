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
                 "holdings", src),
            rows(fred("TREAST") / 1e3, "US Treasuries", "Federal Reserve (weekly balance sheet)", "holdings", src)]


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


def tic_table1() -> list[pd.DataFrame]:
    """Every country's holdings and net purchases of US long-term securities by type, monthly since 2020."""
    src = "US Treasury TIC long-term securities (monthly)"
    txt = get(TIC + "slt_table1.txt")
    lines = txt.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("country\tcountry_code"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep="\t")
    df = df[df["date"].astype(str).str.match(r"\d{4}-\d{2}$")]
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    df["country"] = df["country"].str.strip().replace({"Grand Total": "Foreign (all)"})
    out = []
    for key, market in [("treas", "US Treasury notes & bonds"), ("agcy", "US agency bonds"),
                        ("corp", "US corporate bonds"), ("eqty", "US stocks")]:
        for col, measure in [(f"for_lt_{key}_pos", "holdings"), (f"for_lt_{key}_net", "net purchases")]:
            v = pd.to_numeric(df[col], errors="coerce") / 1e3
            out.append(pd.DataFrame({"date": df["date"], "market": market, "holder": df["country"],
                                     "measure": measure, "amount": v, "source": src}).dropna())
    return out


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
    # Cayman split: notes & bonds (the basis-trade leg) vs bills
    cay = t3[t3["country"] == "Cayman Islands"].set_index("date").sort_index()
    for col, market in [("for_lt_treas_pos", "US Treasury notes & bonds (Cayman)"),
                        ("for_st_treas_pos", "US Treasury bills (Cayman)")]:
        out.append(rows(pd.to_numeric(cay[col], errors="coerce").dropna() / 1e3, market, "Cayman Islands",
                        "holdings", src))
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


JP_SOV_DEST = {"US": "United States", "CA": "Canada", "AU": "Australia", "DE": "Germany", "FR": "France",
               "IT": "Italy", "NL": "Netherlands", "GB": "United Kingdom", "DK": "Denmark", "CH": "Switzerland",
               "HK": "Hong Kong", "SE": "Sweden", "OT": "Other countries"}


JP_ALLBOND_DEST = {"US": "United States", "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "CI": "Cayman Islands",
                   "GB": "United Kingdom", "FR": "France", "DE": "Germany", "IT": "Italy", "ES": "Spain",
                   "NL": "Netherlands", "BE": "Belgium", "LX": "Luxembourg", "IE": "Ireland", "AT": "Austria",
                   "FI": "Finland", "PT": "Portugal", "GR": "Greece", "CH": "Switzerland", "SE": "Sweden",
                   "NO": "Norway", "DK": "Denmark", "AU": "Australia", "NZ": "New Zealand", "CN": "China",
                   "HK": "Hong Kong", "TW": "Taiwan", "KR": "South Korea", "SG": "Singapore", "IN": "India",
                   "ID": "Indonesia", "MY": "Malaysia", "TH": "Thailand", "PH": "Philippines",
                   "SA": "Saudi Arabia", "AE": "UAE", "ZA": "South Africa", "II": "International organizations"}
JP_BUYERS = {"US": "United States", "GB": "United Kingdom", "FR": "France", "DE": "Germany", "CH": "Switzerland",
             "NL": "Netherlands", "BE": "Belgium", "LX": "Luxembourg", "IE": "Ireland", "CI": "Cayman Islands",
             "CA": "Canada", "AU": "Australia", "HK": "Hong Kong", "SG": "Singapore", "CN": "China",
             "TW": "Taiwan", "KR": "South Korea", "NO": "Norway", "SE": "Sweden", "SA": "Saudi Arabia",
             "AE": "UAE", "BM": "Bermuda", "II": "International organizations"}


def japan_flows() -> list[pd.DataFrame]:
    """Monthly: Japanese investors' net purchases of long-term foreign government bonds by issuer country,
    and foreign investors' net purchases of long-term Japanese government bonds."""
    src = "BoJ balance of payments (monthly)"
    codes = ([f"BPPI6D3N9{c}" for c in JP_ALLBOND_DEST] + [f"BPPI6D3NA{c}" for c in JP_SOV_DEST] + ["BPBP6JYNFL22113", "BPBP6JYNFL221", "BPBP6JYNFA21", "BPBP6JYNFA221",
             "BPBP6JYNFA222"] + [f"BPPI6E3N9{c}" for c in JP_BUYERS])
    d = boj("BP01", codes, "201401")
    d.index = [pd.Period(f"{i[:4]}-{i[4:]}", "M").end_time.normalize() for i in d.index]
    fx = 1 / fred("EXJPUS")  # monthly average USD per JPY
    fx.index = fx.index + pd.offsets.MonthEnd(0)
    conv = lambda s: (s * 1e8 * fx.reindex(s.index) / 1e9).dropna()  # noqa: E731  (100mn yen -> USD bn)
    sov = d[[f"BPPI6D3NA{c}" for c in JP_SOV_DEST if f"BPPI6D3NA{c}" in d]]
    out = [rows(conv(sov[c].dropna()), "Japanese investors abroad", JP_SOV_DEST[c[-2:]], "net purchases", src)
           for c in sov.columns]
    out.append(rows(conv(sov.sum(axis=1, min_count=1).dropna()), "Japanese investors abroad", "All countries",
                    "net purchases", src))
    out.append(rows(conv(d["BPBP6JYNFL22113"].dropna()), "Japanese government bonds", "Foreign",
                    "net purchases", src))
    for c, name in JP_ALLBOND_DEST.items():
        if f"BPPI6D3N9{c}" in d:
            out.append(rows(conv(d[f"BPPI6D3N9{c}"].dropna()), "Japanese investors abroad (all bonds)", name,
                            "net purchases", src))
    out.append(rows(conv(d["BPBP6JYNFL221"].dropna()), "Japanese bonds (all long-term)", "Foreign",
                    "net purchases", src))
    # all foreign securities bought by Japanese investors (negative = repatriation)
    for code, label in [("BPBP6JYNFA21", "Foreign stocks & funds"), ("BPBP6JYNFA221", "Foreign bonds (long-term)"),
                        ("BPBP6JYNFA222", "Foreign bonds (short-term)")]:
        out.append(rows(conv(d[code].dropna()), "Japanese investors abroad (all securities)", label,
                        "net purchases", src))
    # who is buying Japanese long-term bonds, by investor country
    for c, name in JP_BUYERS.items():
        if f"BPPI6E3N9{c}" in d:
            out.append(rows(conv(d[f"BPPI6E3N9{c}"].dropna()), "Japanese bonds by buyer", name, "net purchases", src))
    # Japan's official reserves (run by the Ministry of Finance), monthly, IMF via FRED
    out.append(rows(fred("TRESEGJPM052N").pipe(lambda x: x.set_axis(x.index + pd.offsets.MonthEnd(0))) / 1e3,
                    "Japan official reserves", "Ministry of Finance", "holdings", src))
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


# ------------------------------------------------------------------ IMF (foreign assets vs reserves)
IIP_COUNTRIES = {"KOR": "South Korea", "JPN": "Japan", "CHN": "China", "TWN": "Taiwan", "IND": "India",
                 "CHE": "Switzerland", "NOR": "Norway", "GBR": "United Kingdom", "DEU": "Germany", "FRA": "France",
                 "ITA": "Italy", "ESP": "Spain", "NLD": "Netherlands"}
IIP_SECTORS = {"S13": "Government (incl. state pension & wealth funds)", "S12R": "Insurers, pensions & funds",
               "S1V": "Households & companies", "S122": "Banks"}


def imf_iip() -> list[pd.DataFrame]:
    src = "IMF international investment position (quarterly)"
    out = []
    for iso, name in IIP_COUNTRIES.items():
        txt = None
        for attempt in range(4):  # the IMF API throws occasional 503s
            try:
                r = requests.get(f"https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IIP/{iso}.A_P..USD.Q",
                                 headers={**UA, "Accept": "application/vnd.sdmx.data+csv;version=1.0.0"},
                                 timeout=180)
                r.raise_for_status()
                txt = r.text
                break
            except Exception:
                time.sleep(10 * (attempt + 1))
        if txt is None:
            print(f"  IMF: skipped {name} this run", file=sys.stderr)
            continue
        try:
            d = pd.read_csv(io.StringIO(txt), usecols=["INDICATOR", "TIME_PERIOD", "OBS_VALUE"])
        except Exception:
            print(f"  IMF: no data for {name}", file=sys.stderr)
            continue
        d = d[d["TIME_PERIOD"].astype(str).str.match(r"^\d{4}-Q[1-4]$")]
        if d.empty:
            print(f"  IMF: no quarterly data for {name}", file=sys.stderr)
            continue
        d["date"] = [pd.Period(p, "Q").end_time.normalize() for p in d["TIME_PERIOD"]]
        w = d.pivot_table(index="date", columns="INDICATOR", values="OBS_VALUE") / 1e9  # USD -> bn
        if "R" in w:
            out.append(rows(w["R"].dropna(), "Foreign assets", f"{name}|Reserves (central bank)", "holdings", src))
        have_sectors = all(f"P_F5_{k}_MV" in w or f"P_F3_{k}_MV" in w for k in IIP_SECTORS)
        if have_sectors:
            for k, label in IIP_SECTORS.items():
                v = w.get(f"P_F5_{k}_MV", 0) + w.get(f"P_F3_{k}_MV", 0)
                out.append(rows(pd.Series(v).dropna(), "Foreign assets", f"{name}|{label}", "holdings", src))
        elif "P_MV" in w:
            out.append(rows(w["P_MV"].dropna(), "Foreign assets", f"{name}|Portfolio investments (all)",
                            "holdings", src))
    return out


# ------------------------------------------------------------------ TIC table 2 (US investors abroad)
def tic_table2() -> list[pd.DataFrame]:
    """US residents' holdings and net purchases of foreign long-term securities by country, monthly."""
    src = "US Treasury TIC US holdings abroad (monthly)"
    txt = get(TIC + "slt_table2.txt")
    lines = txt.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("country\tcountry_code"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep="\t")
    df = df[df["date"].astype(str).str.match(r"\d{4}-\d{2}$")]
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    df["country"] = df["country"].str.strip().replace({"Grand Total": "All countries"})
    out = []
    for key, market in [("govt_bond", "Foreign government bonds"), ("corp_bond", "Foreign corporate bonds"),
                        ("eqty", "Foreign stocks")]:
        for col, measure in [(f"us_lt_{key}_pos", "holdings"), (f"us_lt_{key}_net", "net purchases")]:
            v = pd.to_numeric(df[col], errors="coerce") / 1e3
            out.append(pd.DataFrame({"date": df["date"], "market": f"US investors abroad: {market}",
                                     "holder": df["country"], "measure": measure, "amount": v,
                                     "source": src}).dropna())
    return out


# ------------------------------------------------------------------ OFR hedge fund monitor (Form PF)
OFR = "https://data.financialresearch.gov/hf/v1/series/timeseries"
OFR_SERIES = {"FPF-ASSETCLASS_LTREASURY_SUM": "Long Treasury exposure",
              "FPF-ASSETCLASS_STREASURY_SUM": "Short Treasury exposure",
              "FPF-BORROW_REPO_SUM": "Repo borrowing"}


def ofr() -> list[pd.DataFrame]:
    src = "OFR Hedge Fund Monitor, SEC Form PF (quarterly)"
    out = []
    for code, name in OFR_SERIES.items():
        r = requests.get(OFR, params={"mnemonic": code}, headers=UA, timeout=120)
        r.raise_for_status()
        s = pd.Series({pd.Timestamp(d): v for d, v in r.json() if v is not None}).sort_index() / 1e9
        out.append(rows(s, "Hedge funds (all, Form PF)", name, "holdings", src))
    return out


# ------------------------------------------------------------------ US Treasury auctions (TreasuryDirect)
AUCTIONS_OUT = ROOT / "data" / "auctions.csv"
TD = "https://www.treasurydirect.gov/TA_WS/securities/search"
TENOR_ORDER = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]


def auctions() -> pd.DataFrame:
    """Every nominal note and bond auction since 2008 with the published demand metrics."""
    recs = []
    for t in ["Note", "Bond"]:
        r = requests.get(TD, params={"type": t, "startDate": "2008-01-01", "endDate": "2099-12-31",
                                     "format": "json"}, headers=UA, timeout=180)
        r.raise_for_status()
        recs += r.json()
    d = pd.DataFrame(recs)
    d = d[(d["tips"] != "Yes") & (d["floatingRate"] != "Yes")]
    num = lambda c: pd.to_numeric(d[c].replace("", None), errors="coerce")  # noqa: E731
    out = pd.DataFrame({
        "date": pd.to_datetime(d["auctionDate"]).dt.normalize(),
        "tenor": d["originalSecurityTerm"].str.replace(r"^29-Year.*", "30-Year", regex=True),
        "term": d["securityTerm"], "reopening": d["reopening"].eq("Yes"), "cusip": d["cusip"],
        "size_bn": num("offeringAmount") / 1e9,
        "high_yield": num("highYield"), "median_yield": num("averageMedianYield"),
        "bid_to_cover": num("bidToCoverRatio"),
        "dealer": num("primaryDealerAccepted"), "direct": num("directBidderAccepted"),
        "indirect": num("indirectBidderAccepted"),
    })
    tot = out[["dealer", "direct", "indirect"]].sum(axis=1)
    for c in ["dealer", "direct", "indirect"]:
        out[f"{c}_pct"] = out[c] / tot * 100
    out["dispersion_bp"] = (out["high_yield"] - out["median_yield"]) * 100
    out = out[out["tenor"].isin(TENOR_ORDER) & out["high_yield"].notna()]
    return out.drop(columns=["dealer", "direct", "indirect"]).sort_values("date")


# ------------------------------------------------------------------ JGB auctions (Japan Ministry of Finance)
JGB_AUCTIONS_OUT = ROOT / "data" / "jgb_auctions.csv"
MOF_XLS = "https://www.mof.go.jp/english/policy/jgbs/auction/past_auction_results/Auction_Results_for_JGBs.xls"
JGB_SHEETS = {"2年債": "2-Year", "5年債": "5-Year", "10年債": "10-Year", "20年債": "20-Year", "30年債": "30-Year",
              "40年債": "40-Year"}


def jgb_auctions() -> pd.DataFrame:
    """Every 2- to 40-year JGB auction: size, highest accepted yield and bid-to-cover."""
    r = requests.get(MOF_XLS, headers=UA, timeout=180)
    r.raise_for_status()
    xls = pd.ExcelFile(io.BytesIO(r.content))
    out = []
    for sheet, tenor in JGB_SHEETS.items():
        raw = pd.read_excel(xls, sheet, header=None)
        hdr = next(i for i in range(10) if "Auction Date" in [str(v).strip() for v in raw.iloc[i]])
        cols = [str(v).strip() for v in raw.iloc[hdr]]
        d = raw.iloc[hdr + 2:].copy()
        d.columns = cols

        def col(name):
            c = next((c for c in cols if c.startswith(name)), None)
            return pd.to_numeric(d[c], errors="coerce") if c else pd.Series(float("nan"), index=d.index)
        t = pd.DataFrame({
            "date": pd.to_datetime(d["Auction Date"], errors="coerce"), "tenor": tenor,
            "size_bn_jpy": col("Offering Amount") / 10, "bids": col("Amounts of Competitive Bids"),
            "accepted": col("Amounts of Bids Accepted"), "avg_price": col("Weighted Average Price"),
            "avg_yield": col("Yield at the Average Price"), "low_price": col("Lowest Accepted Price"),
            "low_yield": col("Yield at the Lowest Accepted Price"), "high_yield_40": col("Highest Accepted Yield"),
        })
        t = t.dropna(subset=["date", "accepted"])
        t["bid_to_cover"] = t["bids"] / t["accepted"]
        t["yield"] = t["low_yield"].fillna(t["high_yield_40"])
        out.append(t[["date", "tenor", "size_bn_jpy", "yield", "bid_to_cover"]])
    return pd.concat(out).sort_values("date")


# ------------------------------------------------------------------ Treasury investor-class allotments
ALLOT_OUT = ROOT / "data" / "allotments.csv"
ALLOT_PAGE = "https://home.treasury.gov/data/investor-class-auction-allotments"
ALLOT_GROUPS = {"Depository institutions": "Banks", "Individuals": "Individuals", "Dealers and brokers": "Dealers",
                "Pension and Retirement funds and Ins. Co.": "Pensions & insurers", "Investment funds": "Investment funds",
                "Foreign and international": "Foreign", "Other": "Other"}


ALLOT_OLD = "https://home.treasury.gov/system/files/276/Website-PDO-4-A-Coupons-Jan-2000-Sep%202009.xls"


def allotments_2000_2009() -> pd.DataFrame:
    """Treasury's historical allotment table (January 2000 to September 2009), older layout, $ millions."""
    r = requests.get(ALLOT_OLD, headers=UA, timeout=180)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), header=None)
    hdr = next(i for i in range(10) if str(raw.iloc[i, 0]).strip().startswith("Issue"))
    d = raw.iloc[hdr + 1:, :15].copy()
    d.columns = ["issue_date", "type", "term", "coupon", "cusip", "maturity", "total", "soma", "banks", "individuals",
                 "dealers", "pensions", "funds", "foreign", "other"]
    d = d[pd.to_datetime(d["issue_date"], errors="coerce").notna() & d["type"].isin(["NOTE", "BOND"])]
    num = lambda c: pd.to_numeric(d[c], errors="coerce")  # noqa: E731
    total = num("total") - num("soma").fillna(0)
    out = pd.DataFrame({"issue_date": pd.to_datetime(d["issue_date"]),
                        "tenor": d["term"].str.extract(r"(\d+)")[0] + "-Year", "cusip": d["cusip"]})
    for c, name in [("banks", "Banks"), ("individuals", "Individuals"), ("dealers", "Dealers"),
                    ("pensions", "Pensions & insurers"), ("funds", "Investment funds"), ("foreign", "Foreign"),
                    ("other", "Other")]:
        out[name] = num(c) / total * 100
    out["public_size_bn"] = total / 1e3
    return out.dropna(subset=["tenor"])


def allotments() -> pd.DataFrame:
    """Who received each coupon auction (Treasury's investor-class allotments), January 2000 onward."""
    page = get(ALLOT_PAGE)
    link = re.search(r'href="?(/system/files/276/[^" >]*IC-Coupons\.xls)', page).group(1)
    r = requests.get("https://home.treasury.gov" + link, headers=UA, timeout=180)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), header=None)
    hdr = next(i for i in range(10) if "Cusip" in [str(v).strip() for v in raw.iloc[i]])
    cols = [re.sub(r"\s+", " ", str(v)).strip() for v in raw.iloc[hdr]]
    d = raw.iloc[hdr + 1:].copy()
    d.columns = cols
    d = d[pd.to_datetime(d[cols[0]], errors="coerce").notna()]
    sec = d["Security type"].astype(str)
    d = d[~sec.str.contains("TIPS|FRN|Floating", case=False)]
    num = lambda c: pd.to_numeric(d[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame({"issue_date": pd.to_datetime(d[cols[0]]),
                        "tenor": d["Security type"].str.extract(r"(\d+-Year)")[0], "cusip": d["Cusip"]})
    soma = num(next(c for c in cols if "SOMA" in c))
    total = num(next(c for c in cols if c.startswith("Total"))) - soma.fillna(0)
    for c in cols:
        key = next((k for k in ALLOT_GROUPS if c.replace(" ", "").lower().startswith(k.replace(" ", "").lower()[:12])),
                   None)
        if key:
            out[ALLOT_GROUPS[key]] = num(c) / total * 100
    out["public_size_bn"] = total
    out = out.dropna(subset=["tenor"])
    try:
        old = allotments_2000_2009()
        out = pd.concat([old[old.issue_date < out.issue_date.min()], out])
    except Exception as e:
        print(f"  allotments: 2000-2009 history unavailable ({e})", file=sys.stderr)
    return out.sort_values("issue_date")


# ------------------------------------------------------------------ main
def main() -> int:
    jobs = {"Fed H.4.1": fed_custody, "Z.1": z1_holders, "TIC (": tic, "CFTC": cftc,
            "BoJ Flow of Funds": japan_holders, "BoJ balance of payments": japan_flows,
            "ONS": uk_holders, "ECB": euro_holders,
            "TIC long-term securities": tic_table1, "IMF": imf_iip,
            "TIC US holdings abroad": tic_table2, "OFR": ofr}
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
    au = None
    try:
        au = auctions()
        au.to_csv(AUCTIONS_OUT, index=False, date_format="%Y-%m-%d")
        print(f"ok   auctions: {len(au):,} rows -> {AUCTIONS_OUT}")
    except Exception as e:  # keep the last good file
        print(f"FAIL auctions: {e}", file=sys.stderr)
    try:
        jg = jgb_auctions()
        jg.to_csv(JGB_AUCTIONS_OUT, index=False, date_format="%Y-%m-%d")
        print(f"ok   JGB auctions: {len(jg):,} rows")
    except Exception as e:
        print(f"FAIL JGB auctions: {e}", file=sys.stderr)
    try:
        al = allotments()
        al.to_csv(ALLOT_OUT, index=False, date_format="%Y-%m-%d")
        print(f"ok   allotments: {len(al):,} rows")
    except Exception as e:
        print(f"FAIL allotments: {e}", file=sys.stderr)
    return 1 if len(failed) == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
