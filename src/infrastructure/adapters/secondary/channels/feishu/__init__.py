"""Feishu channel adapter with full feature support.

Features:
- Messaging: text, cards, images, files, reactions
- Documents: docx create, read, update, blocks
- Wiki: knowledge base operations
- Drive: cloud storage, file upload/download
- Bitable: multi-dimensional tables
- Media: image and file operations
- Cards: interactive card builder
- Webhook: event handling
"""

from src.infrastructure.adapters.secondary.channels.feishu.adapter import FeishuAdapter
from src.infrastructure.adapters.secondary.channels.feishu.cards import (
    CardBuilder,
    PostBuilder,
    build_mentioned_message,
    extract_post_text,
)
from src.infrastructure.adapters.secondary.channels.feishu.client import (
    FeishuClient,
    send_feishu_card,
    send_feishu_text,
)
from src.infrastructure.adapters.secondary.channels.feishu.media import (
    FeishuMediaManager,
    MediaUploadResult,
)
from src.infrastructure.adapters.secondary.channels.feishu.webhook import (
    EVENT_BOT_ADDED,
    EVENT_BOT_DELETED,
    EVENT_MESSAGE_DELETED,
    EVENT_MESSAGE_RECEIVE,
    EVENT_MESSAGE_UPDATED,
    FeishuEventDispatcher,
    FeishuWebhookHandler,
)

__all__ = [
    "EVENT_BOT_ADDED",
    "EVENT_BOT_DELETED",
    "EVENT_MESSAGE_DELETED",
    "EVENT_MESSAGE_RECEIVE",
    "EVENT_MESSAGE_UPDATED",
    # Cards
    "CardBuilder",
    # Main adapter and client
    "FeishuAdapter",
    "FeishuClient",
    "FeishuEventDispatcher",
    # Media
    "FeishuMediaManager",
    # Webhook
    "FeishuWebhookHandler",
    "MediaUploadResult",
    "PostBuilder",
    "build_mentioned_message",
    "extract_post_text",
    "send_feishu_card",
    "send_feishu_text",
]
