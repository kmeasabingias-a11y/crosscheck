"""Unit tests for the Settings panel."""

import pytest
from pydantic import ValidationError

from crosscheck.config import Settings, get_settings


def test_direct_construction_overrides_defaults() -> None:
    s = Settings(log_level="DEBUG", anthropic_api_key="test-key")
    assert s.log_level == "DEBUG"
    assert s.anthropic_api_key == "test-key"


def test_explicit_cost_ceiling_is_kept() -> None:
    assert Settings(max_audit_cost_usd=2.5).max_audit_cost_usd == 2.5


def test_negative_cost_ceiling_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(max_audit_cost_usd=-1.0)


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
