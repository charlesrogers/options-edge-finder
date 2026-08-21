"""Derive the reference table the paper engine's thresholds are calibrated against.

Spec §6.2: "Before freezing PREREGISTRATION.md, re-run the corrected cc_sim
engine (current main, real-fill subset standard) to produce the reference table:
per-ticker expected P&L/cycle, retention, hold-time distribution, worst 30-day
option-leg drawdown across owned + stress windows. Record engine commit SHA and
the table IN the pre-registration."

Why this script exists rather than a number typed into the doc: a threshold
calibrated against a broken baseline is a threshold that means nothing
(tasks/lessons.md 2026-08-16), and a number no committed code can regenerate is
not evidence (2026-08-17). Every figure in PREREGISTRATION.md comes out of here.

Standard: the **real-fill subset** is the result. All-fill numbers are printed
beside it because the spec requires both, never instead of it. Where the two
disagree in sign, the real-fill number is the result (2026-08-17, verbatim).

Run:  python3 experiments/024_paper_engine/derive_reference.py
Out:  experiments/024_paper_engine/reference.json
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'experiments'))

import cc_core
import cc_sim
import lib_phase3 as P3
import ticker_strategies
from paper_engine.config import ARM_D_CLAUSES

OUT = os.path.join(HERE, 'reference.json')

# The paper engine's universe: every non-skip production ticker.
UNIVERSE = [t for t, c in ticker_strategies.TICKER_STRATEGIES.items()
            if c.get('tier') != 'skip']

# Stagger count matches Exp 022 so the two tables are comparable.
N_CHAINS = 25

# The 2020 stress window predates the 5y stock-history default, and IV rank is
# computed against stock closes. Without 10y of history the production gate has
# no rank to read, rejects every day, and the window reports "no trades" — which
# reads as "the strategy never traded in the crash" when it actually means "we
# could not evaluate the crash". The window carries its own stock period.
WINDOWS = [
    ('owned_recent', cc_sim.WINDOW_LEGACY_PRE_STRESS, '5y'),
    ('stress_2020', cc_sim.WINDOW_STRESS_2020, '10y'),
]


def engine_sha():
    """The commit these numbers came from. A baseline without its lineage is
    the failure documented on 2026-08-17 ('trusted an experiment's numbers
    without checking engine lineage')."""
    try:
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                      cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain'],
                                        cwd=ROOT, text=True).strip()
        return {'sha': sha, 'worktree_dirty': bool(dirty)}
    except Exception as e:                                    # pragma: no cover
        return {'sha': None, 'error': str(e)}


def production_cfg(ticker):
    s = ticker_strategies.get_strategy(ticker) or {}
    return {
        'otm_pct': s.get('otm_pct', 0.15),
        'min_dte': s.get('min_dte', 20),
        'max_dte': s.get('max_dte', 45),
        'slippage': 0.0,
    }


def exit_is_real_fill(chain, trade):
    """A settlement is priced off the stock and is always real. A buyback is
    real only if the contract actually printed on the exit date."""
    if trade.exit_reason in ('expiry_worthless', 'expiry_assigned', 'early_exercise'):
        return True
    return chain.price.get((trade.symbol, pd.Timestamp(trade.exit_date))) is not None


# ---------------------------------------------------------------------------
# Split-adjustment contamination guard
# ---------------------------------------------------------------------------
# Databento option strikes are as-traded; the stock history from the proxy is
# split-ADJUSTED. Across a split the two disagree by the split ratio, so every
# strike looks far out of the money, nothing is ever breached, and the window
# reports spectacular retention. The first run of this script produced AAPL
# 2020 = $13,731/cycle at 99.7% retention on 100% coverage. That is not a
# result; it is a 4:1 split (2020-08-31) measured against post-split closes.
#
# The band is derived, not chosen. Measured median-of-daily
# (median strike / spot) across every window this script loads:
#
#     clean:        AAPL 1.04, DIS 1.05, TMUS 1.04, KKR 1.02  (owned_recent)
#                   DIS 1.08, TMUS 1.03, KKR 1.03             (stress_2020)
#                   full observed spread across all clean days: 0.98 .. 1.23
#     contaminated: AAPL 4.02 (4:1 split), GOOGL 20.70 (20:1 split)
#
# [0.70, 1.50] clears the widest clean observation (1.23) by a comfortable
# margin on both sides and still catches a 2:1 split, the smallest that could
# matter. A window is rejected when more than 5% of its days fall outside —
# 5% rather than 0% because AAPL's split lands mid-window, so a median-only
# test would pass a window that is half corrupt.
SPLIT_BAND = (0.70, 1.50)
SPLIT_MAX_OUT_OF_BAND_PCT = 5.0


def split_contamination(chain):
    """Is this ticker-window's strike ladder aligned with its stock history?"""
    ratios = []
    for d in chain.option_days:
        spot = chain.spot(d)
        if not spot:
            continue
        strikes = chain.by_date[d]['strike']
        if strikes.empty:
            continue
        ratios.append(float(strikes.median()) / spot)
    if not ratios:
        return {'checked': False, 'reason': 'no days with both a spot and strikes'}
    a = np.array(ratios)
    out = float(((a < SPLIT_BAND[0]) | (a > SPLIT_BAND[1])).mean() * 100)
    return {
        'checked': True,
        'median_strike_over_spot': round(float(np.median(a)), 2),
        'p05': round(float(np.percentile(a, 5)), 2),
        'p95': round(float(np.percentile(a, 95)), 2),
        'pct_days_out_of_band': round(out, 1),
        'band': list(SPLIT_BAND),
        'contaminated': out > SPLIT_MAX_OUT_OF_BAND_PCT,
    }


def counting_policy(counter, approach_counter):
    """cc_sim's baseline policy, wrapped to record which ladder rung fired.

    `level` is too coarse to audit reachability — five CLOSE_NOW clauses share
    one level — so this reads `alert.clause`, the machine-readable id added to
    PositionAlert for exactly this purpose. A clause that never fires across
    thousands of observations is presumed unwired, not unlucky
    (tasks/lessons.md 2026-08-16); the health page shows the same table live,
    and this is its backtest baseline.
    """
    from position_monitor import assess_position as _assess
    from datetime import timedelta as _td

    def policy(ctx):
        alert = _assess(
            ticker=ctx.ticker, strike=ctx.strike, expiry=ctx.expiration,
            sold_price=ctx.sold_price, contracts=1, current_stock=ctx.spot,
            current_option_ask=ctx.option_price,
            ex_div_date=(ctx.date + _td(days=ctx.days_to_exdiv)
                         if ctx.days_to_exdiv is not None else None),
            earnings_date=None, as_of=ctx.date)
        counter[alert.clause] = counter.get(alert.clause, 0) + 1
        # How often the early-assignment branch was even approachable. A zero
        # assignment count from a state that was never reached is "non-binding",
        # not "constraint met" (Exp 015's tautological result).
        if cc_core.assignment_is_approaching(ctx):
            approach_counter[0] += 1
        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            return cc_sim.CLOSE_NOW, alert.level
        if alert.level == 'CLOSE_SOON':
            return cc_sim.CLOSE_SOON, alert.level
        return cc_sim.HOLD, alert.level
    return policy


def hold_to_expiry_policy(ctx):
    """Arm B's policy: the copilot never acts. Expiry settlement and rational
    early exercise still apply — they are market mechanics, not copilot rules,
    and cc_core enforces that separation."""
    return cc_sim.HOLD, 'HOLD_TO_EXPIRY'


def tp_only_policy(counter=None):
    """Arm D's policy: act ONLY on the take-profit rung and on EMERGENCY.

    Reads `alert.clause`, not `alert.level` — five different CLOSE_NOW clauses
    share one level, and arm D must ignore four of them. This is precisely why
    the ladder needed a machine-readable id.
    """
    from position_monitor import assess_position as _assess
    from datetime import timedelta as _td

    def policy(ctx):
        alert = _assess(
            ticker=ctx.ticker, strike=ctx.strike, expiry=ctx.expiration,
            sold_price=ctx.sold_price, contracts=1, current_stock=ctx.spot,
            current_option_ask=ctx.option_price,
            ex_div_date=(ctx.date + _td(days=ctx.days_to_exdiv)
                         if ctx.days_to_exdiv is not None else None),
            earnings_date=None, as_of=ctx.date)
        if alert.clause not in ARM_D_CLAUSES:
            return cc_sim.HOLD, f'IGNORED:{alert.clause}'
        if alert.level in ('CLOSE_NOW', 'EMERGENCY'):
            return cc_sim.CLOSE_NOW, alert.level
        if alert.level == 'CLOSE_SOON':
            return cc_sim.CLOSE_SOON, alert.level
        return cc_sim.HOLD, alert.level
    return policy


def paired_reference(chain, cfg, threshold, ticker, window_name):
    """Reference distributions for the two paired questions, A-B and A-C.

    Arm A and arm B live the identical market path, so the per-entry difference
    cancels regime noise — which is why the copilot-cost and IV-gate answers
    reach usefulness several times faster than the absolute "does it make
    money" answer. This function measures how much faster, in cycles, instead
    of asserting it.
    """
    gate = cc_sim.iv_rank_gate(threshold)
    a, _ = cc_sim.run(chain, cfg, cc_sim.baseline_policy, gate=gate,
                      progress_every=0, label=f'{ticker}/{window_name}/A')
    b, _ = cc_sim.run(chain, cfg, hold_to_expiry_policy, gate=gate,
                      progress_every=0, label=f'{ticker}/{window_name}/B')
    c, _ = cc_sim.run(chain, cfg, cc_sim.baseline_policy, gate=cc_sim.no_gate(),
                      progress_every=0, label=f'{ticker}/{window_name}/C')
    dd, _ = cc_sim.run(chain, cfg, tp_only_policy(), gate=gate,
                       progress_every=0, label=f'{ticker}/{window_name}/D')

    def power(a_trades, other_trades, label):
        """Cycles needed for a 90% CI on the paired mean to exclude zero.

        n >= (z * sd / |mean|)^2 with z = 1.645 (two-sided 90%). This is a
        normal-approximation power sketch on autocorrelated overlapping
        cohorts, so it is an ORDER OF MAGNITUDE, not a promise — it is
        reported as such and the registered floor is set above it.
        """
        pd_ = cc_sim.paired_difference(a_trades, other_trades)
        if pd_.get('n_paired', 0) < 2:
            return {'label': label, 'n_paired': pd_.get('n_paired', 0),
                    'derivable': False}
        shared = sorted(set(t.entry_date for t in a_trades)
                        & set(t.entry_date for t in other_trades))
        amap = {t.entry_date: t for t in a_trades}
        omap = {t.entry_date: t for t in other_trades}
        deltas = np.array([(amap[d].pnl_per_share - omap[d].pnl_per_share) * 100
                           for d in shared])
        mean, sd = float(deltas.mean()), float(deltas.std(ddof=1))
        n_needed = (1.645 * sd / abs(mean)) ** 2 if mean else None
        return {
            'label': label,
            'n_paired_cohorts': len(deltas),
            'mean_delta_usd_per_contract': round(mean, 2),
            'sd_delta': round(sd, 2),
            'a_better_count': int((deltas > 0).sum()),
            'a_worse_count': int((deltas < 0).sum()),
            'cycles_for_90pct_ci_to_exclude_zero': (
                round(n_needed, 1) if n_needed is not None else None),
            'derivable': True,
            # Raw per-entry deltas, so derive_thresholds.py can POOL across
            # tickers instead of averaging per-ticker sample-size requirements.
            # Averaging required-n is dominated by whichever ticker's mean sits
            # nearest zero, which is a statistic about that ticker, not about
            # the pooled question the verdict rule actually asks.
            'deltas': [round(float(x), 4) for x in deltas],
            'caveat': ('normal approximation on overlapping, autocorrelated '
                       'cohorts — an order of magnitude, not a promise'),
        }

    # The IV gate is NOT a paired comparison. On the days both arms enter, the
    # trades are identical — same contract, same policy — so a paired delta is
    # exactly zero and measures nothing. The gate's entire effect is the set of
    # entries it BLOCKS. Exp 023 measured it this way and found the gate blocks
    # 109 TMUS entries averaging +$48, i.e. it keeps the losers. Same method here.
    a_dates = {t.entry_date for t in a}
    blocked = [t for t in c if t.entry_date not in a_dates]
    blocked_pnl = np.array([t.pnl_per_share * 100 for t in blocked]) if blocked else np.array([])
    gate_effect = {
        'method': ('the gate blocks entries; its value is the P&L of the blocked '
                   'set, not a paired delta on shared entries (which is 0 by '
                   'construction)'),
        'entries_arm_A': len(a),
        'entries_arm_C': len(c),
        'entries_blocked_by_gate': len(blocked),
    }
    if blocked_pnl.size:
        mean, sd = float(blocked_pnl.mean()), float(blocked_pnl.std(ddof=1)) if blocked_pnl.size > 1 else 0.0
        gate_effect.update({
            'blocked_mean_pnl_usd_per_contract': round(mean, 2),
            'blocked_sd': round(sd, 2),
            'blocked_win_count': int((blocked_pnl > 0).sum()),
            'blocked_loss_count': int((blocked_pnl < 0).sum()),
            # A gate that blocks profitable entries is costing money.
            'gate_is_costing_money': mean > 0,
            'cycles_for_90pct_ci_to_exclude_zero': (
                round((1.645 * sd / abs(mean)) ** 2, 1) if mean and sd else None),
            'blocked_pnls': [round(float(x), 4) for x in blocked_pnl],
        })
    else:
        gate_effect['blocked_mean_pnl_usd_per_contract'] = None
        gate_effect['note'] = 'the gate blocked nothing in this window'

    return {
        'A_minus_B_copilot_value': power(a, b, 'A-B (copilot value)'),
        # A-D isolates how much of A's exit cost is defensive (distance, gamma,
        # ex-div, earnings clauses) rather than profit-taking. D keeps TP-75 and
        # EMERGENCY; the difference is everything else the ladder does.
        'A_minus_D_defensive_exits': power(a, dd, 'A-D (defensive exit cost)'),
        'iv_gate_effect': gate_effect,
        # Arm B's option-leg edge is not free: holding to expiry is how the
        # stock gets called away. Option-leg P&L excludes the tax event that is
        # the entire reason the copilot exists, so B's assignment count must be
        # read next to B's P&L, never without it.
        'arm_B_score': summarise(b, 'arm_B_all_fills'),
        'arm_C_score': summarise(c, 'arm_C_all_fills'),
        'arm_A_score': summarise(a, 'arm_A_all_fills'),
        'arm_D_score': summarise(dd, 'arm_D_all_fills'),
    }


def dist(values):
    if not values:
        return None
    a = np.array(values, dtype=float)
    return {'n': int(a.size), 'mean': round(float(a.mean()), 1),
            'median': round(float(np.median(a)), 1),
            'p10': round(float(np.percentile(a, 10)), 1),
            'p90': round(float(np.percentile(a, 90)), 1),
            'min': round(float(a.min()), 1), 'max': round(float(a.max()), 1)}


def worst_rolling_drawdown(trades, window_days=30):
    """Worst peak-to-trough of realised option-leg P&L inside any `window_days`.

    Computed on ONE sequential chain — a real account holds one call at a time,
    so overlapping cohorts would overstate both the peak and the trough. Units
    are dollars per contract, option leg only.
    """
    if not trades:
        return None
    pts = sorted(((pd.Timestamp(t.exit_date), t.pnl_per_share * 100) for t in trades),
                 key=lambda x: x[0])
    dates = [p[0] for p in pts]
    cum, running = [], 0.0
    for _, p in pts:
        running += p
        cum.append(running)

    worst, worst_at = 0.0, None
    for i, d in enumerate(dates):
        lo = d - pd.Timedelta(days=window_days)
        # Peak of the curve inside the trailing window, including the level it
        # entered the window at (index i's own start).
        prior = [cum[j] for j in range(i + 1) if dates[j] >= lo]
        start_level = cum[i - len(prior)] if len(prior) <= i else 0.0
        peak = max(prior + [start_level])
        dd = peak - cum[i]
        if dd > worst:
            worst, worst_at = dd, str(d)[:10]
    return {'worst_drawdown_usd_per_contract': round(worst, 2),
            'trough_date': worst_at, 'n_cycles': len(trades)}


def cycles_per_year(chain_trades, option_days):
    """Completed cycles per 365 calendar days on a sequential chain."""
    if not chain_trades or len(option_days) < 2:
        return None
    span = (option_days[-1] - option_days[0]).days
    if span <= 0:
        return None
    return round(len(chain_trades) * 365.0 / span, 2)


def summarise(trades, label):
    """Score a trade list the way cc_sim does, plus the ratio's two halves."""
    s = cc_sim.score(trades)
    gross = s['gross_premium']
    net = s['net_pnl']
    return {
        'label': label,
        'n_cycles': s['n_trades'],
        'premium_collected_usd': gross,           # retention denominator
        'premium_kept_usd': net,                  # retention numerator
        # A ratio whose numerator can go negative is not a percentage of
        # anything intuitive (tasks/lessons.md 2026-08-16). Both halves are
        # always reported beside it, and a negative numerator is flagged.
        'retention_pct': s['retention_pct'],
        'retention_numerator_negative': net < 0,
        'pnl_per_cycle_usd': round(net / s['n_trades'], 2) if s['n_trades'] else None,
        'win_rate_pct': s['win_rate'],
        'loss_rate_pct': s['loss_rate'],
        'worst_cycle_usd': s['worst_trade'],
        'assignments': s['assignments'],
        'early_assignments': s['early_assignments'],
        'expiry_assignments': s['expiry_assignments'],
        'avg_days_held': s['avg_days_held'],
    }


def run_ticker_window(ticker, window_name, window, stock_period):
    out = {'ticker': ticker, 'window': window_name, 'window_dates': list(window),
           'stock_period': stock_period}
    try:
        chain = cc_sim.load_ticker(ticker, *window, verbose=False,
                                   stock_period=stock_period)
    except Exception as e:
        out['status'] = 'no_data'
        out['detail'] = str(e)[:300]
        return out

    if not chain.option_days:
        out['status'] = 'no_data'
        out['detail'] = 'no option days in window'
        return out

    # Refuse to produce numbers from a chain whose strikes and closes are on
    # opposite sides of a split. Reported loudly, never silently dropped.
    split = split_contamination(chain)
    out['split_check'] = split
    if split.get('contaminated'):
        out['status'] = 'split_contaminated'
        out['detail'] = (
            f"strike/spot ratio median {split['median_strike_over_spot']} with "
            f"{split['pct_days_out_of_band']}% of days outside {SPLIT_BAND} — "
            f"Databento strikes are as-traded, proxy closes are split-adjusted. "
            f"No threshold may be derived from this window.")
        return out

    cfg = production_cfg(ticker)
    threshold = ticker_strategies.get_iv_threshold(ticker)
    gate = cc_sim.iv_rank_gate(threshold)
    clause_fires, approaches = {}, [0]
    trades, diag = cc_sim.run(chain, cfg,
                              counting_policy(clause_fires, approaches),
                              gate=gate, progress_every=0,
                              label=f'{ticker}/{window_name}')

    if not trades:
        out['status'] = 'no_trades'
        out['diagnostics'] = diag
        out['cfg'] = cfg
        out['iv_threshold'] = threshold
        return out

    real = [t for t in trades if exit_is_real_fill(chain, t)]

    out.update({
        'status': 'ok',
        'cfg': cfg,
        'iv_threshold': threshold,
        'data_window': [str(chain.option_days[0])[:10], str(chain.option_days[-1])[:10]],
        'diagnostics': diag,
        'real_fill_coverage_pct': round(len(real) / len(trades) * 100, 1),
        'all_fills': summarise(trades, 'all_fills'),
        'real_fills': summarise(real, 'real_fills'),
        'hold_time_days_all': dist([t.days_held for t in trades]),
        'hold_time_days_real': dist([t.days_held for t in real]),
        # Per-cycle option-leg P&L, real-fill subset. The sample H40's power
        # sketch is computed from — without it, H40's floor would be the only
        # floor in the pre-registration not backed by a variance estimate.
        'per_cycle_pnl_real_fills': [round(t.pnl_per_share * 100, 2) for t in real],
        'clause_fires': dict(sorted(clause_fires.items(),
                                    key=lambda kv: -kv[1])),
        'observations': sum(clause_fires.values()),
        'assignment_branch_approaches': approaches[0],
    })

    # EMERGENCY fires per 30 calendar days of elapsed window — the input to the
    # crash-regime kill switch. Counted over cohort-days, then normalised to
    # ONE sequential position, because the engine holds one call at a time and
    # a cohort-day count would overstate by the overlap factor.
    span_days = (chain.option_days[-1] - chain.option_days[0]).days or 1
    emerg = clause_fires.get('emergency_itm_exdiv_3d', 0)
    n_seq = len(P3.sequential_chain(trades, 0)) or 1
    overlap = len(trades) / n_seq
    out['emergency_fires'] = {
        'cohort_day_fires': emerg,
        'overlap_factor': round(overlap, 2),
        'per_30d_one_position': round(emerg / overlap / span_days * 30, 3),
        'window_span_days': span_days,
    }

    out['paired_reference'] = paired_reference(chain, cfg, threshold,
                                               ticker, window_name)

    # Sequential chains: the unit the engine actually lives in.
    chains = [P3.sequential_chain(trades, s) for s in range(N_CHAINS)]
    chains = [c for c in chains if c]
    chains_real = [[t for t in c if exit_is_real_fill(chain, t)] for c in chains]

    cyc = [cycles_per_year(c, chain.option_days) for c in chains]
    cyc = [c for c in cyc if c is not None]
    out['cycles_per_year_sequential'] = dist(cyc)

    dds = [worst_rolling_drawdown(c) for c in chains]
    dds = [d for d in dds if d]
    out['worst_30d_drawdown_all_fills'] = dist(
        [d['worst_drawdown_usd_per_contract'] for d in dds]) if dds else None
    dds_r = [worst_rolling_drawdown(c) for c in chains_real]
    dds_r = [d for d in dds_r if d]
    out['worst_30d_drawdown_real_fills'] = dist(
        [d['worst_drawdown_usd_per_contract'] for d in dds_r]) if dds_r else None

    # Per-cycle win rate on the sequential chains, real-fill subset — the input
    # to the consecutive-loss binomial bound in PREREGISTRATION.md §kill.
    per_chain_wr = [round(sum(1 for t in c if t.pnl_per_share > 0) / len(c) * 100, 1)
                    for c in chains_real if c]
    out['per_cycle_win_rate_real_fills'] = dist(per_chain_wr)
    return out


def main():
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'engine': engine_sha(),
        'engine_file': 'experiments/cc_sim.py (+ cc_core.py decision core)',
        'standard': 'real-fill subset is the result; all-fill reported beside it',
        'universe': UNIVERSE,
        'n_chains': N_CHAINS,
        'results': [],
        'unusable': {},
    }
    for t in UNIVERSE:
        if t in cc_sim.UNUSABLE_TICKERS:
            report['unusable'][t] = cc_sim.UNUSABLE_TICKERS[t]
    total = len(UNIVERSE) * len(WINDOWS)
    i = 0
    for ticker in UNIVERSE:
        for wname, window, stock_period in WINDOWS:
            i += 1
            print(f'[{i}/{total}] {ticker} / {wname} {window} ...', flush=True)
            r = run_ticker_window(ticker, wname, window, stock_period)
            status = r.get('status')
            if status == 'ok':
                rf = r['real_fills']
                print(f"    ok: {rf['n_cycles']} cycles, real-fill "
                      f"${rf['pnl_per_cycle_usd']}/cycle, retention "
                      f"{rf['retention_pct']}% "
                      f"({rf['premium_kept_usd']}/{rf['premium_collected_usd']}), "
                      f"coverage {r['real_fill_coverage_pct']}%", flush=True)
            else:
                print(f'    {status}: {r.get("detail", "")}', flush=True)
            report['results'].append(r)

    with open(OUT, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f'\nwrote {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
