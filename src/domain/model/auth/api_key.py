from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class APIKey(Entity):
    """API Key domain entity for authentication"""

    user_id: str
    key_hash: str
    name: str
    is_active: bool = True
    permissions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
