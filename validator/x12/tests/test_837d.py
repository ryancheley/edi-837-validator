"""Real-object tests for 837D (dental) support.

Exercises detection (X224), the dental service line (SV3), and that element
strictness is preserved on the dental-specific segment.
"""

from __future__ import annotations

from pathlib import Path

from validator.x12 import parser
from validator.x12.engine import detect_txn_type, validate

_FIXTURE = Path(__file__).parent / "fixtures" / "837D-basic.edi"


def _raw() -> str:
    return _FIXTURE.read_text()


def test_detects_837d_from_x224():
    assert detect_txn_type(parser.parse(_raw())) == "837D"


def test_valid_837d_passes_clean():
    result = validate(_raw())
    assert result.txn_type == "837D"
    assert result.is_valid, result.summary()
    assert result.warning_count == 0


def test_bad_dental_procedure_qualifier_is_caught():
    raw = _raw().replace("SV3*AD:D0120*150", "SV3*ZZ:D0120*150")  # ZZ not a valid SV301-1 qualifier
    errs = [e for e in validate(raw).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "SV301-1" for e in errs)
