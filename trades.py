"""
Trade journal / position tracker.
Stores trades in a local JSON file for persistence across sessions.
"""

import json
import os
from datetime import datetime

TRADES_FILE = os.path.join(os.path.dirname(__file__), "trades.json")


def _load_all():
    if not os.path.exists(TRADES_FILE):
        return []
    with open(TRADES_FILE, "r") as f:
        return json.load(f)


def _save_all(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2, default=str)


def add_trade(
    ticker: str,
    option_type: str,  # "call" or "put"
    strike: float,
    expiration: str,  # "YYYY-MM-DD"
    premium: float,
    contracts: int,
    strategy: str = "covered_call",  # or "cash_secured_put"
    notes: str = "",
):
    trades = _load_all()
    trade = {
        "id": len(trades) + 1,
        "ticker": ticker.upper(),
        "option_type": option_type,
        "strike": strike,
        "expiration": expiration,
        "premium_received": premium,
        "contracts": contracts,
        "strategy": strategy,
        "notes": notes,
        "opened": datetime.now().isoformat(),
        "status": "open",  # open, closed, expired, assigned
        "closed_at": None,
        "close_price": None,
        "close_reason": None,
        # Snapshot at entry for comparison
        "entry_iv": None,
        "entry_rv": None,
        "entry_vrp": None,
        "entry_delta": None,
    }
    trades.append(trade)
    _save_all(trades)
    return trade


def close_trade(trade_id: int, close_price: float, reason: str = "manual"):
    trades = _load_all()
    for t in trades:
        if t["id"] == trade_id:
            t["status"] = "closed"
            t["closed_at"] = datetime.now().isoformat()
            t["close_price"] = close_price
            t["close_reason"] = reason
            break
    _save_all(trades)


def get_open_trades():
    trades = _load_all()
    return [t for t in trades if t["status"] == "open"]


def get_all_trades():
    return _load_all()


def delete_trade(trade_id: int):
    trades = _load_all()
    trades = [t for t in trades if t["id"] != trade_id]
    _save_all(trades)


def update_trade_entry_snapshot(trade_id: int, iv=None, rv=None, vrp=None, delta=None):
    trades = _load_all()
    for t in trades:
        if t["id"] == trade_id:
            if iv is not None:
                t["entry_iv"] = iv
            if rv is not None:
                t["entry_rv"] = rv
            if vrp is not None:
                t["entry_vrp"] = vrp
            if delta is not None:
                t["entry_delta"] = delta
            break
    _save_all(trades)
