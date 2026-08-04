"""FastAPI service layer: upload a corpus, start an audit, poll it (spec v2 §7.7).

Four routes, as §7.7 specifies: ``GET /health``, ``POST /ingest``, ``POST /audit``,
``GET /audit/{id}``. Audits run in the background and ``POST /audit`` answers ``202`` with an
id immediately, because a real audit takes minutes and no HTTP client should hold a connection
open for it.

Three decisions here are not obvious from the route list, and each closes a hole that only
appears once the pipeline is driven by something other than a person at a terminal.

**Every audit resets the claim collection.** Retrieval's only cross-document filter is
``doc_id != self`` — there is no corpus predicate (see ``claim_repo``). On the command line an
operator remembers ``--reset-store`` when switching corpora; through an API nobody is watching,
and auditing corpus B after corpus A would silently match B's claims against A's leftovers and
report contradictions spanning two unrelated document sets. So the service resets
unconditionally rather than exposing the flag. The cost is resume-across-corpora, which an
upload-driven service never uses: each corpus arrives once, is audited once, and its verdict
cache still makes a *retry of the same corpus* cheap. Scoping retrieval by corpus properly is
the real fix and is noted as follow-up work (D47).

**One audit at a time.** The pipeline loads roughly 1.3 GB of models and is CPU-bound; two
concurrent audits would thrash a laptop and can exhaust a container. A second ``POST /audit``
while one is running gets ``409`` naming the audit already in flight, rather than being queued.
A queue is state that has to be explained, drained and bounded, and a demo service does not need
one.

**Running cost is readable mid-flight.** ``orchestrator.audit`` accepts an ``llm`` client, so the
service constructs one, keeps the reference on the task record, and reports
``CostSummary.from_tracker(llm.cost)`` on every poll. §7.7 requires that a caller can see spend
and ``partial`` state as an audit proceeds; this gets it without threading a callback through
eight pipeline stages.
"""

import asyncio
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import Field

from crosscheck import __version__, orchestrator
from crosscheck.aggregation.html_renderer import render_html
from crosscheck.aggregation.report import ContradictionReport, build_report
from crosscheck.config import Settings, get_settings
from crosscheck.ids import content_hash
from crosscheck.ingestion.parsers import SUPPORTED_SUFFIXES
from crosscheck.llm import LLMClient
from crosscheck.models import CrossCheckModel
from crosscheck.orchestrator import AuditStats, CostSummary

#: Lifecycle of a background audit. ``failed`` means the audit raised; a cost-ceiling stop is
#: *not* a failure — it completes with ``partial=True``, which is a degraded success (§4).
AuditState = Literal["queued", "running", "complete", "failed"]


class IngestResponse(CrossCheckModel):
    """What ``POST /ingest`` returns: the handle used to start an audit."""

    corpus_id: str
    document_count: int
    filenames: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(
        default_factory=list,
        description="Uploaded files whose extension no parser handles (§3 supports PDF, DOCX, "
        "Markdown and plain text). Reported rather than rejected, so one stray file does not "
        "fail an otherwise good upload.",
    )


class AuditRequest(CrossCheckModel):
    """Body of ``POST /audit``."""

    corpus_id: str
    max_cost_usd: float | None = Field(
        default=None,
        gt=0,
        description="Override the audit cost ceiling for this run. Defaults to the service's "
        "configured `max_audit_cost_usd`.",
    )


class AuditAccepted(CrossCheckModel):
    """The ``202`` body of ``POST /audit``."""

    audit_id: str
    state: AuditState
    status_url: str


class AuditStatus(CrossCheckModel):
    """What ``GET /audit/{id}`` returns.

    ``cost`` and ``partial`` are live: they reflect the running audit, not only a finished one,
    which is what makes a ceiling-stopped run visible to the caller while it happens (§7.7).
    """

    audit_id: str
    corpus_id: str
    state: AuditState
    started_at: datetime
    finished_at: datetime | None = None
    cost: CostSummary = Field(default_factory=CostSummary)
    cost_ceiling_usd: float
    partial: bool = False
    partial_reason: str | None = None
    error: str | None = None
    stats: AuditStats | None = None
    report: ContradictionReport | None = Field(
        default=None, description="Present once the state is `complete`."
    )


@dataclass
class _AuditTask:
    """One background audit and everything the status route needs to describe it."""

    audit_id: str
    corpus_id: str
    corpus_path: Path
    llm: LLMClient
    started_at: datetime
    state: AuditState = "queued"
    finished_at: datetime | None = None
    partial: bool = False
    partial_reason: str | None = None
    error: str | None = None
    stats: AuditStats | None = None
    report: ContradictionReport | None = None
    handle: asyncio.Task[None] | None = field(default=None, repr=False)

    def to_status(self) -> AuditStatus:
        """Snapshot for the wire, reading live spend off the client's tracker."""
        return AuditStatus(
            audit_id=self.audit_id,
            corpus_id=self.corpus_id,
            state=self.state,
            started_at=self.started_at,
            finished_at=self.finished_at,
            cost=CostSummary.from_tracker(self.llm.cost),
            cost_ceiling_usd=self.llm.cost_ceiling_usd,
            partial=self.partial,
            partial_reason=self.partial_reason,
            error=self.error,
            stats=self.stats,
            report=self.report,
        )


class _Registry:
    """In-process audit tracking (§7.7 is explicit that v1 must not reach for Celery).

    Deliberately not durable: a restart forgets everything, which is correct for a demo whose
    uploads are also ephemeral. The lock guards the "is one already running" check so two
    simultaneous ``POST /audit`` calls cannot both win it.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _AuditTask] = {}
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        """Guards admission of a new audit."""
        return self._lock

    def get(self, audit_id: str) -> _AuditTask | None:
        """The task with this id, or None."""
        return self._tasks.get(audit_id)

    def put(self, task: _AuditTask) -> None:
        """Record a task."""
        self._tasks[task.audit_id] = task

    def in_flight(self) -> _AuditTask | None:
        """The audit currently queued or running, if any."""
        return next((t for t in self._tasks.values() if t.state in ("queued", "running")), None)


app = FastAPI(
    title="CrossCheck",
    version=__version__,
    summary="Cross-document contradiction detection.",
)
_registry = _Registry()


def _corpus_root(settings: Settings, corpus_id: str) -> Path:
    """Directory holding an ingested corpus."""
    return settings.upload_dir / corpus_id


def _corpus_id(staged: Sequence[tuple[str, bytes]]) -> str:
    """Return a deterministic id for a set of uploaded files.

    Derived from every file's name and bytes, order-independent, so uploading the same
    documents twice lands on the same corpus directory — and therefore the same audit id and
    the same caches. That is the CLI's resume behaviour reached through HTTP.

    Bytes are hashed via their hex digest rather than decoded, so a PDF or DOCX contributes its
    real content and two different binaries can never collide by both decoding to replacement
    characters.

    Args:
        staged: ``(filename, content)`` pairs that passed validation.

    Returns:
        A stable hex id.
    """
    parts = sorted(f"{name}\x1e{sha256(payload).hexdigest()}" for name, payload in staged)
    return content_hash("corpus\x1f" + "\x1f".join(parts))


class HealthResponse(CrossCheckModel):
    """``GET /health`` body."""

    status: Literal["ok"] = "ok"
    version: str
    audit_in_flight: str | None = Field(
        default=None, description="Id of the running audit, if the service is busy."
    )


@app.get("/health")
def health() -> HealthResponse:
    """Liveness check, and whether an audit is currently occupying the service."""
    running = _registry.in_flight()
    return HealthResponse(
        version=__version__, audit_in_flight=running.audit_id if running else None
    )


@app.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest(
    settings: Annotated[Settings, Depends(get_settings)],
    files: Annotated[list[UploadFile], File(description="Documents to audit.")],
) -> IngestResponse:
    """Accept a multipart upload and stage it as a corpus.

    The corpus id is a content hash of the uploaded file *names and bytes*, so uploading the
    same documents twice lands on the same corpus and therefore the same audit id and caches —
    the resume behaviour of the CLI, reached through HTTP.

    Args:
        settings: Runtime configuration.
        files: The uploaded documents.

    Returns:
        The corpus handle, with any unparseable files listed rather than rejected.

    Raises:
        HTTPException: 400 if nothing usable was uploaded, or a file exceeds the size limit.
    """
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no files uploaded")

    staged: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    for upload in files:
        name = Path(upload.filename or "unnamed").name
        payload = await upload.read()
        if len(payload) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{name} is {len(payload)} bytes, over the {settings.max_upload_bytes} limit",
            )
        if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            skipped.append(name)
            continue
        staged.append((name, payload))

    if not staged:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"no supported documents uploaded; handled formats are {sorted(SUPPORTED_SUFFIXES)}",
        )

    corpus_id = _corpus_id(staged)
    root = _corpus_root(settings, corpus_id)
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in staged:
        (root / name).write_bytes(payload)

    logger.info(
        "ingested corpus {}: {} document(s){}",
        corpus_id,
        len(staged),
        f", {len(skipped)} skipped" if skipped else "",
    )
    return IngestResponse(
        corpus_id=corpus_id,
        document_count=len(staged),
        filenames=sorted(name for name, _ in staged),
        skipped=sorted(skipped),
    )


async def _run_audit(task: _AuditTask, settings: Settings) -> None:
    """Run one audit to completion in a worker thread, recording the outcome on ``task``.

    The orchestrator is synchronous and CPU-bound, so it goes to a thread rather than blocking
    the event loop — otherwise ``GET /audit/{id}`` could not answer while an audit ran, which
    would defeat the point of returning 202.
    """
    task.state = "running"
    try:
        result = await asyncio.to_thread(
            orchestrator.audit,
            task.corpus_path,
            settings,
            llm=task.llm,
            # Unconditional: retrieval has no corpus filter, so a stale collection would
            # silently pair this corpus against the previous one. See the module docstring.
            reset_store=True,
        )
    except Exception as exc:  # the state must record *any* failure rather than crash the loop
        task.state = "failed"
        task.error = f"{type(exc).__name__}: {exc}"
        task.finished_at = datetime.now(UTC)
        logger.exception("audit {} failed", task.audit_id)
        return

    task.stats = result.stats
    task.partial = result.partial
    task.partial_reason = result.partial_reason
    task.report = build_report(result, generated_at=datetime.now(UTC))
    task.state = "complete"
    task.finished_at = datetime.now(UTC)
    logger.info(
        "audit {} complete: {} finding(s), ${:.4f}{}",
        task.audit_id,
        task.report.contradiction_count,
        result.cost.total_usd,
        " [partial]" if result.partial else "",
    )


@app.post("/audit", status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    request: AuditRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuditAccepted:
    """Start an audit of a previously ingested corpus and return immediately.

    Args:
        request: The corpus to audit and an optional cost ceiling for this run.
        settings: Runtime configuration.

    Returns:
        The audit id and the URL to poll.

    Raises:
        HTTPException: 404 if the corpus is unknown, 409 if an audit is already running,
            503 if no LLM credentials are configured.
    """
    corpus_path = _corpus_root(settings, request.corpus_id)
    if not corpus_path.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown corpus {request.corpus_id}")

    async with _registry.lock:
        running = _registry.in_flight()
        if running is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"audit {running.audit_id} is already running; this service runs one at a time",
            )
        try:
            llm = LLMClient(settings, cost_ceiling_usd=request.max_cost_usd)
        except Exception as exc:  # surfaced to the caller as 503, not as a stack trace
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None

        task = _AuditTask(
            audit_id=orchestrator.audit_id(corpus_path),
            corpus_id=request.corpus_id,
            corpus_path=corpus_path,
            llm=llm,
            started_at=datetime.now(UTC),
        )
        _registry.put(task)
        # Held on the task record: a bare asyncio task can be garbage-collected mid-flight.
        task.handle = asyncio.create_task(_run_audit(task, settings))

    logger.info("audit {} accepted for corpus {}", task.audit_id, task.corpus_id)
    return AuditAccepted(
        audit_id=task.audit_id, state=task.state, status_url=f"/audit/{task.audit_id}"
    )


@app.get("/audit/{audit_id}")
def audit_status(audit_id: str) -> AuditStatus:
    """Poll an audit: state, live cost, `partial` flag, and the report once complete.

    Args:
        audit_id: The id returned by ``POST /audit``.

    Returns:
        The current status.

    Raises:
        HTTPException: 404 if no such audit is known to this process.
    """
    task = _registry.get(audit_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown audit {audit_id}")
    return task.to_status()


@app.get("/audit/{audit_id}/report.html", response_class=HTMLResponse)
def audit_report_html(audit_id: str) -> HTMLResponse:
    """Serve the human-readable report — the §13 demo artifact — for a finished audit.

    Not one of the four routes §7.7 lists. It exists because `html_renderer` already produces a
    self-contained page and a link a reviewer can open beats a JSON blob they have to render.

    Args:
        audit_id: The audit to render.

    Returns:
        The standalone HTML report.

    Raises:
        HTTPException: 404 if the audit is unknown, 409 if it has not finished.
    """
    task = _registry.get(audit_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown audit {audit_id}")
    if task.report is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"audit {audit_id} is {task.state}")
    return HTMLResponse(render_html(task.report))


def reset_state(*, remove_uploads: Path | None = None) -> None:
    """Clear the in-process registry, and optionally staged uploads.

    Exists for tests: the registry is module-level state, so one test's audit would otherwise
    make the next test's ``POST /audit`` return 409.

    Args:
        remove_uploads: Upload directory to delete, if given.
    """
    global _registry  # replacing the module singleton is exactly the point here
    _registry = _Registry()
    if remove_uploads is not None and remove_uploads.exists():
        shutil.rmtree(remove_uploads)
