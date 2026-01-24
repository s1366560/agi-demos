from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Project(Entity):
    """Project domain entity for organizing memories"""

    tenant_id: str
    name: str
    owner_id: str
    description: Optional[str] = None
    member_ids: List[str] = field(default_factory=list)
    memory_rules: Dict[str, Any] = field(default_factory=dict)
    graph_config: Dict[str, Any] = field(default_factory=dict)
    is_public: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
