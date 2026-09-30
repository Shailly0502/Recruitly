"""Minimal text-only PDF writer for the demo and eval resumes."""

import textwrap

LINES_PER_PAGE = 50
WRAP_AT = 92


def build_pdf(lines: list[str]) -> bytes:
    """One line per item; lines starting with "# " are headings."""
    wrapped: list[str] = []
    for line in lines:
        if line.startswith("# ") or not line:
            wrapped.append(line)
        else:
            wrapped.extend(textwrap.wrap(line, WRAP_AT) or [""])
    pages = [wrapped[i:i + LINES_PER_PAGE] for i in range(0, len(wrapped), LINES_PER_PAGE)] or [[]]

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,  # page tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for page in pages:
        stream = _content(page)
        kids.append(len(objects) + 1)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>" % (len(objects) + 2))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % kid for kid in kids), len(kids))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def _content(lines: list[str]) -> bytes:
    parts = [b"BT", b"/F1 10 Tf", b"15 TL", b"50 790 Td"]
    for line in lines:
        if line.startswith("# "):
            parts += [b"/F2 13 Tf", _show(line[2:]), b"/F1 10 Tf"]
        else:
            parts.append(_show(line))
        parts.append(b"T*")
    parts.append(b"ET")
    return b"\n".join(parts)


def _show(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("cp1252", errors="replace") + b") Tj"
