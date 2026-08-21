"""Register H40-H43 — the paper-trading engine's four arms.

MUST be run through `registry-sync.yml`, never from a laptop:

    gh workflow run registry-sync.yml --ref main \\
      -f script=experiments/register_h40_h43.py

Two reasons. Developer machines have no Supabase credentials, and `db.py` falls
back to a gitignored local SQLite file *without saying so* — that is how
signal_graveyard managed not to exist in Supabase for five months while every
registration reported success (tasks/lessons.md 2026-08-16). And the workflow
greps its own log for `sqlite:` and fails the job if it finds it, which is the
only mechanical check that the write was durable.

`workflow_dispatch` only works from the default branch, so PR-1 must be MERGED
before this can run. That ordering is deliberate: it means the pre-registration
is on `main`, with a commit SHA and a timestamp, before the engine can trade.

This script is idempotent for identical content and REFUSES to overwrite
different content — `signal_registry.pre_register` raises `AlreadyRegistered`.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import signal_registry
from paper_engine import config

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(HERE, "024_paper_engine", "PREREGISTRATION.md")
THRESHOLDS = os.path.join(HERE, "024_paper_engine", "thresholds.json")


def doc_hash():
    with open(DOC, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# Tier 1 = core. These four are the study; nothing else in it is a hypothesis.
ARMS = {
    "H40": {
        "name": "Paper engine arm A — full production strategy, forward",
        "hypothesis": (
            "Run forward against real bid/ask quotes captured at the moment "
            "each decision is made, with 15-minute human latency and retail "
            "commissions, the full production covered-call strategy (per-ticker "
            "IV-rank entry gate, production strike/DTE selection, the full "
            "copilot exit ladder) nets POSITIVE option-leg P&L per completed "
            "cycle, per ticker."),
        "filter_desc": (
            "Non-skip production tickers at registration: AAPL, DIS, GOOGL, "
            "KKR, TMUS. Sizing get_max_contracts(ticker, 10000), KKR capped at "
            "7 by the Exp 021 liquidity cap. GOOGL trades but is excluded from "
            "the verdict — it has no backtest reference."),
        "trade_direction": "Sell covered calls; buy back per the copilot ladder",
    },
    "H41": {
        "name": "Paper engine arm B — hold to expiry (measures the copilot, as A-B)",
        "hypothesis": (
            "The copilot's exits ADD value: the paired per-cycle difference "
            "(arm A minus arm B) in net option-leg P&L is positive, where arm B "
            "takes identical entries and identical contracts but never acts on "
            "a copilot verdict. Read only alongside both arms' assignment "
            "counts — arm A took zero assignments in every reference window and "
            "arm B took 0-102, and option-leg P&L cannot see a called-away "
            "stock."),
        "filter_desc": "Identical entries and contracts to arm A",
        "trade_direction": "Sell covered calls; hold to expiry or modelled early exercise",
    },
    "H42": {
        "name": "Paper engine arm C — no IV gate (measures the entry gate)",
        "hypothesis": (
            "The per-ticker IV-rank entry gate ADDS value forward: the entries "
            "it blocks (taken by arm C, refused by arm A) have negative mean "
            "net option-leg P&L. Exp 023 found the opposite on TMUS in "
            "backtest, where the gate blocked 109 entries averaging +$48."),
        "filter_desc": "Liquidity floor only; no IV-rank threshold",
        "trade_direction": "Sell covered calls; identical exits to arm A",
    },
    "H43": {
        "name": "Paper engine arm D — take-profit only (defensive vs profit-taking exits)",
        "hypothesis": (
            "The copilot's DEFENSIVE clauses (distance-to-strike, gamma, "
            "ex-dividend, earnings) carry the majority of arm A's exit cost: "
            "the paired per-cycle difference (arm A minus arm D) is non-zero, "
            "where arm D acts only on the TP-75 rung and on EMERGENCY."),
        "filter_desc": "Identical entries to arm A; acts only on "
                       "close_soon_tp75 and emergency_itm_exdiv_3d",
        "trade_direction": "Sell covered calls; take-profit and emergency exits only",
    },
}


def main():
    sha = doc_hash()
    with open(THRESHOLDS) as f:
        thresholds = json.load(f)

    print(f"[register] backend: {signal_registry.backend()}")
    print(f"[register] PREREGISTRATION.md sha256: {sha}")
    print(f"[register] thresholds from engine {thresholds['generated_from']['engine_sha']}")

    if signal_registry.backend() != "supabase":
        print("::error::registry backend is not Supabase — refusing to register. "
              "A pre-registration in the SQLite fallback is not durable.")
        return 1

    for signal_id, spec in ARMS.items():
        arm = next(a for a, c in config.ARMS.items()
                   if c["hypothesis"] == signal_id)
        rules = thresholds["verdict_rules"][signal_id]
        payload = {
            # THE immutability anchor. The engine recomputes this hash from the
            # committed document before every decision and refuses to trade if
            # it has moved.
            "preregistration_sha256": sha,
            "preregistration_path": "experiments/024_paper_engine/PREREGISTRATION.md",
            "arm": arm,
            "reference_engine_sha": thresholds["generated_from"]["engine_sha"],
            "verdict_rule": rules["rule"],
            "metric": rules["metric"],
            "floors": rules.get("registered_floors_per_ticker"),
            "standard": thresholds["standard"],
        }
        signal_registry.pre_register(
            signal_id=signal_id, name=spec["name"], tier=1,
            hypothesis=spec["hypothesis"],
            filter_desc=spec["filter_desc"],
            trade_direction=spec["trade_direction"],
            primary_metric=rules["metric"],
            pass_thresholds=payload,
            fail_criteria=(
                "See PREREGISTRATION.md section 5 for the kill switches and "
                "section 4 for the verdict rules. A rule whose cycle floor is "
                "not reached is INCONCLUSIVE, which is a verdict."),
        )

    # Read back. "Registered" without a read-back is a claim, not a fact.
    print("\n[register] reading back:")
    ok = True
    for signal_id in ARMS:
        import db
        row = db.get_hypothesis(signal_id)
        if not row:
            print(f"  {signal_id}: MISSING after write")
            ok = False
            continue
        stored = row.get("pass_thresholds")
        if isinstance(stored, str):
            stored = json.loads(stored)
        got = (stored or {}).get("preregistration_sha256")
        match = got == sha
        print(f"  {signal_id}: status={row.get('status')} "
              f"sha={str(got)[:16]}... {'OK' if match else 'MISMATCH'}")
        ok = ok and match

    if not ok:
        print("::error::read-back failed — the registration did not persist correctly")
        return 1
    print("\n[register] all four arms registered and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
