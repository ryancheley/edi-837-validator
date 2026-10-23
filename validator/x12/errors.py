"""Structured validation findings. No Django imports — pure Python."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ValidationError:
    rule_id: str  # stable id, e.g. "ENV.SE.COUNT" or "ELEM.USAGE.REQUIRED"
    message: str
    severity: Severity = Severity.ERROR
    loop: str | None = None  # loop id, e.g. "2300"
    segment_id: str | None = None  # e.g. "CLM"
    segment_pos: int | None = None  # 1-based index of the segment in the file
    element_ref: str | None = None  # e.g. "CLM05-1"

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.value,
            "loop": self.loop,
            "segment_id": self.segment_id,
            "segment_pos": self.segment_pos,
            "element_ref": self.element_ref,
        }


@dataclass
class ValidationResult:
    txn_type: str | None = None
    errors: list[ValidationError] = field(default_factory=list)

    def add(self, err: ValidationError) -> None:
        self.errors.append(err)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.errors if e.severity == Severity.ERROR)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def summary(self) -> dict:
        return {
            "txn_type": self.txn_type,
            "error_count": self.error_count,
            "total_findings": len(self.errors),
            "findings": [e.as_dict() for e in self.errors],
        }
