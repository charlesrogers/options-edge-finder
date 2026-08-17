"""
Per-Ticker Covered Call Strategy Config

Optimal parameters from Experiment 008 (75 combos, 5 tickers, real Databento data).
Each ticker has a researched OTM% and DTE range that maximizes the tri-fold goal:
  1. Zero assignments (copilot handles exit)
  2. Positive net P&L (premium > buyback costs)
  3. Maximum premium retained

IV-aware entry from Experiment 009: only sell when iv_rank >= iv_threshold.
This triples average P&L (+204% improvement).
"""

# Minimum IV rank to recommend selling (from Experiment 009)
DEFAULT_IV_THRESHOLD = 50

TICKER_STRATEGIES = {
    'TMUS': {
        'otm_pct': 0.15,
        'min_dte': 20,
        'max_dte': 45,
        # Exp 022 deployment rule 2 (pre-registered, restricting-only): repricing coverage
        # 56.0% is below the 70% floor fixed before the run, so TMUS drops from 'good' to
        # 'probation' — we looked, but with a weaker instrument. Parameters unchanged.
        'tier': 'probation',
        # Exp 022 (H25 FAIL, -66%): re-derived on cc_sim.py, median of 25 staggered chains.
        # Read the real-fill line before trusting the headline: TMUS has 56% repricing
        # coverage, and on exits that were actual Databento prints the same configuration
        # returns -$81/yr. The positive number is substantially made of carried-forward
        # prices.
        'expected_pnl': 151,
        'expected_win_rate': 92,
        'expected_trades': 14,
        'note': 'Exp 014: 15% OTM validated (11% test loss rate, walk-forward). Was 3%. '
                'Exp 022: $151/yr per contract (chain range -$99..$976), but -$81/yr on '
                'real-fill exits only — 56% repricing coverage. Exp 023: the IV rank >= 50 '
                'gate FAILS on TMUS (it blocks 109 entries averaging +$48 and keeps the '
                'losers); the gate is unevidenced here and stays live only because removing '
                'a restriction needs its own experiment.',
    },
    'KKR': {
        'otm_pct': 0.15,
        'min_dte': 20,
        'max_dte': 45,
        # Exp 022 deployment rule 2 (pre-registered, restricting-only): repricing coverage
        # 36.3% is the worst in the set and far below the 70% floor fixed before the run.
        # 'good' claimed evidence KKR does not have. Parameters unchanged.
        'tier': 'probation',
        # Exp 022 (H25 FAIL on win rate, -36.7pp): the deployed 100% win rate was an
        # artefact of the broken clock. Re-derived on cc_sim.py over 753 days, median of 25
        # staggered chains. KKR has 36.3% repricing coverage — the worst of the set — and on
        # real-fill exits only the same configuration returns -$88/yr. 61 of its 388
        # simulated positions never saw a single real quote after entry.
        'expected_pnl': 316,
        'expected_win_rate': 63,
        'expected_trades': 17,
        # Exp 021: at 15% OTM / 20-45 DTE the contract KKR would actually sell trades a
        # MEDIAN of 3 contracts a day (mean 36.7, p25 1, p75 10) across 753 days of
        # Databento volume. Capping at 20% of average daily volume — the spec's arbitrary
        # starting share — allows 7 contracts. On the median basis it allows zero. At
        # 10,000 shares the un-capped position would be 100 contracts, i.e. 33x the median
        # daily volume of that strike: the position IS the market. Liquidity, not
        # validation, is KKR's binding constraint.
        'max_contracts': 7,
        'max_contracts_reason': (
            'Liquidity cap (Exp 021): 20% of mean daily volume in the 15% OTM / 20-45 DTE '
            'strike, which trades a median of 3 contracts a day.'
        ),
        'note': 'Exp 014: 15% OTM validated (0% test loss rate, walk-forward). Was 3%. '
                'Exp 021: capped at 7 contracts by liquidity. Exp 022: $316/yr per '
                'contract and a 63% win rate (was $386/100%), but -$88/yr on real-fill '
                'exits only — 36% repricing coverage.',
    },
    'DIS': {
        'otm_pct': 0.07,
        'min_dte': 30,
        'max_dte': 60,
        'tier': 'good',
        # Exp 022 (H25 FAIL): the deployed $822 came from the simulator that pinned DTE to
        # 0. Re-derived on cc_sim.py at production settings with the production IV gate:
        # median of 25 staggered sequential chains. Restricted to trades whose exit was a
        # real Databento print (77% of them) it is $204/yr.
        'expected_pnl': 267,
        'expected_win_rate': 80,
        'expected_trades': 11,
        'note': 'Needs more OTM buffer — occasional big moves. Exp 022: $267/yr per '
                'contract (chain range $51..$590 depending on start date), 80% win rate, '
                'was $822/71% on the broken-clock simulator. Half-year retention swings '
                'from -77.9% to +92.8% — the annual figure is a regime, not a rate.',
    },
    'AAPL': {
        'otm_pct': 0.15,
        'min_dte': 20,
        'max_dte': 45,
        'tier': 'conservative',
        'expected_pnl': 351,
        'expected_win_rate': 100,
        'expected_trades': 14,
        'note': '100% win rate at 15% OTM. Tiny premium but never loses.',
    },
    'TXN': {
        'otm_pct': None,
        'min_dte': None,
        'max_dte': None,
        'tier': 'skip',
        'skip': True,
        'expected_pnl': 0,
        'expected_win_rate': 0,
        'expected_trades': 14,
        'note': 'Too volatile. Loses money at every OTM% except 10%.',
    },
    'GOOGL': {
        'otm_pct': 0.10,
        'min_dte': 20,
        'max_dte': 45,
        # Exp 021 clause (a): GOOGL's 10% OTM setting was validated on STOCK CLOSES only
        # (Exp 014). We own 5 trading days of GOOGL option data, so it has never been
        # tested on real option prices like AAPL/DIS/TMUS/KKR were. Displaying it as
        # 'good' claimed evidence it does not have. Parameters unchanged — only the badge.
        'tier': 'probation',
        'expected_pnl': None,
        'expected_win_rate': 94,
        'expected_trades': 18,
        'note': 'Exp 014: 10% OTM validated on stock closes (6% test loss rate, '
                'walk-forward). Exp 021: still no real option data (5 days owned) — '
                'probation until the chain capture accrues a year, review ~2027-02.',
    },
    'AMZN': {
        'otm_pct': 0.05,
        'min_dte': 20,
        'max_dte': 45,
        # Spec directive 8 (2026-08-17). AMZN was live-recommendable at 5% OTM with tier
        # 'untested' and no `skip`, so get_recommended_tickers() returned it. Exp 021's
        # H24(b) then FAILED it at the far more conservative 15% OTM — a 22.9% test loss
        # rate against a 10% gate — while MSFT failed the same test at 20.0%.
        # Pre-registration discipline forbids PROMOTING on a failed test; it does not
        # forbid RESTRICTING a live recommendation on adverse evidence. 5% OTM is more
        # aggressive than the setting that failed, on a ticker with zero option data.
        'tier': 'skip',
        'skip': True,
        'expected_pnl': None,
        'expected_win_rate': None,
        'expected_trades': 0,
        'note': 'No option data was ever purchased. Exp 021 failed AMZN at 15% OTM '
                '(22.9% test loss rate vs a 10% gate) and it was live at a more '
                'aggressive 5% — skip pending revalidation on real option prices.',
    },
    'MSFT': {
        # Same directive, same evidence: MSFT failed Exp 021's H24(b) at 15% OTM with a
        # 20.0% test loss rate. It was never in TICKER_STRATEGIES, so get_strategy()
        # handed it the unknown-ticker default of 5% OTM / tier 'untested' — a more
        # aggressive setting than the one it failed at, presented with no warning.
        'otm_pct': 0.15,
        'min_dte': 20,
        'max_dte': 45,
        'tier': 'skip',
        'skip': True,
        'expected_pnl': None,
        'expected_win_rate': None,
        'expected_trades': 0,
        'note': 'No option data was ever purchased. Exp 021 failed MSFT at 15% OTM '
                '(20.0% test loss rate vs a 10% gate) — skip pending revalidation on '
                'real option prices.',
    },
}

# Tier display config
TIER_CONFIG = {
    'best':         {'color': '#065f46', 'bg': '#d1fae5', 'label': 'Best',         'icon': '🟢'},
    'strong':       {'color': '#1e40af', 'bg': '#dbeafe', 'label': 'Strong',       'icon': '🔵'},
    'good':         {'color': '#7c3aed', 'bg': '#ede9fe', 'label': 'Good',         'icon': '🟣'},
    'conservative': {'color': '#92400e', 'bg': '#fef3c7', 'label': 'Conservative', 'icon': '🟡'},
    'skip':         {'color': '#991b1b', 'bg': '#fee2e2', 'label': 'Skip',         'icon': '🔴'},
    # 'probation' is deliberately NOT 'untested': untested means nobody looked, probation
    # means we looked with a weaker instrument (stock closes, no real option prices).
    'probation':    {'color': '#92400e', 'bg': '#fef3c7', 'label': 'Probation',    'icon': '🟠'},
    'untested':     {'color': '#6b7280', 'bg': '#f3f4f6', 'label': 'Untested',     'icon': '⚪'},
}


def get_max_contracts(ticker, shares_owned):
    """
    Contracts sellable on `shares_owned`, capped by option liquidity where we measured it.

    Owning 10,000 shares does not mean 100 contracts can be sold: KKR's 15%-OTM strike
    trades a median of 3 contracts a day (Exp 021). Selling into that moves the price
    against you, and no amount of strategy validation fixes it.

    Returns (contracts, cap_reason_or_None).
    """
    contracts = shares_owned // 100 if shares_owned >= 100 else 0
    cap = TICKER_STRATEGIES.get(ticker, {}).get('max_contracts')
    if cap is not None and contracts > cap:
        return cap, TICKER_STRATEGIES[ticker].get('max_contracts_reason', 'Liquidity cap')
    return contracts, None


def get_strategy(ticker):
    """Get the optimal strategy for a ticker. Returns default for unknown tickers."""
    return TICKER_STRATEGIES.get(ticker, {
        'otm_pct': 0.05,
        'min_dte': 20,
        'max_dte': 45,
        'tier': 'untested',
        'expected_pnl': None,
        'expected_win_rate': None,
        'expected_trades': 0,
        'note': 'Not in research set. Using conservative 5% OTM default.',
    })


def get_recommended_tickers():
    """Return tickers sorted by expected P&L, excluding skips."""
    recs = []
    for ticker, strat in TICKER_STRATEGIES.items():
        if strat.get('skip'):
            continue
        pnl = strat.get('expected_pnl') or 0
        recs.append((ticker, strat, pnl))
    return sorted(recs, key=lambda x: -x[2])
