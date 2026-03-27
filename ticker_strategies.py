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
        'note': 'Exp 014: 15% OTM validated (0% test loss rate, walk-forward). Was 3%.',
    },
    'DIS': {
        'otm_pct': 0.07,
        'min_dte': 30,
        'max_dte': 60,
        'tier': 'good',
        'expected_pnl': 822,
        'expected_win_rate': 71,
        'expected_trades': 14,
        'note': 'Needs more OTM buffer — occasional big moves.',
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
        'tier': 'good',
        'expected_pnl': None,
        'expected_win_rate': 94,
        'expected_trades': 18,
        'note': 'Exp 014: 10% OTM validated (6% test loss rate, walk-forward). Was 5% untested.',
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
    'untested':     {'color': '#6b7280', 'bg': '#f3f4f6', 'label': 'Untested',     'icon': '⚪'},
}


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
