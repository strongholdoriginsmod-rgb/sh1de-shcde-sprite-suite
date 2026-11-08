# Stronghold Sprite Editor 1.0.0

Lokaler Editor für exportierte PNG-Assets. Arbeitsrichtung: **Stronghold: Definitive Edition → Stronghold Crusader: Definitive Edition** sowie **eigene Grafiken → Stronghold Crusader: Definitive Edition**.

## Start

`Stronghold_Sprite_Editor.html` in einem aktuellen Chromium-basierten Desktop-Browser öffnen. Die Datei enthält die gesamte Anwendung; keine Installation, kein Konto, kein Server und kein npm-Paket erforderlich. Die Bildverarbeitung benötigt keine Internetverbindung. Für KI-Aufträge über Codex den Editor über SpriteSuite starten. Die Standalone-Datei unterstützt auch Anfrageexport und PNG-Import.

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

## Gebäude-Schadensmodelle und Codex\n\nIm Inspector-Reiter **Schaden** das Originalgebäude auswählen. Mit dem lokalen Codex-Client und einer ChatGPT-Anmeldung lassen sich einzelne mechanische oder Feuer-Schadensstufen, Serien mit eigenen HP-Schwellen und neue Gebäudeversionen im Originalstil erstellen. Der Editor schickt passende Prompts und Bildreferenzen mit. Passende Ergebnisse werden als bearbeitbare Tiles übernommen. Fehlende Registrierung kann per Rohbild-Download und manueller Ausrichtung korrigiert werden.

Die Schadensbibliothek kann einschließlich Entwürfen exportiert werden. Die optionale Inhaltsfreigabe ermöglicht einen getrennten Export geprüfter Stufen. Die Bibliothek ist ein Eingabeformat des SpriteSuite-Runtime-Moduls. Bedienung und CLI-Ablauf stehen im [Handbuch für Gebäudeschäden](dokumentation/GEBAEUDESCHADEN.md).

## Gemeinsamer Geometrie-Inspektor und KI-Werkstatt

Der Inspector bietet jetzt **Geometrie** und **KI-Werkstatt** als zusätzliche Reiter. Im Geometrie-Reiter sind Pivot, Bodenanker, Fangraster, Abstand, Winkel, Overlay-Vergleich und optional das Übernehmen eines gemessenen Versatzes in einer gemeinsamen Editoroberfläche zusammengeführt. Der Geometrie-Reiter importiert zusätzlich echte `zinnenlineal.versatz.v1`-Messdateien, visualisiert den vorgeschlagenen Pivot auf demselben Canvas und übernimmt ihn ausschließlich nach Einzelprüfung mit Abnahmevermerk. Der frühere Zinnenlineal-Anwendungsfall benötigt damit keinen zusätzlichen Bildschirm oder eine eigene Verschiebe-Logik. Die alte separate Oberfläche bleibt nur für tiefe BC7-/Spielindex-Gegenprüfungen verfügbar. Unveränderte Originalbilder und die Undo-Historie bleiben geschützt.

In der **KI-Werkstatt** können für Gebäude, Einheiten, Vegetation und UI/HUD individuelle Ziele und Erhaltungsregeln formuliert und bis zu vier getrennte Varianten vorbereitet werden. Der Editor exportiert offline ein ZIP mit Originalreferenz, registriertem Modellbild, Prompt und SHA-256-Nachweis. Das optionale Tool `tools/suite_ai_codex.py` validiert das ZIP standardmäßig **ohne** Netzwerk oder Kosten. Kostenpflichtige GPT-Image-Aufrufe erfordern ausdrücklich `--execute --confirm-paid-requests N` und einen getrennt bereitgestellten API-Schlüssel. Die Varianten werden als unabhängige PNGs kontrolliert, optional zusammen mit gleichnamigen `*_meta.json`-Dateien: Quellbild-, Kandidaten- und Request-SHA müssen übereinstimmen. Der Generator dokumentiert unvollständige Aufrufe in `run-status.json`; selbst ein passendes lokales Manifest ist keine Provider-Signatur. Nichts wird automatisch ins Spiel installiert. Erst eine manuelle Referenzprüfung samt Abnahmevermerk übernimmt einen Kandidaten in die Arbeitskopie. Die Projektprovenienz ist an das exakte RGBA-Bild gebunden.

Der spezifische **HP-/Feuer-Schadensworkflow** behält seine strengeren Freigabe- und Exportschranken; ein normales KI-Sprite ist **kein** automatisch freigegebenes Schadensmodell. Weitere technische Grenzen und QA-Gates sind in `../../docs/SPRITESUITE_CONVERGENCE_V2_20261108.md` dokumentiert. Die Haupt-Suite kann diesen Editor mit `editor_bruecke.py oeffnen --bereich geometry` beziehungsweise `--bereich ai` direkt zum jeweiligen Inspektor öffnen.

## Portierung

Quell-PNGs und zugehörige `_m.png`-Masken importieren. Vorhandene Quellmetadaten hinzufügen. SHCDE-Zielreferenzen und deren Metadaten separat laden. Zielnamen für die ausgewählten Frames einzeln, als Serie oder per CSV zuordnen. Pivot, Auflösung, PPU und Material abgleichen. Unter **Prüfung** Fehler bearbeiten; erst anschließend das Modpaket exportieren.

Die Anwendung erzeugt Einzelbild- oder Atlas-Pakete für **SHCDE Script Extender**, nicht für das unveränderte Spiel. Der Exportweg und seine Einschränkungen sind in `dokumentation/RECHERCHE.md` mit Maintainer-Quellen belegt. BepInEx und Script Extender sind nicht beigepackt oder installiert. Bei Atlas-Ausgaben ist PNG das Arbeits-/Testformat; DDS-Kompression für die Veröffentlichung erfolgt extern.

## Dateiausgaben

Gesamtbild-PNG, bearbeitete Tiles als ZIP, unveränderte Original-PNGs als ZIP, OpenRaster-Ebenen, Atlas-PNG/JSON, Zuordnungs-CSV, Schnitt-ZIP, Schnittmasken-PNG, JSON-Prüfbericht, `.shsprite`-Projekt und Modpaket als ZIP oder `.semod`.

Die Originaldateien bleiben getrennt von Bearbeitungen erhalten. `.shsprite` enthält Originale, aktuelle Bilder, Masken, Zielreferenzen und Schnittdaten mit SHA-256-Prüfsummen. Rückgängig/Wiederholen umfasst bis zu 50 Schritte, wird aber nicht als Historie in der Projektdatei archiviert.

## Prüfung und Grenzen

Der Teststand umfasst die bestehende Kern-/Format-/Überlappungs-Suite, zusätzliche KI- und Geometrie-Kerntests, **49 allgemeine Browser-Prüfungen und 16 Schadensbrowser-Prüfungen** sowie einen separaten Edge-End-to-End-Test der neuen KI-Oberfläche, einschließlich sichtbarer 1-Pixel-Schnittüberlappung und sicher geteilter hinterer Reihen. Dazu gehören echte Importdialoge und Downloads, unabhängige PNG-Vergleiche, der Import des ursprünglichen v0.1-Beispiels sowie ein 4096-Frame-Projekt mit virtualisierter Liste.

**Noch offen:** In-Game-Abnahme der drei konkreten Ruinen, Prüfung an deren extrahierten Original-Tiles, native macOS-Prüfung und dauerhafte native IndexedDB-Wiederherstellung. Der direkte `file://`-Start wurde inzwischen unter Windows mit Edge in Deutsch und Englisch getestet. Die Browserprüfung verwendete die unveränderte HTML-Datei in Chromium per `page.set_content`. Dies ist kein Ersatz für eine Abnahme in der konkreten Spielinstallation.

16 Megapixel je Bild, 32 Megapixel an gehaltenen Bilddaten einschließlich Originalen und Historie, maximal 4096 Sprites. PNG mit 16 Bit pro Kanal und APNG werden abgewiesen; keine stille Reduktion. Große Verarbeitungsschritte laufen im Hauptthread; Abbruch wird an definierten Verarbeitungsgrenzen wirksam, nicht mitten in jeder Pixelschleife.

Kein GM1-Binärpatcher, kein AssetBundle- oder DDS-Editor, kein automatischer Mesh-Extractor, kein ORA-Import, kein Workshop-Publisher und keine Erzeugung neuer Gameplay-Objekte. Ein flaches Gesamtbild enthält keine verdeckten Originalpixel. Der Schnitt erzeugt deshalb neue Tiles, nicht rückwirkend die verlorenen Ebenen.

## Paketinhalt

`beispiele/` enthält ausschließlich synthetische Daten. `dokumentation/ANLEITUNG.md` beschreibt die Bedienung, `RECHERCHE.md` die Quellen und Fallstricke, `ARCHITEKTUR.md` die technischen Verträge und `TESTBERICHT.md` die tatsächlich ausgeführten Prüfungen. `src/` enthält den lesbaren Quellcode, `tests/` die reproduzierbaren Prüfprogramme. `SHA256SUMS.txt` erlaubt die Kontrolle der Paketdateien.

Neu bauen: `python build.py`, anschließend `python sprache/einbauen.py`. Kernprüfungen: `node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs`. Weitere Testbefehle stehen im Testbericht. Für die reine Benutzung wird weder Python noch Node benötigt.
