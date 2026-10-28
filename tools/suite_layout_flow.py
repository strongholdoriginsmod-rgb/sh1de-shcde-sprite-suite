"""Pure, side-effect free directions for the HUD/menu layout editor.

The editor always distinguishes a saved editable project from a verified,
baked PNG output. These labels never imply that a game mod is installed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowAdvice:
    stage: str
    heading: str
    detail: str
    button: str
    action: str


def layout_advice(*, layer_count: int, has_source: bool, unsaved: bool,
                  export_verified: bool) -> FlowAdvice:
    """Return the next useful action, never claim game integration."""
    if layer_count < 1:
        if has_source:
            return FlowAdvice(
                "image", "1 / 4 – Bild platzieren",
                "Die Grafik ist ausgewählt. Mit »Bild einfügen« auf die Arbeitsfläche setzen.",
                "Bild einfügen", "add",
            )
        return FlowAdvice(
            "image", "1 / 4 – Bild öffnen",
            "Eine PNG, JPEG oder WebP auswählen. Das Original bleibt unverändert.",
            "PNG importieren", "import",
        )
    if unsaved:
        return FlowAdvice(
            "save", "2 / 4 – Änderungen speichern",
            "Die Positionen oder Ebenen wurden geändert. Erst das Layout speichern.",
            "Layout speichern", "save",
        )
    if not export_verified:
        return FlowAdvice(
            "export", "3 / 4 – PNG erzeugen",
            "Das Layout ist gespeichert. Jetzt eine zusammengefügte PNG samt Positionsdaten exportieren.",
            "PNG exportieren", "export",
        )
    return FlowAdvice(
        "ready", "4 / 4 – PNG bereit",
        "Layout und zuletzt geprüfter PNG-Export stimmen überein. Das Spiel wurde noch nicht verändert.",
        "Spieloberfläche zuordnen", "noesis",
    )
