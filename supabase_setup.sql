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

-- Enable RLS (Row Level Security) - optional but recommended
ALTER TABLE iv_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

-- Allow all operations for authenticated and anon users (simple setup)
CREATE POLICY "Allow all on iv_snapshots" ON iv_snapshots FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on trades" ON trades FOR ALL USING (true) WITH CHECK (true);
