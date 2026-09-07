#!/usr/bin/env python3
"""Generate Rust catalog parity fixtures from local Python routes, without remote refresh.

Run from the repository root:
    uv run python scripts/generate_llm_catalog_golden.py
    uv run python scripts/generate_llm_catalog_golden.py --check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.infrastructure.adapters.primary.web.routers.llm_providers import (  # noqa: E402
    list_catalog_models,
    list_models_for_provider_type,
    search_catalog_models,
)
from src.infrastructure.adapters.secondary.persistence.models import User  # noqa: E402
from src.infrastructure.llm.model_catalog import ModelCatalogService  # noqa: E402


async def generate(*, check: bool) -> bool:
    """Use the production serializer and committed snapshot as fixture authority."""
    fixture_user = User(email="catalog-fixture@example.invalid")
    responses = {
        "llm_model_catalog_list_response.json": await list_catalog_models(
            provider="cohere", include_deprecated=False, current_user=fixture_user
        ),
        "llm_model_catalog_search_response.json": await search_catalog_models(
            q="claude-fable-5", provider="anthropic", limit=1, current_user=fixture_user
        ),
        "llm_provider_models_response.json": await list_models_for_provider_type(
            provider_type="anthropic", current_user=fixture_user
        ),
    }
    models = ModelCatalogService().list_models(include_deprecated=True)
    print(f"Python snapshot: {len(models)} models; first: {models[0].name}")
    target = REPOSITORY_ROOT / "agi-stack/apps/server/tests/golden"
    matched = True
    for name, response in responses.items():
        rendered = json.dumps(response, ensure_ascii=False, indent=2) + "\n"
        path = target / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                print(f"Stale fixture: {name}")
                matched = False
        else:
            path.write_text(rendered, encoding="utf-8")
            print(f"Generated: {name}")
    return matched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check fixtures without writing")
    args = parser.parse_args()
    return 0 if asyncio.run(generate(check=args.check)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
