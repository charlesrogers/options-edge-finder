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
