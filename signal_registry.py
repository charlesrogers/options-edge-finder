"""
Signal Registry — Pre-registration enforcement and hypothesis management.

Every hypothesis MUST be documented here BEFORE testing. This prevents
post-hoc rationalization ("we found a pattern!"). The graveyard tracks
all tested signals (pass + fail) for Deflated Sharpe Ratio correction.

Workflow:
  1. pre_register() — document hypothesis before touching data
  2. mark_testing() — flag that testing has begun
  3. mark_result() — record pass/fail with metrics
  4. get_graveyard_count() — for DSR denominator

From Sinclair & Mack (2024): "Test 98-99 ideas before finding one promising."
From variance_betting: "The single most dangerous omission is not tracking failed signals."
"""

from datetime import datetime
import db


def backend():
    """Which store is the graveyard actually writing to?

    db.py falls back to a local, gitignored SQLite file when Supabase creds are
    absent or the client is uninstallable. That fallback is silent, so a
    pre-registration can appear to succeed while landing nowhere durable — the
    exact class of failure that produced the 4.5-month data outage
    (tasks/lessons.md 2026-08-15). Every registry call announces the backend so
    'registered' can never mean 'wrote to a temp file on this laptop'.
    """
    try:
        client = db._get_supabase()
    except Exception as e:
        # An uninstallable or unbuildable client IS "not supabase". Raising from
        # a diagnostic is strictly worse than answering it: every caller of this
        # function is asking so it can refuse to proceed, and
        # `registry-sync.yml` greps the log for `sqlite:` to fail the job. A
        # ModuleNotFoundError here would crash the check that exists to catch
        # exactly this condition. (CI has the credentials but not the package.)
        return f"unavailable:{type(e).__name__}"
    return "supabase" if client is not None else f"sqlite:{db.SQLITE_PATH}"


class AlreadyRegistered(RuntimeError):
    """A pre-registration exists and does not match what is being registered.

    `db.register_hypothesis` UPSERTs on `signal_id`, so before this guard a
    re-run with different thresholds silently replaced the original and left no
    record that it had ever said anything else. Pre-registration that can be
    edited after the fact is not pre-registration; it is note-taking.
    """


def pre_register(signal_id, name, tier, hypothesis,
                 filter_desc=None, trade_direction=None,
                 primary_metric="Realized VRP", pass_thresholds=None,
                 fail_criteria=None, allow_overwrite=False):
    """
    Pre-register a hypothesis BEFORE any data analysis.

    Args:
        signal_id: Unique ID (e.g., "H01", "H05")
        name: Short descriptive name
        tier: 1=core, 2=edge sizing, 3=model adjustment, 4=situational
        hypothesis: Full hypothesis text (falsifiable statement)
        filter_desc: What tickers/conditions qualify
        trade_direction: What the signal recommends
        primary_metric: What we measure (default: Realized VRP)
        pass_thresholds: Dict of metric thresholds for passing
        fail_criteria: When to kill the signal
    """
    # Build full hypothesis text with metadata
    full_hypothesis = hypothesis
    parts = []
    if filter_desc:
        parts.append(f"Filter: {filter_desc}")
    if trade_direction:
        parts.append(f"Direction: {trade_direction}")
    if primary_metric:
        parts.append(f"Primary metric: {primary_metric}")
    if pass_thresholds:
        thresh_str = ", ".join(f"{k}: {v}" for k, v in pass_thresholds.items())
        parts.append(f"Pass: {thresh_str}")
    if fail_criteria:
        parts.append(f"Fail: {fail_criteria}")
    if parts:
        full_hypothesis += "\n" + "\n".join(parts)

    # Read before write. Re-registering the IDENTICAL content is a harmless
    # no-op (scripts get re-run); re-registering DIFFERENT content is refused.
    existing = db.get_hypothesis(signal_id)
    if existing and not allow_overwrite:
        differs = []
        if (existing.get("hypothesis") or "") != full_hypothesis:
            differs.append("hypothesis")
        if pass_thresholds is not None:
            stored = existing.get("pass_thresholds")
            if isinstance(stored, str):
                import json as _json
                try:
                    stored = _json.loads(stored)
                except ValueError:
                    pass
            if stored != pass_thresholds:
                differs.append("pass_thresholds")
        if differs:
            raise AlreadyRegistered(
                f"{signal_id} is already pre-registered (on "
                f"{existing.get('pre_registered_date')}) and differs in: "
                f"{', '.join(differs)}. Refusing to overwrite it. A hypothesis "
                f"whose success criteria can be edited after registration is "
                f"not pre-registered. Register a NEW signal_id with a new start "
                f"date and report the two separately."
            )
        print(f"[registry] {signal_id} already registered with identical "
              f"content — no-op -> {backend()}")
        return True

    db.register_hypothesis(signal_id, name, tier, full_hypothesis,
                           pass_thresholds=pass_thresholds)
    print(f"[registry] Pre-registered {signal_id}: {name} (Tier {tier}) "
          f"-> {backend()}")
    return True


def mark_testing(signal_id):
    """Mark that testing has begun for a hypothesis."""
    db.update_hypothesis_result(signal_id, status="testing", layer_reached=0)
    print(f"[registry] {signal_id}: testing started")


def mark_result(signal_id, passed, layer, metrics=None, failure_reason=None):
    """
    Record test results for a hypothesis.

    Args:
        signal_id: The hypothesis ID
        passed: True if passed the gate up to this layer
        layer: Highest layer passed (1-10)
        metrics: Dict with 'sharpe', 'rvrp', 'n_trades', etc.
        failure_reason: Why it failed (if it did)
    """
    metrics = metrics or {}
    status = f"passed_layer_{layer}" if passed else f"failed_layer_{layer}"
    if passed and layer >= 7:
        status = "passed"
    if not passed:
        status = f"failed_layer_{layer}"

    notes = None
    if metrics:
        notes_parts = [f"{k}={v}" for k, v in metrics.items()
                       if k not in ('sharpe', 'rvrp', 'n_trades')]
        notes = "; ".join(notes_parts) if notes_parts else None

    db.update_hypothesis_result(
        signal_id=signal_id,
        status=status,
        layer_reached=layer,
        best_sharpe=metrics.get("sharpe"),
        best_clv=metrics.get("rvrp"),
        n_trades=metrics.get("n_trades"),
        failure_reason=failure_reason,
        notes=notes,
    )
    verb = "PASSED" if passed else "FAILED"
    print(f"[registry] {signal_id}: {verb} at Layer {layer}"
          + (f" — {failure_reason}" if failure_reason else "")
          + f" -> {backend()}")


def validate_pre_registration(signal_id):
    """
    Verify a hypothesis was registered BEFORE testing began.
    Returns True if valid, raises ValueError if not.
    """
    df = db.get_graveyard()
    if df.empty:
        raise ValueError(f"Signal graveyard is empty. Register {signal_id} first.")
    match = df[df["signal_id"] == signal_id]
    if match.empty:
        raise ValueError(
            f"{signal_id} not found in graveyard. "
            "Pre-register with pre_register() before testing."
        )
    row = match.iloc[0]
    if row.get("status") not in ("untested", "testing"):
        print(f"[registry] WARNING: {signal_id} already has status '{row['status']}'. Re-testing.")
    return True


def get_registered(status=None):
    """List hypotheses, optionally filtered by status."""
    df = db.get_graveyard()
    if df.empty:
        return df
    if status:
        df = df[df["status"] == status]
    return df


def get_all_signal_ids():
    """Return list of all registered signal IDs."""
    df = db.get_graveyard()
    if df.empty:
        return []
    return df["signal_id"].tolist()


def summary():
    """Print summary of signal graveyard."""
    df = db.get_graveyard()
    if df.empty:
        print("[registry] Signal graveyard is empty.")
        return

    total = len(df)
    by_status = df["status"].value_counts().to_dict()
    tested = total - by_status.get("untested", 0)

    print(f"[registry] Signal Graveyard: {total} hypotheses ({tested} tested)")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")

    # List each
    for _, row in df.iterrows():
        layer = row.get("layer_reached", 0)
        rvrp = row.get("best_clv")
        rvrp_str = f", RVRP={rvrp:.1%}" if rvrp else ""
        print(f"  {row['signal_id']}: {row['name']} [{row['status']}] "
              f"(Tier {row['tier']}, Layer {layer}{rvrp_str})")
