# Who Owns Government Bonds

Streamlit dashboard of central bank balance sheets and who holds, buys and sells government bonds.

Phase 1 covers US Treasuries (by holder type and by country), the Fed and SNB balance sheets, and hedge fund futures positioning.

- `pipeline/fetch.py` pulls every source into `data/holdings.csv` (date, market, holder, measure, amount in USD bn, source)
- `app.py` is the dashboard
- `.github/workflows/refresh.yml` refreshes the data daily at 06:45 UTC

Sources are Fed H.4.1, Fed Z.1 (via FRED), US Treasury TIC, CFTC Traders in Financial Futures and the SNB data portal.
