"""Backend internationalization (i18n) package.

Provides Accept-Language negotiation, a request-scoped current locale stored
in a contextvar, and gettext / ngettext wrappers that lazily load compiled
.mo translation catalogs.

Typical usage:

    from src.infrastructure.i18n import gettext as _

    raise ValueError(_("Email already in use"))

The translation lookup happens at call time against the locale active for the
current request (set by `LocaleMiddleware`). If no request is active or the
key is missing, the original string is returned, so this is safe to call from
any layer (including tests).
"""

from src.infrastructure.i18n.locale import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    current_locale,
    normalize_locale,
    resolve_locale,
    set_current_locale,
)
from src.infrastructure.i18n.translator import gettext, ngettext, pgettext

__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "current_locale",
    "gettext",
    "ngettext",
    "normalize_locale",
    "pgettext",
    "resolve_locale",
    "set_current_locale",
]
