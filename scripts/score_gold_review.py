"""Compare a second reviewer's blind answers against the hand-written gold labels.

Takes the JSON the review sheet's copy button produces and reports two things the gold set
currently cannot claim for itself:

* **Validity** — of the 28 pairs labelled as contradictions, how many does an independent reader
  agree are contradictions at all. This bounds every recall figure computed on the set: a pair the
  reviewer rejects is one the system arguably should not be penalised for missing.
* **Type agreement** — how often the reviewer picks the same taxonomy label. The eval report warns
  that its own `type_agreement` is inflated because I assigned the gold types knowing the taxonomy;
  this is the unbiased version of that number.

Disagreements are printed in full, because the individual cases are the useful output — a pair two
readers cannot agree on is a bad benchmark item regardless of who is right.

    uv run python scripts/score_gold_review.py answers.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

GOLD = Path("benchmarks/handwritten/gold.json")


def main(answers_path: Path) -> None:
    """Score one reviewer's answers against the gold set."""
    gold = json.loads(GOLD.read_text())
    raw = json.loads(answers_path.read_text())
    answers = raw["reviewer_answers"] if isinstance(raw, dict) else raw
    by_id = {row["pair_id"]: row for row in answers if row.get("pair_id")}

    pairs = gold["pairs"]
    answered = [p for p in pairs if by_id.get(p["pair_id"], {}).get("verdict")]
    verdicts = Counter(by_id[p["pair_id"]]["verdict"] for p in answered)

    print(f"gold pairs: {len(pairs)}   answered: {len(answered)}\n")
    print("--- validity: does an independent reader see a contradiction? ---")
    for name in ("yes", "no", "unsure"):
        count = verdicts.get(name, 0)
        share = count / len(answered) if answered else 0.0
        print(f"  {name:<7} {count:>3}  ({share:.1%})")
    confirmed = verdicts.get("yes", 0)
    if answered:
        print(f"\n  confirmed-contradiction rate: {confirmed / len(answered):.1%}")
        print("  (every recall figure on this benchmark is bounded by this)")

    agreed = [p for p in answered if by_id[p["pair_id"]]["verdict"] == "yes"]
    typed = [p for p in agreed if by_id[p["pair_id"]].get("type")]
    matches = [p for p in typed if by_id[p["pair_id"]]["type"] == p["contradiction_type"]]
    print("\n--- type agreement, on pairs both of us call a contradiction ---")
    if typed:
        print(f"  {len(matches)} of {len(typed)}  ({len(matches) / len(typed):.1%})")
        print("  authored-set figure for comparison: 0.846 (biased — same author assigned both)")
    else:
        print("  no typed answers")

    print("\n--- disagreements (the useful part) ---")
    for pair in answered:
        row = by_id[pair["pair_id"]]
        rejected = row["verdict"] != "yes"
        mistyped = (
            row["verdict"] == "yes"
            and bool(row.get("type"))
            and row["type"] != pair["contradiction_type"]
        )
        if not (rejected or mistyped):
            continue
        print(f"\n  {pair['pair_id']}  gold={pair['contradiction_type']}")
        print(f"    reviewer: {row['verdict']}" + (f" / {row['type']}" if row.get("type") else ""))
        print(f"    A: {' '.join(pair['a']['text'].split())[:96]}")
        print(f"    B: {' '.join(pair['b']['text'].split())[:96]}")
        if row.get("note"):
            print(f"    note: {row['note']}")

    unanswered = [p["pair_id"] for p in pairs if not by_id.get(p["pair_id"], {}).get("verdict")]
    if unanswered:
        print(f"\n  {len(unanswered)} pair(s) unanswered: {', '.join(unanswered[:5])}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: score_gold_review.py <answers.json>")
    main(Path(sys.argv[1]))
