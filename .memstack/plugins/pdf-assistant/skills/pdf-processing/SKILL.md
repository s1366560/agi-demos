# PDF Processing Skill

A skill for processing PDF documents with various operations.

## Description

This skill provides comprehensive PDF processing capabilities including extraction, manipulation, and creation of PDF files.

## Tools

- `pdf_extract_text` - Extract text from PDF
- `pdf_extract_tables` - Extract tables to Excel
- `pdf_extract_images` - Extract images from PDF
- `pdf_extract_metadata` - Extract PDF metadata
- `pdf_get_page_count` - Get page count
- `pdf_merge` - Merge multiple PDFs
- `pdf_split` - Split PDF by pages
- `pdf_rotate` - Rotate PDF pages
- `pdf_add_watermark` - Add watermark to PDF
- `pdf_encrypt` - Encrypt PDF with password
- `pdf_decrypt` - Remove PDF encryption
- `pdf_compress` - Compress PDF file
- `pdf_create` - Create PDF from text
- `pdf_ocr` - OCR for scanned PDFs

## When to Use

Use this skill when you need to:
- Extract text, tables, or images from PDF files
- Merge multiple PDFs into one
- Split a PDF into separate pages
- Add watermarks or encryption to PDFs
- Compress large PDF files
- Perform OCR on scanned documents

## Usage Examples

### Extract text from a PDF
```python
result = pdf_extract_text(
    input_file="/path/to/document.pdf",
    output_file="/path/to/output.txt"
)
```

### Merge multiple PDFs
```python
result = pdf_merge(
    input_files=["/path/to/a.pdf", "/path/to/b.pdf"],
    output_file="/path/to/merged.pdf"
)
```

### Add watermark
```python
result = pdf_add_watermark(
    input_file="/path/to/document.pdf",
    output_file="/path/to/watermarked.pdf",
    watermark_text="CONFIDENTIAL"
)
```

## Configuration

The skill uses the PDF Assistant plugin configuration:
- Default output directory: `./output/pdfs`
- Max file size: 50MB
- OCR enabled: true
- Default watermark: "PDF Assistant"
- Encryption: AES-128
