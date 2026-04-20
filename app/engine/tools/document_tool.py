import csv
import io
import json
from pathlib import Path
from langchain.tools import tool


def _extract_pdf(path: str) -> str:
    from pdfminer.high_level import extract_text
    return extract_text(path)


def _extract_docx(path: str) -> str:
    from docx import Document
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_csv(path: str) -> str:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            rows.append(dict(row))
            if i >= 199:
                rows.append({"_note": "truncated at 200 rows"})
                break
    return json.dumps(rows, indent=2, ensure_ascii=False)


def _extract_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


@tool
def extract_document(file_path: str) -> str:
    """Extract and return the full text or structured content from a PDF, DOCX, CSV, or TXT file."""
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _extract_pdf(file_path)
        elif suffix in (".docx", ".doc"):
            text = _extract_docx(file_path)
        elif suffix == ".csv":
            text = _extract_csv(file_path)
        elif suffix == ".txt":
            text = _extract_txt(file_path)
        else:
            return f"Unsupported file type: {suffix}. Supported: .pdf, .docx, .csv, .txt"

        if not text or not text.strip():
            return f"No content found in: {file_path}"

        if len(text) > 10000:
            text = text[:10000] + "\n...[truncated]"

        return text.strip()
    except Exception as e:
        return f"Extraction failed for {file_path}: {str(e)}"


@tool
def read_csv_as_json(file_path: str) -> str:
    """Read a CSV file and return its contents as a JSON array of row objects. Useful for data analysis."""
    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"
    try:
        return _extract_csv(file_path)
    except Exception as e:
        return f"CSV read failed: {str(e)}"
