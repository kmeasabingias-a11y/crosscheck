"""Unit tests for the demo's API client (§7.7).

Driven through ``httpx.MockTransport``, so every path — including the ones that matter most, the
refusals — is exercised with no server running and no network.
"""

import json

import httpx
import pytest

from crosscheck.ui.client import CrossCheckClient, ServiceError, UploadFile


def _client(handler: object) -> CrossCheckClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return CrossCheckClient("http://svc:8000", client=httpx.Client(transport=transport))


def _json_response(status_code: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(body),
        headers={"content-type": "application/json"},
    )


class TestProbe:
    def test_returns_health_when_reachable(self) -> None:
        client = _client(
            lambda request: _json_response(
                200, {"status": "ok", "version": "0.1.0", "audit_in_flight": None}
            )
        )

        health = client.probe()

        assert health is not None
        assert health.version == "0.1.0"

    def test_reports_an_audit_in_flight(self) -> None:
        client = _client(
            lambda request: _json_response(
                200, {"status": "ok", "version": "0.1.0", "audit_in_flight": "abc123"}
            )
        )

        health = client.probe()

        assert health is not None
        assert health.audit_in_flight == "abc123"

    def test_unreachable_is_none_not_an_exception(self) -> None:
        """Explorer mode is a supported configuration, so no service is a fact, not a failure."""

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        assert _client(refuse).probe() is None

    def test_an_error_status_is_also_none(self) -> None:
        assert _client(lambda request: httpx.Response(503)).probe() is None


class TestIngest:
    def test_uploads_and_returns_the_corpus_handle(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.content
            return _json_response(
                201,
                {
                    "corpus_id": "cafe1234",
                    "document_count": 2,
                    "filenames": ["a.md", "b.md"],
                    "skipped": [],
                },
            )

        result = _client(handler).ingest(
            [UploadFile(name="a.md", data=b"alpha"), UploadFile(name="b.md", data=b"beta")]
        )

        assert result.corpus_id == "cafe1234"
        assert result.document_count == 2
        assert seen["url"] == "http://svc:8000/ingest"
        assert b"alpha" in seen["body"]  # type: ignore[operator]

    def test_surfaces_skipped_files(self) -> None:
        client = _client(
            lambda request: _json_response(
                201,
                {
                    "corpus_id": "c1",
                    "document_count": 1,
                    "filenames": ["a.md"],
                    "skipped": ["notes.yml"],
                },
            )
        )

        assert client.ingest([UploadFile(name="a.md", data=b"x")]).skipped == ["notes.yml"]

    def test_a_rejected_upload_raises_with_the_services_message(self) -> None:
        client = _client(
            lambda request: _json_response(413, {"detail": "notes.md exceeds the 10 MB limit"})
        )

        with pytest.raises(ServiceError) as excinfo:
            client.ingest([UploadFile(name="notes.md", data=b"x")])

        assert "exceeds the 10 MB limit" in str(excinfo.value)
        assert excinfo.value.status_code == 413


class TestStartAudit:
    def test_sends_the_corpus_and_ceiling(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return _json_response(
                202, {"audit_id": "a1", "state": "queued", "status_url": "/audit/a1"}
            )

        accepted = _client(handler).start_audit("cafe1234", max_cost_usd=1.5)

        assert accepted.audit_id == "a1"
        assert seen == {"corpus_id": "cafe1234", "max_cost_usd": 1.5}

    def test_a_concurrent_audit_raises_409_with_its_message(self) -> None:
        """The service runs one audit at a time (D47); the demo must say so, not crash."""
        client = _client(
            lambda request: _json_response(
                409, {"detail": "audit zzz is already running; this service runs one at a time"}
            )
        )

        with pytest.raises(ServiceError) as excinfo:
            client.start_audit("c1")

        assert excinfo.value.status_code == 409
        assert "already running" in str(excinfo.value)

    def test_missing_credentials_raise_503(self) -> None:
        client = _client(
            lambda request: _json_response(503, {"detail": "no ANTHROPIC_API_KEY configured"})
        )

        with pytest.raises(ServiceError) as excinfo:
            client.start_audit("c1")

        assert excinfo.value.status_code == 503


class TestAuditStatus:
    def _status(self, **overrides: object) -> dict[str, object]:
        body: dict[str, object] = {
            "audit_id": "a1",
            "corpus_id": "c1",
            "state": "running",
            "started_at": "2026-08-10T12:00:00Z",
            "cost": {"total_usd": 0.25, "call_count": 10},
            "cost_ceiling_usd": 1.0,
            "partial": False,
        }
        body.update(overrides)
        return body

    def test_live_cost_is_readable_mid_flight(self) -> None:
        client = _client(lambda request: _json_response(200, self._status()))

        status = client.audit_status("a1")

        assert status.state == "running"
        assert status.cost.total_usd == 0.25
        assert status.report is None

    def test_a_ceiling_stopped_audit_reports_partial_and_is_not_an_error(self) -> None:
        client = _client(
            lambda request: _json_response(
                200,
                self._status(state="complete", partial=True, partial_reason="cost ceiling reached"),
            )
        )

        status = client.audit_status("a1")

        assert status.state == "complete"
        assert status.partial
        assert status.partial_reason == "cost ceiling reached"

    def test_an_unknown_audit_raises(self) -> None:
        client = _client(lambda request: _json_response(404, {"detail": "unknown audit a1"}))

        with pytest.raises(ServiceError):
            client.audit_status("a1")


class TestErrorReporting:
    def test_an_unreachable_service_names_the_url(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=request)

        with pytest.raises(ServiceError) as excinfo:
            _client(refuse).audit_status("a1")

        assert "http://svc:8000" in str(excinfo.value)
        assert excinfo.value.status_code is None

    def test_a_non_json_error_body_still_produces_a_message(self) -> None:
        """A proxy or a crash will not return FastAPI's `detail`; the box must not be empty."""
        client = _client(lambda request: httpx.Response(502, content=b"<html>bad gateway</html>"))

        with pytest.raises(ServiceError) as excinfo:
            client.audit_status("a1")

        assert "502" in str(excinfo.value)
