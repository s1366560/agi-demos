"""Example usage of Channels module.

This example demonstrates how to use the Channels module
in the AGI-Demos project.
"""

import asyncio
import os

from src.domain.model.channels import ChannelConfig, Message
from src.application.services.channels import ChannelService
from src.infrastructure.adapters.secondary.channels.feishu import FeishuAdapter


async def basic_example():
    """Basic usage example."""
    # Create channel service
    service = ChannelService()
    
    # Create Feishu adapter
    feishu_config = ChannelConfig(
        enabled=True,
        app_id=os.getenv("FEISHU_APP_ID", "cli_xxx"),
        app_secret=os.getenv("FEISHU_APP_SECRET", "xxx"),
        connection_mode="websocket",
    )
    feishu = FeishuAdapter(feishu_config)
    
    # Register adapter
    service.register_adapter(feishu)
    
    # Handle incoming messages
    def on_message(message: Message):
        print(f"[{message.channel}] {message.sender.name}: {message.content.text}")
        
        # Reply if message contains "hello"
        if message.content.text and "hello" in message.content.text.lower():
            asyncio.create_task(
                feishu.send_text(message.chat_id, "Hello! 👋")
            )
    
    service.on_message(on_message)
    
    # Connect all channels
    await service.connect_all()
    
    # Send a message
    await service.send_text("feishu", "oc_xxx", "大家好！")
    
    # Get chat members
    members = await service.get_chat_members("feishu", "oc_xxx")
    print(f"Chat members: {members}")
    
    # Keep running
    await asyncio.sleep(60)
    
    # Disconnect
    await service.disconnect_all()


async def multi_channel_example():
    """Multi-channel example."""
    service = ChannelService()
    
    # Feishu
    feishu_config = ChannelConfig(
        app_id=os.getenv("FEISHU_APP_ID"),
        app_secret=os.getenv("FEISHU_APP_SECRET"),
    )
    service.register_adapter(FeishuAdapter(feishu_config))
    
    # DingTalk (when implemented)
    # dingtalk_config = ChannelConfig(...)
    # service.register_adapter(DingTalkAdapter(dingtalk_config))
    
    # WeCom (when implemented)
    # wecom_config = ChannelConfig(...)
    # service.register_adapter(WeComAdapter(wecom_config))
    
    # Unified message handling
    service.on_message(lambda msg: print(f"[ALL] {msg.channel}: {msg.content.text}"))
    
    await service.connect_all()
    
    # Broadcast to all channels
    await service.broadcast("oc_xxx", "这是一条广播消息")
    
    await asyncio.sleep(60)
    await service.disconnect_all()


async def direct_api_example():
    """Direct API usage example (without adapter)."""
    from src.infrastructure.adapters.secondary.channels.feishu import (
        send_feishu_text,
        send_feishu_card,
        FeishuClient,
    )
    
    app_id = os.getenv("FEISHU_APP_ID", "cli_xxx")
    app_secret = os.getenv("FEISHU_APP_SECRET", "xxx")
    
    # Send text
    message_id = await send_feishu_text(app_id, app_secret, "oc_xxx", "Hello!")
    print(f"Sent message: {message_id}")
    
    # Send card
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "通知"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": "这是一条卡片消息"}
            }
        ]
    }
    card_id = await send_feishu_card(app_id, app_secret, "oc_xxx", card)
    print(f"Sent card: {card_id}")
    
    # Use client for advanced operations
    client = FeishuClient(app_id, app_secret)
    
    # Get chat info
    info = await client.get_chat_info("oc_xxx")
    print(f"Chat info: {info}")
    
    # Get members
    members = await client.get_chat_members("oc_xxx")
    print(f"Members: {members}")


if __name__ == "__main__":
    # Run example
    asyncio.run(basic_example())
