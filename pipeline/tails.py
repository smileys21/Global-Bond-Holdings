"""Auction tails: high yield minus the when-issued (market) yield at the 1pm bidding deadline.

Two sources, kept separate and labelled:
- "Helious": tails reported by helious.io (desk coverage from July 2026). Its free API only returns the last day,
  so the daily refresh appends each new auction as it happens.
- "Estimate": for reopenings only, the market yield of the same bond from Treasury's FedInvest daytime price
  on the auction day. Checked against Helious's reported tails: within about 0.5bp on average, same direction
  in every case tested. New issues aren't estimated: there's no price for them before the auction, and every
  curve-based method tested was too noisy (about 1.5bp error, direction right only half the time).
"""
from __future__ import annotations

import calendar
import datetime as dt
import html
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
TAILS_OUT = ROOT / "data" / "tails.csv"
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
FEDINVEST = "https://www.treasurydirect.gov/GA-FI/FedInvest/"
HELIOUS = "https://api.helious.io/v1/auctions"

# Helious-reported tails captured from helious.io auction pages on 7 Oct 2026 (credit: Helious, helious.io/auctions)
SEED = [("2-Year", "2026-09-22", 0.2), ("2-Year", "2026-08-25", -0.4), ("2-Year", "2026-07-27", -0.5),
        ("3-Year", "2026-10-06", -0.2), ("3-Year", "2026-09-08", -0.1), ("3-Year", "2026-08-11", -0.5),
        ("3-Year", "2026-07-07", -0.6), ("5-Year", "2026-09-23", 3.1), ("5-Year", "2026-08-26", 0.2),
        ("5-Year", "2026-07-27", 0.9), ("7-Year", "2026-09-24", 0.7), ("7-Year", "2026-08-27", 0.0),
        ("7-Year", "2026-07-28", 0.2), ("10-Year", "2026-10-07", -1.7), ("10-Year", "2026-09-09", -1.5),
        ("10-Year", "2026-08-12", 0.1), ("10-Year", "2026-07-08", -0.6), ("20-Year", "2026-09-15", 2.0),
        ("20-Year", "2026-08-19", 0.5), ("20-Year", "2026-07-22", 0.5), ("30-Year", "2026-09-10", -2.7),
        ("30-Year", "2026-08-13", 0.4), ("30-Year", "2026-07-09", -0.3)]


def fedinvest_prices(day: str) -> dict:
    """Treasury FedInvest prices for every outstanding note and bond on a given day."""
    s = requests.Session()
    s.headers.update(BROWSER)
    r = s.get(FEDINVEST + "selectSecurityPriceDate", timeout=60)
    tok = re.search(r'name="_csrf" value="([^"]+)"', r.text).group(1)
    r = s.post(FEDINVEST + "selectSecurityPriceDate", data={"priceDate": day, "_csrf": tok},
               headers={"Referer": FEDINVEST + "selectSecurityPriceDate"}, timeout=60)
    r.raise_for_status()
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)))
    out = {}
    pat = r"(\w{9}) MARKET BASED (?:NOTE|BOND) ([\d.]+)% (\d\d/\d\d/\d{4}) ([\d.]+) ([\d.]+) ([\d.]+)"
    for m in re.finditer(pat, t):
        cusip, cpn, mat, buy, sell, _eod = m.groups()
        out[cusip] = dict(coupon=float(cpn), maturity=dt.datetime.strptime(mat, "%m/%d/%Y").date(),
                          buy=float(buy), sell=float(sell))
    return out


def _add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    return dt.date(d.year + y, m + 1, min(d.day, calendar.monthrange(d.year + y, m + 1)[1]))


def ytm(clean: float, coupon: float, maturity: dt.date, settle: dt.date) -> float:
    """Street-convention semiannual yield (%) from a clean price."""
    dates = [maturity]
    while dates[-1] > settle:
        dates.append(_add_months(maturity, -6 * len(dates)))
    prev_c, next_c = dates[-1], dates[-2]
    cpns = sorted(d for d in dates if d > settle)
    frac = (next_c - settle).days / (next_c - prev_c).days
    dirty = clean + coupon / 2 * (1 - frac)

    def pv(y):
        return sum((coupon / 2 + (100 if d == maturity else 0)) / (1 + y / 2) ** (i + frac)
                   for i, d in enumerate(cpns))
    lo, hi = -0.05, 0.25
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pv(mid) > dirty else (lo, mid)
    return mid * 100


def estimate_reopening(day: str, cusip: str, high: float, prices: dict) -> float | None:
    p = prices.get(cusip)
    if not p:
        return None
    quotes = [q for q in (p["buy"], p["sell"]) if q > 0]
    if not quotes:
        return None
    settle = dt.date.fromisoformat(day) + dt.timedelta(days=1)
    return round((high - ytm(sum(quotes) / len(quotes), p["coupon"], p["maturity"], settle)) * 100, 1)


def helious_recent() -> list[tuple]:
    r = requests.get(HELIOUS, headers={"User-Agent": "global-bond-tool"}, timeout=60)
    r.raise_for_status()
    rows = []
    for a in r.json().get("data", {}).get("auctions", []):
        if a.get("tail_bps") is not None and a.get("type") in ("Note", "Bond"):
            rows.append((a["tenor"], a["date"], float(a["tail_bps"])))
    return rows


def update_tails(au: pd.DataFrame | None = None) -> pd.DataFrame:
    """Append any newly reported Helious tails. (Reopening estimates from FedInvest were dropped; the
    functions above are kept in case they're wanted again.)"""
    cols = ["date", "tenor", "tail_bp", "source"]
    old = pd.read_csv(TAILS_OUT, dtype={"date": str}) if TAILS_OUT.exists() else pd.DataFrame(columns=cols)
    rows = [r for r in old.to_dict("records") if r["source"] == "Helious"]  # reported tails only
    have = {(r["tenor"], r["date"], r["source"]) for r in rows}

    reported = list(SEED)
    try:
        reported += helious_recent()
    except Exception as e:
        print(f"  tails: Helious unavailable ({e})", file=sys.stderr)
    for tenor, day, tail in reported:
        if (tenor, day, "Helious") not in have:
            rows.append(dict(date=day, tenor=tenor, tail_bp=tail, source="Helious"))
            have.add((tenor, day, "Helious"))

    out = pd.DataFrame(rows, columns=cols).sort_values(["date", "tenor", "source"])
    out.to_csv(TAILS_OUT, index=False)
    return out
