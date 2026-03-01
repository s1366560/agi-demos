"""PDF Assistant Handlers -- Hooks, HTTP routes, CLI commands, services.

This module implements all the event handlers and HTTP endpoints
for the PDF Assistant plugin.
"""

from __future__ import annotations

import os
from typing import Any

# ============================================================================
# Statistics tracking
# ============================================================================

_stats = {
    "total_processed": 0,
    "total_pages_processed": 0,
    "operations": {
        "extract_text": 0,
        "extract_tables": 0,
        "extract_metadata": 0,
        "merge": 0,
        "split": 0,
        "rotate": 0,
        "watermark": 0,
        "encrypt": 0,
        "compress": 0,
        "create": 0,
        "ocr": 0,
    },
}


# ============================================================================
# Hook Handlers
# ============================================================================


async def on_before_pdf_processing(context: dict[str, Any]) -> dict[str, Any]:
    """Hook called before PDF processing starts.

    Can be used to:
    - Validate input file exists
    - Check file size limits
    - Log processing start
    """
    input_file = context.get("input_file")
    operation = context.get("operation", "unknown")

    # Validate input file
    if input_file and not os.path.exists(input_file):
        return {
            "continue": False,
            "error": f"Input file not found: {input_file}",
        }

    # Check file size (if configured)
    if input_file and os.path.exists(input_file):
        file_size_mb = os.path.getsize(input_file) / (1024 * 1024)
        max_size = context.get("max_file_size_mb", 50)
        if file_size_mb > max_size:
            return {
                "continue": False,
                "error": f"File too large: {file_size_mb:.2f}MB > {max_size}MB limit",
            }

    print(f"[PDF Assistant] Starting {operation} on {input_file}")

    return {
        "continue": True,
        "operation": operation,
        "input_file": input_file,
    }


async def on_after_pdf_processing(context: dict[str, Any]) -> dict[str, Any]:
    """Hook called after PDF processing completes.

    Can be used to:
    - Update statistics
    - Log completion
    - Cleanup temporary files
    """
    operation = context.get("operation", "unknown")
    success = context.get("success", True)
    output_file = context.get("output_file")
    pages_processed = context.get("pages_processed", 0)

    # Update statistics
    global _stats
    if success:
        _stats["total_processed"] += 1
        _stats["total_pages_processed"] += pages_processed
        if operation in _stats["operations"]:
            _stats["operations"][operation] += 1

    print(f"[PDF Assistant] Completed {operation}: {'success' if success else 'failed'}")

    return {
        "success": success,
        "operation": operation,
        "output_file": output_file,
    }


# ============================================================================
# HTTP Route Handlers
# ============================================================================


async def health_check_handler(request: Any) -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "plugin": "pdf-assistant",
        "version": "1.0.0",
    }


async def extract_text_handler(request: Any) -> dict[str, Any]:
    """Extract text from PDF via HTTP API."""
    try:
        # Get input file from request
        input_file = request.get("input_file")
        layout = request.get("layout", False)

        if not input_file:
            return {"error": "Missing required field: input_file"}

        if not os.path.exists(input_file):
            return {"error": f"File not found: {input_file}"}

        # Use the tool
        from tools import PDFExtractTextTool

        tool = PDFExtractTextTool()
        result = tool(input_file=input_file, layout=layout)

        return result

    except Exception as e:
        return {"error": str(e)}


async def merge_handler(request: Any) -> dict[str, Any]:
    """Merge multiple PDFs via HTTP API."""
    try:
        input_files = request.get("input_files", [])
        output_file = request.get("output_file")

        if not input_files:
            return {"error": "Missing required field: input_files"}

        if not output_file:
            return {"error": "Missing required field: output_file"}

        # Validate all files exist
        for f in input_files:
            if not os.path.exists(f):
                return {"error": f"File not found: {f}"}

        # Use the tool
        from tools import PDFMergeTool

        tool = PDFMergeTool()
        result = tool(input_files=input_files, output_file=output_file)

        return result

    except Exception as e:
        return {"error": str(e)}


async def stats_handler(request: Any) -> dict[str, Any]:
    """Get PDF processing statistics."""
    return {
        "stats": _stats,
    }


# ============================================================================
# CLI Command Handlers
# ============================================================================


async def cli_info_handler(args: dict[str, Any] = None) -> dict[str, Any]:
    """Display PDF Assistant plugin information."""
    info = """
╔══════════════════════════════════════════════════════════════╗
║              PDF Assistant Plugin v1.0.0                     ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  A powerful PDF processing assistant that can:              ║
║                                                              ║
║  📄 Extraction:                                              ║
║     • Extract text (with/without layout)                   ║
║     • Extract tables to Excel                               ║
║     • Extract images                                        ║
║     • Extract metadata                                      ║
║     • OCR for scanned PDFs                                   ║
║                                                              ║
║  🔧 Manipulation:                                            ║
║     • Merge multiple PDFs                                   ║
║     • Split PDF pages                                        ║
║     • Rotate pages (90/180/270)                             ║
║                                                              ║
║  🛡️  Security:                                               ║
║     • Add watermark                                          ║
║     • Encrypt (AES-128/AES-256)                            ║
║     • Compress                                               ║
║                                                              ║
║  📝 Creation:                                                ║
║     • Create PDF from text                                   ║
║                                                              ║
║  Usage:                                                      ║
║    pdf_extract_text input=document.pdf                       ║
║    pdf_merge inputs="a.pdf,b.pdf" output=merged.pdf         ║
║    pdf_encrypt input=doc.pdf output=protected.pdf            ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    return {"output": info}


async def cli_convert_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Convert a file to PDF via CLI."""
    input_file = args.get("input")
    output_file = args.get("output")

    if not input_file or not output_file:
        return {"error": "Both input and output are required"}

    if not os.path.exists(input_file):
        return {"error": f"Input file not found: {input_file}"}

    # Determine file type and convert
    ext = os.path.splitext(input_file)[1].lower()

    if ext == ".pdf":
        # Just copy
        import shutil

        shutil.copy(input_file, output_file)
        return {"status": "success", "message": f"Copied {input_file} to {output_file}"}
    elif ext in [".txt", ".md"]:
        # Text to PDF
        from tools import PDFCreateTool

        tool = PDFCreateTool()
        with open(input_file) as f:
            content = f.read()
        return tool(content=content, output_file=output_file)
    else:
        return {"error": f"Unsupported file type: {ext}"}


# ============================================================================
# Lifecycle Hook Handlers
# ============================================================================


async def on_load_handler() -> dict[str, Any]:
    """Called when the plugin is loaded."""
    print("[PDF Assistant] Plugin loaded")
    return {"status": "loaded"}


async def on_enable_handler() -> dict[str, Any]:
    """Called when the plugin is enabled."""
    print("[PDF Assistant] Plugin enabled")
    return {"status": "enabled"}


async def on_disable_handler() -> dict[str, Any]:
    """Called when the plugin is disabled."""
    print("[PDF Assistant] Plugin disabled")
    return {"status": "disabled"}


async def on_unload_handler() -> dict[str, Any]:
    """Called when the plugin is unloaded."""
    print("[PDF Assistant] Plugin unloaded")
    return {"status": "unloaded"}


# ============================================================================
# Command Handler
# ============================================================================


async def pdf_summary_command(args: dict[str, Any] = None) -> dict[str, Any]:
    """Generate a summary of a PDF file."""
    if not args or "input_file" not in args:
        return {"error": "Missing required argument: input_file"}

    input_file = args["input_file"]

    if not os.path.exists(input_file):
        return {"error": f"File not found: {input_file}"}

    from tools import (
        PDFExtractMetadataTool,
        PDFExtractTextTool,
        PDFGetPageCountTool,
    )

    metadata_tool = PDFExtractMetadataTool()
    page_tool = PDFGetPageCountTool()
    text_tool = PDFExtractTextTool()

    metadata = metadata_tool(input_file=input_file)
    pages = page_tool(input_file=input_file)
    text_result = text_tool(input_file=input_file)

    return {
        "input_file": input_file,
        "metadata": metadata.get("result", {}),
        "page_count": pages.get("result", {}).get("page_count", 0),
        "text_length": len(text_result.get("result", {}).get("text", "")),
    }


# ============================================================================
# Services
# ============================================================================


class PDFStorageService:
    """Service for managing PDF storage and temporary files."""

    def __init__(self):
        self.temp_dir = "/tmp/pdf-assistant"
        os.makedirs(self.temp_dir, exist_ok=True)

    def store(self, file_data: bytes, filename: str) -> str:
        """Store a PDF file temporarily."""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, "wb") as f:
            f.write(file_data)
        return filepath

    def retrieve(self, filename: str) -> bytes:
        """Retrieve a stored PDF file."""
        filepath = os.path.join(self.temp_dir, filename)
        with open(filepath, "rb") as f:
            return f.read()

    def cleanup(self, older_than_hours: int = 24) -> int:
        """Clean up old temporary files."""
        import time

        cutoff = time.time() - (older_than_hours * 3600)
        count = 0

        for filename in os.listdir(self.temp_dir):
            filepath = os.path.join(self.temp_dir, filename)
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                count += 1

        return count


class PDFStorageProvider:
    """Provider for PDF storage service."""

    def __init__(self, default_output_dir: str = "./output/pdfs"):
        self.default_output_dir = default_output_dir
        os.makedirs(default_output_dir, exist_ok=True)

    def get_output_dir(self) -> str:
        """Get the default output directory."""
        return self.default_output_dir

    def ensure_output_dir(self) -> str:
        """Ensure output directory exists."""
        os.makedirs(self.default_output_dir, exist_ok=True)
        return self.default_output_dir


# Export all handlers
__all__ = [
    "PDFStorageProvider",
    "PDFStorageService",
    "cli_convert_handler",
    "cli_info_handler",
    "extract_text_handler",
    "health_check_handler",
    "merge_handler",
    "on_after_pdf_processing",
    "on_before_pdf_processing",
    "on_disable_handler",
    "on_enable_handler",
    "on_load_handler",
    "on_unload_handler",
    "pdf_summary_command",
    "stats_handler",
]
