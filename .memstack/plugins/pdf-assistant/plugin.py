"""PDF Assistant Plugin -- comprehensive PDF processing capabilities.

This plugin provides complete PDF processing functionality:

  1. PDF Extraction    -- extract text, images, tables, metadata
  2. PDF Creation     -- create PDF from text, HTML, images
  3. PDF Manipulation -- merge, split, rotate, crop
  4. PDF Enhancement  -- watermark, encryption, compression
  5. PDF OCR          -- extract text from scanned documents

Usage:
  plugin_manager(action="enable", plugin_name="pdf-assistant")
  plugin_manager(action="reload")
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

# ---------------------------------------------------------------------------
# Sibling module loader
# ---------------------------------------------------------------------------

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    """Load a Python module from the same directory as this plugin file."""
    file_path = _PLUGIN_DIR / module_file
    module_name = f"pdf_assistant_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# Load co-located modules
_tools_mod = _load_sibling("tools.py")
_handlers_mod = _load_sibling("handlers.py")


# ---------------------------------------------------------------------------
# Plugin config schema (JSON Schema)
# ---------------------------------------------------------------------------

PLUGIN_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "default_output_dir": {
            "type": "string",
            "description": "Default output directory for processed PDFs",
            "default": "./output/pdfs",
        },
        "max_file_size_mb": {
            "type": "integer",
            "description": "Maximum PDF file size in MB",
            "minimum": 1,
            "maximum": 500,
            "default": 50,
        },
        "ocr_enabled": {
            "type": "boolean",
            "description": "Enable OCR for scanned PDFs",
            "default": True,
        },
        "watermark_text": {
            "type": "string",
            "description": "Default watermark text",
            "default": "PDF Assistant",
        },
        "encryption_algorithm": {
            "type": "string",
            "description": "Encryption algorithm for PDF protection",
            "enum": ["AES-128", "AES-256"],
            "default": "AES-128",
        },
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------


class PDFAssistantPlugin:
    """Comprehensive PDF processing assistant plugin."""

    name = "pdf-assistant"

    config: dict[str, Any] = {
        "default_output_dir": "./output/pdfs",
        "max_file_size_mb": 50,
        "ocr_enabled": True,
        "watermark_text": "PDF Assistant",
        "encryption_algorithm": "AES-128",
    }

    def setup(self, api: Any) -> None:
        """Register all PDF processing capabilities."""

        # -- 1. Tools ----------------------------------------------------------
        def _tool_factory(_context: Any) -> dict[str, Any]:
            return {
                "pdf_extract_text": _tools_mod.PDFExtractTextTool(),
                "pdf_extract_tables": _tools_mod.PDFExtractTablesTool(),
                "pdf_extract_images": _tools_mod.PDFExtractImagesTool(),
                "pdf_extract_metadata": _tools_mod.PDFExtractMetadataTool(),
                "pdf_merge": _tools_mod.PDFMergeTool(),
                "pdf_split": _tools_mod.PDFSplitTool(),
                "pdf_rotate": _tools_mod.PDFRotateTool(),
                "pdf_add_watermark": _tools_mod.PDFAddWatermarkTool(),
                "pdf_encrypt": _tools_mod.PDFEncryptTool(),
                "pdf_decrypt": _tools_mod.PDFDecryptTool(),
                "pdf_compress": _tools_mod.PDFCompressTool(),
                "pdf_create": _tools_mod.PDFCreateTool(),
                "pdf_ocr": _tools_mod.PDFOCRTool(),
                "pdf_get_page_count": _tools_mod.PDFGetPageCountTool(),
            }

        api.register_tool_factory(_tool_factory)

        # -- 2. Skills ---------------------------------------------------------
        # Skills are loaded from ./skills/ directory via SKILL.md files

        # -- 3. Hooks ---------------------------------------------------------
        api.register_hook(
            "before_pdf_processing",
            _handlers_mod.on_before_pdf_processing,
            priority=10,
        )
        api.register_hook(
            "after_pdf_processing",
            _handlers_mod.on_after_pdf_processing,
            priority=100,
        )

        # -- 4. HTTP Routes ----------------------------------------------------
        api.register_http_route(
            "GET",
            "/plugins/pdf-assistant/health",
            _handlers_mod.health_check_handler,
            summary="PDF Assistant plugin health check",
            tags=["pdf"],
        )
        api.register_http_route(
            "POST",
            "/plugins/pdf-assistant/extract-text",
            _handlers_mod.extract_text_handler,
            summary="Extract text from PDF",
            tags=["pdf"],
        )
        api.register_http_route(
            "POST",
            "/plugins/pdf-assistant/merge",
            _handlers_mod.merge_handler,
            summary="Merge multiple PDFs",
            tags=["pdf"],
        )
        api.register_http_route(
            "GET",
            "/plugins/pdf-assistant/stats",
            _handlers_mod.stats_handler,
            summary="PDF processing statistics",
            tags=["pdf"],
        )

        # -- 5. CLI Commands ---------------------------------------------------
        api.register_cli_command(
            "pdf-info",
            _handlers_mod.cli_info_handler,
            description="Display PDF Assistant plugin information",
        )
        api.register_cli_command(
            "pdf-convert",
            _handlers_mod.cli_convert_handler,
            description="Convert file to PDF",
            args_schema={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input file path",
                    },
                    "output": {
                        "type": "string",
                        "description": "Output PDF path",
                    },
                },
                "required": ["input", "output"],
            },
        )

        # -- 6. Lifecycle Hooks ------------------------------------------------
        api.register_lifecycle_hook("on_load", _handlers_mod.on_load_handler)
        api.register_lifecycle_hook("on_enable", _handlers_mod.on_enable_handler)
        api.register_lifecycle_hook("on_disable", _handlers_mod.on_disable_handler)
        api.register_lifecycle_hook("on_unload", _handlers_mod.on_unload_handler)

        # -- 7. Config Schema --------------------------------------------------
        api.register_config_schema(PLUGIN_CONFIG_SCHEMA)

        # -- 8. Commands -------------------------------------------------------
        api.register_command("pdf.summary", _handlers_mod.pdf_summary_command)

        # -- 9. Services -------------------------------------------------------
        api.register_service("pdf-storage", _handlers_mod.PDFStorageService())

        # -- 10. Providers -----------------------------------------------------
        api.register_provider(
            "pdf-storage",
            _handlers_mod.PDFStorageProvider(
                default_output_dir=self.config.get("default_output_dir", "./output/pdfs")
            ),
        )


# Module-level export
plugin = PDFAssistantPlugin()
