"""Regression test against a real-world 837P 'all fields' file.

Source: Healthcare-Data-Insight/api-examples (edi_files/837/837P-all-fields.dat).
Exercises the full TR3 loop tree and the any-order sub-loop matcher. Must stay
valid, and a deliberate mutation must still be caught (strictness preserved).
"""

from __future__ import annotations

from pathlib import Path

from validator.x12.engine import validate

_FIXTURE = Path(__file__).parent / "fixtures" / "837P-all-fields.edi"


def _raw() -> str:
    return _FIXTURE.read_text()


def test_all_fields_837p_is_valid():
    result = validate(_raw())
    assert result.txn_type == "837P"
    assert result.is_valid, result.summary()


def test_invalid_place_of_service_still_caught():
    raw = _raw().replace("CLM*36463774*100***11:B:1", "CLM*36463774*100***00:B:1")
    errs = [e for e in validate(raw).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "CLM05-1" for e in errs)


def test_bad_service_unit_basis_still_caught():
    raw = _raw().replace("SV1*HC:87099*15*UN*1***1", "SV1*HC:87099*15*ZZ*1***1")
    errs = [e for e in validate(raw).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "SV103" for e in errs)
