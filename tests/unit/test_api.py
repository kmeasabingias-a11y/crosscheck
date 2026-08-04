"""Unit tests for the FastAPI service layer (§7.7).

The orchestrator is stubbed throughout — these cover routing, upload validation, the
one-audit-at-a-time rule, and how a failed or ceiling-stopped audit surfaces. Running a real
pipeline is `test_orchestrator.py`'s job and would load 1.3 GB of models here.
"""

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from crosscheck import orchestrator
from crosscheck.api import main as api
from crosscheck.config import Settings, get_settings
from crosscheck.detection.taxonomy import ContradictionType
from crosscheck.models import Claim, DocumentRef, Pair, SectionRef, Verdict
from crosscheck.orchestrator import AuditResult, AuditStats, CostSummary

_TEXT_A = "Vendors must carry liability insurance."
_TEXT_B = "Vendors are not required to carry liability insurance."


def _claim(claim_id: str, doc_id: str, section_id: str, text: str, polarity: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id=doc_id,
        section_id=section_id,
        text=text,
        evidence_quote=text,
        evidence_offset=(0, len(text)),
        subject="insurance",
        predicate="is required",
        polarity="negative" if polarity == "negative" else "positive",
    )


def _result(*, partial: bool = False) -> AuditResult:
    """A finished audit with exactly one contradiction."""
    return AuditResult(
        audit_id="aid",
        corpus_path=Path("/corpus"),
        documents=[
            DocumentRef(
                doc_id="d1",
                source_path=Path("/corpus/a.md"),
                sections=[SectionRef(section_id="s1", heading="Insurance")],
            ),
            DocumentRef(
                doc_id="d2",
                source_path=Path("/corpus/b.md"),
                sections=[SectionRef(section_id="s2", heading="Exemptions")],
            ),
        ],
        claims=[
            _claim("c1", "d1", "s1", _TEXT_A, "positive"),
            _claim("c2", "d2", "s2", _TEXT_B, "negative"),
        ],
        judged_pairs=[Pair(pair_id="p1", claim_a_id="c1", claim_b_id="c2")],
        verdicts=[
            Verdict(
                pair_id="p1",
                is_contradiction=True,
                contradiction_type=ContradictionType.OBLIGATION_REVERSAL,
                confidence=0.95,
                rationale="One mandates, the other exempts.",
                evidence_a=_TEXT_A,
                evidence_b=_TEXT_B,
            )
        ],
        stats=AuditStats(document_count=2, claim_count=2, nli_kept_count=1),
        cost=CostSummary(total_usd=0.02, call_count=3),
        partial=partial,
        partial_reason="audit cost ceiling reached while judging" if partial else None,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing uploads at a temp dir, with a key so LLMClient constructs."""
    return Settings(anthropic_api_key="test-key", upload_dir=tmp_path / "uploads")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A test client with settings overridden and the registry reset between tests."""
    api.reset_state()
    api.app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    api.reset_state()


def _upload(client: TestClient, *names: str) -> dict[str, Any]:
    """Ingest some trivial documents and return the response body."""
    files = [("files", (name, f"Content of {name}.".encode(), "text/markdown")) for name in names]
    response = client.post("/ingest", files=files)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _wait_for(
    client: TestClient, audit_id: str, *states: str, timeout: float = 5.0
) -> dict[str, Any]:
    """Poll an audit until it reaches one of ``states``.

    Each poll also yields to the event loop, which is what lets the background task progress
    under the synchronous TestClient.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/audit/{audit_id}").json()
        if body["state"] in states:
            return dict(body)
        time.sleep(0.02)
    raise AssertionError(f"audit {audit_id} never reached {states}")


class TestHealth:
    def test_reports_ok_and_version(self, client: TestClient) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["version"]
        assert body["audit_in_flight"] is None


class TestIngest:
    def test_stages_supported_documents(self, client: TestClient) -> None:
        body = _upload(client, "a.md", "b.txt")
        assert body["document_count"] == 2
        assert body["filenames"] == ["a.md", "b.txt"]
        assert body["skipped"] == []

    def test_is_deterministic_for_the_same_documents(self, client: TestClient) -> None:
        """Same bytes, same corpus id — which is what makes an HTTP retry resume (D47)."""
        assert (
            _upload(client, "a.md", "b.md")["corpus_id"]
            == _upload(client, "b.md", "a.md")["corpus_id"]
        )

    def test_different_content_gives_a_different_corpus(
        self, client: TestClient, settings: Settings
    ) -> None:
        first = _upload(client, "a.md")["corpus_id"]
        second = client.post(
            "/ingest", files=[("files", ("a.md", b"Entirely different.", "text/markdown"))]
        ).json()["corpus_id"]
        assert first != second

    def test_skips_unsupported_files_without_failing_the_upload(self, client: TestClient) -> None:
        response = client.post(
            "/ingest",
            files=[
                ("files", ("good.md", b"Real content.", "text/markdown")),
                ("files", ("nope.xyz", b"binary junk", "application/octet-stream")),
            ],
        )
        assert response.status_code == 201
        assert response.json()["filenames"] == ["good.md"]
        assert response.json()["skipped"] == ["nope.xyz"]

    def test_rejects_an_upload_with_nothing_usable(self, client: TestClient) -> None:
        response = client.post(
            "/ingest", files=[("files", ("nope.xyz", b"junk", "application/octet-stream"))]
        )
        assert response.status_code == 400
        assert "no supported documents" in response.text

    def test_rejects_an_oversized_file(self, client: TestClient, settings: Settings) -> None:
        oversized = b"x" * (settings.max_upload_bytes + 1)
        response = client.post("/ingest", files=[("files", ("big.md", oversized, "text/markdown"))])
        assert response.status_code == 400
        assert "over the" in response.text

    def test_strips_directory_components_from_filenames(self, client: TestClient) -> None:
        """A path in the filename must not escape the corpus directory."""
        response = client.post(
            "/ingest", files=[("files", ("../../etc/passwd.md", b"x", "text/markdown"))]
        )
        assert response.status_code == 201
        assert response.json()["filenames"] == ["passwd.md"]


class TestStartAudit:
    def test_unknown_corpus_is_404(self, client: TestClient) -> None:
        response = client.post("/audit", json={"corpus_id": "nosuchcorpus"})
        assert response.status_code == 404

    def test_accepts_and_completes(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(orchestrator, "audit", lambda *a, **k: _result())
        corpus_id = _upload(client, "a.md", "b.md")["corpus_id"]

        response = client.post("/audit", json={"corpus_id": corpus_id})
        assert response.status_code == 202
        accepted = response.json()
        assert accepted["status_url"] == f"/audit/{accepted['audit_id']}"

        done = _wait_for(client, accepted["audit_id"], "complete")
        assert done["report"]["contradiction_count"] == 1
        assert done["stats"]["document_count"] == 2
        assert done["finished_at"] is not None
        assert done["partial"] is False

    def test_always_resets_the_store(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Retrieval has no corpus filter, so a service must never reuse a stale collection."""
        seen: dict[str, object] = {}

        def fake_audit(corpus: Path, settings: Settings, **kwargs: object) -> AuditResult:
            seen.update(kwargs)
            return _result()

        monkeypatch.setattr(orchestrator, "audit", fake_audit)
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id}).json()
        _wait_for(client, accepted["audit_id"], "complete")
        assert seen["reset_store"] is True

    def test_honours_a_per_request_cost_ceiling(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(orchestrator, "audit", lambda *a, **k: _result())
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id, "max_cost_usd": 0.25}).json()
        assert client.get(f"/audit/{accepted['audit_id']}").json()["cost_ceiling_usd"] == 0.25

    def test_a_second_audit_is_rejected_while_one_runs(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = threading.Event()

        def blocking_audit(*args: object, **kwargs: object) -> AuditResult:
            release.wait(timeout=5)
            return _result()

        monkeypatch.setattr(orchestrator, "audit", blocking_audit)
        corpus_id = _upload(client, "a.md")["corpus_id"]
        first = client.post("/audit", json={"corpus_id": corpus_id})
        assert first.status_code == 202
        _wait_for(client, first.json()["audit_id"], "running")

        second = client.post("/audit", json={"corpus_id": corpus_id})
        assert second.status_code == 409
        assert first.json()["audit_id"] in second.text
        assert client.get("/health").json()["audit_in_flight"] == first.json()["audit_id"]

        release.set()
        _wait_for(client, first.json()["audit_id"], "complete")

    def test_missing_credentials_are_a_503(
        self, client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keyless = Settings(anthropic_api_key=None, upload_dir=tmp_path / "uploads")
        corpus_id = _upload(client, "a.md")["corpus_id"]
        api.app.dependency_overrides[get_settings] = lambda: keyless
        # The corpus was staged under the original settings; point the keyless ones at it too.
        (keyless.upload_dir / corpus_id).mkdir(parents=True, exist_ok=True)
        response = client.post("/audit", json={"corpus_id": corpus_id})
        assert response.status_code == 503


class TestAuditStatus:
    def test_unknown_audit_is_404(self, client: TestClient) -> None:
        assert client.get("/audit/nosuch").status_code == 404

    def test_a_failure_is_recorded_not_raised(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def exploding_audit(*args: object, **kwargs: object) -> AuditResult:
            raise RuntimeError("qdrant is down")

        monkeypatch.setattr(orchestrator, "audit", exploding_audit)
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id}).json()
        failed = _wait_for(client, accepted["audit_id"], "failed")
        assert failed["error"] is not None
        assert "qdrant is down" in failed["error"]
        assert failed["report"] is None

    def test_a_ceiling_stop_is_a_degraded_success(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A partial audit completes and reports why — it is not a failure (§4)."""
        monkeypatch.setattr(orchestrator, "audit", lambda *a, **k: _result(partial=True))
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id}).json()
        done = _wait_for(client, accepted["audit_id"], "complete")
        assert done["partial"] is True
        assert "ceiling" in (done["partial_reason"] or "")
        assert done["report"] is not None


class TestReportHtml:
    def test_renders_a_finished_audit(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(orchestrator, "audit", lambda *a, **k: _result())
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id}).json()
        _wait_for(client, accepted["audit_id"], "complete")

        page = client.get(f"/audit/{accepted['audit_id']}/report.html")
        assert page.status_code == 200
        assert page.text.startswith("<!DOCTYPE html>")
        assert "liability insurance" in page.text

    def test_unfinished_audit_is_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = threading.Event()
        monkeypatch.setattr(
            orchestrator, "audit", lambda *a, **k: (release.wait(timeout=5), _result())[1]
        )
        corpus_id = _upload(client, "a.md")["corpus_id"]
        accepted = client.post("/audit", json={"corpus_id": corpus_id}).json()
        _wait_for(client, accepted["audit_id"], "running")
        assert client.get(f"/audit/{accepted['audit_id']}/report.html").status_code == 409
        release.set()
        _wait_for(client, accepted["audit_id"], "complete")

    def test_unknown_audit_is_404(self, client: TestClient) -> None:
        assert client.get("/audit/nosuch/report.html").status_code == 404
