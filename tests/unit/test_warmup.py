"""Unit tests for the model warm-up stage.

No model is ever loaded here. The probes are the seam: `build_probes` is tested for *which*
models it names (it must read every one from settings, so config changes cannot leave a model
un-warmed), and `warm` is tested for how it treats a probe that raises, using callables that
raise on demand. The real download is exercised by `crosscheck warm-models` against a live
network, which is not a unit test.
"""

import pytest

from crosscheck.config import Settings
from crosscheck.warmup import ModelProbe, WarmupResult, build_probes, warm


def _settings() -> Settings:
    return Settings(
        dense_embedding_model="dense/model",
        sparse_model="sparse/model",
        rerank_model="rerank/model",
        nli_model="nli/model",
    )


def _probe(name: str, *, fails: bool = False) -> ModelProbe:
    def load() -> object:
        if fails:
            raise RuntimeError(f"{name} is broken")
        return object()

    return ModelProbe(stage=f"{name} stage", model_name=name, load=load)


def test_build_probes_names_every_configured_model() -> None:
    """Each of the four models on the settings panel gets exactly one probe."""
    probes = build_probes(_settings())

    assert [probe.model_name for probe in probes] == [
        "sparse/model",
        "nli/model",
        "dense/model",
        "rerank/model",
    ]


def test_build_probes_is_lazy() -> None:
    """Building probes loads nothing — the probe bodies are not called until `warm` runs."""
    # If construction were eager this would try to download four real models from the names
    # above, which do not exist, and raise. Reaching the assertion is the test.
    probes = build_probes(_settings())

    assert all(callable(probe.load) for probe in probes)


def test_warm_reports_a_result_per_probe_in_order() -> None:
    probes = [_probe("first"), _probe("second"), _probe("third")]

    results = warm(probes)

    assert [result.model_name for result in results] == ["first", "second", "third"]
    assert all(result.ok for result in results)
    assert all(result.error is None for result in results)


def test_warm_records_a_failure_instead_of_raising() -> None:
    results = warm([_probe("broken", fails=True)])

    assert len(results) == 1
    assert not results[0].ok
    assert results[0].error is not None
    assert "RuntimeError" in results[0].error
    assert "broken is broken" in results[0].error


def test_warm_runs_every_probe_even_after_one_fails() -> None:
    """A container missing two models must report both in one run, not one per rebuild."""
    results = warm([_probe("a", fails=True), _probe("b"), _probe("c", fails=True)])

    assert [result.ok for result in results] == [False, True, False]


def test_warm_times_every_probe() -> None:
    results = warm([_probe("ok"), _probe("bad", fails=True)])

    # monotonic() differences are non-negative; a failure is timed too, so a slow failure is
    # visible rather than being reported as instant.
    assert all(result.seconds >= 0.0 for result in results)


def test_warm_handles_no_probes() -> None:
    assert warm([]) == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [(None, True), ("OSError: no space left on device", False)],
)
def test_result_ok_tracks_the_error_field(error: str | None, expected: bool) -> None:
    result = WarmupResult(stage="s", model_name="m", seconds=0.0, error=error)

    assert result.ok is expected
