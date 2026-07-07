"""Unit tests for the Qdrant client/collection helpers (hermetic — no live Qdrant).

The client and collection lifecycle against a real Qdrant is exercised by the Phase-2
storage integration test; here we cover the pure id mapping and the branch logic of
``ensure_collection`` with a mocked client so it runs in CI without a service.
"""

from typing import cast
from unittest.mock import MagicMock

from qdrant_client import QdrantClient

from crosscheck.config import Settings
from crosscheck.storage import qdrant_client as qc


def _settings() -> Settings:
    return Settings(qdrant_collection="claims_test", dense_vector_size=8)


def test_point_id_deterministic_and_distinct() -> None:
    assert qc.to_point_id("abc123") == qc.to_point_id("abc123")
    assert qc.to_point_id("abc123") != qc.to_point_id("abc124")
    # A UUID5 string is 36 chars with four hyphens.
    pid = qc.to_point_id("abc123")
    assert len(pid) == 36 and pid.count("-") == 4


def test_ensure_collection_creates_when_absent() -> None:
    mock = MagicMock()
    mock.collection_exists.return_value = False
    qc.ensure_collection(cast(QdrantClient, mock), _settings())
    mock.create_collection.assert_called_once()
    # One payload index per indexed field.
    assert mock.create_payload_index.call_count == len(qc.INDEXED_FIELDS)


def test_ensure_collection_idempotent_when_present() -> None:
    mock = MagicMock()
    mock.collection_exists.return_value = True
    qc.ensure_collection(cast(QdrantClient, mock), _settings())
    mock.create_collection.assert_not_called()
    mock.delete_collection.assert_not_called()


def test_ensure_collection_recreate_drops_then_creates() -> None:
    mock = MagicMock()
    # First check (recreate guard) sees it; second check (create guard) sees it gone.
    mock.collection_exists.side_effect = [True, False]
    qc.ensure_collection(cast(QdrantClient, mock), _settings(), recreate=True)
    mock.delete_collection.assert_called_once()
    mock.create_collection.assert_called_once()
