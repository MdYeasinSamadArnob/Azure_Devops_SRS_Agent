"""Extracts <img> references embedded directly in Azure DevOps rich-text
HTML fields (descriptions, acceptance criteria) — separate from the formal
"AttachedFile" relations the core attachment pipeline already handles.
Real-world work items very often embed screenshots/diagrams inline in the
description rather than as a formal attachment, so both sources are needed
for "every image actually gets captured."
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class EmbeddedImageRef:
    kind: str  # "data_uri" | "azure_hosted" | "external"
    src: str
    # Populated only for data_uri images — decoded inline, no download needed.
    decoded_bytes: bytes | None = None
    content_type: str | None = None


class _ImgTagFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        for name, value in attrs:
            if name == "src" and value:
                self.sources.append(value)


def _classify(src: str, azure_org: str) -> EmbeddedImageRef:
    if src.startswith("data:"):
        try:
            header, b64_data = src.split(",", 1)
            content_type = header.split(";")[0].removeprefix("data:") or None
            decoded = base64.b64decode(b64_data, validate=False)
            return EmbeddedImageRef(kind="data_uri", src=src, decoded_bytes=decoded, content_type=content_type)
        except (ValueError, binascii.Error):
            return EmbeddedImageRef(kind="external", src=src)

    if f"dev.azure.com/{azure_org}" in src or f"{azure_org}.visualstudio.com" in src:
        return EmbeddedImageRef(kind="azure_hosted", src=src)

    return EmbeddedImageRef(kind="external", src=src)


def extract_embedded_images(html: str | None, *, azure_org: str) -> list[EmbeddedImageRef]:
    if not html:
        return []
    finder = _ImgTagFinder()
    finder.feed(html)
    finder.close()
    return [_classify(src, azure_org) for src in finder.sources]
