"""Real-object tests for the X12 engine. No mocks — build EDI, validate, assert.

Run: uv run pytest validator/x12/tests/
"""

from __future__ import annotations

from validator.x12 import parser
from validator.x12.engine import detect_txn_type, validate

# ISA is fixed-width (005010); build it from padded fields so it is exactly
# 106 chars and the component separator / terminator land at the right offsets.
_ISA_WIDTHS = [2, 10, 2, 10, 2, 15, 2, 15, 6, 4, 1, 5, 9, 1, 1, 1]


def _isa(control: str = "000000001") -> str:
    fields = ["00", "", "00", "", "ZZ", "SUBMITTER", "ZZ", "RECEIVER",
              "210101", "1253", "^", "00501", control, "0", "P", ":"]
    padded = [f.ljust(w)[:w] for f, w in zip(fields, _ISA_WIDTHS, strict=True)]
    return "ISA*" + "*".join(padded)


def _edi(body: list[str], isa_control: str = "000000001") -> str:
    """Wrap ST..SE body segments in GS/GE and ISA/IEA, join with ~."""
    segments = [_isa(isa_control)] + body
    return "".join(s + "~" for s in segments)


def _p_body(conv: str = "005010X222A1") -> list[str]:
    """A clean 837P interchange body (GS..IEA), as editable segment strings."""
    return [
        f"GS*HC*SUBMITTER*RECEIVER*20210101*1253*1*X*{conv}",
        f"ST*837*0001*{conv}",
        "BHT*0019*00*REF123*20210101*1253*CH",
        "NM1*41*2*SUBMITTER NAME*****46*TAX123",
        "PER*IC*CONTACT*TE*5551234567",
        "NM1*40*2*RECEIVER NAME*****46*RCV123",
        "HL*1**20*1",
        "NM1*85*2*BILLING PROVIDER*****XX*1234567893",
        "N3*123 MAIN ST",
        "N4*CITY*CA*90001",
        "HL*2*1*22*0",
        "SBR*P*18*******CI",
        "NM1*IL*1*SUBSCRIBER*JOHN***MI*MEMBER123",
        "NM1*PR*2*PAYER NAME*****PI*PAYERID",
        "CLM*CLAIM001*500***11:B:1",
        "LX*1",
        "SV1*HC:99213*150*UN*1",
        "SE*17*0001",
        "GE*1*1",
        "IEA*1*000000001",
    ]


def _i_body(conv: str = "005010X223A2") -> list[str]:
    return [
        f"GS*HC*SUBMITTER*RECEIVER*20210101*1253*1*X*{conv}",
        f"ST*837*0001*{conv}",
        "BHT*0019*00*REF123*20210101*1253*CH",
        "NM1*41*2*SUBMITTER NAME*****46*TAX123",
        "PER*IC*CONTACT*TE*5551234567",
        "NM1*40*2*RECEIVER NAME*****46*RCV123",
        "HL*1**20*1",
        "NM1*85*2*BILLING PROVIDER*****XX*1234567893",
        "N3*123 MAIN ST",
        "N4*CITY*CA*90001",
        "HL*2*1*22*0",
        "SBR*P*18",
        "NM1*IL*1*SUBSCRIBER*JOHN***MI*MEMBER123",
        "NM1*PR*2*PAYER NAME*****PI*PAYERID",
        "CLM*CLAIM001*500***11:A:1",
        "LX*1",
        "SV2*0300*HC:99213*200*UN*1",
        "SE*17*0001",
        "GE*1*1",
        "IEA*1*000000001",
    ]


def _rule_ids(result) -> set[str]:
    return {e.rule_id for e in result.errors}


# --------------------------------------------------------------------------- #
def test_parser_detects_delimiters():
    doc = parser.parse(_edi(_p_body()))
    assert doc.delimiters.element == "*"
    assert doc.delimiters.component == ":"
    assert doc.delimiters.segment == "~"
    assert doc.delimiters.repetition == "^"


def test_valid_837p_passes_clean():
    result = validate(_edi(_p_body()))
    assert result.txn_type == "837P"
    assert result.is_valid, result.summary()


def test_valid_837i_passes_clean():
    result = validate(_edi(_i_body()))
    assert result.txn_type == "837I"
    assert result.is_valid, result.summary()


def test_detect_txn_type():
    assert detect_txn_type(parser.parse(_edi(_p_body()))) == "837P"
    assert detect_txn_type(parser.parse(_edi(_i_body()))) == "837I"


def test_se_segment_count_mismatch():
    body = _p_body()
    body[body.index("SE*17*0001")] = "SE*99*0001"
    assert "ENV.SE.COUNT" in _rule_ids(validate(_edi(body)))


def test_st_se_control_mismatch():
    body = _p_body()
    body[body.index("SE*17*0001")] = "SE*17*9999"
    assert "ENV.ST.CONTROL" in _rule_ids(validate(_edi(body)))


def test_isa_iea_control_mismatch():
    body = _p_body()
    body[body.index("IEA*1*000000001")] = "IEA*1*000000002"
    assert "ENV.ISA.CONTROL" in _rule_ids(validate(_edi(body)))


def test_missing_required_segment():
    body = _p_body()
    body.remove("N3*123 MAIN ST")
    result = validate(_edi(body))
    missing = {e.segment_id for e in result.errors if e.rule_id == "STRUCT.SEG.MISSING"}
    assert "N3" in missing


def test_bad_code_value():
    body = _p_body()
    body[body.index("BHT*0019*00*REF123*20210101*1253*CH")] = "BHT*0019*00*REF123*20210101*1253*XX"
    errs = [e for e in validate(_edi(body)).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "BHT06" for e in errs)


def test_bad_place_of_service_in_composite():
    body = _p_body()
    body[body.index("CLM*CLAIM001*500***11:B:1")] = "CLM*CLAIM001*500***00:B:1"
    errs = [e for e in validate(_edi(body)).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "CLM05-1" for e in errs)


def test_missing_required_element():
    body = _p_body()
    # Drop NM103 (billing provider name) -> required element error
    body[body.index("NM1*85*2*BILLING PROVIDER*****XX*1234567893")] = "NM1*85*2*****XX*1234567893"
    errs = [e for e in validate(_edi(body)).errors if e.rule_id == "ELEM.REQUIRED"]
    assert any(e.element_ref == "NM103" for e in errs)


def test_plan_overlay_restricts_codes():
    body = _p_body()  # SBR09 = CI, valid in base spec
    overlay = {"codes": {"SBR09": ["MC"]}}  # plan only accepts Medicaid
    errs = [e for e in validate(_edi(body), overlay=overlay).errors if e.rule_id == "ELEM.CODE"]
    assert any(e.element_ref == "SBR09" for e in errs)


def test_garbage_is_fatal_parse_error():
    assert "PARSE.FATAL" in _rule_ids(validate("this is not EDI"))


def test_unknown_transaction_type():
    body = _p_body("005010X999")  # bogus implementation convention
    assert "TXN.UNKNOWN" in _rule_ids(validate(_edi(body)))
