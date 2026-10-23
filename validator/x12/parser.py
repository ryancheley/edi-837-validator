"""Parse raw X12 into segments. Delimiters are self-describing in the ISA header.

No Django imports — pure Python, unit-testable without the ORM.
"""

from __future__ import annotations

from dataclasses import dataclass


class ParseError(Exception):
    """Raised when the interchange cannot be parsed structurally."""


@dataclass(frozen=True)
class Delimiters:
    element: str
    component: str
    repetition: str
    segment: str


@dataclass
class Segment:
    id: str
    elements: list[str]  # elements[0] == id; 1-based access via .get()
    pos: int  # 1-based position in the file

    def get(self, index: int) -> str:
        """1-based element access (NM101 -> index 1). Empty string if absent."""
        if 0 < index < len(self.elements):
            return self.elements[index]
        return ""


@dataclass
class Document:
    delimiters: Delimiters
    segments: list[Segment]

    def first(self, seg_id: str) -> Segment | None:
        return next((s for s in self.segments if s.id == seg_id), None)

    def all(self, seg_id: str) -> list[Segment]:
        return [s for s in self.segments if s.id == seg_id]


# ISA is a fixed-width 106-char segment in X12 005010. The component separator
# (ISA16) and the segment terminator are the only reliable way to learn those
# two delimiters, so we read them by fixed offset.
_ISA_LEN = 106
_ISA_REPETITION_IDX = 82
_ISA_COMPONENT_IDX = 104
_ISA_TERMINATOR_IDX = 105


def detect_delimiters(raw: str) -> Delimiters:
    if len(raw) < _ISA_LEN or not raw.startswith("ISA"):
        raise ParseError("File does not start with a 106-character ISA segment")
    return Delimiters(
        element=raw[3],
        repetition=raw[_ISA_REPETITION_IDX],
        component=raw[_ISA_COMPONENT_IDX],
        segment=raw[_ISA_TERMINATOR_IDX],
    )


def parse(raw: str | bytes) -> Document:
    """Parse an X12 interchange into a Document."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw = raw.lstrip("﻿ \r\n\t")  # tolerate BOM / leading whitespace
    delims = detect_delimiters(raw)

    segments: list[Segment] = []
    for chunk in raw.split(delims.segment):
        # Segments are often newline-separated for readability; strip those.
        chunk = chunk.strip("\r\n\t ")
        if not chunk:
            continue
        elements = chunk.split(delims.element)
        segments.append(
            Segment(id=elements[0], elements=elements, pos=len(segments) + 1)
        )

    if not segments:
        raise ParseError("No segments found")
    return Document(delimiters=delims, segments=segments)
