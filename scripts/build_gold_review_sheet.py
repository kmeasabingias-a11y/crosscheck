"""Build a standalone HTML sheet for a second reviewer to validate the hand-written gold set.

Every pair in `benchmarks/handwritten/gold.json` carries `reviewed: false`. I wrote the corpus,
the contradictions and the labels, so every figure derived from that set inherits a single
author's judgement — and the eval report already flags that its type agreement is biased, because
I assigned the gold types knowing the taxonomy the judge would be scored against.

This produces a file a second reviewer can open in a browser with no clone, no install and no
knowledge of the project, and fill in offline. Their answers are collected as JSON via a copy
button; `score_gold_review.py` compares them against the gold labels afterwards.

The review is **blind by construction**. The reviewer sees the two passages and nothing else: not
the assigned type, and not the `notes` field, which spells out the intended reasoning and would
prime the answer completely. The gold label sits behind a collapsed reveal on each card, for the
conversation after the answers are recorded rather than during.

    uv run python scripts/build_gold_review_sheet.py [output.html]
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

GOLD = Path("benchmarks/handwritten/gold.json")
DEFAULT_OUT = Path("../Crosscheck_Runs/gold_review.html")

#: Plain-English glosses. A reviewer who does not know the taxonomy cannot produce a meaningful
#: type judgement, and an unexplained label list would measure vocabulary rather than agreement.
TYPES: list[tuple[str, str]] = [
    ("direct_negation", "One statement is simply the opposite of the other."),
    ("numerical_mismatch", "Same thing, different number, date or threshold."),
    ("temporal_conflict", "One supersedes or replaces the other, but both are still in force."),
    ("obligation_reversal", "One requires something; the other forbids or excuses it."),
    ("scope_jurisdiction", "They agree in general but diverge for a place, group or case."),
]


def render_passage(side: dict[str, Any], letter: str) -> str:
    """Render one side of a pair as a titled panel."""
    return f"""
      <div class="passage">
        <div class="ptag">Passage {letter}</div>
        <div class="pmeta">{html.escape(side["document"])}
          &middot; {html.escape(side.get("section_heading") or "")}</div>
        <blockquote>{html.escape(" ".join(side["text"].split()))}</blockquote>
      </div>"""


def render_card(index: int, pair: dict[str, Any]) -> str:
    """Render one reviewable pair."""
    pid = html.escape(pair["pair_id"])
    options = "\n".join(
        f'<option value="{value}">{value.replace("_", " ")} — {html.escape(gloss)}</option>'
        for value, gloss in TYPES
    )
    gold_type = html.escape(pair["contradiction_type"])
    gold_note = html.escape(pair.get("notes") or "")
    return f"""
  <article class="card" data-pair="{pid}" id="card-{index}">
    <header class="chead"><span class="num">{index} of 28</span></header>
    <div class="passages">{render_passage(pair["a"], "A")}{render_passage(pair["b"], "B")}</div>

    <div class="q">
      <label class="qlabel">1 &middot; Do these two passages contradict each other?</label>
      <div class="radios">
        <label><input type="radio" name="v-{pid}" value="yes"> Yes, they conflict</label>
        <label><input type="radio" name="v-{pid}" value="no"> No, both can be true</label>
        <label><input type="radio" name="v-{pid}" value="unsure"> Unsure / need more context</label>
      </div>
    </div>

    <div class="q">
      <label class="qlabel" for="t-{pid}">2 &middot; If they conflict, what kind?</label>
      <select id="t-{pid}" name="t-{pid}">
        <option value="">— choose —</option>
        {options}
        <option value="other">Something else / none of these</option>
      </select>
    </div>

    <div class="q">
      <label class="qlabel" for="n-{pid}">3 &middot; Anything worth noting? (optional)</label>
      <textarea id="n-{pid}" name="n-{pid}" rows="2"
        placeholder="e.g. only conflicts if closing an account counts as termination"></textarea>
    </div>

    <details class="reveal">
      <summary>Show what this pair was labelled (open only after answering)</summary>
      <p><strong>Labelled:</strong> {gold_type}</p>
      <p><strong>Reasoning recorded at authoring:</strong> {gold_note}</p>
    </details>
  </article>"""


def build(gold: dict[str, Any]) -> str:
    """Render the sheet as a page fragment: title, styles, cards and script, no document shell.

    Kept separate from the document wrapper so the same markup can be served two ways — as a file
    a reviewer opens locally, or as a hosted page whose host supplies its own shell. A reviewer who
    has to be talked through downloading and opening an HTML attachment is a reviewer who does not
    do the review.
    """
    cards = "\n".join(render_card(i, p) for i, p in enumerate(gold["pairs"], 1))
    legend = "\n".join(f"<li><code>{v}</code> — {html.escape(g)}</li>" for v, g in TYPES)
    return f"""<title>CrossCheck — gold set review</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1a1a; --muted: #5c5c5c; --line: #e2e2e2;
    --panel: #fafafa; --accent: #d98324; --ok: #2e7d32;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16181c; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f36;
      --panel: #1d2026; --accent: #e0a458; --ok: #7bc47f;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 2rem 1rem 6rem; background: var(--bg); color: var(--fg);
         font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 46rem; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .5rem; }}
  .intro {{ border: 1px solid var(--line); background: var(--panel);
            border-radius: 10px; padding: 1.25rem; margin-bottom: 2rem; }}
  .intro ol {{ margin: .5rem 0 0; padding-left: 1.2rem; }}
  .intro li {{ margin: .3rem 0; }}
  ul.legend {{ margin: .5rem 0 0; padding-left: 1.2rem; font-size: .9rem; color: var(--muted); }}
  code {{ background: var(--panel); padding: .1em .35em; border-radius: 4px;
          border: 1px solid var(--line); font-size: .9em; }}
  .card {{ border: 1px solid var(--line); border-radius: 10px; padding: 1.25rem;
           margin-bottom: 1.5rem; background: var(--bg); }}
  .card.done {{ border-color: var(--ok); }}
  .chead {{ display: flex; justify-content: space-between; margin-bottom: .75rem; }}
  .num {{ font-size: .8rem; color: var(--muted); letter-spacing: .04em;
          text-transform: uppercase; }}
  .passages {{ display: grid; gap: .75rem; grid-template-columns: 1fr; }}
  @media (min-width: 40rem) {{ .passages {{ grid-template-columns: 1fr 1fr; }} }}
  .passage {{ background: var(--panel); border: 1px solid var(--line);
              border-radius: 8px; padding: .75rem; }}
  .ptag {{ font-size: .75rem; font-weight: 700; color: var(--accent);
           text-transform: uppercase; letter-spacing: .06em; }}
  .pmeta {{ font-size: .78rem; color: var(--muted); margin: .15rem 0 .5rem; }}
  blockquote {{ margin: 0; font-size: .95rem; }}
  .q {{ margin-top: 1rem; }}
  .qlabel {{ display: block; font-weight: 600; font-size: .9rem; margin-bottom: .4rem; }}
  .radios label {{ display: block; font-size: .92rem; margin: .2rem 0; font-weight: 400; }}
  select, textarea {{ width: 100%; padding: .45rem; border-radius: 6px;
                      border: 1px solid var(--line); background: var(--bg);
                      color: var(--fg); font: inherit; font-size: .9rem; }}
  details.reveal {{ margin-top: 1rem; border-top: 1px dashed var(--line); padding-top: .6rem; }}
  details.reveal summary {{ cursor: pointer; font-size: .85rem; color: var(--muted); }}
  details.reveal p {{ font-size: .88rem; margin: .5rem 0 0; }}
  .bar {{ position: fixed; left: 0; right: 0; bottom: 0; background: var(--panel);
          border-top: 1px solid var(--line); padding: .7rem 1rem;
          display: flex; gap: 1rem; align-items: center; justify-content: center; }}
  button {{ font: inherit; font-size: .9rem; padding: .5rem 1rem; border-radius: 6px;
            border: 1px solid var(--line); background: var(--accent); color: #fff;
            font-weight: 600; cursor: pointer; }}
  #count {{ font-size: .9rem; color: var(--muted); }}
  #out {{ width: 100%; margin-top: 1rem; font-family: ui-monospace, monospace; font-size: .8rem; }}
</style>
<main>
  <h1>Does this actually contradict?</h1>

  <div class="intro">
    <p>Below are <strong>28 pairs of passages</strong> taken from a small set of made-up company
    documents — a privacy notice, a data processing addendum, a security standard, and so on. They
    were written so that some statements conflict with each other.</p>
    <p>I need a second opinion on whether they really do. You need no background: just read each
    pair and say whether both statements could be true at the same time.</p>
    <ol>
      <li>Answer all three questions on each card. It takes about 30 minutes.</li>
      <li>Your answers save in this browser automatically, so you can stop and come back.</li>
      <li>At the end, press <strong>Copy answers</strong> and send me the text it copies.</li>
    </ol>
    <p style="margin-bottom:0"><strong>Please answer before opening the “show what this was
    labelled” box</strong> on a card — the point is your independent read, and seeing my answer
    first defeats it. Disagreeing with me is the single most useful thing you can do here.</p>
    <ul class="legend">{legend}</ul>
  </div>

  {cards}

  <textarea id="out" rows="4"
    placeholder="Your answers appear here when you press Copy answers."></textarea>
</main>

<div class="bar">
  <span id="count">0 of 28 answered</span>
  <button id="copy" type="button">Copy answers</button>
</div>

<script>
(function () {{
  var KEY = "crosscheck-gold-review-v1";
  var saved = {{}};
  try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ saved = {{}}; }}

  var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));

  function readCard(card) {{
    var pid = card.dataset.pair;
    var checked = card.querySelector('input[name="v-' + pid + '"]:checked');
    return {{
      pair_id: pid,
      verdict: checked ? checked.value : "",
      type: card.querySelector('select').value,
      note: card.querySelector('textarea').value.trim()
    }};
  }}

  function refresh() {{
    var answered = 0;
    var all = cards.map(function (card) {{
      var row = readCard(card);
      if (row.verdict) {{ answered++; card.classList.add("done"); }}
      else {{ card.classList.remove("done"); }}
      return row;
    }});
    document.getElementById("count").textContent = answered + " of " + cards.length + " answered";
    try {{ localStorage.setItem(KEY, JSON.stringify(all)); }} catch (e) {{ /* private mode */ }}
    return all;
  }}

  // Restore anything previously entered.
  cards.forEach(function (card) {{
    var pid = card.dataset.pair;
    var prior = null;
    if (Array.isArray(saved)) {{
      prior = saved.filter(function (r) {{ return r && r.pair_id === pid; }})[0];
    }}
    if (!prior) return;
    if (prior.verdict) {{
      var input = card.querySelector('input[name="v-' + pid + '"][value="' + prior.verdict + '"]');
      if (input) input.checked = true;
    }}
    if (prior.type) card.querySelector('select').value = prior.type;
    if (prior.note) card.querySelector('textarea').value = prior.note;
  }});

  document.addEventListener("input", refresh);
  document.addEventListener("change", refresh);

  document.getElementById("copy").addEventListener("click", function () {{
    var payload = JSON.stringify({{ reviewer_answers: refresh() }}, null, 1);
    var out = document.getElementById("out");
    out.value = payload;
    out.select();
    if (navigator.clipboard) {{ navigator.clipboard.writeText(payload); }}
    else {{ document.execCommand("copy"); }}
    this.textContent = "Copied — now send me that text";
  }});

  refresh();
}})();
</script>
"""


def wrap_standalone(fragment: str) -> str:
    """Wrap the fragment in a document shell, for a file opened directly from disk."""
    head, _, rest = fragment.partition("</style>")
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{head}</style>\n</head>\n<body>{rest}\n</body>\n</html>\n"
    )


def main(out_path: Path, *, fragment_only: bool = False) -> None:
    """Write the review sheet.

    Args:
        out_path: Destination file.
        fragment_only: Emit the bare fragment, for a host that supplies its own document shell.
    """
    gold = json.loads(GOLD.read_text())
    fragment = build(gold)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(fragment if fragment_only else wrap_standalone(fragment), encoding="utf-8")
    kind = "fragment" if fragment_only else "standalone"
    size = out_path.stat().st_size / 1024
    print(f"wrote {out_path} ({kind}) — {len(gold['pairs'])} pairs, {size:.0f} KB")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--fragment"]
    main(
        Path(args[0]) if args else DEFAULT_OUT,
        fragment_only="--fragment" in sys.argv[1:],
    )
