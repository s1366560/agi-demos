"""Shared structural scope columns for the protocol-v2 publication ledger."""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

# SHA256 of canonical {"kind":"root"}; both ORM and SQL inserts retain root compatibility.
ROOT_SCOPE_KEY_V2 = "0c7db1f10e1daaad62b5a58e3cd779dc19ded0fbdd5b44d760e95e9f0fdcb659"  # gitleaks:allow


class PluginScopeColumnsV2:
    """Exact identity metadata; these columns do not confer authorization."""

    scope_key: Mapped[str] = mapped_column(
        String(64), nullable=False, default=ROOT_SCOPE_KEY_V2, server_default=ROOT_SCOPE_KEY_V2
    )
    scope_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="root", server_default="root"
    )
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


def plugin_scope_constraints_v2(label: str) -> tuple[CheckConstraint, ...]:
    """Reject malformed hierarchy shapes, including empty non-root identifiers."""
    return (
        CheckConstraint("length(scope_key) = 64", name=f"ck_{label}_scope_key"),
        CheckConstraint(
            "(scope_kind = 'root' AND tenant_id IS NULL AND project_id IS NULL "
            "AND session_id IS NULL) OR "
            "(scope_kind = 'tenant' AND tenant_id IS NOT NULL AND project_id IS NULL "
            "AND session_id IS NULL) OR "
            "(scope_kind = 'project' AND tenant_id IS NOT NULL AND project_id IS NOT NULL "
            "AND session_id IS NULL) OR "
            "(scope_kind = 'session' AND tenant_id IS NOT NULL AND project_id IS NOT NULL "
            "AND session_id IS NOT NULL)",
            name=f"ck_{label}_scope_shape",
        ),
        CheckConstraint(
            "(tenant_id IS NULL OR length(trim(tenant_id)) > 0) AND "
            "(project_id IS NULL OR length(trim(project_id)) > 0) AND "
            "(session_id IS NULL OR length(trim(session_id)) > 0)",
            name=f"ck_{label}_scope_ids",
        ),
    )
