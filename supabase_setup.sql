-- Run this in your Supabase SQL editor to create the tables

CREATE TABLE IF NOT EXISTS iv_snapshots (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    atm_iv REAL,
    spot_price REAL,
    front_exp TEXT,
    rv_20 REAL,
    term_label TEXT,
    put_25d_iv REAL,
    call_25d_iv REAL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL NOT NULL,
    expiration TEXT NOT NULL,
    premium_received REAL NOT NULL,
    contracts INTEGER NOT NULL,
    strategy TEXT,
    notes TEXT,
    opened TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    close_price REAL,
    close_reason TEXT,
    entry_iv REAL,
    entry_rv REAL,
    entry_vrp REAL,
    entry_delta REAL
);

CREATE TABLE IF NOT EXISTS predictions (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    signal TEXT NOT NULL,
    spot_price REAL,
    atm_iv REAL,
    rv_forecast REAL,
    vrp REAL,
    iv_rank REAL,
    term_label TEXT,
    regime TEXT,
    skew REAL,
    garch_vol REAL,
    forecast_method TEXT,
    holding_days INTEGER DEFAULT 20,
    outcome_price REAL,
    outcome_return REAL,
    outcome_rv REAL,
    outcome_date TEXT,
    scored INTEGER DEFAULT 0,
    seller_won INTEGER,
    UNIQUE(ticker, date, holding_days)
);

-- Enable RLS (Row Level Security) - optional but recommended
ALTER TABLE iv_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;

-- Allow all operations for authenticated and anon users (simple setup)
CREATE POLICY "Allow all on iv_snapshots" ON iv_snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on trades" ON trades FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on predictions" ON predictions FOR ALL USING (true) WITH CHECK (true);
