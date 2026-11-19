"""Single source for the public API release string.

``/health`` and the OpenAPI ``info.version`` both read this value. Package
metadata for the Python distribution is a separate identifier.
"""

API_RELEASE_VERSION = "0.3.0"
