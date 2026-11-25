"""Short-lived socket admission and per-frame authorization for signed microphone pages."""

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.config import get_settings
from src.host.packages.release_pin import ACTIVE_APPLICATION_PIN
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    PlatformPluginPackageModel,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.project_plugin_installation import (
    ProjectPluginInstallation as Installation,
    ProjectPluginRelease as Release,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

_AUDIENCE = "memstack.signed-page-voice/1"


class VoiceGrantDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("voice_grant_revoked")


type VoiceGrantQuery = Select[tuple[list[str]]]


def _signing_key() -> bytes:
    secret = get_settings().secret_key
    if len(secret) < 32 or secret == "dev-secret-key-change-in-production":
        raise VoiceGrantDenied()
    return hmac.digest(secret.encode(), _AUDIENCE.encode(), "sha256")


def voice_ticket(*, principal: str, tenant: str, project: str, conversation: str) -> str:
    pin = ACTIVE_APPLICATION_PIN.get()
    if not pin or (pin.tenant_id, pin.project_id) != (tenant, project):
        raise OptionalBusinessError("forbidden", "A signed microphone capability is required")
    return jwt.encode(
        {
            "aud": _AUDIENCE,
            "sub": principal,
            "tenant": tenant,
            "project": project,
            "conversation": conversation,
            "plugin": pin.plugin_id,
            "version": pin.version,
            "digest": pin.digest,
            "epoch": pin.authorization_epoch,
            "exp": datetime.now(UTC) + timedelta(seconds=60),
        },
        _signing_key(),
        algorithm="HS256",
    )


@dataclass(frozen=True, slots=True)
class PackageVoiceLease:
    user: str
    tenant: str
    project: str
    conversation: str
    plugin: str
    version: str
    digest: str
    epoch: int

    @classmethod
    def admit(
        cls, ticket: object, *, user: str, tenant: str, project: str, conversation: str
    ) -> "PackageVoiceLease":
        if not isinstance(ticket, str) or not 1 <= len(ticket) <= 4096:
            raise VoiceGrantDenied()
        try:
            grant = jwt.decode(
                ticket,
                _signing_key(),
                algorithms=["HS256"],
                audience=_AUDIENCE,
                options={"require_exp": True, "require_sub": True, "require_aud": True},
            )
        except JWTError as exc:
            raise VoiceGrantDenied() from exc
        if (
            grant.get("sub"),
            grant.get("tenant"),
            grant.get("project"),
            grant.get("conversation"),
        ) != (user, tenant, project, conversation):
            raise VoiceGrantDenied()
        if (
            not all(
                isinstance(grant.get(k), str) and grant[k] for k in ("plugin", "version", "digest")
            )
            or type(grant.get("epoch")) is not int
        ):
            raise VoiceGrantDenied()
        return cls(
            user,
            tenant,
            project,
            conversation,
            grant["plugin"],
            grant["version"],
            grant["digest"],
            grant["epoch"],
        )

    def authorization_query(self) -> VoiceGrantQuery:
        withdrawn = exists().where(
            PlatformPluginPackageModel.plugin_id == self.plugin,
            PlatformPluginPackageModel.version == self.version,
            or_(
                PlatformPluginPackageModel.revoked.is_(True),
                PlatformPluginPackageModel.security_scan_status == "failed",
            ),
        )
        # Only scalar state and approved permissions are read. The signed archive is never
        # loaded on the audio path. FOR SHARE orders PCM delivery against disable/replace.
        return (
            select(Release.permissions)
            .select_from(Installation)
            .join(
                Release,
                and_(
                    Release.project_id == Installation.project_id,
                    Release.plugin_id == Installation.plugin_id,
                    Release.version == Installation.active,
                ),
            )
            .join(
                Conversation,
                and_(
                    Conversation.project_id == Installation.project_id,
                    Conversation.tenant_id == Release.tenant_id,
                ),
            )
            .join(User, User.id == Conversation.user_id)
            .join(
                UserProject,
                and_(
                    UserProject.user_id == User.id,
                    UserProject.project_id == Installation.project_id,
                ),
            )
            .join(
                UserTenant,
                and_(UserTenant.user_id == User.id, UserTenant.tenant_id == Release.tenant_id),
            )
            .where(
                Installation.project_id == self.project,
                Installation.plugin_id == self.plugin,
                Installation.enabled.is_(True),
                Installation.active == self.version,
                Installation.authorization_epoch == self.epoch,
                Release.tenant_id == self.tenant,
                Release.digest == self.digest,
                Conversation.id == self.conversation,
                User.id == self.user,
                User.is_active.is_(True),
                UserProject.role.in_(("owner", "admin", "member")),
                ~withdrawn,
            )
            .with_for_update(
                read=True, of=(Installation, Release, Conversation, User, UserProject, UserTenant)
            )
        )


@asynccontextmanager
async def approved_voice_frame(db: AsyncSession, query: VoiceGrantQuery) -> AsyncIterator[None]:
    async with db.begin():
        permissions = await db.scalar(query)
        if permissions is None or "ui.media.microphone" not in permissions:
            raise VoiceGrantDenied()
        yield
