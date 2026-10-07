# Global Bond Tool

Streamlit dashboard of who owns, buys and sells government bonds, plus US Treasury basis-trade positioning and US and Japanese auction results. All figures in US dollars unless labelled.

## Tabs
- **United States / Japan**: the same four sections each (who owns the bonds, foreign buying and selling, the country's investors abroad, the central bank)
- **Other countries**: foreign share of each market, UK and euro-area ownership, where countries keep their foreign savings
- **Basis trade (US Treasuries)**: hedge fund, asset manager and dealer Treasury futures positions
- **Auctions**: US Treasury and Japanese government bond auction results
- **Data checks**: overlapping sources compared on every refresh, with any gaps explained
- **Sources**: every source, its latest data date and a link

## How it updates
- `.github/workflows/refresh.yml` runs `pipeline/fetch.py` daily at 06:45 UTC and commits the CSVs in `data/`
- Streamlit Cloud redeploys automatically on each commit
- To refresh by hand: GitHub → Actions → Refresh data → Run workflow
- Every source is fetched independently. If one fails, the others still update and the failed one keeps its last good data

## If something looks stale
1. Check the Sources tab for the latest date per source
2. Open the latest run under GitHub → Actions. Failed sources print a `FAIL` line naming the source
3. Most failures are temporary (a site down for maintenance) and fix themselves on the next run. A persistent failure usually means a source changed its file format or web address; the fetch function for that source is in `pipeline/fetch.py`

## Release timing (how current each source can be)
| Source | Frequency | Typical lag |
|---|---|---|
| Fed custody holdings (H.4.1) | Weekly | Days |
| CFTC futures positions | Weekly | 3 days |
| US auctions (TreasuryDirect) | Each auction | Same day |
| US auction allotments | About twice a month | 1–3 weeks |
| Treasury TIC (foreign holdings) | Monthly | About 6 weeks |
| Japan balance of payments flows | Monthly | About 5 weeks |
| Japan auction results (Ministry of Finance file) | About monthly | Up to 1 month |
| Fed Z.1, Bank of Japan Flow of Funds, ONS, ECB, IMF | Quarterly | 2–4 months |

## Running locally
```
pip install -r requirements.txt
python pipeline/fetch.py   # refresh data
streamlit run app.py
```
