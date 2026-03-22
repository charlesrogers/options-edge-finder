# Options Edge Finder

## Large Files — Surgical Edits Only
- `streamlit_app.py` — 2,990 lines. Do NOT rewrite. Use targeted edits.
- `analytics.py` — 1,426 lines. Do NOT rewrite. Use targeted edits.

## Stack
- **Streamlit** (deployed on Streamlit Cloud)
- Python with arch (GARCH), scipy, numpy, pandas, plotly, matplotlib
- **Supabase** for database (credentials via `st.secrets` in `db.py`)
- Dependencies in `requirements.txt`

## Streamlit Cloud
- Uses `st.secrets`, NOT `os.environ` — secrets configured in Streamlit Cloud dashboard
- Supabase credentials: `SUPABASE_URL`, `SUPABASE_KEY` (in st.secrets and GitHub Actions secrets)

## Eval Modules
- 8 evaluation modules (`eval_*.py`) with interdependencies
- **Don't modify completed eval modules without asking** — they have validated outputs that downstream modules depend on
- Currently building Module 1 (GARCH Forecast Evaluation)

## Yahoo Finance Data
- Fetched via Cloudflare Worker proxy (`yf_proxy.py`) — Yahoo blocks direct requests from cloud IPs
- Don't change proxy URL or fetch patterns without checking `yf_proxy.py`

## GitHub Actions
- `daily-iv-sampler.yml` — Runs `batch_sampler.py` at 3:55 PM ET weekdays (~350 tickers)
- `score-predictions.yml` — Runs at 8:00 PM ET weekdays (scores predictions 20+ days old)
- `basket-test.yml` — Test workflow
- **Schedules are timezone-sensitive** — GitHub Actions uses UTC, the cron expressions account for ET offset. Don't adjust without converting correctly.
- Secrets: `SUPABASE_URL`, `SUPABASE_KEY`

## Key Files
- `streamlit_app.py` — Main app (2,990 lines)
- `analytics.py` — Analytics engine (1,426 lines)
- `db.py` — Supabase connection (uses st.secrets)
- `yf_proxy.py` — Yahoo Finance Cloudflare Worker proxy
- `batch_sampler.py` — Daily IV sampling (GitHub Actions)
- `eval_*.py` — Evaluation pipeline modules
