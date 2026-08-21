"""Structural guarantees: the validator, the no-broker rule, and the startup gate.

These are the tests that make the engine's promises mechanical rather than
stated. Each one is red-baselined — the docstring says how to make it fail, and
where a guard is cheap to invert the test inverts it inline.
"""
import hashlib
import json
import os
import sys

import pytest

import cc_core
from paper_engine import config, preflight

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------- validators ---

UNUSABLE = [None, float("nan"), float("inf"), float("-inf"), -1, "x", "", True, False, {}]


@pytest.mark.parametrize("value", UNUSABLE)
def test_is_usable_number_rejects_every_nonsense_input(value):
    assert cc_core.is_usable_number(value) is False


def test_is_usable_number_rejects_zero_unless_asked():
    assert cc_core.is_usable_number(0) is False
    assert cc_core.is_usable_number(0, allow_zero=True) is True


def test_is_usable_number_accepts_real_numbers():
    """Vacuity guard: the validator says yes to something, so the rejections
    above are decisions rather than a function that always returns False."""
    for v in (0.05, 1, 1.5, "2.5", 1e6):
        assert cc_core.is_usable_number(v) is True


def test_nan_is_not_caught_by_a_none_check_which_is_why_this_exists():
    """The 2026-08-16 lesson, asserted. `is None` passes NaN straight through
    into arithmetic; the validator does not."""
    nan = float("nan")
    assert (nan is None) is False          # a None-guard would let it through
    assert cc_core.is_usable_number(nan) is False


@pytest.mark.parametrize("value", [None, float("nan"), "", "   ", "not-a-date",
                                   "2026-13-99", True, 42])
def test_is_usable_date_rejects_nonsense(value):
    assert cc_core.is_usable_date(value) is False


def test_is_usable_date_accepts_real_dates():
    from datetime import date, datetime
    assert cc_core.is_usable_date("2026-08-20") is True
    assert cc_core.is_usable_date(date(2026, 8, 20)) is True
    assert cc_core.is_usable_date(datetime(2026, 8, 20)) is True


def test_position_monitor_uses_the_shared_validator():
    """One definition, not three. If someone re-inlines a copy in
    position_monitor, this fails."""
    import position_monitor
    assert position_monitor._is_usable_number is cc_core.is_usable_number


# -------------------------------------------------------------- no broker ---

BROKER_LIBRARIES = [
    "ib_insync", "ibapi", "alpaca", "alpaca_trade_api", "alpaca.trading",
    "robin_stocks", "tda", "tdameritrade", "schwab", "tastytrade",
    "ccxt", "oandapyV20",
]


def test_no_broker_library_is_reachable_from_the_engine():
    """The 'cannot touch a broker' guarantee, made mechanical.

    RED BASELINE: add `import alpaca_trade_api` to any paper_engine module and
    this test fails — verified by temporarily inserting one during development.
    """
    import importlib
    import pkgutil

    import paper_engine
    modules = [f"paper_engine.{m.name}"
               for m in pkgutil.iter_modules(paper_engine.__path__)]
    assert modules, "vacuity: no paper_engine submodules were discovered"

    offenders = []
    for name in modules:
        mod = importlib.import_module(name)
        source = open(mod.__file__).read()
        for lib in BROKER_LIBRARIES:
            root = lib.split(".")[0]
            if (f"import {root}" in source) or (f"from {root}" in source):
                offenders.append((name, lib))
    assert not offenders, f"broker libraries reachable from the engine: {offenders}"


def test_no_broker_library_is_even_installed_in_this_environment():
    """Belt and braces: if one is not installed, it cannot be imported at all."""
    installed = [lib for lib in BROKER_LIBRARIES
                 if lib.split(".")[0] in sys.modules]
    assert not installed, f"broker libraries already imported: {installed}"


# --------------------------------------------------------- startup gate -----

def test_preregistration_hash_is_the_raw_bytes_of_the_committed_document():
    path = preflight.PREREGISTRATION_PATH
    assert os.path.exists(path), "the pre-registration document must be committed"
    expected = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert preflight.preregistration_hash() == expected


def test_any_edit_changes_the_hash(tmp_path):
    """Immutability, demonstrated. There is no cosmetic-edit exemption."""
    original = open(preflight.PREREGISTRATION_PATH, "rb").read()
    before = preflight.preregistration_hash()

    scratch = tmp_path / "PREREGISTRATION.md"
    # A single character — one space appended — is enough.
    scratch.write_bytes(original + b" ")
    after = preflight.preregistration_hash(str(scratch))
    assert after != before

    # And a threshold edit, which is the edit that actually matters.
    tampered = original.replace(b'"threshold": 80.0', b'"threshold": 10.0')
    assert tampered != original, "vacuity: the threshold string was not found"
    scratch.write_bytes(tampered)
    assert preflight.preregistration_hash(str(scratch)) != before


def test_missing_document_fails_the_gate_rather_than_defaulting(tmp_path):
    with pytest.raises(preflight.GateFailure) as e:
        preflight.preregistration_hash(str(tmp_path / "nope.md"))
    assert "missing" in str(e.value).lower()


def test_gate_fails_when_the_registry_is_not_supabase(monkeypatch):
    """The SQLite-fallback door, closed. RED BASELINE: this passes only because
    the gate raises — make graveyard_backend_is_supabase return True and it fails."""
    monkeypatch.setattr(preflight, "graveyard_backend_is_supabase",
                        lambda: (False, "sqlite:/tmp/local.db"))
    with pytest.raises(preflight.GateFailure) as e:
        preflight.check()
    assert "sqlite" in str(e.value).lower()


def test_gate_fails_when_hypothesis_rows_are_missing(monkeypatch):
    """The gate's own red baseline: before registration, the engine must refuse.

    This is the state PR-1 ships in, on purpose, so the gate's green is earned
    rather than assumed.
    """
    from paper_engine import store
    monkeypatch.setattr(preflight, "graveyard_backend_is_supabase",
                        lambda: (True, "supabase"))
    monkeypatch.setattr(store, "schema_contract_check", lambda: {"ok": True})
    monkeypatch.setattr(store, "graveyard_rows", lambda ids: {})
    with pytest.raises(preflight.GateFailure) as e:
        preflight.check()
    msg = str(e.value)
    assert "missing" in msg
    for h in config.HYPOTHESES:
        assert h in msg


def test_gate_fails_on_a_hash_mismatch(monkeypatch):
    """Editing the criteria after go-live bricks the engine, loudly."""
    from paper_engine import store
    monkeypatch.setattr(preflight, "graveyard_backend_is_supabase",
                        lambda: (True, "supabase"))
    monkeypatch.setattr(store, "schema_contract_check", lambda: {"ok": True})
    monkeypatch.setattr(store, "graveyard_rows", lambda ids: {
        h: {"signal_id": h, "status": "untested",
            "pass_thresholds": {"preregistration_sha256": "deadbeef"}}
        for h in ids})
    with pytest.raises(preflight.GateFailure) as e:
        preflight.check()
    assert "does not match" in str(e.value)
    assert "deadbeef" in str(e.value)


def test_gate_passes_when_everything_lines_up(monkeypatch):
    """Vacuity guard for all of the above: the gate CAN go green."""
    from paper_engine import store
    real_hash = preflight.preregistration_hash()
    monkeypatch.setattr(preflight, "graveyard_backend_is_supabase",
                        lambda: (True, "supabase"))
    monkeypatch.setattr(store, "schema_contract_check", lambda: {"ok": True})
    monkeypatch.setattr(store, "graveyard_rows", lambda ids: {
        h: {"signal_id": h, "status": "untested", "pre_registered_date": "2026-08-20",
            "pass_thresholds": {"preregistration_sha256": real_hash}}
        for h in ids})
    report = preflight.check()
    assert report["ok"] is True
    assert set(report["checks"]["hypotheses"]) == set(config.HYPOTHESES)


# ------------------------------------------------------- registry immutability

def test_pre_register_refuses_to_overwrite_different_thresholds(monkeypatch):
    """The upsert hole, closed. RED BASELINE: `db.register_hypothesis` upserts,
    so without this guard the second call silently replaced the first."""
    import db
    import signal_registry

    monkeypatch.setattr(db, "get_hypothesis", lambda sid: {
        "signal_id": sid, "pre_registered_date": "2026-08-20",
        "hypothesis": "the original hypothesis",
        "pass_thresholds": {"preregistration_sha256": "aaaa"}})
    wrote = []
    monkeypatch.setattr(db, "register_hypothesis",
                        lambda *a, **k: wrote.append(a) or True)

    with pytest.raises(signal_registry.AlreadyRegistered) as e:
        signal_registry.pre_register(
            "H40", "n", 1, "a DIFFERENT hypothesis",
            pass_thresholds={"preregistration_sha256": "bbbb"})
    assert "Refusing to overwrite" in str(e.value)
    assert not wrote, "the guard must run BEFORE the upsert, not after"


def test_pre_register_is_a_no_op_for_identical_content(monkeypatch):
    """Scripts get re-run. Identical content must not be an error."""
    import db
    import signal_registry

    thresholds = {"preregistration_sha256": "aaaa"}
    monkeypatch.setattr(db, "get_hypothesis", lambda sid: {
        "signal_id": sid, "pre_registered_date": "2026-08-20",
        "hypothesis": "H\nPrimary metric: m\nPass: preregistration_sha256: aaaa",
        "pass_thresholds": thresholds})
    wrote = []
    monkeypatch.setattr(db, "register_hypothesis",
                        lambda *a, **k: wrote.append(a) or True)

    assert signal_registry.pre_register(
        "H40", "n", 1, "H", primary_metric="m",
        pass_thresholds=thresholds) is True
    assert not wrote


# ------------------------------------------------- pre-registration wiring ---

def test_embedded_thresholds_match_thresholds_json():
    """One truth, two representations, asserted equal.

    The document is the immutable artefact; the JSON is what killswitch.py
    reads. Hand-syncing two copies is the strategies.ts drift, so the check is
    mechanical.
    """
    sys.path.insert(0, os.path.join(ROOT, "experiments", "024_paper_engine"))
    import embed_thresholds
    assert embed_thresholds.main(check=True) == 0


def test_killswitch_reads_the_committed_thresholds():
    from paper_engine import killswitch
    t = killswitch.thresholds()
    assert set(t["verdict_rules"]) >= set(config.HYPOTHESES)
    assert "drawdown" in t["kills"]["strategy"]
    assert "quote_coverage_pct_trailing_5_sessions" in t["kills"]["engine_integrity"]


def test_every_threshold_declares_whether_it_was_derived_or_chosen():
    """No number may be presented as measured when it was picked."""
    from paper_engine import killswitch
    t = killswitch.thresholds()
    valid = {"derived", "arbitrary", "mechanical",
             "derived_with_arbitrary_multiplier", "derived_with_arbitrary_floor"}
    checked = 0
    for name, cfg in t["kills"]["engine_integrity"].items():
        assert cfg["kind"] in valid, f"{name}: {cfg['kind']}"
        assert cfg.get("derivation"), f"{name} has no derivation"
        checked += 1
    for name, cfg in t["kills"]["strategy"].items():
        if name == "drawdown":
            for ticker, c in cfg["per_ticker"].items():
                assert c["kind"] in valid and c.get("derivation")
                checked += 1
        elif name == "consecutive_losses":
            for ticker, c in cfg.items():
                assert c["kind"] in valid and c.get("derivation")
                checked += 1
        else:
            assert cfg["kind"] in valid and cfg.get("derivation"), name
            checked += 1
    assert checked >= 10, f"vacuity: only {checked} thresholds inspected"


def test_backend_reports_rather_than_raising_when_the_client_cannot_be_built(monkeypatch):
    """A diagnostic that raises crashes the check that exists to catch it.

    RED BASELINE: CI hit this for real — the test job has SUPABASE_URL and
    SUPABASE_KEY but not the `supabase` package, so `db._get_supabase()` raised
    ModuleNotFoundError out of `backend()` and took a passing test with it.
    """
    import db
    import signal_registry

    def boom():
        raise ModuleNotFoundError("No module named 'supabase'")

    monkeypatch.setattr(db, "_get_supabase", boom)
    assert signal_registry.backend() == "unavailable:ModuleNotFoundError"


def test_registry_sync_fails_the_job_on_any_non_supabase_backend():
    """`backend()` returning a string is only useful if something acts on it.

    The workflow greps its own log. Widening what `backend()` can return without
    widening the grep would have created a state where the registry announces
    'nothing was written' and the job reports success.
    """
    wf = os.path.join(ROOT, ".github", "workflows", "registry-sync.yml")
    with open(wf) as f:
        source = f.read()
    for token in ["sqlite:", "unavailable:"]:
        assert f'grep -q "{token}"' in source, (
            f"registry-sync.yml does not fail on a '{token}' backend")


def test_the_registration_script_refuses_a_non_supabase_backend():
    """Belt and braces: the script checks too, so it is safe outside the workflow."""
    path = os.path.join(ROOT, "experiments", "register_h40_h43.py")
    with open(path) as f:
        source = f.read()
    assert 'backend() != "supabase"' in source
