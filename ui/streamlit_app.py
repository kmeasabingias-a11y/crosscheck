"""CrossCheck demo UI (spec §7.7).

Three screens — upload, progress, results — and two modes.

**Live mode** appears when a CrossCheck API is reachable. The demo uploads documents, starts an
audit, polls it, and renders the report: the real pipeline, driven over the real service layer.

**Explorer mode** appears when no service is reachable, and is a supported configuration rather
than a degraded one. The pipeline needs 4.2 GB of local models and a running vector store, which
no free host will give you, so the deployed demo reads reports committed to the repository —
including the NIST SP 800-63B real-corpus run — instead of pretending to compute them. That is
also the more honest artefact for a reader who has thirty seconds: the finding is the point, not
the progress bar (D51).

Every decision this page makes lives in :mod:`crosscheck.ui.presenter` and
:mod:`crosscheck.ui.client`, which import no Streamlit and are unit-tested. What is left here is
widgets.

Run it::

    uv run streamlit run ui/streamlit_app.py
"""

import os
import sys
import time
from pathlib import Path

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:  # running via `streamlit run`, not an installed entry
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from crosscheck.aggregation.report import (  # noqa: E402
    ContradictionReport,
    Finding,
    FindingSide,
)
from crosscheck.detection.taxonomy import ContradictionType  # noqa: E402
from crosscheck.ui.client import CrossCheckClient, ServiceError, UploadFile  # noqa: E402
from crosscheck.ui.presenter import (  # noqa: E402
    Mode,
    bundled_reports,
    confidence_band,
    empty_state_message,
    group_by_type,
    highlight_segments,
    load_bundled,
    summarize,
)

DEFAULT_API_URL = os.environ.get("CROSSCHECK_API_URL", "http://localhost:8000")
POLL_SECONDS = 2.0

_BAND_STYLE: dict[str, tuple[str, str]] = {
    "trustworthy": ("#1a7f37", "Well calibrated in this band."),
    "discounted": ("#bf8700", "Measurably overconfident in this band (+.18 to +.25). Discount it."),
    "low": ("#a40e26", "Low confidence — treat as a lead, not a finding."),
}

_TYPE_LABELS: dict[ContradictionType, str] = {
    ContradictionType.DIRECT_NEGATION: "Direct negation",
    ContradictionType.NUMERICAL_MISMATCH: "Numerical mismatch",
    ContradictionType.TEMPORAL_CONFLICT: "Temporal conflict",
    ContradictionType.OBLIGATION_REVERSAL: "Obligation reversal",
    ContradictionType.SCOPE_JURISDICTION: "Scope / jurisdiction",
}


def _init_state() -> None:
    """Seed session state once, so reruns do not reset an audit in flight."""
    st.session_state.setdefault("audit_id", None)
    st.session_state.setdefault("corpus_id", None)
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("error", None)


def _client() -> CrossCheckClient:
    return CrossCheckClient(st.session_state.get("api_url", DEFAULT_API_URL))


def _escape(text: str) -> str:
    """Escape a passage fragment for the small amount of raw HTML this page emits.

    Escaping happens per fragment, *after* the span has been sliced, so the ``<mark>`` tags are
    the only markup that survives and the highlight offsets stay valid against the raw text —
    the same order of operations as ``html_renderer``.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_passage(label: str, side: FindingSide) -> None:
    """One side of a contradiction: citation, then the passage with the quote marked."""
    heading = side.section_heading or side.section_id
    st.caption(f"**{label}** · `{side.filename}` · {heading}")
    body = "".join(
        f"<mark style='background:#fff3a3;padding:0 .1em;border-radius:2px'>"
        f"{_escape(segment.text)}</mark>"
        if segment.highlighted
        else _escape(segment.text)
        for segment in highlight_segments(side)
    )
    st.markdown(
        f"<blockquote style='border-left:3px solid #d0d7de;margin:0;padding:.35rem .8rem;"
        f"color:#24292f;font-size:.92rem'>{body}</blockquote>",
        unsafe_allow_html=True,
    )


def _render_finding(finding: Finding, index: int) -> None:
    """One expandable contradiction card (§7.7)."""
    band = confidence_band(finding.confidence)
    colour, note = _BAND_STYLE[band]
    title = f"{finding.confidence:.2f} · {finding.subject[:70]}"
    with st.expander(title, expanded=index == 0):
        st.markdown(
            f"<div style='height:8px;border-radius:4px;background:linear-gradient(90deg,"
            f"{colour} {finding.confidence:.0%}, #e6e8eb {finding.confidence:.0%})'></div>"
            f"<div style='font-size:.78rem;color:#57606a;margin-top:.25rem'>{note}</div>",
            unsafe_allow_html=True,
        )
        left, right = st.columns(2)
        with left:
            _render_passage("A", finding.a)
        with right:
            _render_passage("B", finding.b)

        st.markdown("**Why this is a contradiction**")
        st.write(finding.rationale)
        if finding.resolution_hint:
            st.info(f"**Resolution hint:** {finding.resolution_hint}")
        if finding.near_duplicates:
            with st.expander(f"{len(finding.near_duplicates)} near-duplicate(s)"):
                for dupe in finding.near_duplicates:
                    st.caption(f"{dupe.confidence:.2f} · {dupe.subject}")
                    st.write(dupe.rationale)


def _render_report(report: ContradictionReport) -> None:
    """The results screen, including the designed empty state (§7.5)."""
    columns = st.columns(4)
    for column, (label, value) in zip(columns, summarize(report), strict=False):
        column.metric(label, value)

    if report.partial:
        st.warning(f"This audit is **partial**: {report.partial_reason}")

    if report.is_empty:
        st.success(empty_state_message(report))
        st.caption(
            "A clean corpus is a result, not a failure — the pipeline ran end to end and found "
            "nothing to report."
        )
        return

    for contradiction_type, findings in group_by_type(report.findings):
        label = _TYPE_LABELS.get(contradiction_type, contradiction_type.value)
        st.subheader(f"{label} ({len(findings)})")
        for index, finding in enumerate(findings):
            _render_finding(finding, index)


def _screen_upload(client: CrossCheckClient) -> None:
    """Screen 1 — choose documents and start an audit."""
    st.subheader("1 · Upload a corpus")
    st.caption(
        "PDF, DOCX, Markdown or plain text. Two or more documents — contradictions are "
        "found *between* documents, never within one."
    )
    uploads = st.file_uploader(
        "Documents", accept_multiple_files=True, type=["pdf", "docx", "md", "txt"]
    )
    ceiling = st.number_input(
        "Cost ceiling (USD)",
        min_value=0.05,
        max_value=20.0,
        value=1.00,
        step=0.05,
        help="The audit stops dispatching new judge calls at this figure and reports what it has.",
    )
    if st.button("Run audit", type="primary", disabled=not uploads or len(uploads) < 2):
        files = [UploadFile(name=item.name, data=item.getvalue()) for item in uploads or []]
        try:
            ingested = client.ingest(files)
            if ingested.skipped:
                st.warning(f"Skipped unsupported file(s): {', '.join(ingested.skipped)}")
            accepted = client.start_audit(ingested.corpus_id, max_cost_usd=float(ceiling))
        except ServiceError as exc:
            st.session_state["error"] = str(exc)
            return
        st.session_state["corpus_id"] = ingested.corpus_id
        st.session_state["audit_id"] = accepted.audit_id
        st.session_state["report"] = None
        st.rerun()


def _screen_progress(client: CrossCheckClient) -> None:
    """Screen 2 — poll the running audit and show live cost."""
    audit_id = st.session_state["audit_id"]
    st.subheader("2 · Auditing")
    try:
        status = client.audit_status(audit_id)
    except ServiceError as exc:
        st.session_state["error"] = str(exc)
        st.session_state["audit_id"] = None
        return

    st.caption(f"Audit `{audit_id}` · state **{status.state}**")
    st.progress(1.0 if status.state == "complete" else 0.5)
    left, right = st.columns(2)
    left.metric("Spent so far", f"${status.cost.total_usd:.4f}")
    right.metric("Ceiling", f"${status.cost_ceiling_usd:.2f}")

    if status.state == "failed":
        st.error(status.error or "the audit failed")
        st.session_state["audit_id"] = None
        return
    if status.state == "complete":
        st.session_state["report"] = status.report
        st.session_state["audit_id"] = None
        st.rerun()

    st.caption(
        "The pipeline is parsing, extracting claims, embedding, retrieving, reranking, filtering "
        "with NLI, then judging. Minutes, not seconds."
    )
    time.sleep(POLL_SECONDS)
    st.rerun()


def _screen_explorer() -> None:
    """Explorer mode — read a report committed to the repository."""
    reports = bundled_reports(_REPO_ROOT)
    if not reports:
        st.info("No bundled reports found in this checkout.")
        return

    labels = [item.label for item in reports]
    chosen = st.selectbox("Report", labels, index=0)
    selected = next(item for item in reports if item.label == chosen)
    st.caption(selected.description)
    _render_report(load_bundled(selected))


def main() -> None:
    """Render the demo."""
    st.set_page_config(page_title="CrossCheck", page_icon="⚖️", layout="wide")
    _init_state()

    st.title("CrossCheck")
    st.caption(
        "Cross-document contradiction detection — every pair of statements that conflict, with "
        "evidence, a classified type, and a calibrated confidence score."
    )

    with st.sidebar:
        st.session_state["api_url"] = st.text_input("Service URL", DEFAULT_API_URL)
        health = _client().probe()
        mode: Mode = "live" if health else "explorer"
        if health:
            st.success(f"Service reachable · v{health.version}")
            if health.audit_in_flight:
                st.warning(f"Busy with audit `{health.audit_in_flight}`")
        else:
            st.info("No service reachable — exploring committed reports.")
            st.caption(
                "The pipeline needs 4.2 GB of models and a vector store. Run "
                "`docker compose up` locally to audit your own documents."
            )

    if st.session_state["error"]:
        st.error(st.session_state["error"])
        st.session_state["error"] = None

    if mode == "explorer":
        _screen_explorer()
        return

    client = _client()
    if st.session_state["audit_id"]:
        _screen_progress(client)
    elif st.session_state["report"] is not None:
        st.subheader("3 · Results")
        if st.button("← Audit another corpus"):
            st.session_state["report"] = None
            st.rerun()
        _render_report(st.session_state["report"])
    else:
        _screen_upload(client)


if __name__ == "__main__":
    main()
