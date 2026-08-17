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
        'tier': 'good',
        'expected_pnl': 447,
        'expected_win_rate': 89,
        'expected_trades': 18,
        'note': 'Exp 014: 15% OTM validated (11% test loss rate, walk-forward). Was 3%.',
    },
    'KKR': {
        'otm_pct': 0.15,
        'min_dte': 20,
        'max_dte': 45,
        'tier': 'good',
        'expected_pnl': 386,
        'expected_win_rate': 100,
        'expected_trades': 18,
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
                'Exp 021: capped at 7 contracts by liquidity.',
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
        'tier': 'untested',
        'expected_pnl': None,
        'expected_win_rate': None,
        'expected_trades': 0,
        'note': 'No option data. Using conservative 5% OTM default.',
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
