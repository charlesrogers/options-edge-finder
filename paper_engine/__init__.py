"""Forward-validation paper-trading engine.

Runs the production covered-call strategy forward in time against real quotes
captured at the moments decisions happen, in four pre-registered arms, so that
at pre-committed milestones we know — not believe — whether it makes money.

The engine cannot touch a broker. It has no broker credentials and imports no
broker library; `tests/test_paper_engine_guards.py` asserts that mechanically.

Spec: tasks/paper-trading-engine-spec.md
Pre-registration: experiments/024_paper_engine/PREREGISTRATION.md
"""

ENGINE_VERSION = "0.1.0"
