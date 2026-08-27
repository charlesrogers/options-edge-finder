"""Turn reference.json into the pre-registered thresholds, showing every step.

Rule this script serves (global, verbatim): "Every number in a recommendation is
either computed from the data with the derivation shown, or explicitly labeled
as an arbitrary starting value to tune. Mixing invented constants in with
measured ones makes the whole analysis untrustworthy."

So every threshold below carries `derivation` (the arithmetic, in words) and
`kind` — one of:
    derived   — computed from reference.json, arithmetic shown
    arbitrary — a starting value, chosen not measured, to tune from observation
    mechanical— no calibration possible or needed (e.g. "any assignment at all")

Output: thresholds.json, which is embedded verbatim in PREREGISTRATION.md and
read at runtime by paper_engine/killswitch.py. A test asserts the two copies
agree, and the document's SHA-256 is what the engine's startup gate checks — so
moving a threshold after go-live requires editing the doc, which bricks the
engine loudly rather than bending the experiment silently.

Run: python3 experiments/024_paper_engine/derive_thresholds.py
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

REFERENCE = os.path.join(HERE, "reference.json")
OUT = os.path.join(HERE, "thresholds.json")

# Study horizon, from the spec's milestones.
MILESTONES = [30, 90, 180]

# Family-wise false-alarm budget for the per-ticker consecutive-loss kills.
# 5% across the tickers that have a derivable win rate. An alert channel
# survives about two false alarms (docs/crons.md), and there are four of these
# armed at once, so the per-ticker budget is the family budget divided by the
# number of tickers.
FAMILY_ALPHA = 0.05

# Poisson tail budget for the EMERGENCY-cluster kill.
EMERGENCY_ALPHA = 0.05

# LABEL: arbitrary. Multiplier applied on top of (reference drawdown + modelled
# forward friction) before the drawdown kill trips. It buys room for the
# sampling noise of a handful of cycles; it is not measured and should be
# revisited at the day-90 review with real observed variance.
DRAWDOWN_SAFETY_FACTOR = 1.5


def load_reference():
    with open(REFERENCE) as f:
        return json.load(f)


def usable_results(ref):
    """Only ticker-windows that produced trustworthy numbers.

    A split-contaminated or dataless window contributes nothing — silently
    averaging it in is how an invented number acquires a derivation.
    """
    return [r for r in ref["results"] if r.get("status") == "ok"]


def recent(ref):
    return [r for r in usable_results(ref) if r["window"] == "owned_recent"]


# --------------------------------------------------------------------------
# 1. Expected cycles — the floors every verdict rule is conditioned on
# --------------------------------------------------------------------------
def cycle_expectations(ref):
    out, pooled = {}, {d: 0.0 for d in MILESTONES}
    for r in recent(ref):
        cy = r.get("cycles_per_year_sequential")
        if not cy:
            continue
        per_year = cy["median"]
        row = {
            "cycles_per_year_median": per_year,
            "cycles_per_year_range": [cy["min"], cy["max"]],
            "hold_time_median_days": r["hold_time_days_real"]["median"],
            "hold_time_p90_days": r["hold_time_days_real"]["p90"],
            "derivation": (
                f"{per_year} completed cycles/year on the median sequential "
                f"chain (25 staggered starts, real-fill subset, "
                f"{r['data_window'][0]}..{r['data_window'][1]}); "
                f"day-N expectation = {per_year} * N/365"),
            "kind": "derived",
        }
        for d in MILESTONES:
            n = round(per_year * d / 365.0, 1)
            row[f"expected_by_day_{d}"] = n
            pooled[d] += n
        out[r["ticker"]] = row

    missing = sorted({t for t in ref["universe"]} - set(out))
    return {
        "per_ticker": out,
        "pooled": {f"day_{d}": round(v, 1) for d, v in pooled.items()},
        "tickers_without_a_reference": missing,
        "note": (
            f"Pooled counts cover only {sorted(out)}. "
            f"{', '.join(missing) if missing else 'No ticker'} has no usable "
            f"backtest reference, so it contributes cycles the engine will "
            f"observe but no floor it can be graded against. Its forward "
            f"numbers are reported and explicitly excluded from every "
            f"pre-registered verdict."),
    }


# --------------------------------------------------------------------------
# 2. Consecutive-loss kill — binomial, per ticker
# --------------------------------------------------------------------------
def consecutive_loss_kills(ref, cycles):
    """Smallest M whose run-probability inside the study clears the budget.

    P(at least one run of M losses in N cycles) is approximated by
    (N - M + 1) * q^M, the standard first-order bound for rare runs. It
    overestimates slightly, which is the safe direction for a kill switch: it
    makes M larger, so the switch fires less readily on noise.
    """
    per_ticker = {}
    derivable = [r for r in recent(ref)
                 if r.get("per_cycle_win_rate_real_fills")
                 and r["ticker"] in cycles["per_ticker"]]
    alpha = FAMILY_ALPHA / max(1, len(derivable))

    for r in derivable:
        ticker = r["ticker"]
        wr = r["per_cycle_win_rate_real_fills"]["median"]
        q = round(1 - wr / 100.0, 4)
        n = cycles["per_ticker"][ticker]["expected_by_day_180"]
        if q <= 0:
            per_ticker[ticker] = {
                "kind": "mechanical",
                "reference_win_rate_pct": wr,
                "M": None,
                "armed": False,
                "derivation": (
                    f"reference per-cycle win rate is {wr}% — a loss rate of "
                    f"zero gives no binomial to solve. This kill cannot be "
                    f"calibrated for {ticker} and stays DISARMED until the "
                    f"engine has observed its own loss rate. Reporting a "
                    f"threshold here would be an invented number."),
            }
            continue
        steps, M = [], None
        for m in range(2, 12):
            p = max(0.0, (n - m + 1)) * (q ** m)
            steps.append(f"M={m}: ({n} - {m} + 1) x {q}^{m} = {p:.4f}")
            if p < alpha and n >= m:
                M = m
                break
        per_ticker[ticker] = {
            "kind": "derived" if M else "mechanical",
            "reference_win_rate_pct": wr,
            "loss_rate_q": q,
            "expected_cycles_by_day_180": n,
            "per_ticker_alpha": round(alpha, 4),
            "M": M,
            "armed": bool(M),
            "steps": steps,
            "derivation": (
                f"q = 1 - {wr}/100 = {q}; N = {n} cycles expected by day 180; "
                f"family alpha {FAMILY_ALPHA} split across {len(derivable)} "
                f"tickers = {alpha:.4f} each; smallest M with "
                f"(N-M+1)*q^M < alpha and N >= M"
                + (f" is M={M}." if M else
                   " does not exist inside 180 days — DISARMED, and the "
                   "milestone review must say so rather than quote a number.")),
        }
    return per_ticker


# --------------------------------------------------------------------------
# 3. Drawdown kill
# --------------------------------------------------------------------------
def friction_estimate():
    """Modelled forward friction per cycle, from the 2026-08-20 quote probe.

    The reference backtest fills at the daily close with slippage 0. The engine
    fills at bid/ask and pays commission, so its drawdowns MUST run deeper than
    the reference for reasons that have nothing to do with the strategy. Not
    accounting for that would make the kill switch fire on friction.
    """
    from paper_engine import config as pcfg
    # Observed half-spreads, per share, at the production strike (probe_quotes).
    observed = {"AAPL": 0.03 / 2, "KKR": 0.40 / 2}
    comm_round_trip = pcfg.COMMISSION_PER_CONTRACT_PER_SIDE * 2
    out = {}
    for ticker, half in observed.items():
        # Half the spread on each of two legs = one full spread per cycle.
        spread_cost = half * 2 * 100
        out[ticker] = round(spread_cost + comm_round_trip, 2)
    typical = round(sum(out.values()) / len(out), 2)
    return {
        "per_cycle_usd_per_contract": out,
        "typical_per_cycle_usd": typical,
        "kind": "derived",
        "derivation": (
            f"from scripts/probe_quotes.py, 2026-08-20: AAPL spread $0.03, KKR "
            f"$0.40 at the production strike. Half a spread each way = one full "
            f"spread per cycle, x100 shares, plus "
            f"${comm_round_trip:.2f} round-trip commission "
            f"(${pcfg.COMMISSION_PER_CONTRACT_PER_SIDE}/contract/side, itself "
            f"an assumption). Two observations on one day — indicative, not a "
            f"distribution."),
    }


def drawdown_kills(ref, cycles):
    friction = friction_estimate()
    per_ticker = {}
    for r in recent(ref):
        dd = r.get("worst_30d_drawdown_real_fills")
        if not dd:
            continue
        ticker = r["ticker"]
        worst = dd["max"]
        cy = cycles["per_ticker"].get(ticker, {})
        per_year = cy.get("cycles_per_year_median", 0)
        cycles_in_30d = round(per_year * 30 / 365.0, 2)
        fr = friction["per_cycle_usd_per_contract"].get(
            ticker, friction["typical_per_cycle_usd"])
        friction_30d = round(fr * cycles_in_30d, 2)
        threshold = round((worst + friction_30d) * DRAWDOWN_SAFETY_FACTOR, 2)
        per_ticker[ticker] = {
            "kind": "derived_with_arbitrary_multiplier",
            "reference_worst_30d_drawdown_usd": worst,
            "reference_median_30d_drawdown_usd": dd["median"],
            "modelled_30d_friction_usd": friction_30d,
            "safety_factor": DRAWDOWN_SAFETY_FACTOR,
            "threshold_usd_per_contract": threshold,
            "derivation": (
                f"worst 30-day realised option-leg drawdown across 25 staggered "
                f"sequential chains, real-fill subset = ${worst}. Forward "
                f"friction over 30 days = ${fr}/cycle x {cycles_in_30d} cycles "
                f"= ${friction_30d}. Threshold = (${worst} + ${friction_30d}) x "
                f"{DRAWDOWN_SAFETY_FACTOR} = ${threshold}. The two components "
                f"are measured; the {DRAWDOWN_SAFETY_FACTOR}x is an ARBITRARY "
                f"starting value covering small-sample noise, to be revisited "
                f"at day 90 against observed variance."),
        }
    return {"per_ticker": per_ticker, "friction_model": friction}


# --------------------------------------------------------------------------
# 4. EMERGENCY-cluster kill
# --------------------------------------------------------------------------
def emergency_kill(ref):
    rates, detail = [], {}
    for r in recent(ref):
        e = r.get("emergency_fires", {})
        rate = e.get("per_30d_one_position")
        if rate is None:
            continue
        rates.append(rate)
        detail[r["ticker"]] = rate
    if not rates:
        return {"kind": "mechanical", "armed": False,
                "derivation": "no reference EMERGENCY rate available"}

    lam = round(sum(rates), 4)      # one open position per ticker, summed
    steps, E = [], None
    for e in range(1, 10):
        # P(X >= e) under Poisson(lam)
        tail = 1.0 - sum(math.exp(-lam) * lam ** k / math.factorial(k)
                         for k in range(e))
        steps.append(f"E={e}: P(X>={e}) = {tail:.5f}")
        if tail < EMERGENCY_ALPHA:
            E = e
            break
    # The derivation can return E=1 when the reference rate is near zero. One
    # EMERGENCY is the copilot working exactly as designed — it fires, the
    # position closes, nothing is wrong. The kill is for a CLUSTER, which is the
    # signal that the regime changed. So the derived E is floored at 2, and both
    # numbers are reported rather than the floor quietly replacing the maths.
    derived_E = E
    E = max(2, E) if E else 2
    return {
        "kind": "derived_with_arbitrary_floor",
        "derived_E": derived_E,
        "floor_reason": (
            "floored at 2: E=1 would fire on a single EMERGENCY, which is the "
            "copilot doing its job, not a regime change. The floor of 2 is an "
            "ARBITRARY minimum; the Poisson maths above it is derived."),
        "per_ticker_rate_per_30d": detail,
        "portfolio_lambda_per_30d": lam,
        "alpha": EMERGENCY_ALPHA,
        "E": E,
        "armed": bool(E),
        "steps": steps,
        "derivation": (
            f"reference EMERGENCY fires per 30 days per open position, summed "
            f"across the {len(rates)} tickers with a reference = lambda {lam}. "
            f"Smallest E with Poisson tail P(X>=E) < {EMERGENCY_ALPHA} is E={E}. "
            f"The reference rate is near zero because the recent window "
            f"contained no crash — which is exactly why a cluster means we are "
            f"living the untested case."),
    }


# --------------------------------------------------------------------------
# 5. Verdict rules for H40-H43
# --------------------------------------------------------------------------
def pooled_power(samples, label):
    """Cycles needed for a 90% CI on the POOLED mean to exclude zero.

    Pooled, because that is the question the verdict rule asks. Averaging each
    ticker's required-n instead would let one ticker whose mean happens to sit
    near zero dominate a number that is supposed to describe the whole study.
    """
    if not samples:
        return {"derivable": False, "reason": "no samples"}
    a = np.array(samples, dtype=float)
    mean, sd = float(a.mean()), float(a.std(ddof=1)) if a.size > 1 else 0.0
    needed = (1.645 * sd / abs(mean)) ** 2 if mean and sd else None
    return {
        "derivable": needed is not None,
        "label": label,
        "n_pooled_samples": int(a.size),
        "pooled_mean_usd_per_cycle": round(mean, 2),
        "pooled_sd": round(sd, 2),
        "cycles_for_90pct_ci_to_exclude_zero": round(needed, 1) if needed else None,
        "caveat": ("normal approximation on overlapping, autocorrelated cohorts "
                   "— an order of magnitude, not a promise"),
    }


def verdict_rules(ref, cycles):
    pooled_180 = cycles["pooled"]["day_180"]

    ab_pool, ad_pool, gate_pool = [], [], []
    per_ticker_power = {}
    for r in recent(ref):
        pr = r["paired_reference"]
        ab_pool += pr["A_minus_B_copilot_value"].get("deltas", [])
        ad_pool += pr["A_minus_D_defensive_exits"].get("deltas", [])
        gate_pool += pr["iv_gate_effect"].get("blocked_pnls", [])
        per_ticker_power[r["ticker"]] = {
            "A_minus_B": pr["A_minus_B_copilot_value"].get(
                "cycles_for_90pct_ci_to_exclude_zero"),
            "A_minus_D": pr["A_minus_D_defensive_exits"].get(
                "cycles_for_90pct_ci_to_exclude_zero"),
            "iv_gate": pr["iv_gate_effect"].get(
                "cycles_for_90pct_ci_to_exclude_zero"),
        }

    # H40's own power, per ticker: the absolute question, same estimator, so
    # "which question resolves first" is answered by arithmetic rather than by
    # assumption.
    h40_power = {}
    for r in recent(ref):
        h40_power[r["ticker"]] = pooled_power(
            r.get("per_cycle_pnl_real_fills", []), f"H40 {r['ticker']}")

    ab_power = pooled_power(ab_pool, "A-B")
    ad_power = pooled_power(ad_pool, "A-D")
    gate_power = pooled_power(gate_pool, "IV gate blocked set")
    ab_needed = ab_power.get("cycles_for_90pct_ci_to_exclude_zero")
    ad_needed = ad_power.get("cycles_for_90pct_ci_to_exclude_zero")
    gate_needed = gate_power.get("cycles_for_90pct_ci_to_exclude_zero")

    # Floor = 10 pooled cycles or the power sketch, whichever is larger. The 10
    # is arbitrary and labelled; it exists so that a rule cannot be satisfied by
    # three lucky cycles even where the power sketch says two would do.
    floor_min = 10

    def floor(needed):
        if needed is None:
            return floor_min, "power sketch not derivable; floor is the minimum"
        return (max(floor_min, math.ceil(needed)),
                f"max(minimum {floor_min}, power sketch {needed})")

    h41_floor, h41_why = floor(ab_needed)
    h42_floor, h42_why = floor(gate_needed)
    h43_floor, h43_why = floor(ad_needed)

    def per_ticker_floors(key):
        """Registered floors are PER TICKER — see `_power.finding` (2)."""
        out = {}
        for t, needs in per_ticker_power.items():
            n = needs.get(key)
            by_180 = cycles["per_ticker"][t]["expected_by_day_180"]
            f = max(floor_min, math.ceil(n)) if n else floor_min
            out[t] = {
                "floor": f,
                "power_sketch": n,
                "expected_by_day_180": by_180,
                "reachable_by_day_180": by_180 >= f,
                "expected_days_to_floor": (
                    round(f / (by_180 / 180.0)) if by_180 else None),
            }
        return out

    def reachability(floor_n, by_180):
        """Say NOW whether a rule can be graded at day 180.

        Discovering at the review that the floor was unreachable is how a study
        turns into an anecdote. Pre-committing to 'this will be INCONCLUSIVE'
        is a result; improvising a softer rule in month six is not.
        """
        return {
            "expected_by_day_180": by_180,
            "floor": floor_n,
            "reachable_by_day_180": by_180 >= floor_n,
            "expected_days_to_floor": (
                round(floor_n / (by_180 / 180.0)) if by_180 else None),
            "pre_committed_outcome_if_unreachable": (
                "INCONCLUSIVE — reported as 'not enough cycles', with the "
                "point estimate and CI shown and explicitly labelled "
                "under-powered. It is not upgraded to a verdict by "
                "loosening the rule."),
        }

    return {
        "_power": {
            "A_minus_B": ab_power, "A_minus_D": ad_power,
            "iv_gate": gate_power, "per_ticker": per_ticker_power,
            "H40_per_ticker": h40_power,
            "reachability_summary": {
                t: {
                    "expected_cycles_by_day_180": cycles["per_ticker"][t]["expected_by_day_180"],
                    "H40_cycles_needed": h40_power[t].get("cycles_for_90pct_ci_to_exclude_zero"),
                    "A_minus_B_cycles_needed": per_ticker_power[t]["A_minus_B"],
                    "A_minus_D_cycles_needed": per_ticker_power[t]["A_minus_D"],
                    "iv_gate_cycles_needed": per_ticker_power[t]["iv_gate"],
                }
                for t in sorted(h40_power)
            },
            "finding": (
                "Two things, both pre-registered rather than discovered at "
                "review time. (1) The spec's premise HOLDS, per ticker: the "
                "paired arm differences need far fewer cycles than the absolute "
                "P&L question — AAPL 41 vs 793, TMUS 24 vs 58,101, KKR 118 vs "
                "359, DIS 14 vs 22. Pairing cancels the regime noise exactly as "
                "claimed. (2) Pooling ACROSS tickers is the wrong estimator for "
                "the paired questions and must not be used as the primary rule: "
                "the per-ticker means have opposite signs (A-B: TMUS -64, AAPL "
                "-41, KKR +50, DIS +271), so they cancel and the pooled "
                "requirement (270) is worse than every per-ticker one. The "
                "registered rules are therefore per-ticker; pooled figures are "
                "reported as secondary and never as the verdict. (3) The blunt "
                "consequence: NOTHING here is gradeable at day 180. The "
                "cheapest question is DIS A-B at 14 cycles against 2.0 "
                "expected; the cheapest that accrues quickly is TMUS A-B at 24 "
                "against 6.4. Day 180 is an interim readout with point "
                "estimates and honest CIs, not a verdict."),
        },
        "H40": {
            "question": "Does the full strategy net positive per ticker after real friction?",
            "metric": "net option-leg P&L per completed cycle, real-fill subset, per ticker",
            "registered_floors_per_ticker": {
                t: {
                    "floor": max(floor_min, math.ceil(h40_power[t][
                        "cycles_for_90pct_ci_to_exclude_zero"]))
                    if h40_power[t].get("cycles_for_90pct_ci_to_exclude_zero")
                    else floor_min,
                    "power_sketch": h40_power[t].get(
                        "cycles_for_90pct_ci_to_exclude_zero"),
                    "expected_by_day_180": cycles["per_ticker"][t][
                        "expected_by_day_180"],
                    "per_cycle_sd": h40_power[t].get("pooled_sd"),
                    "per_cycle_mean": h40_power[t].get("pooled_mean_usd_per_cycle"),
                }
                for t in sorted(h40_power)},
            "floor_derivation": (
                "n >= (1.645 * sd / |mean|)^2 on the reference per-cycle "
                "real-fill option-leg P&L, floored at the minimum of "
                f"{floor_min}. These floors are large — TMUS's mean per cycle "
                "is $1.50 against a $121 standard deviation, so its absolute "
                "P&L question needs ~58,000 cycles. That is not a defect in the "
                "rule; it is the measurement telling us that TMUS's edge, if "
                "any, is far smaller than its noise."),
            "rule": (
                "H40 PASSES for a ticker iff completed real-fill cycles >= that "
                "ticker's floor AND the 90% bootstrap CI (10,000 resamples of "
                "per-cycle net P&L) excludes 0 above it. FAILS iff the CI "
                "excludes 0 below it. Otherwise INCONCLUSIVE — which is a "
                "verdict, not a deferral."),
            "pooled_expected_by_day_180": pooled_180,
        },
        "H41": {
            "question": "What do the copilot's exits actually cost? (A - B)",
            "metric": "paired per-cycle difference in net option-leg P&L, A minus B",
            "floor_pooled_cycles": h41_floor,
            "floor_derivation": h41_why,
            "reference_power_sketch_pooled": ab_needed,
            "registered_floors_per_ticker": per_ticker_floors("A_minus_B"),
            "pooled_floor_secondary_only": h41_floor,
            "reachability_pooled": reachability(h41_floor, pooled_180),
            "rule": (
                "H41 concludes 'the copilot adds value' iff pooled paired "
                "cycles >= the floor AND the 90% bootstrap CI of per-cycle "
                "(A - B) excludes 0 in A's favour; 'the copilot is net-negative "
                "on the option leg' iff it excludes 0 against A."),
            "mandatory_caveat": (
                "Arm B's option-leg P&L is not comparable to arm A's without "
                "its assignment count. In the reference, arm A took ZERO "
                "assignments in every window while arm B took 10-102. Being "
                "called away is the tax event the copilot exists to prevent, "
                "and option-leg P&L cannot see it. Any A-B readout that omits "
                "both arms' assignment counts is a misreport."),
        },
        "H42": {
            "question": "Is the IV gate worth anything forward? (A vs C)",
            "metric": ("mean net option-leg P&L of the entries the gate BLOCKS "
                       "(arm C entered, arm A did not)"),
            "floor_blocked_entries": h42_floor,
            "floor_derivation": h42_why,
            "reference_power_sketch_pooled": gate_needed,
            "registered_floors_per_ticker": per_ticker_floors("iv_gate"),
            "pooled_floor_secondary_only": h42_floor,
            "reachability_pooled": reachability(h42_floor, pooled_180),
            "accrual_caveat": (
                "The floor counts BLOCKED ENTRIES, not cycles. The reference "
                "counts them in cohort mode (every day is evaluated); the "
                "engine evaluates a ticker only while it is flat, so the "
                "forward accrual rate for blocked entries is NOT derivable from "
                "this reference and must be measured at day 30 before anyone "
                "estimates a date for this verdict."),
            "rule": (
                "H42 concludes 'the IV gate destroys value' iff blocked entries "
                ">= the floor AND the 90% bootstrap CI of their per-cycle net "
                "P&L excludes 0 above it; 'the gate protects' iff it excludes 0 "
                "below it."),
            "method_note": (
                "NOT a paired comparison. On days both arms enter, the trades "
                "are identical, so a paired delta is exactly 0 and measures "
                "nothing. The gate's whole effect is the set it blocks — the "
                "method Exp 023 used to find the gate blocks TMUS winners."),
        },
        "H43": {
            "question": "How much of A's exit cost is defensive vs profit-taking? (A - D)",
            "metric": "paired per-cycle difference in net option-leg P&L, A minus D",
            "floor_pooled_cycles": h43_floor,
            "floor_derivation": h43_why,
            "reference_power_sketch_pooled": ad_needed,
            "registered_floors_per_ticker": per_ticker_floors("A_minus_D"),
            "pooled_floor_secondary_only": h43_floor,
            "reachability_pooled": reachability(h43_floor, pooled_180),
            "rule": (
                "H43 concludes 'the defensive clauses carry the exit cost' iff "
                "pooled paired cycles >= the floor AND the 90% bootstrap CI of "
                "per-cycle (A - D) excludes 0. Sign gives the direction."),
        },
    }


def main():
    ref = load_reference()
    cycles = cycle_expectations(ref)
    out = {
        "generated_from": {
            "reference": "experiments/024_paper_engine/reference.json",
            "reference_generated_at": ref["generated_at_utc"],
            "engine_sha": ref["engine"]["sha"],
            "engine_worktree_dirty": ref["engine"].get("worktree_dirty"),
        },
        "standard": ref["standard"],
        "cycle_expectations": cycles,
        "verdict_rules": verdict_rules(ref, cycles),
        "kills": {
            "engine_integrity": {
                "quote_coverage_pct_trailing_5_sessions": {
                    "kind": "arbitrary",
                    "threshold": 80.0,
                    "derivation": (
                        "ARBITRARY starting value. No forward observation of "
                        "quote coverage exists yet — the backtest's repricing "
                        "coverage (36-99% across tickers) measures a different "
                        "thing (Databento prints, not live bid/ask). Re-derive "
                        "from the first two weeks of observed coverage at the "
                        "day-30 integrity checkpoint."),
                },
                "heartbeat_stale_sessions": {
                    "kind": "arbitrary",
                    "threshold": 1,
                    "derivation": (
                        "ARBITRARY. One closed session with no heartbeat during "
                        "market hours. Calendar-aware via market_calendar, so a "
                        "Friday-afternoon run is not stale all weekend."),
                },
                "consecutive_stale_ticks_warning": {
                    "kind": "arbitrary",
                    "threshold": 3,
                    "derivation": ("ARBITRARY starting value, from spec §5.4. A "
                                   "data problem, not a strategy problem — it "
                                   "warns, it does not kill."),
                },
                "assessed_without_ask_pct": {
                    "kind": "arbitrary",
                    "threshold": 5.0,
                    "derivation": (
                        "ARBITRARY. assess_position defaults premium_captured_pct "
                        "to 0 when the ask is missing, which silently disables "
                        "TP-75 and TP-50. Above this share of ticks, the "
                        "take-profit rungs are effectively off and no exit "
                        "result means anything."),
                },
            },
            "strategy": {
                "drawdown": drawdown_kills(ref, cycles),
                "modeled_assignment_in_arm_A": {
                    "kind": "mechanical",
                    "threshold": 1,
                    "derivation": (
                        "Any modeled assignment in arm A halts that ticker. No "
                        "calibration: arm A's entire purpose is that this never "
                        "happens, and the reference shows zero across every "
                        "usable window. MUST be reported with the "
                        "reachability disclosure — the reference recorded only "
                        "8 approaches to the assignment branch (all KKR) across "
                        "8,458 observations, so a forward zero may mean the "
                        "state was never reached, not that the constraint held."),
                    "reference_approaches": {
                        r["ticker"]: r.get("assignment_branch_approaches")
                        for r in recent(ref)},
                },
                "consecutive_losses": consecutive_loss_kills(ref, cycles),
                "emergency_cluster_30d": emergency_kill(ref),
            },
        },
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
    print(json.dumps(out, indent=2, sort_keys=True))
    print(f"\nwrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
