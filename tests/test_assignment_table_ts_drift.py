"""
web/src/lib/assignment-table.ts must be byte-identical to what position_monitor.py generates.

Same guard as test_strategies_ts_drift.py, for the other table the site copies.
The assignment-probability grid (Exp 006, 145,099 observations) is the evidence
every alert threshold rests on; the how-it-works page renders all 45 cells. A
hand-maintained copy of it would fossilise exactly the way strategies.ts did.

If this test fails, do NOT hand-edit assignment-table.ts. Run:
    python3 scripts/gen_assignment_table_ts.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "gen_assignment_table_ts.py"
COMMITTED = REPO_ROOT / "web" / "src" / "lib" / "assignment-table.ts"

sys.path.insert(0, str(REPO_ROOT))


def _generate() -> str:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"generator failed:\n{result.stderr}"
    return result.stdout


def test_committed_file_matches_generator():
    """The committed TS is exactly what position_monitor.py produces today."""
    assert COMMITTED.exists(), f"{COMMITTED} is missing — run the generator"
    assert COMMITTED.read_text(encoding="utf-8") == _generate(), (
        "assignment-table.ts has drifted from position_monitor.py. "
        "Run: python3 scripts/gen_assignment_table_ts.py"
    )


def test_every_cell_matches_the_alert_engine():
    """Value-level check, independent of formatting.

    The byte test above catches drift but would also pass if BOTH files were
    wrong together. This one reads the numbers back out of the emitted TS and
    compares them to ITM_PROBABILITY itself, so a generator bug that mangles a
    probability cannot ride through green.
    """
    import re

    import position_monitor as pm

    emitted = COMMITTED.read_text(encoding="utf-8")

    # Pull the label -> {dte label: prob} grid back out of the TS source.
    grid_src = emitted.split("export const ASSIGNMENT_PROBABILITY", 1)[1]
    parsed: dict[tuple[str, str], float] = {}
    current_band = None
    for line in grid_src.splitlines():
        band = re.match(r'\s*"([^"]+)":\s*\{\s*$', line)
        if band:
            current_band = band.group(1)
            continue
        cell = re.match(r'\s*"([^"]+)":\s*([\d.]+),\s*$', line)
        if cell and current_band:
            parsed[(current_band, cell.group(1))] = float(cell.group(2))

    assert len(parsed) == len(pm.ITM_PROBABILITY), (
        f"emitted {len(parsed)} cells, engine has {len(pm.ITM_PROBABILITY)}"
    )

    for (m_lo, m_hi, d_lo, d_hi), prob in pm.ITM_PROBABILITY.items():
        from scripts.gen_assignment_table_ts import DTE_LABELS, MONEYNESS_LABELS

        key = (MONEYNESS_LABELS[(m_lo, m_hi)], DTE_LABELS[(d_lo, d_hi)])
        assert key in parsed, f"{key} missing from assignment-table.ts"
        assert parsed[key] == prob, (
            f"{key}: page would render {parsed[key]}, alert engine uses {prob}"
        )
