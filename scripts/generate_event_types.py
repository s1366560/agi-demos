#!/usr/bin/env python3
"""Generate TypeScript type definitions from Python event types.

This script generates TypeScript type definitions for AgentEventType
to ensure Python and TypeScript are always in sync.

Usage:
    python scripts/generate_event_types.py
    # or via make
    make generate-event-types
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.domain.events.types import (
    AgentEventType,
    EventCategory,
    DELTA_EVENT_TYPES,
    HITL_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    get_frontend_event_types,
    get_event_category,
)


def generate_typescript_event_types() -> str:
    """Generate TypeScript type definitions for event types.

    Returns:
        TypeScript code as a string
    """
    lines = [
        "/**",
        " * Auto-generated event types from Python.",
        f" * Generated at: {datetime.utcnow().isoformat()}Z",
        " *",
        " * DO NOT EDIT MANUALLY - run `make generate-event-types` to regenerate.",
        " */",
        "",
        "// Event Categories",
        "export type EventCategory =",
    ]

    # Generate EventCategory
    categories = [f'  | "{cat.value}"' for cat in EventCategory]
    lines.extend(categories)
    lines.append("  ;")
    lines.append("")

    # Generate AgentEventType
    lines.append("// All Agent Event Types")
    lines.append("export type AgentEventType =")

    frontend_types = get_frontend_event_types()
    for i, event_type in enumerate(frontend_types):
        suffix = ";" if i == len(frontend_types) - 1 else ""
        lines.append(f'  | "{event_type}"{suffix}')

    lines.append("")

    # Generate event type sets
    lines.append("// Delta events (not persisted)")
    delta_types = [f'"{et.value}"' for et in DELTA_EVENT_TYPES]
    lines.append(f"export const DELTA_EVENT_TYPES: AgentEventType[] = [{', '.join(delta_types)}];")
    lines.append("")

    lines.append("// Terminal events (stream completion)")
    terminal_types = [f'"{et.value}"' for et in TERMINAL_EVENT_TYPES]
    lines.append(f"export const TERMINAL_EVENT_TYPES: AgentEventType[] = [{', '.join(terminal_types)}];")
    lines.append("")

    lines.append("// HITL events (require user response)")
    hitl_types = [f'"{et.value}"' for et in HITL_EVENT_TYPES]
    lines.append(f"export const HITL_EVENT_TYPES: AgentEventType[] = [{', '.join(hitl_types)}];")
    lines.append("")

    # Generate helper functions
    lines.append("// Helper functions")
    lines.append("export function isTerminalEvent(eventType: AgentEventType): boolean {")
    lines.append("  return TERMINAL_EVENT_TYPES.includes(eventType);")
    lines.append("}")
    lines.append("")

    lines.append("export function isDeltaEvent(eventType: AgentEventType): boolean {")
    lines.append("  return DELTA_EVENT_TYPES.includes(eventType);")
    lines.append("}")
    lines.append("")

    lines.append("export function isHITLEvent(eventType: AgentEventType): boolean {")
    lines.append("  return HITL_EVENT_TYPES.includes(eventType);")
    lines.append("}")
    lines.append("")

    # Generate event type to category mapping
    lines.append("// Event type to category mapping")
    lines.append("export const EVENT_CATEGORIES: Record<AgentEventType, EventCategory> = {")
    for event_type in AgentEventType:
        if event_type not in INTERNAL_EVENT_TYPES:
            category = get_event_category(event_type)
            lines.append(f'  "{event_type.value}": "{category.value}",')
    lines.append("};")
    lines.append("")

    lines.append("export function getEventCategory(eventType: AgentEventType): EventCategory {")
    lines.append('  return EVENT_CATEGORIES[eventType] || "agent";')
    lines.append("}")
    lines.append("")

    # Generate all event types array for iteration
    lines.append("// All event types (for iteration)")
    lines.append("export const ALL_EVENT_TYPES: AgentEventType[] = [")
    for event_type in frontend_types:
        lines.append(f'  "{event_type}",')
    lines.append("];")
    lines.append("")

    return "\n".join(lines)


def main():
    """Generate and write TypeScript event types."""
    # Output path
    output_path = project_root / "web" / "src" / "types" / "generated" / "eventTypes.ts"

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate content
    content = generate_typescript_event_types()

    # Write file
    output_path.write_text(content, encoding="utf-8")

    print(f"✓ Generated TypeScript event types at: {output_path}")
    print(f"  Total event types: {len(get_frontend_event_types())}")

    # Also generate a summary
    print("\n  Event type summary:")
    print(f"    - Delta events: {len(DELTA_EVENT_TYPES)}")
    print(f"    - Terminal events: {len(TERMINAL_EVENT_TYPES)}")
    print(f"    - HITL events: {len(HITL_EVENT_TYPES)}")
    print(f"    - Internal events (excluded): {len(INTERNAL_EVENT_TYPES)}")


if __name__ == "__main__":
    main()
