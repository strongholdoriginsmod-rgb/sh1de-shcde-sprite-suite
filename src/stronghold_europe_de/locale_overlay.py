from __future__ import annotations

from dataclasses import dataclass
import hashlib
import unicodedata


class LocaleOverlayError(ValueError):
    """Raised when a roster locale is not the one canonical safe overlay."""


SECTION_NUMBER = 89
SECTION_NAME = "TEXT_CHIMP_NAMES"
EXPECTED_RAW_INDICES = tuple((*range(70, 77), *range(78, 86)))
MAX_RAW_INDEX = max(EXPECTED_RAW_INDICES)
MAX_LOCALE_BYTES = 64 * 1024

LOCALE_HEADERS = {
    "de-DE": "deDE",
    "en-US": "enUS",
}


def text_key(raw_index: int) -> str:
    return f"{SECTION_NAME}_{raw_index:03d}"


EXPECTED_TEXT_KEYS = tuple(text_key(index) for index in EXPECTED_RAW_INDICES)


@dataclass(frozen=True)
class LocaleOverlay:
    locale: str
    entries: tuple[tuple[int, str], ...]

    @property
    def translations(self) -> dict[str, str]:
        return {text_key(index): value for index, value in self.entries}

    def render(self) -> bytes:
        return render_locale_overlay(self.locale, dict(self.entries))


def _sha256_rows(rows: list[str]) -> str:
    return hashlib.sha256("".join(rows).encode("utf-8")).hexdigest()


def keys_sha256(overlay: LocaleOverlay) -> str:
    return _sha256_rows(
        [f"{text_key(index)}\n" for index, _value in overlay.entries]
    )


def values_sha256(overlay: LocaleOverlay) -> str:
    return _sha256_rows(
        [f"{text_key(index)}={value}\n" for index, value in overlay.entries]
    )


def roster_text_sha256(
    german: LocaleOverlay,
    english: LocaleOverlay,
) -> str:
    if german.locale != "de-DE" or english.locale != "en-US":
        raise LocaleOverlayError("roster digest requires de-DE and en-US overlays")
    german_values = dict(german.entries)
    english_values = dict(english.entries)
    if tuple(german_values) != EXPECTED_RAW_INDICES:
        raise LocaleOverlayError("de-DE roster keys are not canonical")
    if tuple(english_values) != EXPECTED_RAW_INDICES:
        raise LocaleOverlayError("en-US roster keys are not canonical")
    return _sha256_rows(
        [
            f"{index}\t{text_key(index)}\t{german_values[index]}\t"
            f"{english_values[index]}\n"
            for index in EXPECTED_RAW_INDICES
        ]
    )


def _validated_entries(entries: dict[int, str]) -> tuple[tuple[int, str], ...]:
    if tuple(sorted(entries)) != EXPECTED_RAW_INDICES:
        raise LocaleOverlayError(
            "locale must override exactly raw indices 70-76 and 78-85"
        )
    validated: list[tuple[int, str]] = []
    for index in EXPECTED_RAW_INDICES:
        value = entries[index]
        if not isinstance(value, str) or not value:
            raise LocaleOverlayError(f"locale value {index} must be non-empty text")
        if value != value.strip():
            raise LocaleOverlayError(
                f"locale value {index} has surrounding whitespace"
            )
        if any(character in value for character in ("\r", "\n", "\0")):
            raise LocaleOverlayError(f"locale value {index} is not one line")
        if unicodedata.normalize("NFC", value) != value:
            raise LocaleOverlayError(f"locale value {index} is not Unicode NFC")
        validated.append((index, value))
    return tuple(validated)


def render_locale_overlay(locale: str, entries: dict[int, str]) -> bytes:
    try:
        header = LOCALE_HEADERS[locale]
    except KeyError as exc:
        raise LocaleOverlayError(f"unsupported roster locale: {locale!r}") from exc
    validated = _validated_entries(entries)
    values = dict(validated)
    lines = [header, ">>TEXTSTART", f">>{SECTION_NUMBER}-----"]
    lines.extend(values.get(index, "") for index in range(MAX_RAW_INDEX + 1))
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_locale_overlay(data: bytes, locale: str) -> LocaleOverlay:
    if locale not in LOCALE_HEADERS:
        raise LocaleOverlayError(f"unsupported roster locale: {locale!r}")
    if len(data) > MAX_LOCALE_BYTES:
        raise LocaleOverlayError(
            f"locale exceeds {MAX_LOCALE_BYTES} byte safety limit"
        )
    if data.startswith(b"\xef\xbb\xbf"):
        raise LocaleOverlayError("locale must not contain a UTF-8 BOM")
    if b"\0" in data:
        raise LocaleOverlayError("locale must not contain NUL bytes")
    if b"\r" in data:
        raise LocaleOverlayError("locale must use LF line endings")
    if not data.endswith(b"\n"):
        raise LocaleOverlayError("locale must end with one LF")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise LocaleOverlayError("locale is not strict UTF-8") from exc

    lines = text[:-1].split("\n")
    expected_line_count = 3 + MAX_RAW_INDEX + 1
    if len(lines) != expected_line_count:
        raise LocaleOverlayError(
            "locale is not the canonical 89-line sparse overlay: "
            f"expected={expected_line_count} actual={len(lines)}"
        )
    expected_header = [
        LOCALE_HEADERS[locale],
        ">>TEXTSTART",
        f">>{SECTION_NUMBER}-----",
    ]
    if lines[:3] != expected_header:
        raise LocaleOverlayError(
            "locale header must contain only its exact language and section 89"
        )
    entries = {
        index: value
        for index, value in enumerate(lines[3:])
        if value
    }
    validated = _validated_entries(entries)
    overlay = LocaleOverlay(locale=locale, entries=validated)
    if overlay.render() != data:
        raise LocaleOverlayError("locale bytes are not in canonical form")
    return overlay


def locale_manifest_metadata(
    overlay: LocaleOverlay,
    roster_digest: str,
) -> dict[str, object]:
    if len(roster_digest) != 64 or any(
        character not in "0123456789abcdef" for character in roster_digest
    ):
        raise LocaleOverlayError("roster text digest is not lowercase SHA-256")
    return {
        "kind": "shcdese_roster_locale_v1",
        "locale": overlay.locale,
        "section": SECTION_NAME,
        "section_number": SECTION_NUMBER,
        "override_count": len(overlay.entries),
        "keys_sha256": keys_sha256(overlay),
        "values_sha256": values_sha256(overlay),
        "roster_text_sha256": roster_digest,
    }
