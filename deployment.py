"""
Deployment State Machine — 5-stage deployment with kill switches.

From variance_betting INFRASTRUCTURE_IMPROVEMENTS.md:
  Stage 0: Shadow (3 months min) — model runs, no capital
  Stage 1: 10% capital (3 months min)
  Stage 2: 25% capital (3 months min)
  Stage 3: 50% capital (6 months min)
  Stage 4: 100% capital (ongoing)

Gate between stages: Realized VRP still positive, Sharpe > 0.5, max DD < 15%
Kill switch: rolling 30-day RVRP < 0 for 60 days → revert to previous stage

From Sinclair & Mack (2024): "Stop theorizing and do it" — but through
the staged protocol, not all at once.
"""

from datetime import datetime, timedelta
import db


STAGES = {
    0: {"name": "Shadow", "capital_pct": 0, "min_days": 90,
        "description": "Model runs daily, no capital deployed. Track would-be results."},
    1: {"name": "10% Capital", "capital_pct": 10, "min_days": 90,
        "description": "10% of portfolio follows this signal."},
    2: {"name": "25% Capital", "capital_pct": 25, "min_days": 90,
        "description": "25% of portfolio follows this signal."},
    3: {"name": "50% Capital", "capital_pct": 50, "min_days": 180,
        "description": "50% of portfolio follows this signal."},
    4: {"name": "100% Capital", "capital_pct": 100, "min_days": 0,
        "description": "Full deployment with continuous monitoring."},
}

# Gate thresholds for promotion
PROMOTION_GATES = {
    "min_rvrp": 0.01,       # Rolling RVRP > 1%
    "min_sharpe": 0.5,      # Rolling Sharpe > 0.5
    "max_drawdown": -0.15,  # Max DD > -15%
    "min_days_in_stage": 90, # Minimum days at current stage
}

# Kill switch thresholds
KILL_THRESHOLDS = {
    "rvrp_below_zero_days": 60,  # 60 days of negative rolling RVRP
    "max_drawdown": -0.20,       # 20% drawdown = immediate revert
    "sharpe_below": -0.5,        # Negative Sharpe for 30 days
}


def get_deployment_stage(signal_id):
    """Get current deployment stage for a signal."""
    sb = db._get_supabase()
    if sb:
        resp = sb.table("deployment_stages").select("*").eq("signal_id", signal_id).execute()
        if resp.data:
            return resp.data[0]
    else:
        conn = db._get_sqlite()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deployment_stages (
                signal_id TEXT PRIMARY KEY,
                current_stage INTEGER DEFAULT 0,
                stage_entered_date TEXT,
                capital_pct REAL DEFAULT 0,
                rolling_rvrp_30d REAL,
                rolling_sharpe_30d REAL,
                max_drawdown REAL,
                kill_switch_active INTEGER DEFAULT 0,
                days_rvrp_negative INTEGER DEFAULT 0
            )
        """)
        row = conn.execute(
            "SELECT * FROM deployment_stages WHERE signal_id = ?", (signal_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
    return None


def enter_shadow(signal_id):
    """Enter Stage 0 (shadow trading) for a signal that passed the gate."""
    today = datetime.now().strftime("%Y-%m-%d")
    stage_data = {
        "signal_id": signal_id,
        "current_stage": 0,
        "stage_entered_date": today,
        "capital_pct": 0,
        "kill_switch_active": 0,
        "days_rvrp_negative": 0,
    }
    sb = db._get_supabase()
    if sb:
        sb.table("deployment_stages").upsert(
            stage_data, on_conflict="signal_id"
        ).execute()
    else:
        conn = db._get_sqlite()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deployment_stages (
                signal_id TEXT PRIMARY KEY, current_stage INTEGER DEFAULT 0,
                stage_entered_date TEXT, capital_pct REAL DEFAULT 0,
                rolling_rvrp_30d REAL, rolling_sharpe_30d REAL,
                max_drawdown REAL, kill_switch_active INTEGER DEFAULT 0,
                days_rvrp_negative INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO deployment_stages "
            "(signal_id, current_stage, stage_entered_date, capital_pct, kill_switch_active) "
            "VALUES (?, 0, ?, 0, 0)", (signal_id, today)
        )
        conn.commit()
        conn.close()
    print(f"[deploy] {signal_id} entered Stage 0 (Shadow) on {today}")


def check_promotion(signal_id, rolling_rvrp, rolling_sharpe, max_dd):
    """
    Check if a signal should be promoted to the next stage.

    Returns: (should_promote: bool, reason: str)
    """
    stage = get_deployment_stage(signal_id)
    if not stage:
        return False, "Signal not in deployment"

    current = stage["current_stage"]
    if current >= 4:
        return False, "Already at maximum stage"

    entered = stage.get("stage_entered_date", "2020-01-01")
    days_in_stage = (datetime.now() - datetime.strptime(entered, "%Y-%m-%d")).days
    min_days = STAGES[current]["min_days"]

    checks = {
        f"days_in_stage >= {min_days}": days_in_stage >= min_days,
        f"rolling_rvrp > {PROMOTION_GATES['min_rvrp']:.1%}": rolling_rvrp > PROMOTION_GATES["min_rvrp"],
        f"rolling_sharpe > {PROMOTION_GATES['min_sharpe']}": rolling_sharpe > PROMOTION_GATES["min_sharpe"],
        f"max_dd > {PROMOTION_GATES['max_drawdown']:.0%}": max_dd > PROMOTION_GATES["max_drawdown"],
    }

    all_pass = all(checks.values())
    failed = [k for k, v in checks.items() if not v]

    if all_pass:
        return True, f"All gates passed after {days_in_stage} days"
    else:
        return False, f"Failed: {', '.join(failed)}"


def promote(signal_id):
    """Promote signal to next deployment stage."""
    stage = get_deployment_stage(signal_id)
    if not stage:
        print(f"[deploy] {signal_id} not in deployment")
        return

    current = stage["current_stage"]
    if current >= 4:
        print(f"[deploy] {signal_id} already at Stage 4")
        return

    next_stage = current + 1
    today = datetime.now().strftime("%Y-%m-%d")
    capital = STAGES[next_stage]["capital_pct"]

    update = {
        "current_stage": next_stage,
        "stage_entered_date": today,
        "capital_pct": capital,
        "kill_switch_active": 0,
        "days_rvrp_negative": 0,
    }
    sb = db._get_supabase()
    if sb:
        sb.table("deployment_stages").update(update).eq("signal_id", signal_id).execute()
    else:
        conn = db._get_sqlite()
        cols = ", ".join(f"{k} = ?" for k in update.keys())
        vals = list(update.values()) + [signal_id]
        conn.execute(f"UPDATE deployment_stages SET {cols} WHERE signal_id = ?", vals)
        conn.commit()
        conn.close()

    print(f"[deploy] {signal_id} PROMOTED: Stage {current} ({STAGES[current]['name']}) "
          f"→ Stage {next_stage} ({STAGES[next_stage]['name']}) [{capital}% capital]")


def check_kill_switch(signal_id, rolling_rvrp, rolling_sharpe, max_dd):
    """
    Check if kill switch should fire — revert to previous stage.

    Returns: (should_kill: bool, reason: str)
    """
    stage = get_deployment_stage(signal_id)
    if not stage:
        return False, "Not in deployment"

    if max_dd < KILL_THRESHOLDS["max_drawdown"]:
        return True, f"Max drawdown {max_dd:.1%} breached {KILL_THRESHOLDS['max_drawdown']:.0%}"

    if rolling_sharpe < KILL_THRESHOLDS["sharpe_below"]:
        return True, f"Rolling Sharpe {rolling_sharpe:.2f} below {KILL_THRESHOLDS['sharpe_below']}"

    days_neg = stage.get("days_rvrp_negative", 0)
    if rolling_rvrp < 0:
        days_neg += 1
    else:
        days_neg = 0

    if days_neg >= KILL_THRESHOLDS["rvrp_below_zero_days"]:
        return True, f"RVRP negative for {days_neg} days (threshold: {KILL_THRESHOLDS['rvrp_below_zero_days']})"

    # Update days_rvrp_negative
    sb = db._get_supabase()
    if sb:
        sb.table("deployment_stages").update({
            "days_rvrp_negative": days_neg,
            "rolling_rvrp_30d": rolling_rvrp,
            "rolling_sharpe_30d": rolling_sharpe,
            "max_drawdown": max_dd,
        }).eq("signal_id", signal_id).execute()

    return False, f"OK (rvrp_neg_days={days_neg})"


def revert(signal_id):
    """Revert signal to previous deployment stage (kill switch fired)."""
    stage = get_deployment_stage(signal_id)
    if not stage:
        return

    current = stage["current_stage"]
    prev = max(current - 1, 0)
    today = datetime.now().strftime("%Y-%m-%d")

    update = {
        "current_stage": prev,
        "stage_entered_date": today,
        "capital_pct": STAGES[prev]["capital_pct"],
        "kill_switch_active": 1,
        "days_rvrp_negative": 0,
    }
    sb = db._get_supabase()
    if sb:
        sb.table("deployment_stages").update(update).eq("signal_id", signal_id).execute()
    else:
        conn = db._get_sqlite()
        cols = ", ".join(f"{k} = ?" for k in update.keys())
        vals = list(update.values()) + [signal_id]
        conn.execute(f"UPDATE deployment_stages SET {cols} WHERE signal_id = ?", vals)
        conn.commit()
        conn.close()

    print(f"[deploy] KILL SWITCH: {signal_id} REVERTED Stage {current} → Stage {prev} "
          f"({STAGES[prev]['name']})")


def summary():
    """Print deployment status for all signals."""
    sb = db._get_supabase()
    if sb:
        resp = sb.table("deployment_stages").select("*").execute()
        stages = resp.data or []
    else:
        conn = db._get_sqlite()
        try:
            rows = conn.execute("SELECT * FROM deployment_stages").fetchall()
            stages = [dict(r) for r in rows]
        except Exception:
            stages = []
        conn.close()

    if not stages:
        print("[deploy] No signals in deployment pipeline.")
        return

    print(f"\n{'Signal':>10s} {'Stage':>3s} {'Name':>15s} {'Capital':>8s} {'RVRP':>8s} {'Sharpe':>8s} {'Kill':>5s}")
    print("-" * 65)
    for s in stages:
        stage_num = s.get("current_stage", 0)
        name = STAGES.get(stage_num, {}).get("name", "?")
        capital = f"{s.get('capital_pct', 0):.0f}%"
        rvrp = f"{s['rolling_rvrp_30d']:.1%}" if s.get("rolling_rvrp_30d") else "N/A"
        sharpe = f"{s['rolling_sharpe_30d']:.2f}" if s.get("rolling_sharpe_30d") else "N/A"
        kill = "YES" if s.get("kill_switch_active") else "no"
        print(f"{s['signal_id']:>10s} {stage_num:>3d} {name:>15s} {capital:>8s} {rvrp:>8s} {sharpe:>8s} {kill:>5s}")
