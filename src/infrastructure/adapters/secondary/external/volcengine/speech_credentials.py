"""Tenant-bound speech profiles reference runtime secrets without persisting credentials."""

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeechCredentials:
    profile_id: str
    app_id: str = field(repr=False)
    access_token: str = field(repr=False)
    provider: str = "volcengine"


def resolve_speech_credentials(
    profiles_json: str | None, tenant_id: str, profile_id: str | None = None
) -> SpeechCredentials:
    """Resolve only an exact tenant's declared environment references.

    Profile JSON contains id, tenant_id, provider, app_id_ref and access_token_ref.
    References use env://MEMSTACK_SPEECH_*; credential values never belong in JSON.
    """
    try:
        profiles = json.loads(profiles_json or "[]")
    except (ValueError, TypeError) as error:
        raise ValueError("speech_profiles_invalid") from error
    if not isinstance(profiles, list) or len(profiles) > 1000:
        raise ValueError("speech_profiles_invalid")
    candidates = [
        item
        for item in profiles
        if isinstance(item, dict)
        and item.get("tenant_id") == tenant_id
        and (profile_id is None or item.get("id") == profile_id)
    ]
    if len(candidates) != 1:
        raise ValueError("speech_profile_required")
    profile = candidates[0]
    if set(profile) != {"id", "tenant_id", "provider", "app_id_ref", "access_token_ref"}:
        raise ValueError("speech_profile_invalid")
    if profile["provider"] != "volcengine" or not isinstance(profile["id"], str):
        raise ValueError("speech_provider_unsupported")

    def read(reference: object) -> str:
        if not isinstance(reference, str) or not reference.startswith("env://MEMSTACK_SPEECH_"):
            raise ValueError("speech_secret_reference_invalid")
        name = reference.removeprefix("env://")
        if not name.isascii() or not all(
            char.isupper() or char.isdigit() or char == "_" for char in name
        ):
            raise ValueError("speech_secret_reference_invalid")
        value = os.environ.get(name)
        if not value:
            raise ValueError("speech_credentials_required")
        return value

    return SpeechCredentials(
        profile["id"], read(profile["app_id_ref"]), read(profile["access_token_ref"])
    )
