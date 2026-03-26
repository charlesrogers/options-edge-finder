"""
Paper Trade Scorer — Score recommendations 30+ days after logging.

For each unscored paper trade older than 30 days:
1. Check if the option expired (past expiration date)
2. If expired: P&L = premium collected (100% profit)
3. If still open: fetch current option price, P&L = premium - current price
4. Record outcome
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import yf_proxy
from db import get_unscored_paper_trades, score_paper_trade


def main():
    print("=" * 60)
    print(f"Paper Trade Scorer — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    trades = get_unscored_paper_trades(min_age_days=30)
    print(f"Found {len(trades)} unscored paper trades (30+ days old)")

    if not trades:
        print("Nothing to score.")
        return

    scored = 0
    for trade in trades:
        ticker = trade["ticker"]
        strike = trade["strike"]
        premium = trade["premium_at_rec"]
        expiration = trade.get("expiration", "")

        print(f"  {ticker} ${strike:.0f} Call (rec {trade['recommended_at']})...", end=" ", flush=True)

        try:
            # Check if expired
            exp_date = datetime.strptime(expiration, "%Y-%m-%d")
            now = datetime.now()

            if now > exp_date:
                # Expired — check if it expired ITM or OTM
                hist = yf_proxy.get_stock_history(ticker, period="5d")
                if not hist.empty:
                    final_price = float(hist["Close"].iloc[-1])
                    expired_itm = final_price > strike

                    if expired_itm:
                        # Would have been assigned — copilot should have closed earlier
                        # For scoring: P&L = premium - (final_price - strike)
                        intrinsic = final_price - strike
                        pnl_pct = ((premium - intrinsic) / premium) * 100
                        expired_worthless = False
                    else:
                        # Expired OTM — full premium kept
                        pnl_pct = 100.0
                        expired_worthless = True

                    score_paper_trade(
                        trade_id=trade["id"],
                        outcome_price=0 if expired_worthless else intrinsic,
                        expired_worthless=expired_worthless,
                        pnl_pct=round(pnl_pct, 2),
                        clv=round(premium * (pnl_pct / 100), 4),
                    )
                    status = "expired OTM (100% profit)" if expired_worthless else f"expired ITM (P&L: {pnl_pct:+.0f}%)"
                    print(status)
                    scored += 1
                else:
                    print("no price data for scoring")
            else:
                # Not expired yet — fetch current option price
                chain = yf_proxy.get_option_chain(ticker, expiration)
                if chain and hasattr(chain, 'calls') and not chain.calls.empty:
                    match = chain.calls[chain.calls["strike"] == strike]
                    if not match.empty:
                        bid = match.iloc[0].get("bid", 0) or 0
                        ask = match.iloc[0].get("ask", 0) or 0
                        current_price = (bid + ask) / 2 if bid > 0 else float(match.iloc[0].get("lastPrice", 0))

                        pnl_pct = ((premium - current_price) / premium) * 100 if premium > 0 else 0

                        score_paper_trade(
                            trade_id=trade["id"],
                            outcome_price=round(current_price, 2),
                            expired_worthless=False,
                            pnl_pct=round(pnl_pct, 2),
                            clv=round(premium - current_price, 4),
                        )
                        print(f"current ${current_price:.2f}, P&L: {pnl_pct:+.0f}%")
                        scored += 1
                    else:
                        print("strike not found in chain")
                else:
                    print("no chain data")

        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nScored {scored} of {len(trades)} paper trades")


if __name__ == "__main__":
    main()
