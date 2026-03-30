from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(kw_only=True)
class EventLog:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    event_type: str  # e.g., "gene.installed", "deploy.started", "user.login"
    message: str
    source: str  # e.g., "system", "user", "agent"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
