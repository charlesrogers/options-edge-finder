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


def pre_register(signal_id, name, tier, hypothesis,
                 filter_desc=None, trade_direction=None,
                 primary_metric="Realized VRP", pass_thresholds=None,
                 fail_criteria=None):
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

    db.register_hypothesis(signal_id, name, tier, full_hypothesis)
    print(f"[registry] Pre-registered {signal_id}: {name} (Tier {tier})")
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
          + (f" — {failure_reason}" if failure_reason else ""))


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
