"""Feishu interactive card builders for HITL requests.

Builds card JSON compatible with Feishu Card 2.0 schema for
clarification, decision, environment variable, and permission requests.
"""

import json
from typing import Any


class HITLCardBuilder:
    """Builds interactive Feishu cards for HITL (Human-in-the-Loop) requests.

    Each card type includes action buttons that carry the ``hitl_request_id``
    in their ``value`` payload so the card action handler can route the
    response back to the HITL coordinator.
    """

    # Normalize event type names to canonical HITL types
    _TYPE_MAP = {
        "clarification": "clarification",
        "clarification_asked": "clarification",
        "decision": "decision",
        "decision_asked": "decision",
        "permission": "permission",
        "permission_asked": "permission",
        "env_var": "env_var",
        "env_var_requested": "env_var",
    }

    def build_card(
        self,
        hitl_type: str,
        request_id: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        """Build a card for the given HITL type.

        Args:
            hitl_type: One of clarification, decision, env_var, permission
                       (or their ``_asked`` variants).
            request_id: The HITL request ID for routing responses.
            data: Event data containing question, options, fields, etc.
            tenant_id: Tenant ID embedded in button values for direct Redis publish.
            project_id: Project ID embedded in button values for direct Redis publish.

        Returns:
            Card dict compatible with Feishu interactive message, or None.
        """
        canonical = self._TYPE_MAP.get(hitl_type)
        if not canonical:
            return None

        builders = {
            "clarification": self._build_clarification,
            "decision": self._build_decision,
            "permission": self._build_permission,
            "env_var": self._build_env_var,
        }
        builder = builders.get(canonical)
        if not builder:
            return None
        return builder(request_id, canonical, data, tenant_id=tenant_id, project_id=project_id)

    def _build_clarification(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        """Card with question text + option buttons."""
        question = data.get("question", "")
        if not question:
            return None

        options = data.get("options") or []
        elements: list[dict[str, Any]] = [
            {"tag": "markdown", "content": question},
        ]

        if options:
            actions = self._build_option_buttons(
                request_id,
                hitl_type,
                options,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            elements.append({"tag": "action", "actions": actions})

        return self._wrap_card(
            title="Agent needs clarification",
            template="blue",
            elements=elements,
        )

    def _build_decision(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        """Card with options as buttons + risk indicator."""
        question = data.get("question", "")
        if not question:
            return None

        options = data.get("options") or []
        risk_level = data.get("risk_level", "")

        content = question
        if risk_level:
            risk_icon = {"high": "[!]", "medium": "[~]", "low": ""}.get(risk_level.lower(), "")
            if risk_icon:
                content = f"{risk_icon} **Risk: {risk_level}**\n\n{question}"

        elements: list[dict[str, Any]] = [
            {"tag": "markdown", "content": content},
        ]

        if options:
            actions = self._build_option_buttons(
                request_id,
                hitl_type,
                options,
                tenant_id=tenant_id,
                project_id=project_id,
            )
            elements.append({"tag": "action", "actions": actions})

        return self._wrap_card(
            title="Agent needs a decision",
            template="orange",
            elements=elements,
        )

    def _build_permission(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        """Card with Allow/Deny buttons + tool description."""
        tool_name = data.get("tool_name", "unknown tool")
        description = data.get("description") or data.get("message") or ""

        content = f"The agent wants to use **{tool_name}**."
        if description:
            content += f"\n\n{description}"

        elements: list[dict[str, Any]] = [
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
                            "hitl_type": hitl_type,
                            "response_data": json.dumps({"action": "allow"}),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Deny"},
                        "type": "danger",
                        "value": {
                            "hitl_request_id": request_id,
                            "hitl_type": hitl_type,
                            "response_data": json.dumps({"action": "deny"}),
                            "tenant_id": tenant_id,
                            "project_id": project_id,
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
        hitl_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> dict[str, Any] | None:
        """Card with form inputs for environment variable collection."""
        tool_name = data.get("tool_name", "")
        fields = data.get("fields") or []
        message = data.get("message") or ""

        if not fields and not message:
            return None

        content = ""
        if tool_name:
            content += f"**Tool**: {tool_name}\n\n"
        if message:
            content += message

        elements: list[dict[str, Any]] = []
        if content.strip():
            elements.append({"tag": "markdown", "content": content})

        # Build form with input fields
        form_elements: list[dict[str, Any]] = []
        for field in fields:
            if isinstance(field, dict):
                name = field.get("name", "")
                label = field.get("label", name)
                desc = field.get("description", "")
                required = field.get("required", False)
                input_type = field.get("input_type", "text")
            else:
                name = str(field)
                label = name
                desc = ""
                required = False
                input_type = "text"

            feishu_input_type = "password" if input_type == "password" else "text"
            input_el: dict[str, Any] = {
                "tag": "input",
                "name": name,
                "required": required,
                "input_type": feishu_input_type,
                "label": {"tag": "plain_text", "content": label},
                "label_position": "top",
                "placeholder": {
                    "tag": "plain_text",
                    "content": desc or f"Enter {label}",
                },
            }
            default_value = field.get("default_value") if isinstance(field, dict) else None
            if default_value:
                input_el["default_value"] = str(default_value)
            form_elements.append(input_el)

        # Submit button
        form_elements.append(
            {
                "tag": "button",
                "action_type": "form_submit",
                "name": "submit_env_vars",
                "text": {"tag": "plain_text", "content": "Submit"},
                "type": "primary",
                "value": {
                    "hitl_request_id": request_id,
                    "hitl_type": hitl_type,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
            }
        )

        elements.append(
            {
                "tag": "form",
                "name": f"env_form_{request_id[:8]}",
                "elements": form_elements,
            }
        )

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
        hitl_type: str,
        options: list[Any],
        max_buttons: int = 5,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """Build button elements from option list."""
        actions: list[dict[str, Any]] = []
        for i, opt in enumerate(options[:max_buttons]):
            if isinstance(opt, dict):
                label = str(opt.get("label", opt.get("text", opt.get("value", ""))))
                value = str(opt.get("value", opt.get("id", label)))
            else:
                label = str(opt)
                value = str(opt)

            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": "primary" if i == 0 else "default",
                    "value": {
                        "hitl_request_id": request_id,
                        "hitl_type": hitl_type,
                        "response_data": json.dumps({"answer": value}),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                    },
                }
            )
        return actions

    def _wrap_card(
        self,
        title: str,
        template: str,
        elements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Wrap elements in a Feishu Card JSON 2.0 envelope."""
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "body": {
                "elements": elements,
            },
        }

    def build_responded_card(
        self,
        hitl_type: str,
        selected_label: str = "",
    ) -> dict[str, Any]:
        """Build a confirmation card after the user has responded.

        This card replaces the original interactive card (with buttons)
        to show the user's selection and a "submitted" confirmation.
        Returned as the ``card.data`` in the callback response body.

        Args:
            hitl_type: The canonical HITL type.
            selected_label: The label the user selected (button text / answer).

        Returns:
            Feishu Card JSON dict (used as ``card.data`` in callback response).
        """
        type_titles = {
            "clarification": "Clarification Responded",
            "decision": "Decision Made",
            "permission": "Permission Responded",
            "env_var": "Variables Submitted",
        }
        canonical = self._TYPE_MAP.get(hitl_type, hitl_type)
        title = type_titles.get(canonical, "Response Submitted")

        content = "Your response has been submitted to the agent."
        if selected_label:
            content = f"**Selected**: {selected_label}\n\n{content}"

        return self._wrap_card(
            title=title,
            template="green",
            elements=[{"tag": "markdown", "content": content}],
        )

    # ------------------------------------------------------------------
    # CardKit-compatible builders (Card JSON 2.0)
    # ------------------------------------------------------------------

    def build_card_entity_data(
        self,
        hitl_type: str,
        request_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Build a card entity structure (JSON 2.0) with question text only.

        This creates the base card (header + question/description) without
        interactive buttons.  Buttons are added separately via the CardKit
        ``add_card_elements`` API so they can be managed independently.

        Args:
            hitl_type: HITL event type (or its ``_asked`` variant).
            request_id: The HITL request ID.
            data: Event data with question, tool_name, fields, etc.

        Returns:
            Card JSON 2.0 dict suitable for ``create_card_entity()``,
            or ``None`` if the data is insufficient.
        """
        canonical = self._TYPE_MAP.get(hitl_type)
        if not canonical:
            return None

        builders = {
            "clarification": self._entity_clarification,
            "decision": self._entity_decision,
            "permission": self._entity_permission,
            "env_var": self._entity_env_var,
        }
        builder = builders.get(canonical)
        if not builder:
            return None
        return builder(request_id, canonical, data)

    def build_hitl_action_elements(
        self,
        hitl_type: str,
        request_id: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """Build interactive button elements for the CardKit Add Elements API.

        Returns a flat list of button element dicts (card JSON 2.0 format)
        with ``element_id`` set for each button.

        Args:
            hitl_type: HITL event type.
            request_id: The HITL request ID.
            data: Event data with options, etc.
            tenant_id: Tenant ID embedded in button values for direct Redis publish.
            project_id: Project ID embedded in button values for direct Redis publish.

        Returns:
            List of button element dicts, empty if no buttons are needed.
        """
        canonical = self._TYPE_MAP.get(hitl_type)
        if not canonical:
            return []

        if canonical in ("clarification", "decision"):
            options = data.get("options") or []
            if not options:
                return []
            return self._build_cardkit_option_buttons(
                request_id,
                canonical,
                options,
                tenant_id=tenant_id,
                project_id=project_id,
            )

        if canonical == "permission":
            return self._build_cardkit_permission_buttons(
                request_id,
                canonical,
                tenant_id=tenant_id,
                project_id=project_id,
            )

        # env_var uses form container with input fields
        if canonical == "env_var":
            return self._build_cardkit_env_var_form(
                request_id,
                canonical,
                data,
                tenant_id=tenant_id,
                project_id=project_id,
            )

    # ------------------------------------------------------------------
    # CardKit entity builders (JSON 2.0 base cards, no buttons)
    # ------------------------------------------------------------------

    def _entity_clarification(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        question = data.get("question", "")
        if not question:
            return None
        return self._wrap_card_v2(
            title="Agent needs clarification",
            template="blue",
            elements=[
                {
                    "tag": "markdown",
                    "element_id": f"hitl_q_{request_id[:8]}",
                    "content": question,
                }
            ],
        )

    def _entity_decision(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        question = data.get("question", "")
        if not question:
            return None
        risk_level = data.get("risk_level", "")
        content = question
        if risk_level:
            risk_icon = {"high": "[!]", "medium": "[~]", "low": ""}.get(risk_level.lower(), "")
            if risk_icon:
                content = f"{risk_icon} **Risk: {risk_level}**\n\n{question}"
        return self._wrap_card_v2(
            title="Agent needs a decision",
            template="orange",
            elements=[
                {
                    "tag": "markdown",
                    "element_id": f"hitl_q_{request_id[:8]}",
                    "content": content,
                }
            ],
        )

    def _entity_permission(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        tool_name = data.get("tool_name", "unknown tool")
        description = data.get("description") or data.get("message") or ""
        content = f"The agent wants to use **{tool_name}**."
        if description:
            content += f"\n\n{description}"
        return self._wrap_card_v2(
            title="Permission Request",
            template="red",
            elements=[
                {
                    "tag": "markdown",
                    "element_id": f"hitl_q_{request_id[:8]}",
                    "content": content,
                }
            ],
        )

    def _entity_env_var(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        tool_name = data.get("tool_name", "")
        message = data.get("message") or ""

        content = ""
        if tool_name:
            content += f"**Tool**: {tool_name}\n\n"
        if message:
            content += message
        if not content.strip():
            content = "Please provide the required environment variables."

        return self._wrap_card_v2(
            title="Environment Variables Needed",
            template="yellow",
            elements=[
                {
                    "tag": "markdown",
                    "element_id": f"hitl_q_{request_id[:8]}",
                    "content": content,
                }
            ],
        )

    # ------------------------------------------------------------------
    # CardKit button element builders
    # ------------------------------------------------------------------

    def _build_cardkit_option_buttons(
        self,
        request_id: str,
        hitl_type: str,
        options: list[Any],
        max_buttons: int = 5,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """Build button elements (JSON 2.0) for option selection."""
        buttons: list[dict[str, Any]] = []
        for i, opt in enumerate(options[:max_buttons]):
            if isinstance(opt, dict):
                label = str(opt.get("label", opt.get("text", opt.get("value", ""))))
                value = str(opt.get("value", opt.get("id", label)))
            else:
                label = str(opt)
                value = str(opt)

            buttons.append(
                {
                    "tag": "button",
                    "element_id": f"hitl_btn_{request_id[:8]}_{i}",
                    "text": {"tag": "plain_text", "content": label},
                    "type": "primary" if i == 0 else "default",
                    "width": "default",
                    "size": "medium",
                    "value": {
                        "hitl_request_id": request_id,
                        "hitl_type": hitl_type,
                        "response_data": json.dumps({"answer": value}),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                    },
                }
            )
        return buttons

    def _build_cardkit_permission_buttons(
        self,
        request_id: str,
        hitl_type: str,
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """Build Allow/Deny button elements (JSON 2.0) for permission requests."""
        return [
            {
                "tag": "button",
                "element_id": f"hitl_allow_{request_id[:8]}",
                "text": {"tag": "plain_text", "content": "Allow"},
                "type": "primary",
                "width": "default",
                "size": "medium",
                "value": {
                    "hitl_request_id": request_id,
                    "hitl_type": hitl_type,
                    "response_data": json.dumps({"action": "allow"}),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
            },
            {
                "tag": "button",
                "element_id": f"hitl_deny_{request_id[:8]}",
                "text": {"tag": "plain_text", "content": "Deny"},
                "type": "danger",
                "width": "default",
                "size": "medium",
                "value": {
                    "hitl_request_id": request_id,
                    "hitl_type": hitl_type,
                    "response_data": json.dumps({"action": "deny"}),
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
            },
        ]

    def _build_cardkit_env_var_form(
        self,
        request_id: str,
        hitl_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str = "",
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """Build a form container with input fields (JSON 2.0) for env var collection."""
        fields = data.get("fields") or []
        if not fields:
            return []

        form_elements: list[dict[str, Any]] = []
        for i, field in enumerate(fields):
            if isinstance(field, dict):
                name = field.get("name", f"var_{i}")
                label = field.get("label", name)
                desc = field.get("description", "")
                required = field.get("required", False)
                input_type = field.get("input_type", "text")
            else:
                name = str(field)
                label = name
                desc = ""
                required = False
                input_type = "text"

            feishu_input_type = "password" if input_type == "password" else "text"
            input_el: dict[str, Any] = {
                "tag": "input",
                "element_id": f"hitl_input_{request_id[:8]}_{i}",
                "name": name,
                "required": required,
                "input_type": feishu_input_type,
                "label": {"tag": "plain_text", "content": label},
                "label_position": "top",
                "placeholder": {
                    "tag": "plain_text",
                    "content": desc or f"Enter {label}",
                },
            }
            default_value = field.get("default_value") if isinstance(field, dict) else None
            if default_value:
                input_el["default_value"] = str(default_value)
            form_elements.append(input_el)

        # Submit button
        form_elements.append(
            {
                "tag": "button",
                "element_id": f"hitl_submit_{request_id[:8]}",
                "action_type": "form_submit",
                "name": "submit_env_vars",
                "text": {"tag": "plain_text", "content": "Submit"},
                "type": "primary",
                "width": "default",
                "size": "medium",
                "value": {
                    "hitl_request_id": request_id,
                    "hitl_type": hitl_type,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                },
            }
        )

        # Return a single form container element
        return [
            {
                "tag": "form",
                "element_id": f"hitl_form_{request_id[:8]}",
                "name": f"env_form_{request_id[:8]}",
                "elements": form_elements,
            }
        ]

    def _wrap_card_v2(
        self,
        title: str,
        template: str,
        elements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Wrap elements in a Feishu Card JSON 2.0 envelope.

        Card JSON 2.0 uses ``schema: "2.0"``, ``body`` instead of top-level
        ``elements``, and requires ``update_multi: true`` for CardKit updates.
        """
        return {
            "schema": "2.0",
            "config": {"update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }
