"""Spec-driven X12 validation engine. No Django imports — pure Python.

Pipeline: parse -> envelope/control checks -> detect 837P/837I -> recursive
structure match against the TR3 spec (loops, segment usage/order, element
usage, data types, code values).
"""

from __future__ import annotations

import re

from .errors import Severity, ValidationError, ValidationResult
from .parser import Document, ParseError, Segment, parse
from .spec import (
    ElementSpec,
    LoopSpec,
    SegmentSpec,
    TransactionSpec,
    load_codeset,
    load_transaction,
)


def validate(raw: str | bytes, overlay: dict | None = None) -> ValidationResult:
    """Validate an X12 837 interchange. ``overlay`` is an optional plan RuleSet."""
    result = ValidationResult()
    try:
        doc = parse(raw)
    except ParseError as exc:
        result.add(ValidationError("PARSE.FATAL", str(exc)))
        return result

    _validate_envelope(doc, result)

    txn_type = detect_txn_type(doc)
    result.txn_type = txn_type
    if txn_type is None:
        result.add(
            ValidationError(
                "TXN.UNKNOWN",
                "Could not identify an 837P/837I transaction (checked ST03/GS08)",
            )
        )
        return result

    spec = load_transaction(txn_type)
    for st_segments in _transaction_sets(doc):
        _Matcher(doc, spec, overlay, result).run(st_segments)
    return result


# --------------------------------------------------------------------------- #
# Envelope / control numbers
# --------------------------------------------------------------------------- #
def _validate_envelope(doc: Document, result: ValidationResult) -> None:
    isa = doc.first("ISA")
    iea = doc.first("IEA")
    if isa is None:
        result.add(ValidationError("ENV.ISA.MISSING", "Missing ISA header"))
    if iea is None:
        result.add(ValidationError("ENV.IEA.MISSING", "Missing IEA trailer"))
    if isa and iea:
        if isa.get(13) != iea.get(2):
            result.add(
                ValidationError(
                    "ENV.ISA.CONTROL",
                    f"IEA02 control number '{iea.get(2)}' does not match "
                    f"ISA13 '{isa.get(13)}'",
                    segment_id="IEA",
                    segment_pos=iea.pos,
                )
            )
        groups = doc.all("GS")
        if iea.get(1).lstrip("0") not in ("", str(len(groups))):
            result.add(
                ValidationError(
                    "ENV.IEA.COUNT",
                    f"IEA01 claims {iea.get(1)} functional groups; found {len(groups)}",
                    segment_id="IEA",
                    segment_pos=iea.pos,
                )
            )

    _validate_groups(doc, result)
    _validate_transaction_counts(doc, result)


def _validate_groups(doc: Document, result: ValidationResult) -> None:
    gs = doc.first("GS")
    ge = doc.first("GE")
    if gs is None:
        result.add(ValidationError("ENV.GS.MISSING", "Missing GS functional group header"))
    if ge is None:
        result.add(ValidationError("ENV.GE.MISSING", "Missing GE functional group trailer"))
    if gs and ge:
        if gs.get(6) != ge.get(2):
            result.add(
                ValidationError(
                    "ENV.GS.CONTROL",
                    f"GE02 control '{ge.get(2)}' does not match GS06 '{gs.get(6)}'",
                    segment_id="GE",
                    segment_pos=ge.pos,
                )
            )
        sts = doc.all("ST")
        if ge.get(1).lstrip("0") not in ("", str(len(sts))):
            result.add(
                ValidationError(
                    "ENV.GE.COUNT",
                    f"GE01 claims {ge.get(1)} transaction sets; found {len(sts)}",
                    segment_id="GE",
                    segment_pos=ge.pos,
                )
            )


def _validate_transaction_counts(doc: Document, result: ValidationResult) -> None:
    for st_segments in _transaction_sets(doc):
        st, se = st_segments[0], st_segments[-1]
        if se.id != "SE":
            result.add(
                ValidationError(
                    "ENV.SE.MISSING",
                    f"Transaction set starting at ST (pos {st.pos}) has no SE trailer",
                    segment_id="ST",
                    segment_pos=st.pos,
                )
            )
            continue
        if st.get(2) != se.get(2):
            result.add(
                ValidationError(
                    "ENV.ST.CONTROL",
                    f"SE02 control '{se.get(2)}' does not match ST02 '{st.get(2)}'",
                    segment_id="SE",
                    segment_pos=se.pos,
                )
            )
        claimed = se.get(1).lstrip("0")
        actual = len(st_segments)  # ST..SE inclusive
        if claimed not in ("", str(actual)):
            result.add(
                ValidationError(
                    "ENV.SE.COUNT",
                    f"SE01 claims {se.get(1)} segments; counted {actual} (ST..SE inclusive)",
                    segment_id="SE",
                    segment_pos=se.pos,
                )
            )


def _transaction_sets(doc: Document) -> list[list[Segment]]:
    """Slice the document into ST..SE segment runs."""
    sets: list[list[Segment]] = []
    current: list[Segment] | None = None
    for seg in doc.segments:
        if seg.id == "ST":
            current = [seg]
            sets.append(current)
        elif current is not None:
            current.append(seg)
            if seg.id == "SE":
                current = None
    return sets


def detect_txn_type(doc: Document) -> str | None:
    st = next((s for s in doc.segments if s.id == "ST" and s.get(1) == "837"), None)
    if st is None:
        return None
    ref = st.get(3) or ""  # ST03 implementation convention reference (HIPAA 5010)
    if not ref:
        gs = doc.first("GS")
        ref = gs.get(8) if gs else ""
    if "X222" in ref:
        return "837P"
    if "X223" in ref:
        return "837I"
    return None


# --------------------------------------------------------------------------- #
# Structure matcher (recursive descent, greedy sequential)
# --------------------------------------------------------------------------- #
class _Cursor:
    def __init__(self, segments: list[Segment]):
        self.segments = segments
        self.i = 0

    def current(self) -> Segment | None:
        return self.segments[self.i] if self.i < len(self.segments) else None

    def advance(self) -> None:
        self.i += 1

    def at_end(self) -> bool:
        return self.i >= len(self.segments)


class _Matcher:
    # ponytail: greedy sequential match — good for well-ordered files, reports
    # out-of-order segments as unexpected rather than resynchronising. Upgrade to
    # a backtracking matcher only if real files need lenient recovery.
    def __init__(
        self,
        doc: Document,
        spec: TransactionSpec,
        overlay: dict | None,
        result: ValidationResult,
    ):
        self.component = doc.delimiters.component
        self.spec = spec
        self.overlay = overlay or {}
        self.result = result

    def run(self, segments: list[Segment]) -> None:
        cur = _Cursor(segments)
        self._match_nodes(self.spec.structure, cur, loop_id=None)
        while not cur.at_end():
            seg = cur.current()
            assert seg is not None
            self.result.add(
                ValidationError(
                    "STRUCT.UNEXPECTED",
                    f"Unexpected or out-of-order segment {seg.id}",
                    segment_id=seg.id,
                    segment_pos=seg.pos,
                )
            )
            cur.advance()

    def _match_nodes(self, nodes, cur: _Cursor, loop_id: str | None) -> None:
        # Segment children are matched in declared order; a contiguous run of
        # sibling loops is matched in *any* order (TR3 nests loops within a
        # parent but real files order those sub-loops freely, e.g. 2430 before
        # 2410 at the service-line level).
        i = 0
        n = len(nodes)
        while i < n:
            if isinstance(nodes[i], SegmentSpec):
                self._match_segment(nodes[i], cur, loop_id)
                i += 1
            else:
                j = i
                while j < n and isinstance(nodes[j], LoopSpec):
                    j += 1
                self._match_loop_run(nodes[i:j], cur)
                i = j

    def _seg_matches(self, segspec: SegmentSpec, seg: Segment | None) -> bool:
        if seg is None or seg.id != segspec.id:
            return False
        for ref, val in segspec.trigger.items():
            pos = int(ref[len(segspec.id):])
            if seg.get(pos) != val:
                return False
        return True

    def _match_segment(self, segspec: SegmentSpec, cur: _Cursor, loop_id: str | None) -> None:
        count = 0
        limit = segspec.max_use or 10**9
        while count < limit and self._seg_matches(segspec, cur.current()):
            seg = cur.current()
            assert seg is not None
            self._validate_elements(seg, segspec, loop_id)
            cur.advance()
            count += 1
        if count == 0 and self._effective_usage(segspec, loop_id) == "R":
            self.result.add(
                ValidationError(
                    "STRUCT.SEG.MISSING",
                    f"Required segment {segspec.id} ({segspec.name}) is missing",
                    loop=loop_id,
                    segment_id=segspec.id,
                )
            )

    def _first_segment(self, loopspec: LoopSpec) -> SegmentSpec | None:
        for child in loopspec.children:
            if isinstance(child, SegmentSpec):
                return child
            if isinstance(child, LoopSpec):
                found = self._first_segment(child)
                if found:
                    return found
        return None

    def _match_loop_run(self, loops: list[LoopSpec], cur: _Cursor) -> None:
        # Greedily match whichever sibling loop's trigger matches the current
        # segment, respecting each loop's repeat limit, until none match.
        counts = [0] * len(loops)
        while True:
            matched = False
            for idx, loopspec in enumerate(loops):
                limit = loopspec.repeat or 10**9
                if counts[idx] >= limit:
                    continue
                trigger = self._first_segment(loopspec)
                if trigger is not None and self._seg_matches(trigger, cur.current()):
                    self._match_nodes(loopspec.children, cur, loop_id=loopspec.id)
                    counts[idx] += 1
                    matched = True
                    break
            if not matched:
                break
        for idx, loopspec in enumerate(loops):
            if counts[idx] == 0 and loopspec.usage == "R":
                self.result.add(
                    ValidationError(
                        "STRUCT.LOOP.MISSING",
                        f"Required loop {loopspec.id} ({loopspec.name}) is missing",
                        loop=loopspec.id,
                    )
                )

    # ----- element-level validation ---------------------------------------- #
    def _validate_elements(self, seg: Segment, segspec: SegmentSpec, loop_id: str | None) -> None:
        for el in segspec.elements:
            raw = seg.get(el.position)
            if not raw:
                if self._effective_usage(el, loop_id, segspec.id) == "R":
                    self._err(
                        "ELEM.REQUIRED",
                        f"{el.ref} ({el.name}) is required",
                        seg,
                        loop_id,
                        el.ref,
                    )
                continue
            if el.components:
                parts = raw.split(self.component)
                for comp in el.components:
                    sub = parts[comp.position - 1] if comp.position <= len(parts) else ""
                    if not sub:
                        if comp.usage == "R":
                            self._err(
                                "ELEM.REQUIRED",
                                f"{comp.ref} ({comp.name}) is required",
                                seg,
                                loop_id,
                                comp.ref,
                            )
                        continue
                    self._validate_scalar(sub, comp, seg, loop_id)
            else:
                self._validate_scalar(raw, el, seg, loop_id)

    def _validate_scalar(self, value: str, el: ElementSpec, seg: Segment, loop_id: str | None) -> None:
        if el.max_len and len(value) > el.max_len:
            self._err(
                "ELEM.MAXLEN",
                f"{el.ref} exceeds max length {el.max_len} (got {len(value)})",
                seg,
                loop_id,
                el.ref,
            )
        if el.min_len and len(value) < el.min_len:
            self._err(
                "ELEM.MINLEN",
                f"{el.ref} is shorter than min length {el.min_len} (got {len(value)})",
                seg,
                loop_id,
                el.ref,
            )
        dt = el.data_type
        if dt in ("N", "Nn") and not _NUMERIC.match(value):
            self._err("ELEM.TYPE", f"{el.ref} must be numeric (got '{value}')", seg, loop_id, el.ref)
        elif dt == "R" and not _DECIMAL.match(value):
            self._err("ELEM.TYPE", f"{el.ref} must be a decimal number (got '{value}')", seg, loop_id, el.ref)
        elif dt == "DT" and not _is_date(value):
            self._err("ELEM.TYPE", f"{el.ref} must be a date CCYYMMDD/YYMMDD (got '{value}')", seg, loop_id, el.ref)
        elif dt == "TM" and not _is_time(value):
            self._err("ELEM.TYPE", f"{el.ref} must be a time HHMM[SS] (got '{value}')", seg, loop_id, el.ref)

        codes = self._codes_for(el)
        if codes and value not in codes:
            self._err("ELEM.CODE", f"{el.ref} value '{value}' is not an allowed code", seg, loop_id, el.ref)

    def _codes_for(self, el: ElementSpec) -> frozenset[str] | tuple[str, ...]:
        # Plan overlay may restrict an element's allowed codes to a subset.
        restrict = self.overlay.get("codes", {}).get(el.ref)
        if restrict:
            return tuple(restrict)
        if el.codes:
            return el.codes
        if el.codeset:
            return load_codeset(el.codeset)
        return ()

    def _effective_usage(self, spec, loop_id: str | None, seg_id: str | None = None) -> str:
        """Apply plan overlay that can tighten Situational -> Required."""
        usage = spec.usage
        ref = getattr(spec, "ref", None) or getattr(spec, "id", None)
        if usage == "S" and ref in self.overlay.get("required", []):
            return "R"
        return usage

    def _err(self, rule: str, msg: str, seg: Segment, loop_id: str | None, ref: str) -> None:
        self.result.add(
            ValidationError(
                rule,
                msg,
                severity=Severity.ERROR,
                loop=loop_id,
                segment_id=seg.id,
                segment_pos=seg.pos,
                element_ref=ref,
            )
        )


_NUMERIC = re.compile(r"^-?\d+$")
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")


def _is_date(value: str) -> bool:
    if not value.isdigit() or len(value) not in (6, 8):
        return False
    mmdd = value[-4:]
    month, day = int(mmdd[:2]), int(mmdd[2:])
    return 1 <= month <= 12 and 1 <= day <= 31


def _is_time(value: str) -> bool:
    if not value.isdigit() or len(value) < 4:
        return False
    hour, minute = int(value[:2]), int(value[2:4])
    return hour <= 23 and minute <= 59
