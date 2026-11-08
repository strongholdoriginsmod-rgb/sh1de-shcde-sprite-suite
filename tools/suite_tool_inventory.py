r"""Reproducible, read-only SHA inventory of Stronghold/SpriteSuite tool trees.

Examples:
  python tools/suite_tool_inventory.py --compare "E:\\SU\\projekt" --format markdown
  python tools/suite_tool_inventory.py --compare "E:\\SS QA" --format json

The scanner does NOT import, run, install, delete, or copy scanned tools.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import sys

from suite_tool_policy import classify
from suite_tool_registry import SPECIALISTS

SCHEMA = "stronghold.spritesuite.tool-matrix.v1"
ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = frozenset({
    ".py", ".pyw", ".ps1", ".psm1", ".psd1", ".cmd", ".bat",
    ".cs", ".csproj", ".sln", ".js", ".cjs", ".mjs", ".ts", ".tsx",
    ".lua", ".tcl", ".sh", ".cpp", ".h", ".hpp",
})
MAX_SOURCE_BYTES = 16 * 1024 * 1024
INDEX = {item.filename: item for item in SPECIALISTS}


class InventoryError(ValueError):
    """A requested source cannot be verified safely."""


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path, "is_junction", lambda: False)()
    )


def _tools_dir(project_root: str | Path) -> tuple[Path, Path]:
    source = Path(project_root).expanduser()
    if _is_link(source):
        raise InventoryError("Verknüpfte Projektwurzel nicht zulässig")
    try:
        root = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InventoryError("Projektwurzel nicht lesbar") from exc
    tools = root / "tools"
    if _is_link(tools) or not tools.is_dir():
        raise InventoryError("Kein regulärer tools-Ordner vorhanden")
    return root, tools


def _hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _main_entrypoint(path: Path) -> bool | None:
    """Parse text; never execute user/legacy Python modules."""
    if path.suffix.lower() not in (".py", ".pyw"):
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"),
                         filename=path.name)
    except (SyntaxError, UnicodeError, OSError, ValueError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq)
                and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__"):
            return True
    return False


# Recursive mode is opt-in. Generated/third-party folders are not our tools.
_SKIP_RECURSIVE = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "vendor",
    "bin", "obj", "dist", "cache", "work", ".pytest_cache", "packages",
})
MAX_SCAN_FILES = 8000
MAX_SCAN_DEPTH = 8


def _source_paths(tools: Path, *, recursive: bool) -> list[Path]:
    """Enumerate without following a symlink/junction into any other tree."""
    if not recursive:
        return sorted(tools.iterdir(), key=lambda p: p.name.casefold())
    pending = [(tools, 0)]
    files: list[Path] = []
    while pending:
        folder, depth = pending.pop()
        for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if _is_link(path):
                # Include the unsafe source-file name as an untrusted entry.
                if path.suffix.lower() in SUFFIXES:
                    files.append(path)
                continue
            if path.is_dir():
                if path.name.casefold() in _SKIP_RECURSIVE:
                    continue
                if depth >= MAX_SCAN_DEPTH:
                    raise InventoryError("Tool-Unterverzeichnisse sind zu tief verschachtelt")
                pending.append((path, depth + 1))
            else:
                files.append(path)
            if len(files) + len(pending) > MAX_SCAN_FILES:
                raise InventoryError("Zu viele Tool-Dateien für sicheren Scan")
    return sorted(files, key=lambda p: p.relative_to(tools).as_posix().casefold())


def scan(project_root: str | Path, *, recursive: bool = False) -> dict:
    root, tools = _tools_dir(project_root)
    found = {}
    for path in _source_paths(tools, recursive=recursive):
        relative = path.relative_to(tools).as_posix()
        if path.suffix.lower() not in SUFFIXES:
            continue
        # Links (including broken links) are reported, never followed.
        if _is_link(path):
            found[relative] = {"status": "unsicherer_link", "sha256": None,
                                "bytes": None, "entrypoint": None,
                                "risk": "unknown", "specialist": False}
            continue
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            if not 0 < size <= MAX_SOURCE_BYTES:
                found[relative] = {"status": "ungültige_größe", "sha256": None,
                                    "bytes": size, "entrypoint": None,
                                    "risk": "unknown", "specialist": False}
                continue
            digest = _hash(path)
        except OSError as exc:
            raise InventoryError(f"Quelldatei kann nicht gelesen werden: {path.name}") from exc
        direct_tool = path.parent == tools
        policy = (classify(path.name, ()).category if direct_tool and
                  path.suffix.lower() in (".py", ".pyw") else "unknown")
        specialist = direct_tool and path.name in INDEX
        found[relative] = {
            "status": "regulär", "sha256": digest, "bytes": size,
            "entrypoint": _main_entrypoint(path),
            "risk": policy,
            "specialist": specialist,
            "workstream": INDEX[path.name].category_en if specialist else None,
        }
    return {"root": str(root), "tools": found, "count": len(found)}


def compare(base: dict, other: dict) -> dict:
    a, b = base["tools"], other["tools"]
    rows = []
    counts = {"identisch": 0, "abweichend": 0,
              "nur_aktuell": 0, "nur_historisch": 0, "nicht_vergleichbar": 0}
    for name in sorted(set(a) | set(b), key=str.casefold):
        left, right = a.get(name), b.get(name)
        if left is None:
            status = "nur_historisch"
        elif right is None:
            status = "nur_aktuell"
        elif left["sha256"] is None or right["sha256"] is None:
            status = "nicht_vergleichbar"
        elif left["sha256"] == right["sha256"]:
            status = "identisch"
        else:
            status = "abweichend"
        counts[status] += 1
        rows.append({
            "name": name, "status": status,
            "current_sha256": left["sha256"] if left else None,
            "historical_sha256": right["sha256"] if right else None,
            "current_risk": left["risk"] if left else None,
            "historical_risk": right["risk"] if right else None,
            "current_entrypoint": left["entrypoint"] if left else None,
            "historical_entrypoint": right["entrypoint"] if right else None,
            "specialist": bool(left and left["specialist"]),
        })
    return {"source": other["root"], "counts": counts, "tools": rows}


def build_matrix(current: str | Path, historical: list[str | Path],
                 *, recursive: bool = False) -> dict:
    base = scan(current, recursive=recursive)
    comparisons = []
    seen = {Path(base["root"])}
    for source in historical:
        other = scan(source, recursive=recursive)
        key = Path(other["root"])
        if key in seen:
            raise InventoryError("Doppelte oder identische Vergleichswurzel")
        seen.add(key)
        comparisons.append(compare(base, other))
    return {
        "schema": SCHEMA,
        "recursive": recursive,
        "current": base,
        "comparisons": comparisons,
        "operation": "Dateivergleich ausschließlich lesend; keine Toolausführung",
    }


def markdown(matrix: dict) -> str:
    lines = [
        "# Stronghold/SpriteSuite – Tool-Matrix",
        "",
        "Standbasis: " + matrix["current"]["root"],
        "SHA-256 belegt Bytegleichheit, nicht Funktions- oder ABI-Kompatibilität.",
        "Kein Tool wurde ausgeführt, kopiert oder in ein Spiel installiert.",
        "",
        "| Vergleichsquelle | Identisch | Unterschiedlich | Nur aktuell | Nur historisch | Unprüfbar |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for block in matrix["comparisons"]:
        c = block["counts"]
        lines.append(
            f"| {block['source'].replace('|', '/')} | {c['identisch']} | "
            f"{c['abweichend']} | {c['nur_aktuell']} | "
            f"{c['nur_historisch']} | {c['nicht_vergleichbar']} |"
        )
    for block in matrix["comparisons"]:
        lines.extend(["", "## Historisch fehlende/abweichende Tools: "
                      + block["source"], "",
                      "| Tool | Status | historisches Risiko |",
                      "|---|---|---|"])
        for row in block["tools"]:
            if row["status"] in ("nur_historisch", "abweichend", "nicht_vergleichbar"):
                lines.append(f"| {row['name']} | {row['status']} | "
                             f"{row['historical_risk'] or 'unknown'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="Aktuelle, nicht zu ändernde SpriteSuite-Wurzel")
    parser.add_argument("--compare", type=Path, action="append", default=[],
                        help="Historische Stronghold-Projektwurzel, wiederholbar")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--recursive", action="store_true",
                        help="Auch eigene verschachtelte tools/-Quellen ohne Links lesen")
    args = parser.parse_args(argv)
    try:
        result = build_matrix(args.root, args.compare, recursive=args.recursive)
    except (InventoryError, OSError, ValueError) as exc:
        print(f"TOOL_INVENTORY_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "markdown":
        sys.stdout.write(markdown(result))
    else:
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
