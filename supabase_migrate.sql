-- Run this in Supabase SQL editor to add new columns to existing tables

-- iv_snapshots: expanded vol data
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS rv_10 REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS rv_30 REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS rv_60 REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS yz_20 REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS garch_vol REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS iv_rank REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS iv_pctl REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS vrp REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS signal TEXT;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS regime TEXT;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS skew REAL;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS fomc_days INTEGER;
ALTER TABLE iv_snapshots ADD COLUMN IF NOT EXISTS earnings_days INTEGER;

-- predictions: expanded context
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS rv_20 REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS iv_pctl REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS skew_penalty REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS signal_reason TEXT;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS earnings_days INTEGER;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS fomc_days INTEGER;

-- predictions: P&L scoring columns (Module 2)
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS expected_move_pct REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS actual_move_pct REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS premium_estimate REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pnl_estimate REAL;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS pnl_pct REAL;

-- basket_results: track basket test runs over time (Module 8 monitoring)
CREATE TABLE IF NOT EXISTS basket_results (
    id SERIAL PRIMARY KEY,
    run_date TEXT NOT NULL,
    n_tickers INTEGER,
    n_successful INTEGER,
    holding_period INTEGER DEFAULT 20,
    avg_win_rate REAL,
    avg_pnl_pct REAL,
    avg_sharpe REAL,
    green_avg_pnl REAL,
    green_win_rate REAL,
    oos_avg_pnl REAL,
    oos_win_rate REAL,
    avg_overfit_ratio REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
