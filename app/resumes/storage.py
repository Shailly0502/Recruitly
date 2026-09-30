"""Resume storage, one folder per PDF hash. Outside static/; the PDF is never served."""

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import render


@dataclass(frozen=True)
class ResumeRecord:
    """What the audit trail stores about a resume."""
    sha256: str
    filename: str
    pages: int
    text_chars: int  # 0 = no text layer, can't be rated

    def to_dict(self) -> dict:
        return asdict(self)


class ResumeStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def save(self, data: bytes, filename: str) -> ResumeRecord:
        """Raises InvalidResume if the file isn't a usable PDF."""
        parsed = render.read_pdf(data)
        sha256 = hashlib.sha256(data).hexdigest()
        folder = self.root / sha256
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "original.pdf").write_bytes(data)
        # Bytes, so Windows doesn't rewrite line endings.
        (folder / "text.txt").write_bytes(parsed.text.encode("utf-8"))
        for number, image in enumerate(parsed.page_images, start=1):
            (folder / f"page-{number}.png").write_bytes(image)
        return ResumeRecord(sha256, _clean_filename(filename), len(parsed.page_images), len(parsed.text))

    def text(self, sha256: str) -> str:
        return (self._folder(sha256) / "text.txt").read_bytes().decode("utf-8")

    def page_image(self, sha256: str, number: int) -> bytes | None:
        path = self._folder(sha256) / f"page-{number}.png"
        return path.read_bytes() if path.is_file() else None

    def _folder(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("not a resume hash")
        return self.root / sha256


def _clean_filename(filename: str) -> str:
    name = re.split(r"[\\/]", filename or "")[-1].strip()
    return name[:120] or "resume.pdf"
