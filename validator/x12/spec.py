"""Declarative TR3 spec model + JSON loader.

A transaction spec is *data* (JSON under specs/), not code. The engine walks a
parsed Document against this structure, so "full TR3 coverage" is a matter of
completing the JSON, not writing more Python.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

SPECS_DIR = Path(__file__).parent / "specs"
CODESETS_DIR = SPECS_DIR / "codesets"


@dataclass(frozen=True)
class ElementSpec:
    position: int  # 1-based (NM101 -> 1)
    ref: str  # e.g. "NM101"
    name: str = ""
    usage: str = "S"  # R | S | N  (required / situational / not used)
    data_type: str = "AN"  # AN | ID | N | Nn | R | DT | TM
    min_len: int = 0
    max_len: int = 0  # 0 == unbounded
    codes: tuple[str, ...] = ()  # inline valid code values (ID elements)
    codeset: str | None = None  # name of a shared codeset JSON (codesets/<name>.json)
    components: tuple[ElementSpec, ...] = ()  # for composite elements


@dataclass(frozen=True)
class SegmentSpec:
    id: str
    name: str = ""
    usage: str = "S"
    max_use: int = 1  # 0 == unbounded
    trigger: dict[str, str] = field(default_factory=dict)  # {"NM101": "41"}
    elements: tuple[ElementSpec, ...] = ()


@dataclass(frozen=True)
class LoopSpec:
    id: str
    name: str = ""
    usage: str = "S"
    repeat: int = 0  # 0 == unbounded
    children: tuple[object, ...] = ()  # SegmentSpec | LoopSpec, in order


@dataclass(frozen=True)
class TransactionSpec:
    transaction: str  # "837P" / "837I"
    version: str  # "005010X222A1"
    structure: tuple[object, ...]  # top-level SegmentSpec | LoopSpec nodes


def _element(d: dict) -> ElementSpec:
    return ElementSpec(
        position=d["position"],
        ref=d["ref"],
        name=d.get("name", ""),
        usage=d.get("usage", "S"),
        data_type=d.get("data_type", "AN"),
        min_len=d.get("min_len", 0),
        max_len=d.get("max_len", 0),
        codes=tuple(d.get("codes", ())),
        codeset=d.get("codeset"),
        components=tuple(_element(c) for c in d.get("components", ())),
    )


def _node(d: dict) -> object:
    if d.get("type") == "loop":
        return LoopSpec(
            id=d["id"],
            name=d.get("name", ""),
            usage=d.get("usage", "S"),
            repeat=d.get("repeat", 0),
            children=tuple(_node(c) for c in d.get("children", ())),
        )
    return SegmentSpec(
        id=d["id"],
        name=d.get("name", ""),
        usage=d.get("usage", "S"),
        max_use=d.get("max_use", 1),
        trigger=d.get("trigger", {}),
        elements=tuple(_element(e) for e in d.get("elements", ())),
    )


@lru_cache
def load_transaction(name: str) -> TransactionSpec:
    """Load a transaction spec JSON by name, e.g. '837P'."""
    data = json.loads((SPECS_DIR / f"{name}.json").read_text())
    return TransactionSpec(
        transaction=data["transaction"],
        version=data["version"],
        structure=tuple(_node(n) for n in data["structure"]),
    )


@lru_cache
def load_codeset(name: str) -> frozenset[str]:
    path = CODESETS_DIR / f"{name}.json"
    if not path.exists():
        return frozenset()
    return frozenset(json.loads(path.read_text()))
