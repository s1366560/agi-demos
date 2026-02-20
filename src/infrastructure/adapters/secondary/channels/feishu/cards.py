"""Feishu card message builder and utilities."""

import json
from typing import Any, Dict, List, Optional, Union


class CardBuilder:
    """Builder for Feishu interactive cards."""
    
    @staticmethod
    def create_markdown_card(
        content: str,
        title: Optional[str] = None,
        wide_screen: bool = True
    ) -> Dict[str, Any]:
        """Create a simple markdown card.
        
        Args:
            content: Markdown content
            title: Optional card title
            wide_screen: Whether to use wide screen mode
            
        Returns:
            Card configuration dict
        """
        card = {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": wide_screen,
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ]
            }
        }
        
        if title:
            card["header"] = {
                "title": {
                    "tag": "plain_text",
                    "content": title,
                }
            }
        
        return card
    
    @staticmethod
    def create_info_card(
        title: str,
        content: List[Dict[str, Any]],
        actions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Create an info card with title and content elements.
        
        Args:
            title: Card title
            content: List of content elements (div, markdown, etc.)
            actions: Optional action buttons
            
        Returns:
            Card configuration dict
        """
        card = {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title,
                }
            },
            "body": {
                "elements": content
            }
        }
        
        if actions:
            card["body"]["elements"].append({
                "tag": "action",
                "actions": actions
            })
        
        return card
    
    @staticmethod
    def create_table_card(
        title: str,
        headers: List[str],
        rows: List[List[str]],
        column_widths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Create a card with a table.
        
        Args:
            title: Card title
            headers: Column headers
            rows: Table rows
            column_widths: Optional column width percentages
            
        Returns:
            Card configuration dict
        """
        # Build table markdown
        header_line = " | ".join(headers)
        separator = " | ".join(["---"] * len(headers))
        
        rows_lines = []
        for row in rows:
            rows_lines.append(" | ".join(row))
        
        table_md = f"{header_line}\n{separator}\n" + "\n".join(rows_lines)
        
        return CardBuilder.create_markdown_card(
            content=f"**{title}**\n\n{table_md}",
            wide_screen=True
        )
    
    @staticmethod
    def create_note_card(
        title: str,
        note_text: str,
        note_type: str = "default"  # default, info, warning, danger
    ) -> Dict[str, Any]:
        """Create a note/callout card.
        
        Args:
            title: Card title
            note_text: Note content
            note_type: Note style type
            
        Returns:
            Card configuration dict
        """
        type_emoji = {
            "default": "💡",
            "info": "ℹ️",
            "warning": "⚠️",
            "danger": "🚨",
        }
        
        emoji = type_emoji.get(note_type, "💡")
        content = f"{emoji} **{title}**\n\n{note_text}"
        
        return CardBuilder.create_markdown_card(content=content)
    
    @staticmethod
    def create_button(
        text: str,
        url: Optional[str] = None,
        value: Optional[Dict[str, Any]] = None,
        button_type: str = "default"  # default, primary, danger
    ) -> Dict[str, Any]:
        """Create a button element.
        
        Args:
            text: Button text
            url: Optional URL for link button
            value: Optional value for callback button
            button_type: Button style
            
        Returns:
            Button element dict
        """
        button = {
            "tag": "button",
            "text": {
                "tag": "plain_text",
                "content": text,
            },
            "type": button_type,
        }
        
        if url:
            button["url"] = url
        
        if value:
            button["value"] = value
        
        return button
    
    @staticmethod
    def create_divider() -> Dict[str, Any]:
        """Create a divider element."""
        return {"tag": "hr"}
    
    @staticmethod
    def create_text_element(
        text: str,
        text_type: str = "plain_text",
        bold: bool = False
    ) -> Dict[str, Any]:
        """Create a text element.
        
        Args:
            text: Text content
            text_type: "plain_text" or "lark_md"
            bold: Whether to make text bold
            
        Returns:
            Text element dict
        """
        element = {
            "tag": "text",
            "text": text,
        }
        
        if text_type == "lark_md":
            element["tag"] = "markdown"
            element["content"] = text
            del element["text"]
        
        return element


class PostBuilder:
    """Builder for Feishu rich text posts."""
    
    def __init__(self, title: str = ""):
        self.title = title
        self.content: List[List[Dict[str, Any]]] = []
        self.current_paragraph: List[Dict[str, Any]] = []
    
    def add_text(self, text: str) -> "PostBuilder":
        """Add plain text."""
        self.current_paragraph.append({
            "tag": "text",
            "text": text,
        })
        return self
    
    def add_link(self, text: str, href: str) -> "PostBuilder":
        """Add a hyperlink."""
        self.current_paragraph.append({
            "tag": "a",
            "text": text,
            "href": href,
        })
        return self
    
    def add_mention(self, user_id: str, user_name: str = "") -> "PostBuilder":
        """Add a user mention."""
        self.current_paragraph.append({
            "tag": "at",
            "user_id": user_id,
            "user_name": user_name,
        })
        return self
    
    def add_image(self, image_key: str) -> "PostBuilder":
        """Add an image."""
        self.current_paragraph.append({
            "tag": "img",
            "image_key": image_key,
        })
        return self
    
    def new_paragraph(self) -> "PostBuilder":
        """Start a new paragraph."""
        if self.current_paragraph:
            self.content.append(self.current_paragraph)
            self.current_paragraph = []
        return self
    
    def build(self) -> Dict[str, Any]:
        """Build the post content."""
        if self.current_paragraph:
            self.content.append(self.current_paragraph)
        
        post = {
            "zh_cn": {
                "title": self.title,
                "content": self.content,
            }
        }
        
        return post
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.build())


def build_mentioned_message(
    mentions: List[Dict[str, str]],
    message_text: str
) -> str:
    """Build message text with @mentions.
    
    Args:
        mentions: List of mention targets with 'id' and 'name' keys
        message_text: Original message text
        
    Returns:
        Message text with @mentions prepended
    """
    if not mentions:
        return message_text
    
    mention_texts = []
    for m in mentions:
        name = m.get("name", "")
        user_id = m.get("id", "")
        mention_texts.append(f"@{name}")
    
    return " ".join(mention_texts) + " " + message_text


def extract_post_text(content: Union[str, Dict[str, Any]]) -> str:
    """Extract plain text from a post message.
    
    Args:
        content: Post content (JSON string or dict)
        
    Returns:
        Extracted plain text
    """
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return content
    
    # Handle both zh_cn and en_us
    post_data = content.get("zh_cn", content.get("en_us", content))
    
    title = post_data.get("title", "")
    paragraphs = post_data.get("content", [])
    
    text_parts = []
    if title:
        text_parts.append(title)
    
    for paragraph in paragraphs:
        if isinstance(paragraph, list):
            para_text = ""
            for element in paragraph:
                tag = element.get("tag", "")
                if tag == "text":
                    para_text += element.get("text", "")
                elif tag == "a":
                    para_text += element.get("text", element.get("href", ""))
                elif tag == "at":
                    para_text += f"@{element.get('user_name', '')}"
                elif tag == "img":
                    para_text += "[图片]"
            text_parts.append(para_text)
    
    return "\n".join(text_parts)
