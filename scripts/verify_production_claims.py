#!/usr/bin/env python3
"""
Assert that production renders the corrected world and no longer renders the fossil.

This is the acceptance test from tasks/web-overhaul-spec.md §7. It exists because
the failure it guards against is specifically "the deploy went green and the page
still served March's numbers" — a green build is not evidence about what a
browser receives.

/sell is client-rendered, so the strategy values arrive in a JS chunk rather than
in the server HTML. This fetches the page, follows every chunk it references, and
searches the combined payload. Checking only the SSR HTML would pass vacuously.

Usage:
    python3 scripts/verify_production_claims.py
    python3 scripts/verify_production_claims.py --base https://options.imprevista.com
"""

import argparse
import json
import re
import sys
import urllib.request

DEFAULT_BASE = "https://options.imprevista.com"
CHUNK_RE = re.compile(r'/_next/static/chunks/[A-Za-z0-9~_.\-]+\.js')

# Anchored on field names, not bare numbers: minified bundles are full of
# incidental digits, and "351" appears in chunk hashes and unrelated constants.
# `\s*` tolerates whether the minifier kept the space after the colon.
#
# (regex, why it must be there)
REQUIRED = [
    (r'expectedPnl:\s*141\b', "AAPL's corrected expected P&L ($141)"),
    (r'expectedWinRate:\s*91\b', "AAPL's corrected win rate (91%)"),
    (r'expectedPnl:\s*267\b', "DIS's corrected expected P&L ($267)"),
    (r'expectedPnl:\s*151\b', "TMUS's corrected expected P&L ($151)"),
    (r'expectedPnl:\s*316\b', "KKR's corrected expected P&L ($316)"),
    (r'expectedWinRate:\s*63\b', "KKR's corrected win rate (63%)"),
    (r'maxContracts:\s*7\b', "KKR's 7-contract liquidity cap"),
    (r'ivThreshold:\s*75\b', "DIS's per-ticker IV gate (>= 75)"),
    (r'"probation"|\'probation\'', "the probation tier reaches the browser"),
    (r'Probation', "the probation badge label"),
    (r'MSFT', "MSFT is present at all (it was absent from the table entirely)"),
    (r'AMZN', "AMZN is present"),
    (r'skip:\s*!0|skip:\s*true', "the skip flag the Not-Recommended partition reads"),
    (r'Liquidity cap', "KKR's cap reason is renderable on the card"),
    (r'pnlRangeLow', "the range field that stops a point estimate rendering alone"),
    (r'realFillPnl', "the real-fill figure shown against the headline"),
    (r'Expected P&L / yr per contract', "the P&L unit label — a bare dollar figure reads as the at-size total, a 100x misread"),
    (r'\(liquidity-capped\)', "the at-size line's cap marker (KKR: 7 x \$316, not 100 x)"),
    (r'real-fill basis', "the at-size real-fill figure where Exp 022 measured one"),
    (r'ended profitable', "win definition: wins include early profitable buybacks, not just expiry"),
]

# (regex, why it must be gone)
FORBIDDEN = [
    (r'of simulated trades expired worthless|trades where the option expired worthless', "misdescribes cc_sim wins — Exp 022 ran the copilot policy, wins include early buybacks. (Paper-trade pages legitimately say 'expired worthless': that scorer IS hold-to-expiry.)"),
    (r'expectedPnl:\s*351\b', "AAPL's fossil P&L ($351)"),
    (r'expectedPnl:\s*822\b', "DIS's fossil P&L ($822)"),
    (r'expectedPnl:\s*447\b', "TMUS's fossil P&L ($447)"),
    (r'expectedPnl:\s*386\b', "KKR's fossil P&L ($386)"),
    (r'expectedWinRate:\s*100\b', "the 100% win-rate claim"),
    (r'\+204%', "the invalidated Exp 009 headline"),
    (r'204% P&L', "the invalidated Exp 009 headline"),
    (r'never loses', "AAPL's 'never loses' note"),
    (r'Experiment 009', "the Exp 009 attribution on the IV caption"),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "claims-verifier"})
    with urllib.request.urlopen(req, timeout=60) as fh:
        return fh.read().decode("utf-8", errors="replace")


def gather(base: str, path: str) -> str:
    """Page HTML plus every JS chunk it pulls — what the browser actually gets."""
    html = fetch(base + path)
    payload = [html]
    for chunk in sorted(set(CHUNK_RE.findall(html))):
        try:
            payload.append(fetch(base + chunk))
        except Exception as exc:
            print(f"  ! could not fetch {chunk}: {exc}", file=sys.stderr)
    return "\n".join(payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    args = ap.parse_args()

    print(f"Fetching {args.base}/sell and its chunks...")
    blob = gather(args.base, "/sell")
    print(f"  {len(blob):,} bytes of HTML + JS\n")

    failures = []

    print("REQUIRED — the corrected values must be present:")
    for pattern, why in REQUIRED:
        ok = re.search(pattern, blob) is not None
        print(f"  [{'OK ' if ok else 'MISS'}] {pattern:34} {why}")
        if not ok:
            failures.append(f"missing /{pattern}/ ({why})")

    print("\nFORBIDDEN — the fossil values must be gone:")
    for pattern, why in FORBIDDEN:
        hit = re.search(pattern, blob)
        print(f"  [{'OK ' if not hit else 'FAIL'}] {pattern:34} {why}")
        if hit:
            failures.append(f"still serving /{pattern}/ ({why})")

    print("\nSCORECARD — provenance split must be published:")
    try:
        api = json.loads(fetch(args.base + "/api/paper-trades"))
        prov = api.get("provenance")
        if not prov:
            failures.append("/api/paper-trades has no provenance split")
            print("  [FAIL] provenance absent — the scorecard would render 'audit pending'")
        else:
            live = prov["live"]
            syn = prov["synthetic"]
            print(f"  [OK ] synthetic: {syn['scored']} scored   live: {live['scored']} scored "
                  f"of {live['total']} logged")
            print(f"  [OK ] first live outcome due: {prov.get('first_live_outcome_due')}")
            if live["scored"] == 0 and api.get("win_rate"):
                print("  [OK ] blended win rate still returned for compatibility, but the "
                      "scorecard renders the live split")
    except Exception as exc:
        failures.append(f"/api/paper-trades unreadable: {exc}")
        print(f"  [FAIL] {exc}")

    print()
    if failures:
        print(f"FAILED — {len(failures)} problem(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS — production renders the corrected values and none of the fossil ones.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
