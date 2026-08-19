#!/usr/bin/env python3
"""
Generate web/src/lib/assignment-table.ts from position_monitor.py.

The assignment-probability table (Experiment 006, 145,099 real option
observations) is the single piece of evidence the alert ladder rests on, and
the how-it-works page renders all 45 of its cells. Hand-copying 45 numbers into
TypeScript is precisely how strategies.ts froze in March 2026 while four merged
PRs corrected the Python — the project's signature defect class. So this table
is generated too, and tests/test_assignment_table_ts_drift.py fails CI on drift.

The buckets are read out of position_monitor.ITM_PROBABILITY itself, not
restated here, so adding or re-cutting a bucket propagates to the site.

Usage:
    python3 scripts/gen_assignment_table_ts.py            # write the file
    python3 scripts/gen_assignment_table_ts.py --check    # exit 1 if stale
    python3 scripts/gen_assignment_table_ts.py --stdout   # print, write nothing
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import position_monitor as pm  # noqa: E402

OUT_PATH = REPO_ROOT / "web" / "src" / "lib" / "assignment-table.ts"

HEADER = """// GENERATED FROM position_monitor.py — DO NOT EDIT
//
// The empirical assignment-probability table: Experiment 006, 145,099 real
// Databento option observations, P(finish ITM) by moneyness x days-to-expiry.
// Every alert threshold in the copilot is justified by a cell in here, so the
// page that shows it must show the same numbers the alert engine uses.
//
// Change position_monitor.py, then run:
//     python3 scripts/gen_assignment_table_ts.py
// tests/test_assignment_table_ts_drift.py fails CI if this file drifts.
"""

# Presentation labels for the moneyness bands, keyed by the (lo, hi) bounds used
# in position_monitor.ITM_PROBABILITY. Positive = OTM (stock below strike, safe).
MONEYNESS_LABELS = {
    (10, 100): ">10% OTM",
    (5, 10): "5-10% OTM",
    (3, 5): "3-5% OTM",
    (1, 3): "1-3% OTM",
    (0, 1): "0-1% OTM",
    (-1, 0): "0-1% ITM",
    (-3, -1): "1-3% ITM",
    (-5, -3): "3-5% ITM",
    (-100, -5): ">5% ITM",
}

DTE_LABELS = {
    (0, 3): "0-3",
    (3, 7): "3-7",
    (7, 14): "7-14",
    (14, 30): "14-30",
    (30, 60): "30-60",
}


def _ordered(pairs, labels, kind):
    """Distinct bucket bounds in table order, each with its label.

    Ordering is taken from ITM_PROBABILITY's own key order rather than sorted,
    so the emitted table reads top-to-bottom the way the source does (safest
    band first). An unlabelled bucket is a hard error: a silently unlabelled
    row would render as a blank axis on the page.
    """
    seen = []
    for bounds in pairs:
        if bounds not in seen:
            seen.append(bounds)
    missing = [b for b in seen if b not in labels]
    if missing:
        raise SystemExit(
            f"position_monitor.ITM_PROBABILITY has {kind} buckets with no label "
            f"in gen_assignment_table_ts.py: {missing}. Add them before regenerating."
        )
    return [(b, labels[b]) for b in seen]


def render() -> str:
    table = pm.ITM_PROBABILITY

    moneyness = _ordered([(k[0], k[1]) for k in table], MONEYNESS_LABELS, "moneyness")
    dte = _ordered([(k[2], k[3]) for k in table], DTE_LABELS, "DTE")

    out = [HEADER]

    out.append(
        "/** Total real option observations behind the table (Experiment 006). */\n"
        "export const ASSIGNMENT_TABLE_N = 145099\n"
    )

    out.append(
        "export interface MoneynessBand {\n"
        "  /** Lower bound, percent from strike. Positive = OTM. */\n"
        "  low: number\n"
        "  /** Upper bound, exclusive. */\n"
        "  high: number\n"
        "  label: string\n"
        "  /** True when the stock is already through the strike. */\n"
        "  itm: boolean\n"
        "}\n"
    )

    band_lines = ["export const MONEYNESS_BANDS: MoneynessBand[] = ["]
    for (lo, hi), label in moneyness:
        band_lines.append(
            f"  {{ low: {lo}, high: {hi}, label: {label!r}, itm: {'true' if hi <= 0 else 'false'} }},"
        )
    band_lines.append("]")
    out.append("\n".join(band_lines).replace("'", '"') + "\n")

    out.append(
        "export interface DteBucket {\n"
        "  low: number\n"
        "  /** Upper bound, exclusive. */\n"
        "  high: number\n"
        "  label: string\n"
        "}\n"
    )

    dte_lines = ["export const DTE_BUCKETS: DteBucket[] = ["]
    for (lo, hi), label in dte:
        dte_lines.append(f'  {{ low: {lo}, high: {hi}, label: "{label}" }},')
    dte_lines.append("]")
    out.append("\n".join(dte_lines) + "\n")

    out.append(
        "/**\n"
        " * P(finish ITM) indexed [moneyness label][DTE label]. A missing cell means\n"
        " * position_monitor.py has no observation for that combination — render it\n"
        " * blank rather than inventing a zero.\n"
        " */"
    )
    grid_lines = ["export const ASSIGNMENT_PROBABILITY: Record<string, Record<string, number>> = {"]
    for (m_lo, m_hi), m_label in moneyness:
        grid_lines.append(f'  "{m_label}": {{')
        for (d_lo, d_hi), d_label in dte:
            prob = table.get((m_lo, m_hi, d_lo, d_hi))
            if prob is None:
                continue
            grid_lines.append(f'    "{d_label}": {prob},')
        grid_lines.append("  },")
    grid_lines.append("}")
    out.append("\n".join(grid_lines) + "\n")

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
            print(f"STALE: {OUT_PATH} differs from position_monitor.py", file=sys.stderr)
            print("Run: python3 scripts/gen_assignment_table_ts.py", file=sys.stderr)
            return 1
        print(f"OK: {OUT_PATH} matches position_monitor.py")
        return 0

    OUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(pm.ITM_PROBABILITY)} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
