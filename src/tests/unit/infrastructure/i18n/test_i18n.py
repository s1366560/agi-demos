"""Tests for src.infrastructure.i18n."""

from __future__ import annotations

import pytest

from src.infrastructure.i18n import (
    DEFAULT_LOCALE,
    current_locale,
    gettext,
    normalize_locale,
    resolve_locale,
    set_current_locale,
)
from src.infrastructure.i18n.locale import reset_current_locale


@pytest.fixture(autouse=True)
def _isolate_locale():
    """Reset the contextvar after each test so tests do not bleed locale state."""
    token = set_current_locale(DEFAULT_LOCALE)
    yield
    reset_current_locale(token)


class TestNormalizeLocale:
    def test_handles_hyphens(self) -> None:
        assert normalize_locale("zh-CN") == "zh_CN"

    def test_canonicalizes_case(self) -> None:
        assert normalize_locale("ZH-cn") == "zh_CN"

    def test_returns_none_for_empty(self) -> None:
        assert normalize_locale("") is None
        assert normalize_locale(None) is None


class TestResolveLocale:
    def test_explicit_override_wins(self) -> None:
        assert resolve_locale(accept_language="en-US,en;q=0.9", explicit="zh-CN") == "zh_CN"

    def test_accept_language_quality_ordering(self) -> None:
        assert resolve_locale(accept_language="en;q=0.5,zh-CN;q=0.9") == "zh_CN"

    def test_falls_back_to_default_when_unsupported(self) -> None:
        assert resolve_locale(accept_language="fr-FR,de;q=0.8") == DEFAULT_LOCALE

    def test_language_prefix_match(self) -> None:
        # `en` should match `en_US` even though region differs
        assert resolve_locale(accept_language="en") == "en_US"

    def test_ignores_invalid_explicit(self) -> None:
        assert resolve_locale(accept_language="zh-CN", explicit="xx-YY") == "zh_CN"


class TestGettext:
    def test_returns_chinese_when_zh_locale_set(self) -> None:
        set_current_locale("zh_CN")
        assert gettext("Invalid email or password") == "邮箱或密码错误"

    def test_returns_english_when_en_locale_set(self) -> None:
        set_current_locale("en_US")
        assert gettext("Invalid email or password") == "Invalid email or password"

    def test_unknown_key_returns_identity(self) -> None:
        set_current_locale("zh_CN")
        # Unknown source string should fall back to itself rather than raising.
        assert gettext("__definitely_not_in_catalog__") == "__definitely_not_in_catalog__"

    def test_current_locale_reflects_setter(self) -> None:
        set_current_locale("zh_CN")
        assert current_locale() == "zh_CN"
