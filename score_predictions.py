"""
Score matured predictions (20+ days old).

Extracted from an inline `python -c "..."` block in score-predictions.yml, which
was invalid YAML — GitHub could never parse the workflow, so this job has never
run. Complex Python belongs in a script file, never inlined in shell.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from db import (
    reset_predictions_missing_pnl,
    score_pending_predictions,
    get_pending_predictions_count,
)


def main():
    reset = reset_predictions_missing_pnl()
    if reset:
        print(f"Reset {reset} old predictions missing P&L data", flush=True)

    pending = get_pending_predictions_count()
    print(f"Pending predictions to check: {pending}", flush=True)

    if pending > 0:
        scored = score_pending_predictions()
        print(f"Scored: {scored}", flush=True)
    else:
        print("Nothing to score yet.", flush=True)


if __name__ == "__main__":
    main()
