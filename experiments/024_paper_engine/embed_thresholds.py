"""Inject thresholds.json into PREREGISTRATION.md between its markers.

The document is the immutable artefact and the JSON is what the engine reads at
runtime. Keeping two hand-maintained copies in sync is exactly the drift that
produced strategies.ts (tasks/lessons.md 2026-08-18), so one is generated from
the other and a test asserts they still match.

Run after any change to derive_thresholds.py:
    python3 experiments/024_paper_engine/embed_thresholds.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(HERE, "PREREGISTRATION.md")
JSON_PATH = os.path.join(HERE, "thresholds.json")
BEGIN = "<!-- BEGIN thresholds.json -->"
END = "<!-- END thresholds.json -->"


def embedded_block(text):
    """The JSON currently inside the document, or None."""
    if BEGIN not in text or END not in text:
        return None
    inner = text.split(BEGIN, 1)[1].split(END, 1)[0]
    inner = inner.strip()
    if inner.startswith("```json"):
        inner = inner[len("```json"):]
    if inner.endswith("```"):
        inner = inner[:-3]
    return inner.strip()


def main(check=False):
    with open(JSON_PATH) as f:
        payload = f.read().strip()
    with open(DOC) as f:
        text = f.read()

    current = embedded_block(text)
    if current is None:
        print("FAIL: PREREGISTRATION.md is missing its thresholds markers")
        return 1
    if check:
        if current != payload:
            print("FAIL: the JSON embedded in PREREGISTRATION.md has drifted "
                  "from thresholds.json. Run embed_thresholds.py.")
            return 1
        print("OK: embedded thresholds match thresholds.json")
        return 0

    before = text.split(BEGIN, 1)[0]
    after = text.split(END, 1)[1]
    with open(DOC, "w") as f:
        f.write(f"{before}{BEGIN}\n```json\n{payload}\n```\n{END}{after}")
    print(f"embedded {len(payload)} bytes of thresholds.json into PREREGISTRATION.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))
