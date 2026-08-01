"""Render a :class:`~crosscheck.aggregation.report.ContradictionReport` as standalone HTML.

This is the demo artifact (§7.5), so it has one hard constraint: the output must open from a
``file://`` URL on a machine with no network. Every byte — CSS, the type filter, the icons — is
inline. No CDN, no web font, no external stylesheet.

Written without a templating engine on purpose (D35). The dependency surface is a stated design
value (§4), and one page does not justify an engine; instead every interpolation goes through
:func:`_esc`, and there is a test that feeds the renderer a claim containing ``<script>`` to
prove it. The CSS lives in a module constant rather than an f-string so its braces need no
escaping, and rather than a package data file so no build-backend configuration is needed.

Output is deterministic for a given report — the only variable input is
``ContradictionReport.generated_at``, which the builder leaves ``None`` by default — so the §12
regression snapshot can be committed and diffed.
"""

from html import escape
from pathlib import Path

from crosscheck.aggregation.report import (
    ContradictionReport,
    DocumentPairGroup,
    Finding,
    FindingSide,
)
from crosscheck.detection.taxonomy import ContradictionType

_TYPE_LABELS: dict[str, str] = {
    ContradictionType.DIRECT_NEGATION.value: "Direct negation",
    ContradictionType.NUMERICAL_MISMATCH.value: "Numerical mismatch",
    ContradictionType.TEMPORAL_CONFLICT.value: "Temporal conflict",
    ContradictionType.OBLIGATION_REVERSAL.value: "Obligation reversal",
    ContradictionType.SCOPE_JURISDICTION.value: "Scope / jurisdiction",
    ContradictionType.UNCLEAR.value: "Unclear",
    ContradictionType.CONDITIONAL_TRIPLET.value: "Conditional triplet",
}

_CSS = """
:root {
  --bg: #f6f7f9; --surface: #ffffff; --surface-alt: #fbfbfd;
  --border: #dfe3e8; --border-soft: #eceef1;
  --ink: #1b1f24; --ink-soft: #5c6672; --ink-faint: #8a939e;
  --accent: #2f5d8a; --mark: #ffe9a8; --mark-edge: #e5c356;
  --ok: #2d7a4d; --warn: #9a6410; --warn-bg: #fdf4e3; --danger: #a3342c;
  --radius: 10px;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171a; --surface: #1c2024; --surface-alt: #21262b;
    --border: #2f363d; --border-soft: #262c32;
    --ink: #e6e9ec; --ink-soft: #a3adb8; --ink-faint: #78828d;
    --accent: #7aa9d6; --mark: #5a4a16; --mark-edge: #8a7327;
    --ok: #6cc08b; --warn: #d8a441; --warn-bg: #2e2717; --danger: #e08279;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans);
       font-size: 15px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 32px 24px 80px; }
header.doc { border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 24px; }
.brand { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.brand h1 { font-size: 22px; margin: 0; letter-spacing: -0.01em; }
.meta { margin-top: 10px; display: flex; gap: 20px; flex-wrap: wrap;
        font-size: 13px; color: var(--ink-soft); }
.meta code { font-family: var(--mono); font-size: 12px; color: var(--ink); }
.headline { background: var(--surface); border: 1px solid var(--border);
            border-left: 4px solid var(--danger); border-radius: var(--radius);
            padding: 18px 20px; margin-bottom: 18px; }
.headline h2 { margin: 0 0 4px; font-size: 18px; }
.headline p { margin: 0; color: var(--ink-soft); font-size: 14px; }
.partial { background: var(--warn-bg); border: 1px solid var(--warn); border-radius: var(--radius);
           padding: 13px 16px; margin-bottom: 18px; font-size: 14px; color: var(--warn); }
.partial b { display: block; margin-bottom: 3px; }
.partial .detail { color: var(--ink-soft); font-size: 13px; }
.funnel { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
          gap: 1px; background: var(--border-soft); border: 1px solid var(--border);
          border-radius: var(--radius); overflow: hidden; margin-bottom: 18px; }
.funnel .step { background: var(--surface); padding: 12px 14px; }
.funnel .n { font-family: var(--mono); font-size: 19px; font-weight: 600; display: block; }
.funnel .k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
             color: var(--ink-faint); }
.funnel .step.final .n { color: var(--danger); }
details.counters { background: var(--surface); border: 1px solid var(--border);
                   border-radius: var(--radius); margin-bottom: 26px; }
details.counters > summary { cursor: pointer; padding: 12px 16px; font-size: 13px;
                             font-weight: 600; color: var(--ink-soft); list-style: none; }
details.counters > summary::-webkit-details-marker { display: none; }
details.counters > summary::before { content: "\\25B8 "; color: var(--ink-faint); }
details.counters[open] > summary::before { content: "\\25BE "; }
.counter-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 10px 24px; padding: 4px 16px 18px; font-size: 13px; }
.counter-grid div { display: flex; justify-content: space-between;
                    border-bottom: 1px dotted var(--border-soft); padding-bottom: 4px; gap: 12px; }
.counter-grid span:last-child { font-family: var(--mono); white-space: nowrap; }
.counter-grid .good span:last-child { color: var(--ok); }
.counter-grid .flag span:last-child { color: var(--warn); }
.filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 22px; align-items: center; }
.filters .lbl { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em;
                color: var(--ink-faint); margin-right: 4px; }
.chip { font: inherit; font-size: 12px; cursor: pointer; border: 1px solid var(--border);
        background: var(--surface); color: var(--ink-soft); padding: 5px 11px;
        border-radius: 999px; }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip .cnt { font-family: var(--mono); opacity: 0.7; margin-left: 5px; }
.group { margin-bottom: 34px; }
.group > h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
              color: var(--ink-faint); margin: 0 0 12px; display: flex;
              align-items: center; gap: 10px; }
.group > h3 code { font-family: var(--mono); font-size: 12px; color: var(--ink-soft);
                   text-transform: none; letter-spacing: 0; }
.group > h3::after { content: ""; flex: 1; height: 1px; background: var(--border); }
.finding { background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); margin-bottom: 14px; overflow: hidden; }
.finding > .head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
                   padding: 13px 16px; border-bottom: 1px solid var(--border-soft);
                   background: var(--surface-alt); }
.badge { font-family: var(--mono); font-size: 11px; letter-spacing: 0.04em; padding: 3px 9px;
         border-radius: 5px; white-space: nowrap; border: 1px solid currentColor; }
.t-direct_negation { color: #a3342c; }
.t-numerical_mismatch { color: #8a5a09; }
.t-temporal_conflict { color: #6b4396; }
.t-obligation_reversal { color: #1c6b6b; }
.t-scope_jurisdiction { color: #35508f; }
.t-unclear, .t-conditional_triplet { color: #6b7280; }
@media (prefers-color-scheme: dark) {
  .t-direct_negation { color: #e08279; }
  .t-numerical_mismatch { color: #d8a441; }
  .t-temporal_conflict { color: #b79ae0; }
  .t-obligation_reversal { color: #63b9b9; }
  .t-scope_jurisdiction { color: #8ba6e0; }
  .t-unclear, .t-conditional_triplet { color: #9aa3ae; }
}
.subject { font-size: 12px; color: var(--ink-faint); }
.conf { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.conf .bar { width: 96px; height: 7px; border-radius: 4px; background: var(--border);
             overflow: hidden; }
.conf .bar i { display: block; height: 100%; border-radius: 4px; }
.conf .v { font-family: var(--mono); font-size: 12px; color: var(--ink-soft); min-width: 30px; }
.c-high i { background: #a3342c; }
.c-med i { background: #b8811a; }
.c-low i { background: #7f8892; }
.sides { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border-soft); }
@media (max-width: 720px) { .sides { grid-template-columns: 1fr; } }
.side { background: var(--surface); padding: 15px 16px; min-width: 0; }
.side .src { font-size: 12px; margin-bottom: 9px; display: flex; gap: 6px;
             align-items: baseline; flex-wrap: wrap; }
.side .src .file { color: var(--accent); font-family: var(--mono); font-weight: 600; }
.side .src .sec { color: var(--ink-faint); }
.side .src .pol { font-family: var(--mono); font-size: 10px; letter-spacing: 0.04em;
                  border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px;
                  color: var(--ink-faint); }
blockquote.passage { margin: 0; padding: 11px 13px; background: var(--surface-alt);
                     border-left: 3px solid var(--border); border-radius: 0 6px 6px 0;
                     font-size: 14px; color: var(--ink); white-space: pre-wrap; }
blockquote.passage mark { background: var(--mark); color: inherit;
                          box-shadow: inset 0 -1px 0 var(--mark-edge);
                          padding: 1px 2px; border-radius: 2px; }
.side .normalized { margin: 9px 0 0; font-size: 12.5px; color: var(--ink-soft); }
.side .normalized b { font-weight: 600; font-size: 10px; text-transform: uppercase;
                      letter-spacing: 0.06em; color: var(--ink-faint); display: block;
                      margin-bottom: 2px; }
.why { padding: 14px 16px; border-top: 1px solid var(--border-soft); }
.why h4 { margin: 0 0 5px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em;
          color: var(--ink-faint); font-weight: 600; }
.why p { margin: 0 0 10px; font-size: 14px; color: var(--ink); }
.why p:last-child { margin-bottom: 0; }
.hint { font-size: 13px; color: var(--ink-soft); background: var(--surface-alt);
        border: 1px solid var(--border-soft); border-radius: 6px; padding: 9px 12px; }
.hint b { color: var(--ink); }
.scores { display: flex; gap: 18px; flex-wrap: wrap; padding: 9px 16px;
          border-top: 1px solid var(--border-soft); background: var(--surface-alt);
          font-family: var(--mono); font-size: 11px; color: var(--ink-faint); }
.scores b { color: var(--ink-soft); font-weight: 600; }
details.dupes { border-top: 1px solid var(--border-soft); }
details.dupes > summary { cursor: pointer; list-style: none; padding: 9px 16px; font-size: 12px;
                          color: var(--ink-soft); background: var(--surface-alt); }
details.dupes > summary::-webkit-details-marker { display: none; }
details.dupes > summary::before { content: "\\25B8 "; color: var(--ink-faint); }
details.dupes[open] > summary::before { content: "\\25BE "; }
details.dupes .body { padding: 4px 16px 14px; font-size: 13px; color: var(--ink-soft); }
details.dupes .row { padding: 7px 0; border-bottom: 1px dotted var(--border-soft); }
details.dupes .row:last-child { border-bottom: 0; }
.empty { background: var(--surface); border: 1px solid var(--border);
         border-left: 4px solid var(--ok); border-radius: var(--radius);
         padding: 34px 30px; text-align: center; }
.empty .tick { width: 42px; height: 42px; border-radius: 50%; border: 2px solid var(--ok);
               color: var(--ok); display: inline-flex; align-items: center;
               justify-content: center; font-size: 21px; margin-bottom: 12px; }
.empty h2 { margin: 0 0 7px; font-size: 19px; }
.empty p { margin: 0 auto 6px; max-width: 620px; color: var(--ink-soft); font-size: 14px; }
.empty .caveat { font-size: 12.5px; color: var(--ink-faint); margin-top: 14px; }
footer.doc { margin-top: 44px; padding-top: 20px; border-top: 1px solid var(--border);
             font-size: 12.5px; color: var(--ink-faint); }
footer.doc .disclaimer { max-width: 720px; }
"""

_JS = """
var chips = document.querySelectorAll('.chip');
var findings = document.querySelectorAll('.finding');
for (var i = 0; i < chips.length; i++) {
  chips[i].addEventListener('click', function (event) {
    var want = event.currentTarget.getAttribute('data-type');
    for (var c = 0; c < chips.length; c++) {
      chips[c].setAttribute('aria-pressed', chips[c] === event.currentTarget ? 'true' : 'false');
    }
    for (var f = 0; f < findings.length; f++) {
      var show = want === 'all' || findings[f].getAttribute('data-type') === want;
      findings[f].style.display = show ? '' : 'none';
    }
    var groups = document.querySelectorAll('.group');
    for (var g = 0; g < groups.length; g++) {
      var visible = groups[g].querySelectorAll('.finding:not([style*="none"])').length;
      groups[g].style.display = visible ? '' : 'none';
    }
  });
}
"""


def render_html(report: ContradictionReport, *, title: str = "Contradiction Audit") -> str:
    """Render a report as a single self-contained HTML document.

    Args:
        report: The report to render.
        title: Document title, shown in the browser tab and as the page heading.

    Returns:
        A complete HTML document. Deterministic for a given report.
    """
    body = _render_findings(report) if not report.is_empty else _render_empty(report)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        '<div class="wrap">',
        _render_header(report, title),
        _render_partial_banner(report),
        _render_headline(report),
        _render_funnel(report),
        _render_counters(report),
        body,
        _render_footer(),
        "</div>",
        f"<script>{_JS}</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(part for part in parts if part)


def write_html(report: ContradictionReport, path: Path) -> None:
    """Write the rendered report to ``path``, creating parent directories as needed.

    Args:
        report: The report to render.
        path: Destination ``.html`` file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")


def _esc(value: object) -> str:
    """Escape a value for HTML text and attribute context.

    Every interpolation in this module goes through here. Claim text comes from documents the
    system did not author, so it is untrusted input as far as the renderer is concerned.
    """
    return escape(str(value), quote=True)


def _render_header(report: ContradictionReport, title: str) -> str:
    """The document title and audit identity strip."""
    meta = [
        f"<span>Corpus <code>{_esc(report.corpus_path)}</code></span>",
        f"<span>Audit <code>{_esc(report.audit_id)}</code></span>",
        f"<span>{report.document_count} document(s)</span>",
    ]
    if report.generated_at is not None:
        stamp = report.generated_at.strftime("%Y-%m-%d %H:%M %Z").strip()
        meta.insert(2, f"<span>{_esc(stamp)}</span>")
    return (
        '<header class="doc"><div class="brand">'
        f"<h1>{_esc(title)}</h1></div>"
        f'<div class="meta">{"".join(meta)}</div></header>'
    )


def _render_partial_banner(report: ContradictionReport) -> str:
    """The §4 ceiling-stopped notice, or nothing when the audit completed."""
    if not report.partial:
        return ""
    reason = report.partial_reason or "the audit stopped early"
    return (
        '<div class="partial"><b>Partial audit — this run did not finish.</b>'
        f'<span class="detail">{_esc(reason)}. The findings below are real but incomplete; '
        "re-run with a higher --max-cost to continue. Work already paid for is cached and "
        "will not be charged again.</span></div>"
    )


def _render_headline(report: ContradictionReport) -> str:
    """The one-line verdict on the corpus."""
    if report.is_empty:
        return ""
    noun = "contradiction" if report.contradiction_count == 1 else "contradictions"
    return (
        f'<div class="headline"><h2>{report.contradiction_count} {noun} '
        f"across {report.document_count} documents</h2>"
        f"<p>{report.pairs_evaluated} claim pairs evaluated by the judge, from "
        f"{report.claim_count} extracted claims. Grouped by document pair, "
        "highest confidence first.</p></div>"
    )


def _render_funnel(report: ContradictionReport) -> str:
    """The stage-by-stage counts that make a bad run diagnosable at a glance."""
    steps = [
        (report.stats.chunk_count, "Chunks"),
        (report.claim_count, "Claims"),
        (report.candidate_pair_count, "Candidates"),
        (report.stats.reranked_pair_count, "Reranked"),
        (report.pairs_evaluated, "NLI survivors"),
        (report.contradiction_count, "Contradictions"),
    ]
    cells = [
        f'<div class="step{" final" if index == len(steps) - 1 else ""}">'
        f'<span class="n">{count:,}</span><span class="k">{label}</span></div>'
        for index, (count, label) in enumerate(steps)
    ]
    return f'<div class="funnel">{"".join(cells)}</div>'


def _render_counters(report: ContradictionReport) -> str:
    """Pipeline-health and cost counters (§9.2), collapsed by default."""
    stats = report.stats
    judged = stats.judge_llm_calls + stats.judge_cache_hits
    rows = [
        (
            "good" if not stats.hallucination_count else "flag",
            "Judge hallucination rate",
            f"{_rate(stats.hallucination_count, judged):.1%} "
            f"({stats.hallucination_count}/{judged})",
        ),
        (
            "good" if not stats.rejected_evidence_count else "flag",
            "Rejected evidence quotes",
            str(stats.rejected_evidence_count),
        ),
        (
            "good" if not stats.truncated_chunk_count else "flag",
            "Truncated chunks",
            str(stats.truncated_chunk_count),
        ),
        (
            "flag" if stats.decontextualization_flags else "good",
            "Decontextualization failures",
            f"{stats.decontextualization_failure_rate:.1%} "
            f"({stats.decontextualization_flags}/{stats.claim_count})",
        ),
        ("", "Extraction cache hits", f"{stats.extraction_cache_hits}"),
        ("", "Judge LLM calls", f"{stats.judge_llm_calls}"),
        ("", "Judge cache hits", f"{stats.judge_cache_hits}"),
        ("", "Total cost", f"${report.cost.total_usd:,.2f}"),
    ]
    cells = "".join(
        f'<div class="{css}"><span>{_esc(label)}</span><span>{_esc(value)}</span></div>'
        for css, label, value in rows
    )
    return (
        '<details class="counters"><summary>Pipeline health &amp; cost</summary>'
        f'<div class="counter-grid">{cells}</div></details>'
    )


def _render_filters(report: ContradictionReport) -> str:
    """Type filter chips, ordered by the taxonomy so the row is stable across runs."""
    chips = [
        '<button class="chip" aria-pressed="true" data-type="all">All'
        f'<span class="cnt">{report.contradiction_count}</span></button>'
    ]
    for contradiction_type in ContradictionType:
        count = report.type_counts.get(contradiction_type.value)
        if not count:
            continue
        label = _TYPE_LABELS[contradiction_type.value]
        chips.append(
            f'<button class="chip" aria-pressed="false" '
            f'data-type="{_esc(contradiction_type.value)}">'
            f'{_esc(label)}<span class="cnt">{count}</span></button>'
        )
    if len(chips) <= 2:  # a single type needs no filter row
        return ""
    return f'<div class="filters"><span class="lbl">Type</span>{"".join(chips)}</div>'


def _render_findings(report: ContradictionReport) -> str:
    """The filter row plus every document-pair group."""
    groups = "".join(_render_group(group) for group in report.groups)
    return _render_filters(report) + groups


def _render_group(group: DocumentPairGroup) -> str:
    """One document pair and its findings (D34)."""
    findings = "".join(_render_finding(finding) for finding in group.findings)
    return (
        f'<section class="group"><h3><code>{_esc(group.doc_a)}</code> &#8596; '
        f"<code>{_esc(group.doc_b)}</code></h3>{findings}</section>"
    )


def _render_finding(finding: Finding) -> str:
    """One contradiction card: badge, confidence, both sides, rationale, scores."""
    type_value = finding.contradiction_type.value
    label = _TYPE_LABELS[type_value]
    parts = [
        f'<article class="finding" data-type="{_esc(type_value)}">',
        '<div class="head">',
        f'<span class="badge t-{_esc(type_value)}">{_esc(label)}</span>',
        f'<span class="subject">{_esc(finding.subject)}</span>',
        _render_confidence(finding.confidence),
        "</div>",
        '<div class="sides">',
        _render_side(finding.a),
        _render_side(finding.b),
        "</div>",
        _render_why(finding),
        _render_scores(finding),
        _render_duplicates(finding),
        "</article>",
    ]
    return "".join(part for part in parts if part)


def _render_confidence(confidence: float) -> str:
    """Confidence as a labelled bar; the number is always shown, not only the colour."""
    band = "c-high" if confidence >= 0.85 else "c-med" if confidence >= 0.6 else "c-low"
    width = max(0, min(100, round(confidence * 100)))
    return (
        f'<span class="conf {band}"><span class="bar"><i style="width:{width}%"></i></span>'
        f'<span class="v">{confidence:.2f}</span></span>'
    )


def _render_side(side: FindingSide) -> str:
    """One half of the side-by-side view, with the judge's quote marked in the passage."""
    citation = [f'<span class="file">{_esc(side.filename)}</span>']
    if side.section_heading:
        citation.append(f'<span class="sec">&sect; {_esc(side.section_heading)}</span>')
    if side.page_span:
        first, last = side.page_span
        pages = f"p. {first}" if first == last else f"pp. {first}&ndash;{last}"
        citation.append(f'<span class="sec">{pages}</span>')
    citation.append(f'<span class="pol">{_esc(side.polarity.upper())}</span>')
    return (
        f'<div class="side"><div class="src">{"".join(citation)}</div>'
        f'<blockquote class="passage">{_highlight(side)}</blockquote>'
        f'<p class="normalized"><b>Claim as compared</b>{_esc(side.claim_text)}</p></div>'
    )


def _highlight(side: FindingSide) -> str:
    """Escape the passage and wrap the judge's evidence span in ``<mark>``.

    Escaping happens per fragment, after slicing, so the ``<mark>`` tags are the only markup
    that survives and the offsets stay valid against the raw text.
    """
    if side.highlight_span is None:
        return _esc(side.evidence_quote)
    start, end = side.highlight_span
    quote = side.evidence_quote
    return f"{_esc(quote[:start])}<mark>{_esc(quote[start:end])}</mark>{_esc(quote[end:])}"


def _render_why(finding: Finding) -> str:
    """The judge's rationale and, when it offered one, the resolution hint."""
    hint = ""
    if finding.resolution_hint:
        hint = f'<div class="hint"><b>Resolution hint:</b> {_esc(finding.resolution_hint)}</div>'
    return (
        '<div class="why"><h4>Why this is a contradiction</h4>'
        f"<p>{_esc(finding.rationale)}</p>{hint}</div>"
    )


def _render_scores(finding: Finding) -> str:
    """Per-stage scores, so a reader can see why this pair reached the judge at all."""
    scores = [
        ("retrieval", finding.retrieval_score),
        ("rerank", finding.rerank_score),
        ("P(contradiction)", finding.nli_contradiction_prob),
    ]
    shown = [
        f"<span><b>{_esc(name)}</b> {value:.3f}</span>"
        for name, value in scores
        if value is not None
    ]
    return f'<div class="scores">{"".join(shown)}</div>' if shown else ""


def _render_duplicates(finding: Finding) -> str:
    """The rolled-up same-section findings, behind a disclosure."""
    if not finding.near_duplicates:
        return ""
    count = len(finding.near_duplicates)
    noun = "finding" if count == 1 else "findings"
    rows = "".join(
        f'<div class="row">{_esc(_TYPE_LABELS[dupe.contradiction_type.value])}, '
        f"confidence {dupe.confidence:.2f} &mdash; {_esc(dupe.rationale)}</div>"
        for dupe in finding.near_duplicates
    )
    return (
        f'<details class="dupes"><summary>{count} near-duplicate {noun} rolled up</summary>'
        f'<div class="body">{rows}</div></details>'
    )


def _render_empty(report: ContradictionReport) -> str:
    """The designed empty state (§7.5) — a confident result, not a blank page."""
    return (
        '<div class="empty"><div class="tick">&#10003;</div>'
        "<h2>No contradictions detected</h2>"
        f"<p>CrossCheck compared <strong>{report.claim_count} claims</strong> extracted from "
        f"<strong>{report.document_count} documents</strong> and evaluated "
        f"<strong>{report.pairs_evaluated} candidate claim pairs</strong> against the full "
        "contradiction taxonomy.</p>"
        "<p>Nothing in this corpus conflicts at the confidence threshold in force.</p>"
        '<p class="caveat">A clean result is bounded by what retrieval surfaced: pairs that '
        "never entered the candidate set were never judged.</p></div>"
    )


def _render_footer() -> str:
    """The standing caveat — CrossCheck detects, it does not adjudicate."""
    return (
        '<footer class="doc"><p class="disclaimer">CrossCheck reports pairs of statements that '
        "appear to conflict. It does not decide which statement is correct or authoritative, "
        "and it is not legal advice. Every evidence quote above was substring-validated against "
        "its source document; findings whose quotes could not be located were discarded and "
        "counted in the hallucination rate.</p></footer>"
    )


def _rate(numerator: int, denominator: int) -> float:
    """Return ``numerator / denominator``, or 0.0 when the denominator is zero."""
    return numerator / denominator if denominator else 0.0
