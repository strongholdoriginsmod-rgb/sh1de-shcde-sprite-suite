"""Bounded and typed diagnostic results for all twelve offline tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .safety import StudioError, nfc, require_id


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    target: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "target": self.target,
        }


@dataclass
class Report:
    module: str
    findings: list[Finding] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def add(self, severity: str, code: str, message: str, target: str = "") -> None:
        if severity not in {"BLOCK", "REVIEW", "INFO"}:
            raise StudioError("unknown report severity")
        if len(self.findings) >= 500:
            raise StudioError("too many diagnostic findings; refuse truncated report")
        self.findings.append(Finding(severity, code, str(message)[:1200], target))

    @property
    def status(self) -> str:
        if any(item.severity == "BLOCK" for item in self.findings):
            return "BLOCKED"
        if any(item.severity == "REVIEW" for item in self.findings):
            return "REVIEW"
        return "SOURCE_PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "status": self.status,
            "findings": [item.to_dict() for item in self.findings],
            "facts": self.facts,
            "release_status": "never_in_game_verified",
        }


def exact_object(value: Any, required: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != required:
        raise StudioError(f"{label} must have exactly {sorted(required)}")
    return value


def integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise StudioError(f"{label} must be integer in {minimum}..{maximum}")
    return value


def boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise StudioError(f"{label} must be true or false")
    return value


def one_of(value: Any, options: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in options:
        raise StudioError(f"{label} must be one of {sorted(options)}")
    return value


def vector(value: Any, label: str, width: int, height: int) -> tuple[int, int]:
    if type(value) is not list or len(value) != 2:
        raise StudioError(f"{label} must be a two-integer [x, y] array")
    return (
        integer(value[0], label + ".x", 0, width - 1),
        integer(value[1], label + ".y", 0, height - 1),
    )


def analyze_items(report: Report, records: list, key: str, check: Callable[[dict, int], None]) -> None:
    used: set[str] = set()
    for index, raw in enumerate(records):
        label = f"{report.module}.{key}[{index}]"
        try:
            if type(raw) is not dict:
                raise StudioError(f"{label} must be an object")
            ident = require_id(raw.get("id"), label + ".id")
            if ident in used:
                raise StudioError(f"{label} duplicates id {ident}")
            used.add(ident)
            check(raw, index)
        except (StudioError, KeyError, TypeError, ValueError) as exc:
            report.add("BLOCK", "INVALID_ENTRY", str(exc), label)


def cost_map(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 32:
        raise StudioError(f"{label} must be a bounded resource map")
    result = {}
    for key, amount in value.items():
        name = require_id(key, f"{label}.good")
        result[name] = integer(amount, f"{label}.{name}", 0, 10_000_000)
    return result


def text(value: Any, label: str, maximum: int = 255) -> str:
    return nfc(value, label, maximum)


def report_all(reports: dict[str, Report]) -> dict[str, Any]:
    rows = {key: value.to_dict() for key, value in sorted(reports.items())}
    return {
        "schema": "spritesuite.modding-studio.report.v1",
        "status": (
            "BLOCKED" if any(r.status == "BLOCKED" for r in reports.values())
            else "REVIEW" if any(r.status == "REVIEW" for r in reports.values())
            else "SOURCE_PASS"
        ),
        "release_status": "not_in_game_verified",
        "modules": rows,
    }
