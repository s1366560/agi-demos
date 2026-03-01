# PDF Assistant Plugin

A powerful PDF processing assistant plugin for MemStack that provides comprehensive PDF manipulation capabilities.

## Features

### 📄 Extraction
- **Extract Text** - Extract text content from PDFs with optional layout preservation
- **Extract Tables** - Extract tables and save to Excel format
- **Extract Images** - Extract all images embedded in PDFs
- **Extract Metadata** - Get PDF metadata (title, author, creation date, etc.)
- **OCR Support** - Extract text from scanned PDFs using OCR

### 🔧 Manipulation
- **Merge PDFs** - Combine multiple PDF files into one
- **Split PDF** - Split a PDF into individual pages or a specific range
- **Rotate Pages** - Rotate pages by 90, 180, or 270 degrees

### 🛡️ Security
- **Add Watermark** - Add text or image watermarks to PDFs
- **Encrypt PDF** - Add password protection (AES-128/AES-256)
- **Compress** - Reduce PDF file size

### 📝 Creation
- **Create PDF** - Create new PDFs from text content

## Installation

The plugin is automatically discovered by MemStack from the `.memstack/plugins/pdf-assistant/` directory.

```bash
# Enable the plugin
plugin_manager(action="enable", plugin_name="pdf-assistant")

# Reload to apply changes
plugin_manager(action="reload")
```

## Configuration

Edit `plugin.py` to configure default settings:

```python
config: dict[str, Any] = {
    "default_output_dir": "./output/pdfs",
    "max_file_size_mb": 50,
    "ocr_enabled": True,
    "watermark_text": "PDF Assistant",
    "encryption_algorithm": "AES-128",
}
```

## Usage

### Using Tools (MCP)

#### Extract Text
```
pdf_extract_text(input_file="/path/to/document.pdf", output_file="/path/to/output.txt", layout=False)
```

#### Extract Tables
```
pdf_extract_tables(input_file="/path/to/document.pdf", output_excel="/path/to/tables.xlsx")
```

#### Merge PDFs
```
pdf_merge(input_files=["/path/to/a.pdf", "/path/to/b.pdf"], output_file="/path/to/merged.pdf")
```

#### Split PDF
```
pdf_split(input_file="/path/to/document.pdf", output_dir="/path/to/output/", start_page=1, end_page=10)
```

#### Add Watermark
```
pdf_add_watermark(input_file="/path/to/document.pdf", output_file="/path/to/watermarked.pdf", watermark_text="CONFIDENTIAL")
```

#### Encrypt PDF
```
pdf_encrypt(input_file="/path/to/document.pdf", output_file="/path/to/protected.pdf", user_password="open123", owner_password="admin123", algorithm="AES-256")
```

#### Create PDF
```
pdf_create(content="Hello, World!", output_file="/path/to/new.pdf", title="My Document")
```

### Using CLI Commands

```bash
# Show plugin info
pdf-info

# Convert file to PDF
pdf-convert --input document.txt --output document.pdf
```

### Using HTTP API

```bash
# Health check
GET /plugins/pdf-assistant/health

# Extract text
POST /plugins/pdf-assistant/extract-text
{
  "input_file": "/path/to/document.pdf",
  "layout": false
}

# Merge PDFs
POST /plugins/pdf-assistant/merge
{
  "input_files": ["/path/to/a.pdf", "/path/to/b.pdf"],
  "output_file": "/path/to/merged.pdf"
}

# Get statistics
GET /plugins/pdf-assistant/stats
```

### Using Commands

```bash
# Generate PDF summary
pdf.summary input_file="/path/to/document.pdf"
```

## Available Tools

| Tool | Description |
|------|-------------|
| `pdf_extract_text` | Extract text from PDF |
| `pdf_extract_tables` | Extract tables to Excel |
| `pdf_extract_images` | Extract images from PDF |
| `pdf_extract_metadata` | Extract PDF metadata |
| `pdf_get_page_count` | Get page count |
| `pdf_merge` | Merge multiple PDFs |
| `pdf_split` | Split PDF by pages |
| `pdf_rotate` | Rotate PDF pages |
| `pdf_add_watermark` | Add watermark to PDF |
| `pdf_encrypt` | Encrypt PDF with password |
| `pdf_decrypt` | Remove PDF encryption |
| `pdf_compress` | Compress PDF file |
| `pdf_create` | Create PDF from text |
| `pdf_ocr` | OCR for scanned PDFs |

## Hooks

The plugin provides hooks for customizing behavior:

- `before_pdf_processing` - Called before PDF processing starts
- `after_pdf_processing` - Called after PDF processing completes

## Statistics

The plugin tracks processing statistics:
- Total PDFs processed
- Total pages processed
- Operations by type

Access via `/plugins/pdf-assistant/stats` HTTP endpoint or `pdf.stats` command.

## Requirements

- Python 3.8+
- PyPDF2 or pypdf (for basic operations)
- pdfplumber (for table extraction)
- pytesseract + tesseract (for OCR)

## License

MIT
