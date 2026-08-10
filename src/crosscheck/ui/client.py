"""HTTP client for the CrossCheck service, used by the Streamlit demo (spec §7.7).

The demo drives the pipeline **over the API** rather than importing
:func:`crosscheck.orchestrator.audit` directly. That costs a network hop on localhost and buys
three things: the Phase 7 service layer stays the one way an audit is started (so its decisions
about resetting the store and refusing concurrent runs apply to the demo too, rather than being
quietly bypassed), the UI stays a client of a documented contract instead of a second entry point
into the pipeline, and the demo can point at a service running anywhere — including a container —
without the models having to load in the Streamlit process.

Request and response bodies are the API's own pydantic models, imported rather than restated.
A hand-written mirror of the schema would drift the first time a field changed, and §11 forbids
bare dicts across module boundaries in any case.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from loguru import logger

from crosscheck.api.main import (
    AuditAccepted,
    AuditRequest,
    AuditStatus,
    HealthResponse,
    IngestResponse,
)

#: How long to wait when probing for a service. Deliberately short: this runs on every page load
#: to decide which mode the demo is in, and a user staring at a blank page is worse than a demo
#: that decides quickly it is running standalone.
PROBE_TIMEOUT_SECONDS = 2.0

#: Everything else. An audit is started asynchronously and polled, so no request here is long —
#: but the service loads models on its first real call, which can take a while on a cold start.
DEFAULT_TIMEOUT_SECONDS = 30.0


class ServiceError(RuntimeError):
    """A request to the service failed, with a message fit to show a user.

    Carries ``status_code`` when the service answered and said no — 409 for an audit already in
    flight, 503 for missing credentials — so the caller can tell "the service refused" from
    "the service is not there".
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Build the error.

        Args:
            message: Human-readable explanation, shown in the UI as-is.
            status_code: HTTP status the service answered with, if it answered at all.
        """
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class UploadFile:
    """One document to upload: its filename and its bytes.

    Streamlit hands back an object with ``.name`` and ``.read()``; this is the shape the client
    wants, so the conversion happens in the app rather than the client knowing about Streamlit.
    """

    name: str
    data: bytes


class CrossCheckClient:
    """Talks to a running CrossCheck API.

    Every method raises :class:`ServiceError` rather than letting an ``httpx`` exception reach
    the UI, because the demo has to render *something* for a reader and a stack trace is not it.
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Build a client for the service at ``base_url``.

        Args:
            base_url: Root URL of the service, e.g. ``http://localhost:8000``.
            client: A pre-built ``httpx.Client``; tests inject one with a mock transport, which
                is what keeps this module testable with no server running.
            timeout: Per-request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def probe(self) -> HealthResponse | None:
        """Return the service's health, or ``None`` if it is not reachable.

        Never raises. This is the mode switch: a demo deployed without a service behind it is a
        supported configuration (D51), not an error, so an unreachable service is a fact to
        report rather than a failure to surface.
        """
        try:
            response = self._client.get(f"{self.base_url}/health", timeout=PROBE_TIMEOUT_SECONDS)
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("service probe failed for {}: {}", self.base_url, exc)
            return None
        return HealthResponse.model_validate(response.json())

    def ingest(self, files: Sequence[UploadFile]) -> IngestResponse:
        """Upload documents and stage them as a corpus.

        Args:
            files: The documents to upload.

        Returns:
            The corpus handle, including any files the service skipped as unsupported.

        Raises:
            ServiceError: If the upload is rejected or the service is unreachable.
        """
        payload = [("files", (item.name, item.data)) for item in files]
        data = self._request("POST", "/ingest", files=payload)
        return IngestResponse.model_validate(data)

    def start_audit(self, corpus_id: str, *, max_cost_usd: float | None = None) -> AuditAccepted:
        """Start an audit and return as soon as the service accepts it (202).

        Args:
            corpus_id: Handle returned by :meth:`ingest`.
            max_cost_usd: Override the service's cost ceiling for this run.

        Returns:
            The audit id and the URL to poll.

        Raises:
            ServiceError: 404 unknown corpus, 409 an audit is already running, 503 no
                credentials configured — each with the service's own message.
        """
        request = AuditRequest(corpus_id=corpus_id, max_cost_usd=max_cost_usd)
        data = self._request("POST", "/audit", json=request.model_dump(mode="json"))
        return AuditAccepted.model_validate(data)

    def audit_status(self, audit_id: str) -> AuditStatus:
        """Poll one audit.

        Args:
            audit_id: The id returned by :meth:`start_audit`.

        Returns:
            Its current state, live cost, and — once complete — the full report.

        Raises:
            ServiceError: If the audit is unknown or the service is unreachable.
        """
        data = self._request("GET", f"/audit/{audit_id}")
        return AuditStatus.model_validate(data)

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        """Issue one request, translating every failure into :class:`ServiceError`."""
        try:
            response = self._client.request(method, f"{self.base_url}{path}", **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            raise ServiceError(f"could not reach the service at {self.base_url}: {exc}") from None
        if response.is_error:
            raise ServiceError(_detail(response), status_code=response.status_code)
        return response.json()


def _detail(response: httpx.Response) -> str:
    """Pull FastAPI's ``detail`` out of an error body, falling back to the status line.

    FastAPI puts the useful message in ``detail``; a proxy or a crash will not, so the fallback
    keeps the UI from rendering an empty error box.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return f"service returned {response.status_code}"
