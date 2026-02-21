"""Feishu interactive card builders for HITL requests.

Builds card JSON compatible with Feishu Card 2.0 schema for
clarification, decision, environment variable, and permission requests.
"""
import json
from typing import Any, Dict, List, Optional


class HITLCardBuilder:
    """Builds interactive Feishu cards for HITL (Human-in-the-Loop) requests.

    Each card type includes action buttons that carry the ``hitl_request_id``
    in their ``value`` payload so the card action handler can route the
    response back to the HITL coordinator.
    """

    def build_card(
        self,
        hitl_type: str,
        request_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build a card for the given HITL type.

        Args:
            hitl_type: One of clarification, decision, env_var, permission.
            request_id: The HITL request ID for routing responses.
            data: Event data containing question, options, fields, etc.

        Returns:
            Card dict compatible with Feishu interactive message, or None.
        """
        builders = {
            "clarification": self._build_clarification,
            "clarification_asked": self._build_clarification,
            "decision": self._build_decision,
            "decision_asked": self._build_decision,
            "permission": self._build_permission,
            "permission_asked": self._build_permission,
            "env_var": self._build_env_var,
            "env_var_requested": self._build_env_var,
        }
        builder = builders.get(hitl_type)
        if not builder:
            return None
        return builder(request_id, data)

    def _build_clarification(
        self,
        request_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Card with question text + option buttons."""
        question = data.get("question", "")
        if not question:
            return None

        options = data.get("options") or []
        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": question},
        ]

        if options:
            actions = self._build_option_buttons(request_id, options)
            elements.append({"tag": "action", "actions": actions})

        return self._wrap_card(
            title="Agent needs clarification",
            template="blue",
            elements=elements,
        )

    def _build_decision(
        self,
        request_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Card with options as buttons + risk indicator."""
        question = data.get("question", "")
        if not question:
            return None

        options = data.get("options") or []
        risk_level = data.get("risk_level", "")

        content = question
        if risk_level:
            risk_icon = {"high": "[!]", "medium": "[~]", "low": ""}.get(
                risk_level.lower(), ""
            )
            if risk_icon:
                content = f"{risk_icon} **Risk: {risk_level}**\n\n{question}"

        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": content},
        ]

        if options:
            actions = self._build_option_buttons(request_id, options)
            elements.append({"tag": "action", "actions": actions})

        return self._wrap_card(
            title="Agent needs a decision",
            template="orange",
            elements=elements,
        )

    def _build_permission(
        self,
        request_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Card with Allow/Deny buttons + tool description."""
        tool_name = data.get("tool_name", "unknown tool")
        description = data.get("description") or data.get("message") or ""

        content = f"The agent wants to use **{tool_name}**."
        if description:
            content += f"\n\n{description}"

        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": content},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Allow"},
                        "type": "primary",
                        "value": {
                            "hitl_request_id": request_id,
                            "response_data": {"action": "allow"},
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Deny"},
                        "type": "danger",
                        "value": {
                            "hitl_request_id": request_id,
                            "response_data": {"action": "deny"},
                        },
                    },
                ],
            },
        ]

        return self._wrap_card(
            title="Permission Request",
            template="red",
            elements=elements,
        )

    def _build_env_var(
        self,
        request_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Card showing requested env vars (text-only, no form input in Feishu cards).

        Since Feishu cards don't support free-text input fields, we show the
        request details and ask the user to reply with the values as a message.
        """
        tool_name = data.get("tool_name", "")
        fields = data.get("fields") or []
        message = data.get("message") or ""

        field_lines = []
        for field in fields:
            name = field.get("name", "") if isinstance(field, dict) else str(field)
            desc = field.get("description", "") if isinstance(field, dict) else ""
            line = f"- `{name}`"
            if desc:
                line += f": {desc}"
            field_lines.append(line)

        content = ""
        if tool_name:
            content += f"**Tool**: {tool_name}\n\n"
        if message:
            content += f"{message}\n\n"
        if field_lines:
            content += "**Required variables:**\n" + "\n".join(field_lines)
            content += "\n\nPlease reply with the values in format:\n"
            content += "`VAR_NAME=value` (one per line)"

        if not content.strip():
            return None

        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": content},
        ]

        return self._wrap_card(
            title="Environment Variables Needed",
            template="yellow",
            elements=elements,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_option_buttons(
        self,
        request_id: str,
        options: List[Any],
        max_buttons: int = 5,
    ) -> List[Dict[str, Any]]:
        """Build button elements from option list."""
        actions: List[Dict[str, Any]] = []
        for i, opt in enumerate(options[:max_buttons]):
            if isinstance(opt, dict):
                label = str(opt.get("label", opt.get("text", opt.get("value", ""))))
                value = str(opt.get("value", opt.get("id", label)))
            else:
                label = str(opt)
                value = str(opt)

            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": "primary" if i == 0 else "default",
                "value": {
                    "hitl_request_id": request_id,
                    "response_data": {"answer": value},
                },
            })
        return actions

    def _wrap_card(
        self,
        title: str,
        template: str,
        elements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Wrap elements in a standard Feishu card envelope."""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        }
