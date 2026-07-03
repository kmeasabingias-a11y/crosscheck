"""Unit tests for the versioned prompt library."""

import pytest

from crosscheck.prompts import Prompt, load_prompt


def test_load_defaults_to_highest_version() -> None:
    prompt = load_prompt("claim_extraction_system")
    assert isinstance(prompt, Prompt)
    assert prompt.version == 1
    assert prompt.name == "claim_extraction_system"
    assert prompt.text
    assert prompt.text == prompt.text.strip()


def test_explicit_version_matches_default() -> None:
    assert (
        load_prompt("claim_extraction_system", version=1).text
        == load_prompt("claim_extraction_system").text
    )


def test_render_substitutes_and_survives_literal_braces() -> None:
    user = load_prompt("claim_extraction_user")
    payload = "[chunk_id: c1]\nRefunds within {30} days."
    rendered = user.render(chunks=payload)
    assert payload in rendered
    assert "{{chunks}}" not in rendered


def test_unknown_name_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        load_prompt("nope")


def test_missing_version_raises() -> None:
    with pytest.raises(KeyError, match="v1"):
        load_prompt("claim_extraction_system", version=99)
