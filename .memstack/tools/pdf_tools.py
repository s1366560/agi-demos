"""PDF Processing Tools - Tool version of the PDF skill.

This module provides PDF processing functionality as callable tools.
"""

from pathlib import Path

from memstack_tools import ToolResult, tool_define


@tool_define(
    name="pdf_merge",
    description="Merge multiple PDF files into a single PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of input PDF file paths to merge.",
            },
            "output_file": {
                "type": "string",
                "description": "Output path for the merged PDF.",
            },
        },
        "required": ["input_files", "output_file"],
    },
    permission="write",
    category="pdf",
)
async def pdf_merge(ctx: object, input_files: list[str], output_file: str) -> ToolResult:
    """Merge multiple PDF files into one."""
    try:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        for pdf_file in input_files:
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                writer.add_page(page)

        with open(output_file, "wb") as output:
            writer.write(output)

        return ToolResult(output=f"Successfully merged {len(input_files)} PDFs into {output_file}")
    except Exception as e:
        return ToolResult(output="", error=f"Error merging PDFs: {e!s}")


@tool_define(
    name="pdf_split",
    description="Split a PDF into individual pages or a range of pages.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "output_dir": {
                "type": "string",
                "description": "Directory to save split PDF files.",
            },
            "start_page": {
                "type": "integer",
                "description": "Start page (1-based). If not specified, splits all pages.",
            },
            "end_page": {
                "type": "integer",
                "description": "End page (1-based). If not specified, goes to last page.",
            },
        },
        "required": ["input_file", "output_dir"],
    },
    permission="write",
    category="pdf",
)
async def pdf_split(
    ctx: object,
    input_file: str,
    output_dir: str,
    start_page: int | None = None,
    end_page: int | None = None,
) -> ToolResult:
    """Split a PDF into individual pages."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(input_file)
        total_pages = len(reader.pages)

        start = start_page - 1 if start_page else 0
        end = end_page if end_page else total_pages

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for i in range(start, min(end, total_pages)):
            writer = PdfWriter()
            writer.add_page(reader.pages[i])
            output_path = Path(output_dir) / f"page_{i+1}.pdf"
            with open(output_path, "wb") as output:
                writer.write(output)

        return ToolResult(
            output=f"Split {input_file} into {end - start} pages in {output_dir}"
        )
    except Exception as e:
        return ToolResult(output="", error=f"Error splitting PDF: {e!s}")


@tool_define(
    name="pdf_extract_text",
    description="Extract text content from a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "output_file": {
                "type": "string",
                "description": "Output text file path. If not specified, returns text directly.",
            },
            "layout": {
                "type": "boolean",
                "description": "Preserve layout (default: false).",
            },
        },
        "required": ["input_file"],
    },
    permission="read",
    category="pdf",
)
async def pdf_extract_text(
    ctx: object,
    input_file: str,
    output_file: str | None = None,
    layout: bool = False,
) -> ToolResult:
    """Extract text from PDF."""
    try:
        import pdfplumber

        text = ""
        with pdfplumber.open(input_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(layout=layout)
                if page_text:
                    text += page_text + "\n\n"

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)
            return ToolResult(output=f"Text extracted to {output_file}")
        else:
            return ToolResult(output=text)
    except Exception as e:
        return ToolResult(output="", error=f"Error extracting text: {e!s}")


@tool_define(
    name="pdf_extract_tables",
    description="Extract tables from a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "output_excel": {
                "type": "string",
                "description": "Output Excel file path to save all tables.",
            },
        },
        "required": ["input_file"],
    },
    permission="read",
    category="pdf",
)
async def pdf_extract_tables(
    ctx: object,
    input_file: str,
    output_excel: str | None = None,
) -> ToolResult:
    """Extract tables from PDF."""
    try:
        import pandas as pd
        import pdfplumber

        all_tables = []
        with pdfplumber.open(input_file) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                for j, table in enumerate(tables):
                    if table:
                        df = pd.DataFrame(table[1:], columns=table[0])
                        df.attrs["page"] = i + 1
                        df.attrs["table_num"] = j + 1
                        all_tables.append(df)

        if not all_tables:
            return ToolResult(output="No tables found in the PDF.")

        if output_excel:
            with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
                for _idx, df in enumerate(all_tables):
                    sheet_name = f"Page{df.attrs['page']}_Tbl{df.attrs['table_num']}"
                    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            return ToolResult(output=f"Extracted {len(all_tables)} tables to {output_excel}")
        else:
            result = f"Found {len(all_tables)} tables:\n"
            for idx, df in enumerate(all_tables):
                result += f"\n--- Table {idx + 1} (Page {df.attrs['page']}) ---\n"
                result += df.to_string(index=False) + "\n"
            return ToolResult(output=result)
    except Exception as e:
        return ToolResult(output="", error=f"Error extracting tables: {e!s}")


@tool_define(
    name="pdf_extract_metadata",
    description="Extract metadata (title, author, subject, etc.) from a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
        },
        "required": ["input_file"],
    },
    permission="read",
    category="pdf",
)
async def pdf_extract_metadata(ctx: object, input_file: str) -> ToolResult:
    """Extract metadata from PDF."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(input_file)
        meta = reader.metadata

        if not meta:
            return ToolResult(output="No metadata found in the PDF.")

        result = f"PDF Metadata for {input_file}:\n"
        result += f"  Title: {meta.get('/Title', 'N/A')}\n"
        result += f"  Author: {meta.get('/Author', 'N/A')}\n"
        result += f"  Subject: {meta.get('/Subject', 'N/A')}\n"
        result += f"  Creator: {meta.get('/Creator', 'N/A')}\n"
        result += f"  Producer: {meta.get('/Producer', 'N/A')}\n"
        result += f"  Creation Date: {meta.get('/CreationDate', 'N/A')}\n"
        result += f"  Modification Date: {meta.get('/ModDate', 'N/A')}\n"
        result += f"  Page Count: {len(reader.pages)}\n"

        return ToolResult(output=result)
    except Exception as e:
        return ToolResult(output="", error=f"Error extracting metadata: {e!s}")


@tool_define(
    name="pdf_rotate",
    description="Rotate pages in a PDF by 90, 180, or 270 degrees.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "output_file": {"type": "string", "description": "Output PDF file path."},
            "degrees": {
                "type": "integer",
                "description": "Rotation degrees (90, 180, or 270).",
            },
            "pages": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Page numbers to rotate (1-based). If not specified, rotates all pages.",
            },
        },
        "required": ["input_file", "output_file", "degrees"],
    },
    permission="write",
    category="pdf",
)
async def pdf_rotate(
    ctx: object,
    input_file: str,
    output_file: str,
    degrees: int,
    pages: list[int] | None = None,
) -> ToolResult:
    """Rotate PDF pages."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(input_file)
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            if pages is None or (i + 1) in pages:
                page.rotate(degrees)
            writer.add_page(page)

        with open(output_file, "wb") as output:
            writer.write(output)

        return ToolResult(
            output=f"Rotated {len(pages) if pages else len(reader.pages)} pages by {degrees} degrees. Saved to {output_file}"
        )
    except Exception as e:
        return ToolResult(output="", error=f"Error rotating PDF: {e!s}")


@tool_define(
    name="pdf_add_watermark",
    description="Add a watermark to all pages of a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "watermark_file": {"type": "string", "description": "Watermark PDF file path."},
            "output_file": {"type": "string", "description": "Output PDF file path."},
        },
        "required": ["input_file", "watermark_file", "output_file"],
    },
    permission="write",
    category="pdf",
)
async def pdf_add_watermark(
    ctx: object,
    input_file: str,
    watermark_file: str,
    output_file: str,
) -> ToolResult:
    """Add watermark to PDF."""
    try:
        from pypdf import PdfReader, PdfWriter

        watermark = PdfReader(watermark_file).pages[0]
        reader = PdfReader(input_file)
        writer = PdfWriter()

        for page in reader.pages:
            page.merge_page(watermark)
            writer.add_page(page)

        with open(output_file, "wb") as output:
            writer.write(output)

        return ToolResult(output=f"Watermark added to {input_file}. Saved to {output_file}")
    except Exception as e:
        return ToolResult(output="", error=f"Error adding watermark: {e!s}")


@tool_define(
    name="pdf_encrypt",
    description="Add password protection (encryption) to a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
            "output_file": {"type": "string", "description": "Output encrypted PDF file path."},
            "user_password": {
                "type": "string",
                "description": "User password (for opening the PDF).",
            },
            "owner_password": {
                "type": "string",
                "description": "Owner password (for full permissions).",
            },
        },
        "required": ["input_file", "output_file", "user_password"],
    },
    permission="write",
    category="pdf",
)
async def pdf_encrypt(
    ctx: object,
    input_file: str,
    output_file: str,
    user_password: str,
    owner_password: str | None = None,
) -> ToolResult:
    """Encrypt PDF with password."""
    try:
        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(input_file)
        writer = PdfWriter()

        for page in reader.pages:
            writer.add_page(page)

        writer.encrypt(user_password, owner_password)

        with open(output_file, "wb") as output:
            writer.write(output)

        return ToolResult(output=f"PDF encrypted and saved to {output_file}")
    except Exception as e:
        return ToolResult(output="", error=f"Error encrypting PDF: {e!s}")


@tool_define(
    name="pdf_create",
    description="Create a new PDF with text content.",
    parameters={
        "type": "object",
        "properties": {
            "output_file": {"type": "string", "description": "Output PDF file path."},
            "title": {"type": "string", "description": "Document title."},
            "content": {
                "type": "string",
                "description": "Text content to include in the PDF.",
            },
        },
        "required": ["output_file", "content"],
    },
    permission="write",
    category="pdf",
)
async def pdf_create(
    ctx: object,
    output_file: str,
    content: str,
    title: str | None = None,
) -> ToolResult:
    """Create a new PDF with content."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

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
        return ToolResult(output=f"PDF created: {output_file}")
    except Exception as e:
        return ToolResult(output="", error=f"Error creating PDF: {e!s}")


@tool_define(
    name="pdf_ocr",
    description="Extract text from scanned PDFs using OCR.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input scanned PDF file path."},
            "output_file": {
                "type": "string",
                "description": "Output text file path. If not specified, returns text directly.",
            },
        },
        "required": ["input_file"],
    },
    permission="read",
    category="pdf",
)
async def pdf_ocr(
    ctx: object,
    input_file: str,
    output_file: str | None = None,
) -> ToolResult:
    """Perform OCR on scanned PDF."""
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(input_file)
        text = ""

        for i, image in enumerate(images):
            text += f"--- Page {i + 1} ---\n"
            text += pytesseract.image_to_string(image)
            text += "\n\n"

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)
            return ToolResult(output=f"OCR completed. Text extracted to {output_file}")
        else:
            return ToolResult(output=text)
    except Exception as e:
        return ToolResult(output="", error=f"Error performing OCR: {e!s}")


@tool_define(
    name="pdf_get_page_count",
    description="Get the number of pages in a PDF.",
    parameters={
        "type": "object",
        "properties": {
            "input_file": {"type": "string", "description": "Input PDF file path."},
        },
        "required": ["input_file"],
    },
    permission="read",
    category="pdf",
)
async def pdf_get_page_count(ctx: object, input_file: str) -> ToolResult:
    """Get page count of PDF."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(input_file)
        return ToolResult(output=f"{len(reader.pages)}")
    except Exception as e:
        return ToolResult(output="", error=f"Error reading PDF: {e!s}")
