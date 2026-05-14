"""Unit tests for `agent/i18n/language_resolver`."""

from __future__ import annotations

import pytest

from src.infrastructure.agent.i18n import (
    directive_for,
    normalize_language,
    resolve_response_language,
)
from src.infrastructure.i18n import set_current_locale


@pytest.fixture(autouse=True)
def _reset_locale():
    """Each test starts with no active locale."""
    set_current_locale(None)
    yield
    set_current_locale(None)


class TestNormalizeLanguage:
    def test_returns_none_for_empty(self):
        assert normalize_language(None) is None
        assert normalize_language("") is None
        assert normalize_language("   ") is None

    def test_returns_none_for_unsupported(self):
        assert normalize_language("fr-FR") is None
        assert normalize_language("ja") is None

    @pytest.mark.parametrize(
        "value",
        ["zh-CN", "zh_CN", "zh", "zh-Hans", "zh-Hans-CN", "ZH-cn"],
    )
    def test_accepts_chinese_aliases(self, value):
        assert normalize_language(value) == "zh-CN"

    @pytest.mark.parametrize("value", ["en-US", "en_US", "en", "en-GB", "EN"])
    def test_accepts_english_aliases(self, value):
        assert normalize_language(value) == "en-US"


class TestResolveResponseLanguage:
    def test_runtime_override_wins(self):
        set_current_locale("zh_CN")
        result = resolve_response_language(
            runtime_override="en-US", preferred_language="zh-CN"
        )
        assert result == "en-US"

    def test_falls_back_to_preferred_language(self):
        set_current_locale("en_US")
        result = resolve_response_language(preferred_language="zh-CN")
        assert result == "zh-CN"

    def test_falls_back_to_current_locale(self):
        set_current_locale("zh_CN")
        assert resolve_response_language() == "zh-CN"

    def test_defaults_to_en_us(self):
        assert resolve_response_language() == "en-US"

    def test_ignores_unsupported_override(self):
        set_current_locale("zh_CN")
        # Unsupported override falls through to preferred, then locale.
        result = resolve_response_language(runtime_override="fr-FR")
        assert result == "zh-CN"


class TestDirectiveFor:
    def test_includes_label_and_tag_for_chinese(self):
        directive = directive_for("zh-CN")
        assert "[Language Directive]" in directive
        assert "Chinese (Simplified)" in directive
        assert "zh-CN" in directive

    def test_includes_label_and_tag_for_english(self):
        directive = directive_for("en-US")
        assert "[Language Directive]" in directive
        assert "English" in directive
        assert "en-US" in directive

    def test_preserves_machine_surfaces_clause(self):
        directive = directive_for("zh-CN")
        # Tool args / code must stay original; this clause is load-bearing.
        assert "tool arguments" in directive
        assert "code" in directive
