"""Constants, arms and the universe. One definition, served to the web.

Every number in this file is either derived (with its derivation named) or
explicitly labelled an arbitrary starting value. Nothing here is a constant that
looks measured but was invented — the failure the global rule calls out by name.

Nothing in `web/` re-declares these. The health API serves them, because a TS
mirror of a Python truth is production drift by definition
(tasks/lessons.md 2026-08-18, strategies.ts).
"""
import os

import ticker_strategies

# ---------------------------------------------------------------- identity ---
ENGINE_NAME = "paper_engine"
ENGINE_VERSION = "0.1.0"
HEARTBEAT_SOURCE = "github-actions"
HEARTBEAT_ROLE = "paper-engine"


def engine_commit_sha():
    """The commit this run is executing. Stamped on every row written."""
    return os.environ.get("GITHUB_SHA") or os.environ.get("ENGINE_COMMIT_SHA") or "local"


# ------------------------------------------------------------------- arms ----
# Arms differ ONLY in which decisions they act on — never in data, pricing or
# accounting. A quote missing for one arm is missing for all.
ARMS = {
    "A": {
        "hypothesis": "H40",
        "name": "full strategy",
        "iv_gate": True,
        "exits": "full_ladder",
        "isolates": "the product as shipped",
    },
    "B": {
        "hypothesis": "H41",
        "name": "hold to expiry",
        "iv_gate": True,
        "exits": "none",
        "isolates": "the copilot's entire value and cost (measured as A-B)",
    },
    "C": {
        "hypothesis": "H42",
        "name": "no IV gate",
        "iv_gate": False,
        "exits": "full_ladder",
        "isolates": "the IV gate's forward value (measured as A-C)",
    },
    "D": {
        "hypothesis": "H43",
        "name": "take-profit only",
        "iv_gate": True,
        "exits": "tp_and_emergency",
        "isolates": "how much of A's exit cost is defensive vs profit-taking",
    },
}
ARM_ORDER = ["A", "B", "C", "D"]
HYPOTHESES = [ARMS[a]["hypothesis"] for a in ARM_ORDER]

# Arm D acts only on these clauses. The TP-75 rung is
# `close_soon_tp75` (position_monitor.py); EMERGENCY is the ex-dividend
# catastrophe rule and is never disabled in any arm.
ARM_D_CLAUSES = {"close_soon_tp75", "emergency_itm_exdiv_3d"}


def universe():
    """Non-skip production tickers, read from the single source of truth.

    Hard-coding the list here would be a second definition of the universe;
    when a ticker is demoted to `skip` in ticker_strategies.py it must leave the
    engine on the next run, not when someone remembers.
    """
    return sorted(t for t, c in ticker_strategies.TICKER_STRATEGIES.items()
                  if c.get("tier") != "skip")


def contracts_for(ticker, account_value=10_000):
    """Dad's size with the Exp 021 liquidity caps applied (KKR = 7)."""
    n, reason = ticker_strategies.get_max_contracts(ticker, account_value)
    return int(n), reason


# ------------------------------------------------------------------ fills ----
# LABEL: assumption, not measurement. $0.65/contract/side is a typical retail
# rate; replace with Dad's actual rate when known. Reported as its own line on
# every trade and never buried inside P&L.
COMMISSION_PER_CONTRACT_PER_SIDE = 0.65

# LABEL: arbitrary starting value, to tune once two weeks of observed quotes
# exist. Dad cannot sell at a zero bid, and KKR's 15%-OTM strike traded a
# median of 3 contracts a day (Exp 021). Probed 2026-08-20: KKR's bid was
# $0.15 against a $0.55 ask — passing this floor, and still a 267%-of-credit
# round trip.
MIN_ENTRY_BID = 0.05

# Human latency. Dad is not an HFT. A decision at tick T fills at the first tick
# with tick_ts >= T + this many minutes. Cron drift is absorbed by construction:
# "first tick at or after" is later, never earlier.
LATENCY_MINUTES = 15

# The Cloudflare worker caches option chains for 5 minutes. Never tighten the
# tick grid below that TTL — it would serve the same quote as two observations.
TICK_GRID_MINUTES = 15
WORKER_CACHE_TTL_MINUTES = 5

# Entry evaluation happens at the tick nearest this ET wall-clock time, computed
# from the calendar rather than a fixed UTC hour (fixed-UTC crons drift an hour
# twice a year — docs/crons.md).
# LABEL: arbitrary starting value.
ENTRY_EVAL_ET_MINUTES = 15 * 60 + 30      # 15:30 ET

# ------------------------------------------------------------- data health ---
# LABEL: arbitrary starting value. Three consecutive carried-forward quotes on
# an open position is a data problem, not a strategy problem, and says so.
STALE_STREAK_WARN = 3

# --------------------------------------------------------------- exit sim ----
# cc_sim's DEFAULT_CFG semantics, imported rather than restated where possible.
# `slippage` is 0 here on purpose: this engine does not model slippage, it pays
# the real spread. Adding a slippage multiplier on top of a bid/ask fill would
# charge for the same friction twice.
POLICY_CFG = {
    "slippage": 0.0,
    "close_soon_days": 5,        # CALENDAR days — see cc_core's docstring
    "close_soon_sticky": True,
}

# ------------------------------------------------------------------ tables ---
TABLES = {
    "entry_evals": "paper_engine_entry_evals",
    "quotes": "paper_engine_quotes",
    "trades": "paper_engine_trades",
    "events": "paper_engine_events",
}

# The startup schema contract (spec §5.6). PostgREST rejects an unknown column
# even against an empty table, so selecting this exact list is a real contract
# check — and it runs before the first decision, not after the first write.
SCHEMA_CONTRACT = {
    "paper_engine_entry_evals": [
        "id", "tick_ts", "trading_day", "ticker", "chain_status", "spot",
        "spot_usable", "contract_symbol", "strike", "expiry", "dte", "bid",
        "ask", "last", "volume", "open_interest", "implied_volatility",
        "iv_rank", "iv_threshold", "iv_rank_source", "liquidity_ok",
        "liquidity_reason", "arm_results", "engine_commit_sha",
        "engine_version", "created_at",
    ],
    "paper_engine_quotes": [
        "id", "contract_symbol", "tick_ts", "trading_day", "ticker", "bid",
        "ask", "last", "volume", "open_interest", "implied_volatility", "spot",
        "bid_usable", "ask_usable", "spot_usable", "source_status", "stale",
        "stale_from_tick_ts", "engine_commit_sha", "engine_version", "created_at",
    ],
    "paper_engine_trades": [
        "id", "arm", "ticker", "cycle_seq", "status", "contract_symbol",
        "strike", "expiry", "dte_at_entry", "contracts", "entry_decision_ts",
        "entry_decision_bid", "entry_decision_ask", "entry_decision_spot",
        "entry_fill_ts", "entry_fill_bid", "entry_fill_ask", "entry_fill_spot",
        "entry_fill_price", "entry_spread", "entry_spread_pct",
        "entry_latency_min", "entry_overnight_gap", "entry_quote_stale",
        "entry_commission", "exit_decision_ts", "exit_decision_bid",
        "exit_decision_ask", "exit_decision_spot", "exit_fill_ts",
        "exit_fill_bid", "exit_fill_ask", "exit_fill_spot", "exit_fill_price",
        "exit_spread", "exit_spread_pct", "exit_latency_min",
        "exit_overnight_gap", "exit_quote_stale", "exit_commission",
        "exit_kind", "exit_clause", "exit_verdict", "exit_priced_from",
        "close_soon_armed_on", "assigned", "assignment_type",
        "assignment_modeled", "assignment_inputs", "premium_per_share",
        "buyback_per_share", "pnl_per_share", "gross_pnl", "commissions_total",
        "spread_cost_total", "net_pnl", "real_fill", "engine_commit_sha",
        "engine_version", "opened_at", "closed_at", "updated_at",
    ],
    "paper_engine_events": [
        "id", "event_ts", "trading_day", "kind", "severity", "arm", "ticker",
        "cycle_seq", "dedup_key", "payload", "engine_commit_sha",
        "engine_version",
    ],
    # Shared migration-003 table. Only the columns the engine actually writes —
    # and deliberately NOT engine_commit_sha, which this table does not have
    # (stamping it made every heartbeat 400 and every run fail).
    "monitor_heartbeats": [
        "id", "ran_at", "source", "role", "engine", "engine_version",
        "positions_checked", "positions_unassessed", "alerts_fired",
        "alerts_undelivered", "ok", "detail",
    ],
}
