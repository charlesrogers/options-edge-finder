"""The startup gate: make the success criteria physically immutable.

A pre-registration you can edit is not a pre-registration. Two holes made that
literally true here before this module existed:

  * `signal_registry.pre_register()` -> `db.register_hypothesis()` **upserts on
    signal_id** (db.py:572). Re-running a registration script with different
    thresholds silently overwrites the original and leaves no trace.
  * `db.py` falls back to a gitignored local SQLite file when Supabase
    credentials are absent, and returns the same value either way. A
    "registered" hypothesis can live on one laptop (tasks/lessons.md
    2026-08-16 — signal_graveyard had never existed in Supabase at all).

So the criteria are pinned twice. `PREREGISTRATION.md` is committed and merged,
which makes git the durable record even if Supabase were lost; and its SHA-256
is stored in each H40–H43 graveyard row. This gate recomputes the hash of the
file on disk and compares it to what was registered. Editing the doc after
go-live does not bend the experiment — it bricks the engine, loudly, before the
engine makes a single decision.

The gate is designed to be RED before registration happens. That is deliberate:
PR-1 ships the gate while H40–H43 are still absent, so its red state is its own
baseline and nobody has to trust a check that has only ever been green
(tasks/lessons.md 2026-08-18, "a check born green is presumed vacuous").
"""
import hashlib
import os

from . import config, store

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PREREGISTRATION_PATH = os.path.join(
    ROOT, "experiments", "024_paper_engine", "PREREGISTRATION.md")


class GateFailure(RuntimeError):
    """The engine must not trade. Always exit 1; never degrade and continue."""


def preregistration_hash(path=None):
    """SHA-256 of the committed pre-registration document, bytes as committed.

    Hashed as raw bytes rather than parsed content: any edit at all — a
    threshold, a milestone date, a caveat someone found inconvenient — changes
    the hash. That is the point. There is no "cosmetic edit" exemption, because
    deciding what counts as cosmetic is exactly the discretion this removes.
    """
    path = path or PREREGISTRATION_PATH
    if not os.path.exists(path):
        raise GateFailure(
            f"PREREGISTRATION.md is missing at {path}. The engine cannot trade "
            f"without the document its success criteria are pinned to.")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def graveyard_backend_is_supabase():
    """Assert the registry is talking to Supabase, not the SQLite fallback.

    Imported lazily so a missing `supabase` client cannot take the engine down
    at import time — the answer we want in that case is 'not supabase', not a
    stack trace.
    """
    try:
        import signal_registry
        backend = signal_registry.backend()
    except Exception as e:                                     # pragma: no cover
        return False, f"registry backend unreadable: {e}"
    return backend == "supabase", backend


def check(*, path=None, require_backend=True):
    """Run every startup check. Returns a report dict, or raises GateFailure.

    Order matters: the cheapest and most fundamental checks run first, so a
    missing document does not produce a confusing Supabase error.
    """
    report = {"checks": {}, "ok": False}

    # 1. The document exists and hashes.
    doc_hash = preregistration_hash(path)
    report["checks"]["preregistration_doc"] = {
        "path": path or PREREGISTRATION_PATH, "sha256": doc_hash}

    # 2. The registry is durable, not a local file.
    if require_backend:
        ok, backend = graveyard_backend_is_supabase()
        report["checks"]["graveyard_backend"] = backend
        if not ok:
            raise GateFailure(
                f"signal_graveyard backend is '{backend}', not 'supabase'. A "
                f"pre-registration in the SQLite fallback is not a "
                f"pre-registration (tasks/lessons.md 2026-08-16).")

    # 3. The schema contract — before the first decision, not after the first
    #    write. PostgREST rejects an unknown column even on an empty table.
    report["checks"]["schema_contract"] = store.schema_contract_check()

    # 4. Every arm's hypothesis is registered, and registered against THIS doc.
    rows = store.graveyard_rows(config.HYPOTHESES)
    missing = [h for h in config.HYPOTHESES if h not in rows]
    if missing:
        raise GateFailure(
            f"pre-registration rows missing from signal_graveyard: "
            f"{', '.join(missing)}. Register H40–H43 via registry-sync.yml "
            f"before the engine may trade (spec §6.5 step 1).")

    mismatched = []
    for h in config.HYPOTHESES:
        thresholds = rows[h].get("pass_thresholds") or {}
        registered = thresholds.get("preregistration_sha256")
        if registered != doc_hash:
            mismatched.append({
                "signal_id": h,
                "registered_sha256": registered,
                "document_sha256": doc_hash,
            })
    if mismatched:
        raise GateFailure(
            "PREREGISTRATION.md does not match what was registered. Either the "
            "document was edited after go-live, or the wrong commit is "
            "deployed. The engine will not trade against success criteria that "
            "have moved.\n" + "\n".join(
                f"  {m['signal_id']}: registered={m['registered_sha256']} "
                f"document={m['document_sha256']}" for m in mismatched))

    report["checks"]["hypotheses"] = {
        h: {"status": rows[h].get("status"),
            "pre_registered_date": rows[h].get("pre_registered_date")}
        for h in config.HYPOTHESES}
    report["ok"] = True
    return report


def main():                                                    # pragma: no cover
    """Standalone gate run, for the workflow's pre-trade step and for demos."""
    import json
    import sys
    try:
        report = check()
    except (GateFailure, store.StoreError) as e:
        print("STARTUP GATE: FAIL\n")
        print(str(e))
        sys.exit(1)
    print("STARTUP GATE: PASS")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":                                     # pragma: no cover
    raise SystemExit(main())
