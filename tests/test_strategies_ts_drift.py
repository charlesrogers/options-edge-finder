"""
web/src/lib/strategies.ts must be byte-identical to what ticker_strategies.py generates.

This is the guard for the project's signature defect class: a second copy of a
fact that drifts from the first. strategies.ts was hand-maintained and froze in
March 2026 — four merged PRs corrected the Python while the site kept serving
AAPL at $351/100% (corrected: $141/91%), KKR at 100 contracts (liquidity-capped
at 7), and three probation tickers badged 'Good'.

If this test fails, do NOT hand-edit strategies.ts. Run:
    python3 scripts/gen_strategies_ts.py
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "gen_strategies_ts.py"
COMMITTED = REPO_ROOT / "web" / "src" / "lib" / "strategies.ts"

sys.path.insert(0, str(REPO_ROOT))


def _generate() -> str:
    """Render the file the way the generator would, without touching the tree."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--stdout"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"generator failed:\n{result.stderr}"
    return result.stdout


def test_committed_file_matches_generator():
    """The committed TS is exactly what ticker_strategies.py produces today."""
    assert COMMITTED.exists(), f"{COMMITTED} is missing — run scripts/gen_strategies_ts.py"

    expected = _generate()
    actual = COMMITTED.read_text(encoding="utf-8")

    if actual != expected:
        # Point at the first divergence rather than dumping 200 lines of TS.
        exp_lines, act_lines = expected.splitlines(), actual.splitlines()
        for i, (e, a) in enumerate(zip(exp_lines, act_lines), start=1):
            if e != a:
                pytest.fail(
                    f"strategies.ts has drifted from ticker_strategies.py at line {i}:\n"
                    f"  committed: {a!r}\n"
                    f"  generated: {e!r}\n"
                    "Run: python3 scripts/gen_strategies_ts.py"
                )
        pytest.fail(
            f"strategies.ts has drifted in length "
            f"(committed {len(act_lines)} lines, generated {len(exp_lines)}).\n"
            "Run: python3 scripts/gen_strategies_ts.py"
        )


def test_check_mode_agrees():
    """`--check` is what CI would call; it must agree with the comparison above."""
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"--check reported drift:\n{result.stdout}{result.stderr}"


def test_generated_file_carries_do_not_edit_header():
    """A human opening the file must be told not to edit it."""
    head = COMMITTED.read_text(encoding="utf-8")[:400]
    assert "GENERATED FROM ticker_strategies.py" in head
    assert "DO NOT EDIT" in head


def test_corrected_values_are_the_ones_exported():
    """
    Spot-check the specific numbers the fossil got wrong.

    Byte-equality above already covers this, but it fails opaquely ("line 47
    differs"). These assertions name the defect, so a regression reads as
    "AAPL is publishing $351 again" instead of "the file drifted".
    """
    ts_src = COMMITTED.read_text(encoding="utf-8")

    # The corrected values must be present.
    assert "expectedPnl: 141," in ts_src, "AAPL's corrected P&L is missing"
    assert "expectedWinRate: 91," in ts_src, "AAPL's corrected win rate is missing"
    assert "maxContracts: 7," in ts_src, "KKR's liquidity cap is missing"
    assert "ivThreshold: 75," in ts_src, "DIS's per-ticker IV gate is missing"
    assert '"probation"' in ts_src, "the probation tier is missing"

    # The fossil values must be gone.
    for stale in ("expectedPnl: 351,", "expectedPnl: 822,", "expectedPnl: 447,", "expectedPnl: 386,"):
        assert stale not in ts_src, f"fossil value still exported: {stale}"
    assert "never loses" not in ts_src, "the 'never loses' claim is still exported"
    assert "+204%" not in ts_src, "the invalidated +204% claim is still exported"


def test_every_live_pnl_ships_with_a_spread():
    """
    No point estimate renders alone (spec 2.3).

    Exp 022 measured half-year retention swinging -77.9% -> +92.8% on identical
    rules, so an annual point figure describes a regime, not a rate. The
    generator refuses to emit a live non-zero expected_pnl unless the note also
    carries a chain range or a real-fill-only figure; this asserts that the rule
    is actually in force rather than merely written down.
    """
    import ticker_strategies

    from scripts.gen_strategies_ts import build_rows  # noqa: PLC0415

    rows = build_rows()
    for ticker, row in rows.items():
        if row["skip"] or not row["expectedPnl"]:
            continue
        assert row["pnlRangeLow"] is not None or row["realFillPnl"] is not None, (
            f"{ticker} publishes expected_pnl={row['expectedPnl']} with no spread"
        )

    # And the generator must actively reject a bare point estimate, not just
    # happen to have none today.
    original = ticker_strategies.TICKER_STRATEGIES.get("AAPL", {}).get("note")
    try:
        ticker_strategies.TICKER_STRATEGIES["AAPL"]["note"] = "A number with no spread at all."
        with pytest.raises(SystemExit) as exc:
            build_rows()
        assert "AAPL" in str(exc.value)
    finally:
        ticker_strategies.TICKER_STRATEGIES["AAPL"]["note"] = original


def test_skip_tickers_are_all_exported():
    """
    AMZN and MSFT must reach the web as skips.

    Both were live-recommendable at settings more aggressive than the ones they
    failed (Exp 021 H24(b)): AMZN at 5% OTM, MSFT via the unknown-ticker default.
    MSFT was absent from the hand-written table entirely.
    """
    ts_src = COMMITTED.read_text(encoding="utf-8")
    for ticker in ("AMZN", "MSFT", "TXN"):
        assert f"  {ticker}: {{" in ts_src, f"{ticker} is not exported to the web at all"

    import ticker_strategies

    for ticker in ("AMZN", "MSFT", "TXN"):
        assert ticker_strategies.TICKER_STRATEGIES[ticker].get("skip") is True, (
            f"{ticker} is no longer a skip in the source of truth"
        )
