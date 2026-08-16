"""Generic custom-field content discovery.

Azure DevOps process templates are customized per organization — this is
not optional metadata, it's often where the real requirement content
lives (this org's process has Custom.ERD, Custom.ClassDiagram,
Custom.BusinessRules, Custom.FunctionalRequirement, and more, none of
which are standard Azure fields). Hardcoding field names for one
organization would silently drop this content for every other org's
differently-customized process.

Instead, any field is treated as "content" if it is NOT one of Azure's
built-in system/identity/metadata fields and its value is a substantial
string — this keeps the pipeline working across differently-customized
organizations without per-org configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EXCLUDED_PREFIXES = ("System.", "Microsoft.VSTS.", "WEF_")
# Handled explicitly elsewhere (as `description` / `acceptance_criteria`) —
# never duplicated here.
_EXPLICITLY_HANDLED = frozenset({"System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria"})
_MIN_CONTENT_LENGTH = 15

# Splits lower/digit -> Upper ("ClassDiagram" -> "Class Diagram") and the
# tail end of an acronym run -> new word ("UISourceCode" -> "UI Source Code"),
# but never splits inside an acronym itself ("ERD" stays "ERD", not "E R D") —
# this org's process template has several all-caps custom field names.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _humanize_field_name(reference_name: str) -> str:
    """"Custom.ClassDiagram" -> "Class Diagram", "Custom.ERD" -> "ERD" """
    short_name = reference_name.rsplit(".", 1)[-1]
    return _CAMEL_BOUNDARY_RE.sub(" ", short_name)


@dataclass(frozen=True)
class ContentField:
    reference_name: str
    label: str
    value: str


def extract_content_fields(raw_fields: dict) -> list[ContentField]:
    """Every custom field likely to hold requirement/architecture content,
    sorted alphabetically by reference name for deterministic output.
    """
    results: list[ContentField] = []
    for name, value in raw_fields.items():
        if name in _EXPLICITLY_HANDLED:
            continue
        if any(name.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        if not isinstance(value, str):
            continue
        if len(value.strip()) < _MIN_CONTENT_LENGTH:
            continue
        results.append(ContentField(reference_name=name, label=_humanize_field_name(name), value=value))

    results.sort(key=lambda f: f.reference_name)
    return results
