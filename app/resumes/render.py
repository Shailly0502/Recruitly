"""PDF -> text and one PNG per page."""

import io
from dataclasses import dataclass

import pypdfium2 as pdfium

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
RENDER_SCALE = 1.6  # ~115 dpi


class InvalidResume(ValueError):
    pass


@dataclass(frozen=True)
class ParsedResume:
    text: str            # empty for scans with no text layer
    page_images: list[bytes]  # PNG, one per page


def read_pdf(data: bytes) -> ParsedResume:
    if len(data) > MAX_BYTES:
        raise InvalidResume("The resume is larger than 5 MB.")
    if not data.startswith(b"%PDF"):
        raise InvalidResume("The resume must be a PDF file.")
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError:
        raise InvalidResume("This PDF can't be opened. It may be damaged or password-protected.") from None
    try:
        if len(document) == 0:
            raise InvalidResume("This PDF has no pages.")
        if len(document) > MAX_PAGES:
            raise InvalidResume(f"The resume has more than {MAX_PAGES} pages.")
        texts, images = [], []
        for page in document:
            textpage = page.get_textpage()
            texts.append("\n".join(textpage.get_text_bounded().splitlines()))
            textpage.close()
            buffer = io.BytesIO()
            page.render(scale=RENDER_SCALE).to_pil().save(buffer, format="PNG")
            images.append(buffer.getvalue())
            page.close()
    finally:
        document.close()
    return ParsedResume(text="\n".join(texts).strip(), page_images=images)
