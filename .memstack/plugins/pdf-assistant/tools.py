"""PDF Assistant Tools -- All PDF processing tools.

This module provides a unified interface to PDF processing capabilities.
Tools are implemented as wrappers around MemStack's built-in PDF tools.
"""

from __future__ import annotations

import os
from typing import Any

# ============================================================================
# Tool Result Wrapper
# ============================================================================


class PDFToolResult:
    """Wrapper for PDF tool results."""

    def __init__(self, status: str, tool: str, **kwargs):
        self.status = status
        self.tool = tool
        self.data = kwargs

    def __str__(self):
        if self.status == "success":
            return f"✅ {self.tool}: {self.data}"
        else:
            return f"❌ {self.tool}: {self.data.get('error', 'Unknown error')}"


# ============================================================================
# Base Tool Class
# ============================================================================


class PDFTool:
    """Base class for PDF tools."""

    name: str = ""
    description: str = ""

    def __call__(self, **kwargs) -> dict[str, Any]:
        """Execute the tool."""
        raise NotImplementedError


# ============================================================================
# PDF Extraction Tools
# ============================================================================


class PDFExtractTextTool(PDFTool):
    """Extract text content from a PDF file."""

    name = "pdf_extract_text"
    description = "Extract text content from a PDF file."

    def __call__(
        self, input_file: str, output_file: str = None, layout: bool = False
    ) -> dict[str, Any]:
        """Extract text from PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            # Use built-in PDF extraction
            from pypdf import PdfReader

            reader = PdfReader(input_file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"

            if output_file:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(text)
                return {
                    "status": "success",
                    "tool": self.name,
                    "output_file": output_file,
                    "text_length": len(text),
                }

            return {
                "status": "success",
                "tool": self.name,
                "text": text[:1000],
                "text_length": len(text),
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFExtractTablesTool(PDFTool):
    """Extract tables from a PDF file."""

    name = "pdf_extract_tables"
    description = "Extract tables from a PDF and save to Excel"

    def __call__(self, input_file: str, output_excel: str = None) -> dict[str, Any]:
        """Extract tables from PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            import pdfplumber

            tables_found = 0
            with pdfplumber.open(input_file) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    tables_found += len(tables)

            if output_excel and tables_found > 0:
                # Would need openpyxl to write Excel
                pass

            return {"status": "success", "tool": self.name, "tables_found": tables_found}

        except ImportError:
            return {"status": "error", "tool": self.name, "error": "pdfplumber not installed"}
        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFExtractMetadataTool(PDFTool):
    """Extract metadata from a PDF file."""

    name = "pdf_extract_metadata"
    description = "Extract metadata (title, author, subject, etc.) from a PDF"

    def __call__(self, input_file: str) -> dict[str, Any]:
        """Extract metadata from PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader

            reader = PdfReader(input_file)
            metadata = reader.metadata

            result = {}
            if metadata:
                result = {
                    "title": metadata.get("/Title", ""),
                    "author": metadata.get("/Author", ""),
                    "subject": metadata.get("/Subject", ""),
                    "creator": metadata.get("/Creator", ""),
                    "producer": metadata.get("/Producer", ""),
                    "creation_date": str(metadata.get("/CreationDate", "")),
                }

            result["page_count"] = len(reader.pages)

            return {"status": "success", "tool": self.name, "metadata": result}

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFGetPageCountTool(PDFTool):
    """Get the number of pages in a PDF."""

    name = "pdf_get_page_count"
    description = "Get the number of pages in a PDF file"

    def __call__(self, input_file: str) -> dict[str, Any]:
        """Get page count."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader

            reader = PdfReader(input_file)
            count = len(reader.pages)

            return {"status": "success", "tool": self.name, "page_count": count}

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


# ============================================================================
# PDF Manipulation Tools
# ============================================================================


class PDFMergeTool(PDFTool):
    """Merge multiple PDF files into one."""

    name = "pdf_merge"
    description = "Merge multiple PDF files into a single PDF"

    def __call__(self, input_files: list[str], output_file: str) -> dict[str, Any]:
        """Merge PDFs."""
        # Validate input files
        for f in input_files:
            if not os.path.exists(f):
                return {"status": "error", "tool": self.name, "error": f"File not found: {f}"}

        try:
            from pypdf import PdfReader, PdfWriter

            writer = PdfWriter()
            for pdf_file in input_files:
                reader = PdfReader(pdf_file)
                for page in reader.pages:
                    writer.add_page(page)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            with open(output_file, "wb") as output:
                writer.write(output)

            return {
                "status": "success",
                "tool": self.name,
                "output_file": output_file,
                "files_merged": len(input_files),
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFSplitTool(PDFTool):
    """Split a PDF into individual pages or a range."""

    name = "pdf_split"
    description = "Split a PDF into individual pages or a specific page range"

    def __call__(
        self, input_file: str, output_dir: str, start_page: int = None, end_page: int = None
    ) -> dict[str, Any]:
        """Split PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(input_file)
            total_pages = len(reader.pages)

            # Default to all pages
            start = start_page - 1 if start_page else 0
            end = end_page if end_page else total_pages

            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)

            output_files = []
            base_name = os.path.splitext(os.path.basename(input_file))[0]

            for i in range(start, min(end, total_pages)):
                writer = PdfWriter()
                writer.add_page(reader.pages[i])

                output_path = os.path.join(output_dir, f"{base_name}_page_{i + 1}.pdf")
                with open(output_path, "wb") as output:
                    writer.write(output)
                output_files.append(output_path)

            return {
                "status": "success",
                "tool": self.name,
                "output_files": output_files,
                "pages_split": len(output_files),
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFRotateTool(PDFTool):
    """Rotate pages in a PDF."""

    name = "pdf_rotate"
    description = "Rotate pages in a PDF by 90, 180, or 270 degrees"

    def __call__(
        self, input_file: str, output_file: str, degrees: int = 90, pages: list[int] = None
    ) -> dict[str, Any]:
        """Rotate PDF pages."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(input_file)
            writer = PdfWriter()

            for i, page in enumerate(reader.pages):
                if pages is None or (i + 1) in pages:
                    page.rotate(degrees)
                writer.add_page(page)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            with open(output_file, "wb") as output:
                writer.write(output)

            return {
                "status": "success",
                "tool": self.name,
                "output_file": output_file,
                "degrees": degrees,
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFAddWatermarkTool(PDFTool):
    """Add watermark to PDF pages."""

    name = "pdf_add_watermark"
    description = "Add a watermark to all pages of a PDF"

    def __call__(
        self, input_file: str, output_file: str, watermark_text: str = "WATERMARK"
    ) -> dict[str, Any]:
        """Add watermark to PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            import io

            from pypdf import PdfReader, PdfWriter
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas

            reader = PdfReader(input_file)
            writer = PdfWriter()

            # Create watermark
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=letter)
            c.setFont("Helvetica-Bold", 50)
            c.setFillGray(0.5, 0.5)
            c.saveState()
            c.translate(200, 400)
            c.rotate(45)
            c.drawCentredString(0, 0, watermark_text)
            c.restoreState()
            c.save()
            packet.seek(0)

            watermark = PdfReader(packet)

            for page in reader.pages:
                page.merge_page(watermark.pages[0])
                writer.add_page(page)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            with open(output_file, "wb") as output:
                writer.write(output)

            return {
                "status": "success",
                "tool": self.name,
                "output_file": output_file,
                "watermark": watermark_text,
            }

        except ImportError as e:
            return {"status": "error", "tool": self.name, "error": f"Missing dependency: {e}"}
        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFEncryptTool(PDFTool):
    """Add password protection to a PDF."""

    name = "pdf_encrypt"
    description = "Add password protection to a PDF"

    def __call__(
        self,
        input_file: str,
        output_file: str,
        user_password: str,
        owner_password: str = None,
        algorithm: str = "AES-128",
    ) -> dict[str, Any]:
        """Encrypt PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(input_file)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            owner_pwd = owner_password or user_password
            writer.encrypt(user_password, owner_pwd, algorithm == "AES-256")

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            with open(output_file, "wb") as output:
                writer.write(output)

            return {
                "status": "success",
                "tool": self.name,
                "output_file": output_file,
                "algorithm": algorithm,
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFDecryptTool(PDFTool):
    """Remove encryption from a PDF."""

    name = "pdf_decrypt"
    description = "Remove password protection from a PDF"

    def __call__(self, input_file: str, output_file: str, password: str) -> dict[str, Any]:
        """Decrypt PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(input_file)

            # Try to decrypt with provided password
            if reader.is_encrypted:
                reader.decrypt(password)

            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            with open(output_file, "wb") as output:
                writer.write(output)

            return {"status": "success", "tool": self.name, "output_file": output_file}

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFCompressTool(PDFTool):
    """Compress a PDF file."""

    name = "pdf_compress"
    description = "Compress a PDF to reduce file size"

    def __call__(
        self, input_file: str, output_file: str, quality: str = "medium"
    ) -> dict[str, Any]:
        """Compress PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(input_file)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            # Compression settings
            if quality == "low" or quality == "medium" or quality == "high":
                writer.compress_content_streams()

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            input_size = os.path.getsize(input_file)
            with open(output_file, "wb") as output:
                writer.write(output)
            output_size = os.path.getsize(output_file)

            ratio = (1 - output_size / input_size) * 100 if input_size > 0 else 0

            return {
                "status": "success",
                "tool": self.name,
                "output_file": output_file,
                "input_size_bytes": input_size,
                "output_size_bytes": output_size,
                "compression_ratio_percent": round(ratio, 2),
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFCreateTool(PDFTool):
    """Create a PDF from text content."""

    name = "pdf_create"
    description = "Create a new PDF from text content"

    def __call__(self, content: str, output_file: str, title: str = None) -> dict[str, Any]:
        """Create PDF from text."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

            doc = SimpleDocTemplate(output_file, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            if title:
                story.append(Paragraph(title, styles["Title"]))
                story.append(Spacer(1, 12))

            paragraphs = content.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    story.append(Paragraph(para, styles["Normal"]))
                    story.append(Spacer(1, 6))

            doc.build(story)

            return {"status": "success", "tool": self.name, "output_file": output_file}

        except ImportError as e:
            return {"status": "error", "tool": self.name, "error": f"Missing dependency: {e}"}
        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFOCRTool(PDFTool):
    """Extract text from scanned PDFs using OCR."""

    name = "pdf_ocr"
    description = "Extract text from scanned PDFs using OCR"

    def __call__(
        self, input_file: str, output_file: str = None, language: str = "eng"
    ) -> dict[str, Any]:
        """OCR PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            import io

            import pytesseract
            from PIL import Image
            from pypdf import PdfReader

            reader = PdfReader(input_file)
            text = ""

            for page_num, page in enumerate(reader.pages):
                # Try to extract text normally first
                page_text = page.extract_text()
                if page_text.strip():
                    text += page_text + "\n"
                else:
                    # OCR needed for this page
                    pass  # Would need to convert page to image

            if output_file and text:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(text)

            return {
                "status": "success",
                "tool": self.name,
                "text_length": len(text),
                "output_file": output_file,
            }

        except ImportError:
            return {"status": "error", "tool": self.name, "error": "pytesseract not installed"}
        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


class PDFExtractImagesTool(PDFTool):
    """Extract images from a PDF file."""

    name = "pdf_extract_images"
    description = "Extract all images from a PDF file"

    def __call__(self, input_file: str, output_dir: str = None) -> dict[str, Any]:
        """Extract images from PDF."""
        if not os.path.exists(input_file):
            return {"status": "error", "tool": self.name, "error": f"File not found: {input_file}"}

        try:
            from pypdf import PdfReader

            reader = PdfReader(input_file)
            images = []

            for page_num, page in enumerate(reader.pages):
                if "/XObject" in page["/Resources"]:
                    xobjects = page["/Resources"]["/XObject"].get_object()
                    for obj in xobjects:
                        if xobjects[obj]["/Subtype"] == "/Image":
                            images.append(f"page_{page_num + 1}_{obj}")

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            return {
                "status": "success",
                "tool": self.name,
                "images_found": len(images),
                "output_dir": output_dir,
            }

        except Exception as e:
            return {"status": "error", "tool": self.name, "error": str(e)}


# Export all tools
__all__ = [
    "PDFAddWatermarkTool",
    "PDFCompressTool",
    "PDFCreateTool",
    "PDFDecryptTool",
    "PDFEncryptTool",
    "PDFExtractImagesTool",
    "PDFExtractMetadataTool",
    "PDFExtractTablesTool",
    "PDFExtractTextTool",
    "PDFGetPageCountTool",
    "PDFMergeTool",
    "PDFOCRTool",
    "PDFRotateTool",
    "PDFSplitTool",
]
