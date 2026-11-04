"""Localized *display-only* text for the unified SpriteSuite workflow.

The project model, category IDs, file paths and export manifests stay German /
canonical. Only text shown to the user is translated; original diagnostics
and filenames are never guessed or modified.
"""
from __future__ import annotations
import re
import tkinter as tk

CATEGORY_EN = {
    "Menüs / UI-Bilder": "Menu images",
    "HUD / UI-Sprites": "HUD sprites",
    "Spiel-Sprites": "Game sprites",
    "Zusätzliche Atlanten": "Atlases",
}

STATIC_EN = {
    "Noch keine Datei ausgewählt.": "No file selected.",
    "Noch keine Datei. Links Bild oder XAML hinzufügen.":
        "No file yet. Add an image or XAML on the left.",
    "Noch keine originale Noesis-Menüseite zugeordnet. Bilder lassen sich auch allein bearbeiten.":
        "No original Noesis menu page is assigned. Images can still be edited independently.",
    "Noch kein geprüfter Export für dieses Projekt.":
        "No verified export for this project.",
    "Projekt wurde seit dem letzten ZIP verändert. Bitte erneut prüfen und exportieren.":
        "Project changed since the last ZIP. Validate and export again.",
    "✓ QUELLEN  →  ✓ BEARBEITEN  →  ✓ PRÜFEN  →  ✓ MOD-ZIP":
        "✓ SOURCES  →  ✓ EDIT  →  ✓ VALIDATE  →  ✓ MOD ZIP",
    "QUELLEN HINZUFÜGEN  →  BEARBEITEN  →  PRÜFEN  →  MOD-ZIP":
        "ADD SOURCES  →  EDIT  →  VALIDATE  →  MOD ZIP",
    "Wähle eine Originalgrafik oder eine Noesis-XAML-Seite.":
        "Choose an image or a Noesis XAML page.",
    "Prüfung der Arbeitsdateien fehlgeschlagen.":
        "Workspace file validation failed.",
    "Statische Assets und XAML syntaktisch geprüft. Native Spielbefehle benötigen weiterhin einen Ingame-Test.":
        "Static assets and XAML passed syntax checks. Native game actions still require an in-game test.",
    "Ein tatsächlich geprüftes, DLL-freies Mod-ZIP wurde erstellt. Keine Spielinstallation vorgenommen; Ingame-Funktion bleibt separat zu prüfen.":
        "Verified DLL-free mod ZIP created. No game installation occurred; in-game behavior requires separate testing.",
    "Prüfe das Projekt und erstelle das Paket …":
        "Checking project and building package…",
    "Zuerst ein gültiges Mod-ZIP erstellen.":
        "Build a valid mod ZIP first.",
    "Steam-Kompatibilitätsdiagnose fehlt.":
        "Steam compatibility diagnostic is missing.",
    "Lokale Steam-Version wird lesend geprüft. Keine Modinstallation oder native ABI-Freigabe.":
        "Reading local Steam version only. No mod installation or native ABI approval.",
    "Keine Datei im Projekt": "No files in this project",
    "Bild wählen oder hinzufügen": "Choose or add an image",
    "Text-/XAML-Datei – Bearbeiten öffnen": "Text/XAML file – open editor",
    "Kein Pixelbild – passenden Editor öffnen": "Not an image – open the appropriate editor",
    "Zuerst eine Datei in der Projektliste auswählen.":
        "Select a project file first.",
    "Für diese Datei gibt es keinen integrierten Editor.":
        "No integrated editor is available for this file.",
    "Editor geöffnet · Speichern aktualisiert dieselbe Projektdatei.":
        "Editor opened · Saving updates this project file.",
}

PREFIX_EN = (
    ("Aktives Projekt: ", "Active project: "),
    ("Noesis-Original: ", "Noesis original: "),
    ("Letztes geprüftes ZIP: ", "Last verified ZIP: "),
    ("Projekt kann nicht gelesen werden: ", "Project cannot be read: "),
    ("Prüfung fehlgeschlagen: ", "Validation failed: "),
    ("Keine Paketfreigabe: ", "Package approval denied: "),
    ("Kein gültiges Paket erstellt: ", "No valid package created: "),
    ("Export gestoppt; keine Erfolgsmeldung: ", "Export stopped; no successful build: "),
    ("Transparentes Bild erzeugt: ", "Transparent image created: "),
    ("Bearbeitbares Projekt gesichert: ", "Editable project backed up: "),
    ("Bearbeitbares Projekt und Noesis-Revisionen wiederhergestellt: ",
     "Editable project and Noesis revisions restored: "),
    ("Vorschau ungültig: ", "Invalid preview: "),
    ("Bild mit Noesis-Image verbunden: ", "Image linked to Noesis image: "),
    ("Steam-Kompatibilitätsdiagnose fehlt", "Steam compatibility diagnostic missing"),
)


def display_text(value: str, english: bool) -> str:
    """Translate known UX status contracts, preserving untrusted paths/values."""
    if not english or not isinstance(value, str):
        return value
    if value in STATIC_EN:
        return STATIC_EN[value]
    m = re.fullmatch(r"(\d+) Arbeitsdatei\(en\) · Paketprüfung vor dem Export erforderlich", value)
    if m:
        return f"{m[1]} workspace file(s) · Validation required before export"
    m = re.fullmatch(r"(\d+) DATEI\(EN\)  →  BEARBEITEN  →  PRÜFEN  →  MOD-ZIP", value)
    if m:
        return f"{m[1]} FILE(S)  →  EDIT  →  VALIDATE  →  MOD ZIP"
    m = re.fullmatch(r"(\d+) Dateien geprüft · SHA-256 (.+)", value)
    if m:
        return f"{m[1]} files checked · SHA-256 {m[2]}"
    m = re.fullmatch(r"(\d+) Dateien geprüft · (\d+) Hinweis\(e\) zur Spielanbindung", value)
    if m:
        return f"{m[1]} files checked · {m[2]} game-integration notice(s)"
    if value.startswith("FERTIG: "):
        return ("DONE: " + value[len("FERTIG: "):].replace(
            " geprüfte Dateien · ", " verified files · ", 1))
    if value.startswith("Unabhängiger ZIP-/Assetvergleich bestanden · "):
        return ("Independent ZIP/asset check passed · " +
                value.split(" · ", 1)[1].replace(" Hinweise", " notice(s)", 1))
    for german, english_label in PREFIX_EN:
        if value.startswith(german):
            rest=value[len(german):]
            if german=="Noesis-Original: ":
                rest=rest.replace("(geprüfte private Kopie)", "(verified local copy)")
            return english_label+rest
    return value


class WorkflowDisplayVar(tk.StringVar):
    """A Tk StringVar whose displayed value can be reversed without data loss."""

    def __init__(self, master, is_english, value=""):
        self._is_english = is_english
        self._raw_value = str(value)
        super().__init__(master=master)
        # Initialize the Tk value without invoking our overridden set(),
        # which would otherwise replace the original DE status on startup.
        super().set(display_text(self._raw_value, bool(is_english())))

    def set(self, value):
        self._raw_value=str(value)
        super().set(display_text(self._raw_value, bool(self._is_english())))

    def refresh_language(self):
        super().set(display_text(self._raw_value, bool(self._is_english())))
