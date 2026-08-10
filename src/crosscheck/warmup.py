"""Pre-load the four local models so the first audit does not pay for the download.

CrossCheck runs three torch models and one lexical model on the machine doing the auditing:
bge-large for dense embedding (1.3 GB), bge-reranker-v2-m3 for reranking (2.2 GB),
nli-deberta-v3-base for the NLI filter (704 MB), and fastembed's BM25 for the sparse side of
hybrid retrieval (a few MB). Every one of them loads *lazily*, on first use, which is the right
behaviour for a CLI: ``crosscheck --help`` and the unit suite stay fast and offline because
nothing is fetched until an embedding is actually needed.

It is the wrong behaviour for a container. Laziness moves a 4.2 GB download into the middle of
the first audit, where it surfaces as a request that hangs for ten minutes with no progress
anywhere the caller can see it — and if the download fails, it fails as a mysterious audit error
rather than as a startup error. This module makes the download an explicit, ordered step that
happens *before* the service accepts traffic (see the ``warm-models`` service in
``docker-compose.yml``, which the API waits on via ``service_completed_successfully``).

**Why it runs real inferences rather than downloading files.** The obvious implementation is
``huggingface_hub.snapshot_download`` for each repo id. It is also wrong twice over. A full
snapshot pulls every artefact in the repo — bge-large ships ``pytorch_model.bin`` *and*
``model.safetensors`` *and* ONNX exports, so a snapshot fetches several gigabytes the pipeline
will never open, and an allow-list of filenames to avoid that is a second copy of
sentence-transformers' loading rules that would drift the moment either side changed. Driving the
real embedder, reranker and scorer through one tiny inference caches exactly the files the
pipeline opens, by construction, because it *is* the pipeline opening them.

It also buys a genuine smoke test for free: a warm-up that exits non-zero means the models cannot
load in this container at all, and it says so at startup instead of at first audit.

Model names come from :class:`~crosscheck.config.Settings`, never from a list here, so pointing
the config at a different reranker warms the reranker you configured rather than the one that was
current when this file was written.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from loguru import logger

from crosscheck.config import Settings
from crosscheck.detection.nli_filter import build_nli_scorer
from crosscheck.retrieval.reranker import build_reranker
from crosscheck.storage.embeddings import build_dense_embedder, build_sparse_embedder

#: A pair of claims that genuinely contradict, used as the probe input. The reranker and the NLI
#: scorer both take a *pair*, and feeding them a real contradiction keeps the warm-up honest:
#: whatever the models are asked to do here is the shape of what the pipeline asks of them.
_PROBE_A = "Vendors must carry liability insurance for the term of the agreement."
_PROBE_B = "Vendors are not required to carry liability insurance."


@dataclass(frozen=True)
class ModelProbe:
    """One model to warm, paired with the smallest call that forces it to load.

    Attributes:
        stage: The pipeline stage the model serves, for human-readable output.
        model_name: Identifier of the model being fetched, read from settings.
        load: Performs one real inference, which downloads and loads the model as a side
            effect. Its return value is discarded; only whether it raises matters.
    """

    stage: str
    model_name: str
    load: Callable[[], object]


@dataclass(frozen=True)
class WarmupResult:
    """The outcome of warming one model.

    Attributes:
        stage: The pipeline stage the model serves.
        model_name: Identifier of the model that was warmed.
        seconds: Wall-clock time spent loading, whether or not it succeeded.
        error: ``None`` on success, otherwise the failure rendered as a string.
    """

    stage: str
    model_name: str
    seconds: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the model loaded successfully."""
        return self.error is None


def build_probes(settings: Settings) -> list[ModelProbe]:
    """Build one probe per local model named in the settings panel.

    Ordered cheapest-first so an obviously broken environment (no network, no disk) fails on the
    few-megabyte BM25 fetch in seconds rather than partway through a 2.2 GB reranker download.

    Args:
        settings: Runtime configuration supplying the four model names.

    Returns:
        A probe per model: sparse, NLI, dense, then reranker.
    """
    return [
        ModelProbe(
            stage="sparse retrieval",
            model_name=settings.sparse_model,
            load=lambda: build_sparse_embedder(settings).embed_query(_PROBE_A),
        ),
        ModelProbe(
            stage="NLI filtering",
            model_name=settings.nli_model,
            load=lambda: build_nli_scorer(settings).score([(_PROBE_A, _PROBE_B)]),
        ),
        ModelProbe(
            stage="dense embedding",
            model_name=settings.dense_embedding_model,
            load=lambda: build_dense_embedder(settings).embed_query(_PROBE_A),
        ),
        ModelProbe(
            stage="reranking",
            model_name=settings.rerank_model,
            load=lambda: build_reranker(settings).score_pairs([(_PROBE_A, _PROBE_B)]),
        ),
    ]


def warm(probes: Sequence[ModelProbe]) -> list[WarmupResult]:
    """Run every probe, timing each and recording failures rather than raising.

    Every probe runs even after one fails. A container that is missing two models should say so
    in one run: stopping at the first failure would hide the second behind a rebuild-and-retry
    cycle that costs minutes per attempt.

    Args:
        probes: The probes to run, in order.

    Returns:
        One result per probe, in the same order. Callers decide what a failure means; this
        function never raises on a model that will not load.
    """
    results: list[WarmupResult] = []
    for index, probe in enumerate(probes, start=1):
        logger.info(
            "[{}/{}] warming {} model {!r}", index, len(probes), probe.stage, probe.model_name
        )
        started = time.monotonic()
        try:
            probe.load()
        # Deliberately broad: a model can fail to load as an OSError (no disk), a network error
        # from the hub, a torch RuntimeError, or a bare ValueError on a malformed config. The
        # point of this stage is to report which models are unusable, not to enumerate the ways.
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.error("{!r} failed to load after {:.1f}s: {}", probe.model_name, elapsed, exc)
            results.append(
                WarmupResult(
                    stage=probe.stage,
                    model_name=probe.model_name,
                    seconds=elapsed,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            elapsed = time.monotonic() - started
            logger.info("{!r} ready in {:.1f}s", probe.model_name, elapsed)
            results.append(
                WarmupResult(stage=probe.stage, model_name=probe.model_name, seconds=elapsed)
            )
    return results
