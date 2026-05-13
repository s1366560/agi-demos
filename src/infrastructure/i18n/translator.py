"""gettext-style translator that reads compiled .mo catalogs lazily.

Catalogs live under ``src/infrastructure/i18n/locales/<locale>/LC_MESSAGES/<domain>.mo``
and are produced by Babel's ``pybabel compile``. If a catalog is missing (e.g. a
developer hasn't run ``make i18n-compile`` yet) the wrappers degrade gracefully
to identity — the source string is returned. This keeps tests and ad-hoc imports
working without forcing a build step.
"""

from __future__ import annotations

import gettext as _gettext_stdlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Final

from src.infrastructure.i18n.locale import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    current_locale,
)

logger = logging.getLogger(__name__)

DOMAIN: Final[str] = "messages"
_LOCALES_DIR: Final[Path] = Path(__file__).parent / "locales"


@lru_cache(maxsize=len(SUPPORTED_LOCALES) + 1)
def _load_translation(locale_code: str) -> _gettext_stdlib.NullTranslations:
    """Load (and cache) the gettext catalog for ``locale_code``.

    Returns a `NullTranslations` instance when the .mo file is missing so
    callers can blindly invoke gettext methods.
    """
    try:
        return _gettext_stdlib.translation(
            DOMAIN,
            localedir=str(_LOCALES_DIR),
            languages=[locale_code],
            fallback=True,
        )
    except OSError:
        logger.debug("No compiled catalog for locale %s; using identity", locale_code)
        return _gettext_stdlib.NullTranslations()


def _translation_for_current() -> _gettext_stdlib.NullTranslations:
    locale_code = current_locale() or DEFAULT_LOCALE
    return _load_translation(locale_code)


def gettext(message: str) -> str:
    """Translate ``message`` using the active locale's catalog."""
    return _translation_for_current().gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware gettext."""
    return _translation_for_current().ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    """Context-aware gettext (disambiguate same source string)."""
    return _translation_for_current().pgettext(context, message)


def clear_translation_cache() -> None:
    """Clear the cached catalogs (useful in tests after recompiling .mo)."""
    _load_translation.cache_clear()
