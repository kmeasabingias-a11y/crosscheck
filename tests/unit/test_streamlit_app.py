"""Smoke tests for the demo page itself, through Streamlit's AppTest harness (§7.7).

`test_ui_presenter.py` and `test_ui_client.py` cover the decisions; this covers the *page*, which
they structurally cannot. Streamlit re-runs the whole script on every interaction, so the failures
that actually happen here are import errors, session-state mistakes and exceptions raised
mid-render — none of which a unit test on a pure function would ever see. The demo is the artefact
a reader looks at first (§13), so it gets rendered in CI rather than trusted.

Explorer mode is what these exercise, by pointing the app at a port with nothing on it. That is
also the deployed configuration (D51), so it is the path most worth protecting.
"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="the demo's extra is not installed")

from streamlit.testing.v1 import AppTest

#: A port nothing is listening on, so the health probe fails and the app falls into explorer mode.
_DEAD_SERVICE = "http://127.0.0.1:59999"

#: Absolute, because AppTest resolves a relative path against its own package rather than the
#: working directory, and the suite must not depend on where pytest was invoked from.
_APP = str(Path(__file__).resolve().parents[2] / "ui" / "streamlit_app.py")


def _run(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """Render the app once in explorer mode.

    The URL is set through the environment rather than session state because the sidebar's text
    input supplies its own default on every run and would overwrite a pre-seeded value — which is
    correct behaviour for the widget, and a trap worth writing down.
    """
    monkeypatch.setenv("CROSSCHECK_API_URL", _DEAD_SERVICE)
    app = AppTest.from_file(_APP, default_timeout=120)
    app.run()
    return app


def test_the_page_renders_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _run(monkeypatch)

    assert not app.exception, app.exception
    assert [title.value for title in app.title] == ["CrossCheck"]


def test_an_unreachable_service_falls_back_to_explorer_rather_than_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No service is a supported configuration, not a failure (D51)."""
    app = _run(monkeypatch)

    assert not app.exception
    assert any("No service reachable" in info.value for info in app.info)
    # The upload screen belongs to live mode and must not appear.
    assert not any("Upload a corpus" in sub.value for sub in app.subheader)


def test_the_real_corpus_report_is_offered_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """§7.7 wants the demo shown against the real-corpus run, so it leads the list."""
    app = _run(monkeypatch)

    assert app.selectbox, "expected a report chooser in explorer mode"
    assert "800-63B" in app.selectbox[0].options[0]


def test_it_renders_the_headline_numbers_including_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _run(monkeypatch)

    labels = {metric.label: metric.value for metric in app.metric}
    assert labels["Contradictions"] == "20"
    assert labels["Documents"] == "2"
    # Cost is on screen deliberately: a demo that hides what it spent is the habit this project
    # argues against.
    assert labels["Cost"].startswith("$")


def test_findings_are_grouped_by_type_with_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _run(monkeypatch)

    headings = [sub.value for sub in app.subheader]
    assert headings, "expected one subheader per contradiction type present"
    assert all("(" in heading and heading.endswith(")") for heading in headings)
    # Taxonomy order, not by count: direct negation precedes numerical mismatch.
    assert headings == sorted(
        headings,
        key=lambda h: ["Direct", "Numerical", "Temporal", "Obligation", "Scope"].index(
            h.split()[0]
        ),
    )


def test_every_finding_is_an_expandable_card(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _run(monkeypatch)

    assert len(app.expander) >= 15, "expected at least one expander per finding"
