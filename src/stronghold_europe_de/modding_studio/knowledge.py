"""Search external source baselines without copying them or treating them as live ABI."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .catalog import NATIVE_BASELINE_SHA256
from .safety import StudioError, canonical_root, read_file, read_text

SERP_KNOWLEDGE = (
    "sem/FBCB9319/knowledge/function-claims.jsonl",
    "sem/FBCB9319/knowledge/hook-spans.jsonl",
    "sem/FBCB9319/knowledge/api-contracts.jsonl",
)
MAX_KNOWLEDGE_FILE = 32 * 1024 * 1024
MAX_KNOWLEDGE_ROWS = 25_000


def _strict_pairs(rows: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in rows:
        if key in result:
            raise StudioError("duplicate field in knowledge record")
        result[key] = value
    return result


def _bounded_records(source: str, content: bytes, query: str, limit: int) -> tuple[int, list[dict]]:
    matches = []
    count = 0
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            continue
        count += 1
        if count > MAX_KNOWLEDGE_ROWS:
            raise StudioError(source + " knowledge file exceeds row limit")
        if len(line) > 128 * 1024:
            raise StudioError(source + " has an oversized evidence record")
        try:
            raw = json.loads(line.decode("utf-8", "strict"), object_pairs_hook=_strict_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise StudioError(source + " has invalid JSONL at " + str(line_number)) from exc
        if type(raw) is not dict:
            raise StudioError(source + " must contain JSONL objects")
        if query and query.casefold() not in json.dumps(
            raw, ensure_ascii=False, sort_keys=True
        ).casefold():
            continue
        if len(matches) < limit:
            # Preserve all source fields in a bounded excerpt; never infer
            # unverified function names, signatures, layouts or owners.
            canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            matches.append({
                "source": source, "line": line_number,
                "record": canonical[:3000],
                "truncated": len(canonical) > 3000,
            })
    return count, matches


def search_native_baseline(
    baseline_root: Path, query: str = "", limit: int = 30
) -> dict[str, Any]:
    root = canonical_root(baseline_root)
    if not isinstance(query, str) or len(query) > 200:
        raise StudioError("baseline search term must be at most 200 characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise StudioError("native search limit must be in 1..100")
    header = read_text(root, "CURRENT.md", 1024 * 1024)
    if NATIVE_BASELINE_SHA256 not in header.casefold():
        raise StudioError("baseline CURRENT.md is for a different native image")
    found = []
    totals = {}
    digests = {}
    for relative in SERP_KNOWLEDGE:
        data = read_file(root, relative, MAX_KNOWLEDGE_FILE)
        total, rows = _bounded_records(relative, data, query, limit - len(found))
        totals[relative] = total
        digests[relative] = sha256(data).hexdigest()
        found.extend(rows)
    return {
        "schema": "spritesuite.native-knowledge-search.v1",
        "baseline_sha256": NATIVE_BASELINE_SHA256,
        "query": query,
        "limits": {"requested": limit, "returned": len(found)},
        "rows_scanned": totals, "file_sha256": digests,
        "matches": found,
        "source_status": "unverified_external_copy_of_published_baseline",
        "in_game_compatibility": "not_established",
    }


def search_api_surface(
    api_root: Path, query: str, limit: int = 50
) -> dict[str, Any]:
    root = canonical_root(api_root)
    if not isinstance(query, str) or not 1 <= len(query) <= 200:
        raise StudioError("API surface query must be 1..200 characters")
    if type(limit) is not int or not 1 <= limit <= 200:
        raise StudioError("API surface limit must be 1..200")
    relative = "tests/ApiBaseline/PublicApi.txt"
    data = read_file(root, relative, MAX_KNOWLEDGE_FILE)
    if data.startswith(b"\xef\xbb\xbf"):
        raise StudioError("public API baseline must be BOM-free")
    try:
        lines = data.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise StudioError("public API baseline is not UTF-8") from exc
    matches = [
        {"line": index + 1, "declaration": value[:1000]}
        for index, value in enumerate(lines)
        if query.casefold() in value.casefold()
    ]
    return {
        "schema": "spritesuite.api-surface-search.v1",
        "query": query, "sha256": sha256(data).hexdigest(),
        "lines": len(lines), "total_matches": len(matches),
        "matches": matches[:limit],
        "source_status": "local_source_copy_not_compiled_binary_attestation",
    }


def attest_native_image(candidate: Path) -> dict[str, Any]:
    """Read only the explicitly supplied DLL and compare its exact SHA-256."""
    from .safety import is_link
    path = Path(candidate).absolute()
    if (
        not path.is_file()
        or is_link(path)
        or path.resolve(strict=True) != path
        or path.suffix.lower() != ".dll"
    ):
        raise StudioError("native binary must be a canonical unlinked .dll")
    size = path.stat().st_size
    if not 1 <= size <= 256 * 1024 * 1024:
        raise StudioError("native binary has unsupported size")
    hash_ = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hash_.update(chunk)
    if path.stat().st_size != size:
        raise StudioError("native binary changed during hashing")
    result = hash_.hexdigest()
    return {
        "schema": "spritesuite.native-image-attestation.v1",
        "size": size,
        "actual_sha256": result,
        "published_baseline_sha256": NATIVE_BASELINE_SHA256,
        "matches_published_baseline": result == NATIVE_BASELINE_SHA256,
        "hooks_installed": False,
        "in_game_compatibility": "not_established",
    }
