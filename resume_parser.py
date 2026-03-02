import os
import fitz  # PyMuPDF
import docx
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

def clean_text(text):
    """Normalize text by removing excessive whitespace and non-printable characters."""
    if not text:
        return ""
    # Remove non-printable characters
    text = "".join(char for char in text if char.isprintable())
    # Replace multiple spaces/newlines with single ones
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_text_from_pdf(stream):
    """Extract text from a PDF file stream."""
    try:
        text = ""
        with fitz.open(stream=stream, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        logger.error(f"Error extracting PDF: {str(e)}")
        return ""

def extract_text_from_docx(stream):
    """Extract text from a Docx file stream."""
    try:
        doc = docx.Document(stream)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        logger.error(f"Error extracting Docx: {str(e)}")
        return ""

def get_resume_text(file_stream, filename):
    """Main wrapper to extract and clean text from various resume formats."""
    if not file_stream:
        return ""

    # Check size
    file_stream.seek(0, os.SEEK_END)
    size = file_stream.tell()
    file_stream.seek(0)
    
    if size > MAX_FILE_SIZE:
        logger.warning(f"File {filename} exceeds size limit ({size} bytes)")
        return ""

    ext = os.path.splitext(filename)[1].lower()
    raw_text = ""

    if ext == '.pdf':
        raw_text = extract_text_from_pdf(file_stream)
    elif ext in ['.docx', '.doc']:
        raw_text = extract_text_from_docx(file_stream)
    else:
        logger.warning(f"Unsupported file extension: {ext}")
        return ""

    return clean_text(raw_text)
