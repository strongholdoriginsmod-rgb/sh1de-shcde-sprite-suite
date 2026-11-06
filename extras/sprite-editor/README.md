# Stronghold Sprite Editor 1.0.0

Lokaler Editor für exportierte PNG-Assets. Arbeitsrichtung: **Stronghold: Definitive Edition → Stronghold Crusader: Definitive Edition** sowie **eigene Grafiken → Stronghold Crusader: Definitive Edition**.

## Start

`Stronghold_Sprite_Editor.html` in einem aktuellen Chromium-basierten Desktop-Browser öffnen. Die Datei enthält die gesamte Anwendung; keine Installation, kein Konto, kein Server und kein npm-Paket erforderlich. Die Bildverarbeitung benötigt keine Internetverbindung. Nur der ausdrücklich angeklickte Dokumentationslink in der Hilfe führt nach außen.

**Projekt → Beispiel öffnen** lädt einen synthetischen 5×5-Steinhof. **Projekt → Öffnen** lädt `.shsprite` und die alten v0.1-Projektdateien. Zum Arbeiten mit eigenen Dateien **Importieren → PNG-Serie / ZIP** verwenden. Projekte regelmäßig mit **Speichern** als Datei sichern. Die Meldung „Ohne Autosicherung“ bedeutet, dass der Browser keine lokale Wiederherstellung erlaubt; normale Dateiimporte und Exporte bleiben verfügbar.

## Arbeitsbereiche

| Bereich | Zweck |
|---|---|
| Aufbau | Isometrisches Raster, variable Sprite-Höhen, Rasterplätze, Ebenenreihenfolge, Versatz und Sichtbarkeit. |
| Sprite | Pivot, Original-/Zielvergleich, Differenzbild, Farb- und Maskenkanäle, Ersetzen und Stapeltransformationen. |
| Animation | Ausgewählte Frames oder sichtbare Gruppe; Wiedergabe, Einzelschritt, gemeinsamer Pivot und vorheriger Frame. |
| Schnitt | Gesamtbild mit anpassbaren Rautenflächen und manuell korrigierbarer Pixelzuordnung zerlegen; neue Schnitte verwenden einen sicheren 1-Pixel-Überlappungsrand und zusätzliche gemeinsame Bildbereiche in sämtlichen hinteren Reihen, ohne die Tilebreite über 64 Pixel zu vergrößern. |
| Atlas | Zielgruppen zusammenpacken, Abstände und Randwiederholung prüfen, Masken synchron mitführen. |

Rechts liegen **Eigenschaften**, **Ziel** und **Prüfung**. Quelldateiname, Rasterplatz und SHCDE-Zielname sind getrennte Größen. Es gibt keine automatische, behauptete ID-Übersetzung zwischen den Spielen.

## Gebäude-Schadensmodelle und Codex\n\nDer neue Inspector-Reiter **Schaden** ergänzt den normalen Gebäude-Workflow: Gebäudegruppe wählen, mechanische oder Feuer-Zerstörungsstufen mit eigenen HP-Schwellen (0–99 %) anlegen, bestehende Tiles bearbeiten oder Referenz-PNG und präzisen Prompt für **GPT Image 2.6** exportieren. Codex kann über `tools/building_damage_codex.py` Bilder erzeugen und getrennt zur Qualitätsprüfung ablegen. Neue PNGs werden erst nach explizitem Import, verlustgeprüfter 64-px-Zerlegung und visueller Freigabe als Schadensmodelle ausgegeben. Projektdatei, Undo, vorhandene Tile-Überlappungen und Originale bleiben erhalten.\n\nDie Schadensbibliothek enthält freigegebene Tiles und `damage-manifest.json`; die **dynamische Engine-Umschaltung** ist noch nicht belegt und wird **nicht** als fertiger Spiel-Hook ausgegeben. Der normale Mod-Export schließt zusätzliche Schadensstufen bewusst aus. Bedienung, Codex-Kommandos und Grenzen: [dokumentation/GEBAEUDESCHADEN.md](dokumentation/GEBAEUDESCHADEN.md).\n\n## Portierung

Quell-PNGs und zugehörige `_m.png`-Masken importieren. Vorhandene Quellmetadaten hinzufügen. SHCDE-Zielreferenzen und deren Metadaten separat laden. Zielnamen für die ausgewählten Frames einzeln, als Serie oder per CSV zuordnen. Pivot, Auflösung, PPU und Material abgleichen. Unter **Prüfung** Fehler bearbeiten; erst anschließend das Modpaket exportieren.

Die Anwendung erzeugt Einzelbild- oder Atlas-Pakete für **SHCDE Script Extender**, nicht für das unveränderte Spiel. Der Exportweg und seine Einschränkungen sind in `dokumentation/RECHERCHE.md` mit Maintainer-Quellen belegt. BepInEx und Script Extender sind nicht beigepackt oder installiert. Bei Atlas-Ausgaben ist PNG das Arbeits-/Testformat; DDS-Kompression für die Veröffentlichung erfolgt extern.

## Dateiausgaben

Gesamtbild-PNG, bearbeitete Tiles als ZIP, unveränderte Original-PNGs als ZIP, OpenRaster-Ebenen, Atlas-PNG/JSON, Zuordnungs-CSV, Schnitt-ZIP, Schnittmasken-PNG, JSON-Prüfbericht, `.shsprite`-Projekt und Modpaket als ZIP oder `.semod`.

Die Originaldateien bleiben getrennt von Bearbeitungen erhalten. `.shsprite` enthält Originale, aktuelle Bilder, Masken, Zielreferenzen und Schnittdaten mit SHA-256-Prüfsummen. Rückgängig/Wiederholen umfasst bis zu 50 Schritte, wird aber nicht als Historie in der Projektdatei archiviert.

## Prüfung und Grenzen

Der aktuelle Teststand umfasst **114 bestandene Kern-/Format-/Überlappungs-Tests und 49 bestandene Browser-Prüfungen**, einschließlich sichtbarer 1-Pixel-Schnittüberlappung und sicher geteilter hinterer Reihen. Dazu gehören echte Importdialoge und Downloads, unabhängige PNG-Vergleiche, der Import des ursprünglichen v0.1-Beispiels sowie ein 4096-Frame-Projekt mit virtualisierter Liste.

**Noch offen:** In-Game-Abnahme der drei konkreten Ruinen, Prüfung an deren extrahierten Original-Tiles, native macOS-Prüfung und dauerhafte native IndexedDB-Wiederherstellung. Der direkte `file://`-Start wurde inzwischen unter Windows mit Edge in Deutsch und Englisch getestet. Die Browserprüfung verwendete die unveränderte HTML-Datei in Chromium per `page.set_content`. Dies ist kein Ersatz für eine Abnahme in der konkreten Spielinstallation.

16 Megapixel je Bild, 32 Megapixel an gehaltenen Bilddaten einschließlich Originalen und Historie, maximal 4096 Sprites. PNG mit 16 Bit pro Kanal und APNG werden abgewiesen; keine stille Reduktion. Große Verarbeitungsschritte laufen im Hauptthread; Abbruch wird an definierten Verarbeitungsgrenzen wirksam, nicht mitten in jeder Pixelschleife.

Kein GM1-Binärpatcher, kein AssetBundle- oder DDS-Editor, kein automatischer Mesh-Extractor, kein ORA-Import, kein Workshop-Publisher und keine Erzeugung neuer Gameplay-Objekte. Ein flaches Gesamtbild enthält keine verdeckten Originalpixel. Der Schnitt erzeugt deshalb neue Tiles, nicht rückwirkend die verlorenen Ebenen.

## Paketinhalt

`beispiele/` enthält ausschließlich synthetische Daten. `dokumentation/ANLEITUNG.md` beschreibt die Bedienung, `RECHERCHE.md` die Quellen und Fallstricke, `ARCHITEKTUR.md` die technischen Verträge und `TESTBERICHT.md` die tatsächlich ausgeführten Prüfungen. `src/` enthält den lesbaren Quellcode, `tests/` die reproduzierbaren Prüfprogramme. `SHA256SUMS.txt` erlaubt die Kontrolle der Paketdateien.

Neu bauen: `python build.py`, anschließend `python sprache/einbauen.py`. Kernprüfungen: `node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs`. Weitere Testbefehle stehen im Testbericht. Für die reine Benutzung wird weder Python noch Node benötigt.
