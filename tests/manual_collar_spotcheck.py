"""
Independent recompute of published collar_menu rows. NOT collected by pytest
(it needs the network and a live chain); run it by hand.

    python3 tests/manual_collar_spotcheck.py results/collar_menu.json

It re-fetches the raw chain from the proxy and recomputes net cost, effective
basis, max loss, max gain, R:R and both leg IVs with a completely separate
implementation — its own Black-Scholes-Merton, its own bisection solver, its own
HTTP call. It imports nothing from collar_menu, so a shared bug cannot hide in
both. Any mismatch is a real defect.

This is the machine half of the Part D acceptance criterion. The other half —
comparing bid/ask against broker-quoted prices — needs a broker terminal; use
`python3 collar_menu.py --verify <TICKER>` for the contract symbols to type in,
and run it during regular trading hours (outside RTH Yahoo returns bid=ask=0).
"""

import json
import math
import sys
import urllib.request

BASE = "https://yfinance-proxy.charlesrogers.workers.dev"
RATE = 0.045          # must match the --rate collar_menu.py was run with
TOL = {"net": 5e-3, "pct": 6e-4, "rr": 6e-3, "iv": 6e-4}


def fetch(ticker, expiration):
    req = urllib.request.Request(
        f"{BASE}/stock/{ticker}/options/{expiration}",
        headers={"User-Agent": "python-requests/2.32"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def price_of(row):
    bid, ask = row.get("bid") or 0, row.get("ask") or 0
    if bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2, "mid"
    return row.get("lastPrice"), "last"


def _n(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bsm(flag, S, K, T, r, sigma, q):
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if flag == "c":
        return S * math.exp(-q * T) * _n(d1) - K * math.exp(-r * T) * _n(d2)
    return K * math.exp(-r * T) * _n(-d2) - S * math.exp(-q * T) * _n(-d1)


def solve_iv(price, flag, S, K, T, r, q):
    lo, hi = 1e-4, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if bsm(flag, S, K, T, r, mid, q) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def check(name, got, published, tol):
    ok = published is None or abs(got - published) <= tol
    flag = "MATCH" if ok else "*** MISMATCH ***"
    pub = "—" if published is None else f"{published:+.4f}"
    print(f"    {name:<10s} recomputed={got:+.4f}  published={pub}  {flag}")
    return ok


def main(path):
    menus = json.load(open(path))
    failures = 0
    for menu in menus:
        if menu.get("error"):
            continue
        q = menu.get("dividend_yield") or 0.0
        for tenor in menu.get("tenors", []):
            if tenor.get("error"):
                continue
            raw = fetch(menu["ticker"], tenor["expiration"])
            S = raw["underlyingPrice"]
            T = tenor["dte"] / 365
            print(f"\n{menu['ticker']} {tenor['expiration']}  S={S}  DTE={tenor['dte']}")
            for row in tenor["rows"]:
                if not row.get("priceable"):
                    continue
                pk, ck = row["put_strike"], row["call_strike"]
                pr = next(x for x in raw["puts"] if x["strike"] == pk)
                cr = next(x for x in raw["calls"] if x["strike"] == ck)
                pp, psrc = price_of(pr)
                cp, csrc = price_of(cr)
                net = pp - cp
                basis = S + net
                ml, mg = (pk - basis) / basis, (ck - basis) / basis
                print(f"  {row['floor_target_pct'] * 100:.0f}% floor  "
                      f"put {pk} @ {pp} ({psrc})  call {ck} @ {cp} ({csrc})")
                results = [
                    check("net/share", net, row["net_per_share"], TOL["net"]),
                    check("basis", basis, row["effective_basis"], TOL["net"]),
                    check("max loss", ml, row["max_loss_pct"], TOL["pct"]),
                    check("max gain", mg, row["max_gain_pct"], TOL["pct"]),
                    check("R:R", mg / abs(ml), row.get("risk_reward"), TOL["rr"]),
                    check("put IV", solve_iv(pp, "p", S, pk, T, RATE, q),
                          row.get("put_iv"), TOL["iv"]),
                    check("call IV", solve_iv(cp, "c", S, ck, T, RATE, q),
                          row.get("call_iv"), TOL["iv"]),
                ]
                failures += results.count(False)
    print(f"\n{'ALL ROWS MATCH' if not failures else f'{failures} MISMATCHES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
