"""Bounded diagnostics for provider-declared incomplete completions."""

from typing import Literal


class ProviderCompletionError(ValueError):
    """A terminal protocol failure; retrying cannot complete the same response."""

    def __init__(self, reason: Literal["length", "content_filter"]) -> None:
        self.finish_reason = reason
        if reason == "length":
            self.code = "provider_response_incomplete"
            message = "provider_response_incomplete: finish_reason=length"
        else:
            self.code = "provider_response_filtered"
            message = "provider_response_filtered: finish_reason=content_filter"
        super().__init__(message)


def check_completion_finish_reason(reason: object) -> None:
    """Reject known incomplete results without echoing untrusted provider fields."""
    if reason == "length":
        raise ProviderCompletionError("length")
    if reason == "content_filter":
        raise ProviderCompletionError("content_filter")


def check_completion_error_code(code: object) -> None:
    """Restore a typed failure from our own structured stream error codes."""
    if code == "provider_response_incomplete":
        raise ProviderCompletionError("length")
    if code == "provider_response_filtered":
        raise ProviderCompletionError("content_filter")
