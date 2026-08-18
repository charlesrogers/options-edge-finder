#!/usr/bin/env python3
"""
Generate web/src/lib/strategies.ts from ticker_strategies.py.

ticker_strategies.py is the single source of truth for every strategy fact the
site renders. Before this script existed, strategies.ts was a hand-maintained
duplicate that froze in March 2026: four merged PRs corrected the Python and
nothing propagated, so /sell served AAPL at $351/100% (corrected value $141/91%), KKR
at 100 contracts (liquidity-capped at 7) and three probation tickers badged
'Good'. The duplicate is now generated and CI fails on drift
(tests/test_strategies_ts_drift.py).

Usage:
    python3 scripts/gen_strategies_ts.py            # write the file
    python3 scripts/gen_strategies_ts.py --check    # exit 1 if the file is stale
    python3 scripts/gen_strategies_ts.py --stdout   # print, write nothing
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import ticker_strategies as ts  # noqa: E402

OUT_PATH = REPO_ROOT / "web" / "src" / "lib" / "strategies.ts"

HEADER = """// GENERATED FROM ticker_strategies.py — DO NOT EDIT
//
// Hand-editing this file is how /sell came to show March 2026 numbers months
// after the Python was corrected. Change ticker_strategies.py, then run:
//     python3 scripts/gen_strategies_ts.py
// tests/test_strategies_ts_drift.py fails CI if this file drifts from source.
"""

# Spread affordances parsed out of the source-of-truth notes. Exp 022 measured
# half-year retention swinging -77.9% -> +92.8% on identical rules, so a bare
# annual point estimate reports a regime, not a rate; it may never render alone.
CHAIN_RANGE_RE = re.compile(r"chain range (-?\$[\d,]+)\.\.(-?\$[\d,]+)")
REAL_FILL_RE = re.compile(r"(-?\$[\d,]+)/yr on real-fill exits only")
COVERAGE_RE = re.compile(r"(\d+(?:\.\d+)?)% repricing coverage")


def _money(raw: str) -> int:
    """'-$776' -> -776"""
    return int(raw.replace("$", "").replace(",", ""))


def _ts(value) -> str:
    """Render a Python scalar as a TypeScript literal."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def extract_spread(note: str) -> dict:
    """
    Pull the spread facts the note already carries into structured fields.

    Nothing here invents a number: every value is a substring of the note that
    ticker_strategies.py publishes. If the note stops carrying one, the field
    goes null and validate() decides whether that is allowed.
    """
    out = {"pnlRangeLow": None, "pnlRangeHigh": None, "realFillPnl": None, "repricingCoverage": None}
    m = CHAIN_RANGE_RE.search(note)
    if m:
        out["pnlRangeLow"] = _money(m.group(1))
        out["pnlRangeHigh"] = _money(m.group(2))
    m = REAL_FILL_RE.search(note)
    if m:
        out["realFillPnl"] = _money(m.group(1))
    m = COVERAGE_RE.search(note)
    if m:
        out["repricingCoverage"] = float(m.group(1))
    return out


def validate(rows: dict) -> None:
    """
    Enforce the spec's ranges-over-points rule at codegen time, not render time.

    Any live ticker publishing a non-zero expected P&L must also publish a
    spread the UI can show next to it — either the chain range or the
    real-fill-only figure. A future edit that adds a bare point estimate fails
    the build here rather than shipping a lone number to the site.
    """
    offenders = []
    for ticker, r in rows.items():
        if r["skip"] or not r["expectedPnl"]:
            continue
        if r["pnlRangeLow"] is None and r["realFillPnl"] is None:
            offenders.append(ticker)
    if offenders:
        raise SystemExit(
            "ticker_strategies.py publishes an expected_pnl with no spread for: "
            + ", ".join(sorted(offenders))
            + "\nAdd a 'chain range $X..$Y' or '$X/yr on real-fill exits only' clause to the "
            "note, or set expected_pnl to None. A point estimate may not render alone "
            "(web-overhaul-spec.md 2.3)."
        )


def build_rows() -> dict:
    rows = {}
    for ticker, strat in ts.TICKER_STRATEGIES.items():
        note = strat.get("note", "")
        row = {
            "otmPct": strat.get("otm_pct"),
            "minDte": strat.get("min_dte"),
            "maxDte": strat.get("max_dte"),
            "tier": strat.get("tier", "untested"),
            "expectedPnl": strat.get("expected_pnl"),
            "expectedWinRate": strat.get("expected_win_rate"),
            "expectedTrades": strat.get("expected_trades"),
            "note": note,
            "skip": bool(strat.get("skip", False)),
            "ivThreshold": ts.get_iv_threshold(ticker),
            "maxContracts": strat.get("max_contracts"),
            "maxContractsReason": strat.get("max_contracts_reason"),
        }
        row.update(extract_spread(note))
        rows[ticker] = row
    validate(rows)
    return rows


FIELD_ORDER = [
    "otmPct",
    "minDte",
    "maxDte",
    "tier",
    "expectedPnl",
    "expectedWinRate",
    "expectedTrades",
    "skip",
    "ivThreshold",
    "maxContracts",
    "maxContractsReason",
    "pnlRangeLow",
    "pnlRangeHigh",
    "realFillPnl",
    "repricingCoverage",
    "note",
]


def render() -> str:
    rows = build_rows()
    out = [HEADER]
    out.append(
        """
export interface TickerStrategy {
  otmPct: number | null
  minDte: number | null
  maxDte: number | null
  /** Free-form: unknown tiers must render via the TIER_CONFIG fallback, never crash. */
  tier: string
  expectedPnl: number | null
  expectedWinRate: number | null
  expectedTrades: number | null
  skip: boolean
  /** Per-ticker IV-rank entry gate (Exp 023). Falls back to DEFAULT_IV_THRESHOLD. */
  ivThreshold: number
  /** Hard liquidity cap on contracts, independent of shares owned (Exp 021). */
  maxContracts: number | null
  maxContractsReason: string | null
  /** Spread of the annual figure across staggered start dates (Exp 022). */
  pnlRangeLow: number | null
  pnlRangeHigh: number | null
  /** Same configuration counting only exits that were real Databento prints. */
  realFillPnl: number | null
  repricingCoverage: number | null
  note: string
}
"""
    )
    out.append(
        "/**\n"
        " * Global minimum IV rank before calls may be sold (Exp 009, retained).\n"
        " * Exp 023 put the rule on trial per ticker; only DIS earned a different\n"
        " * number. Use ivThreshold on the ticker, not this constant, when rendering.\n"
        " */\n"
        f"export const DEFAULT_IV_THRESHOLD = {ts.DEFAULT_IV_THRESHOLD}\n"
    )

    lines = ["export const TICKER_STRATEGIES: Record<string, TickerStrategy> = {"]
    for ticker, row in rows.items():
        lines.append(f"  {ticker}: {{")
        for field in FIELD_ORDER:
            lines.append(f"    {field}: {_ts(row[field])},")
        lines.append("  },")
    lines.append("}")
    out.append("\n".join(lines) + "\n")

    tier_lines = [
        "export interface TierConfig {",
        "  label: string",
        "  icon: string",
        "  color: string",
        "  bg: string",
        "}",
        "",
        "export const TIER_CONFIG: Record<string, TierConfig> = {",
    ]
    for tier, cfg in ts.TIER_CONFIG.items():
        tier_lines.append(
            f"  {tier}: {{ label: {_ts(cfg['label'])}, icon: {_ts(cfg['icon'])}, "
            f"color: {_ts(cfg['color'])}, bg: {_ts(cfg['bg'])} }},"
        )
    tier_lines.append("}")
    out.append("\n".join(tier_lines) + "\n")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args()

    content = render()

    if args.stdout:
        sys.stdout.write(content)
        return 0

    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != content:
            print(f"STALE: {OUT_PATH} differs from ticker_strategies.py", file=sys.stderr)
            print("Run: python3 scripts/gen_strategies_ts.py", file=sys.stderr)
            return 1
        print(f"OK: {OUT_PATH} matches ticker_strategies.py")
        return 0

    OUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(ts.TICKER_STRATEGIES)} tickers, {len(ts.TIER_CONFIG)} tiers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
