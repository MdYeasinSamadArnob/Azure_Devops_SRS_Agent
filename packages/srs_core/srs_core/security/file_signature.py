"""Magic-byte content-type sniffing.

Azure DevOps frequently serves attachments with a generic
`application/octet-stream` Content-Type regardless of the actual file —
trusting that header alone silently drops legitimate PDFs and images.
This checks the real file signature first, falling back to the filename
extension only if the signature is unrecognized.

Phase 2 layers `python-magic`-based validation on top of this for the
full file set; this covers exactly the Phase 1 MIME allowlist.
"""

from __future__ import annotations

import mimetypes

_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"%PDF-", "application/pdf"),
]


def sniff_content_type(body: bytes, filename: str, header_hint: str | None = None) -> str:
    """Returns the best-guess content type for `body`.

    Order of trust: real file signature > filename extension > the header
    Azure supplied (only used verbatim if it's not a generic placeholder).
    """
    for signature, content_type in _SIGNATURES:
        if body.startswith(signature):
            return content_type

    # WEBP: RIFF????WEBP
    if body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"

    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed

    if header_hint and header_hint not in ("application/octet-stream", ""):
        return header_hint

    return "application/octet-stream"
