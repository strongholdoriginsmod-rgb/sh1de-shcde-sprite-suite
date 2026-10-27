# Entwicklungsplan

Stand: 28.09.2026. Arbeitsgrundlage: die bereitgestellte ODT-Spezifikation, die vorhandene Version 0.1 und die in RECHERCHE.md bezeichneten Primärquellen.

## 1. Fachliche Abgrenzung

Die Anwendung bearbeitet exportierte PNG-Sprites, deren Zuordnung und Metadaten. Ziel ist eine nachvollziehbare Vorbereitung von SHDE- und eigenen Grafiken für SHCDE. Die 64-Pixel-Tilebreite ist ein Arbeitsraster aus der Vorlage, keine universelle Größenbeschränkung für Einheiten oder Vegetation. Kein ungesicherter Binärpatcher, kein vorgetäuschter In-Game-Test. Der recherchierte Ausgabeweg ist das dokumentierte SHCDE Script Extender Atlas-/Sprite-Override-Format.

## 2. Ziele und Abnahmekriterien

| Ziel | Abnahmekriterium |
|---|---|
| Sachliche Oberfläche | Kompakte Werkzeugleisten, Arbeitsfläche, Dateiliste und getrennte Eigenschaften/Ziel/Prüfung; keine Werbesprüche, KI-Labels, Startkarten oder dekorativen Kennzahlen. |
| Verlässliche Bilddaten | Export ohne Canvas-Rücklesen; separater PNG-Codec, CRC-Prüfung, Erhalt der ursprünglichen PNG-Bytes; Tests mit niedrigen Alphawerten. |
| Gebäude-Workflow | Nummerierung gemäß 5×5-Vorlage, rechteckige Raster, Nummernlücken, Ebenenreihenfolge, Versatz, Sichtbarkeit und variable Höhe. |
| Portierung | Explizite Quell-/Zielnamen, Zielreferenzen, Pivot/PPU, Masken, CSV-Zuordnung und Konfliktprüfung; keine erfundene SHDE→SHCDE-ID-Tabelle. |
| Rückweg | Schnittvorschau, Überstände, vollständige Pixelzuordnung, manuell korrigierbare Schnittmaske und Abbruch bei sichtbaren unzugeordneten Pixeln. |
| Weitere Assettypen | Einzelbild- und Animationsansicht mit gemeinsamen Ankern, Maskenkanälen und Referenzvergleich. |
| Ausgabe | PNG, Originale, OpenRaster-Ebenen, Atlas-PNG/JSON, Projekt und Script-Extender-Paket; validierte Dateinamen und Exportbericht. |
| Datenhaltung | Transaktionale Importe, Rückgängig/Wiederholen, gespeicherte Schnittdaten, lokale Wiederherstellung, Import alter v0.1-Projekte. |
| Absicherung | Format-, Geometrie-, Bild-, Archiv- und Browser-Tests, schadhafte Eingaben, Netzwerkprüfung und tatsächliche Sichtprüfung bei mehreren Fenstergrößen. |

## 3. Reihenfolge

Recherche → Datenmodell und Dateiformate → Pixel-/Geometriekern → Import/Export → Oberfläche → automatisierte Tests → Sichtprüfung → Fehlerkorrekturen → erneuter Gesamtlauf → Paketprüfung.

## 4. Nicht Teil der Abnahme

Originale SHDE-/SHCDE-Assets und eine Spielinstallation wurden nicht bereitgestellt. Deshalb gehören tatsächliche Zuordnung einzelner Spiel-IDs, Shaderwiedergabe, Engine-Kompatibilität einer konkreten Installation und In-Game-Abnahme nicht zu den behaupteten Testergebnissen. DDS-Kompression und Unity-AssetBundle-Erzeugung bleiben externe Schritte. Das ist eine fachliche Grenze, keine durch einen synthetischen Test ersetzbare Prüfung.

## 5. Abschluss am 29.09.2026

Die Implementierungsstufen sind umgesetzt: isolierter Pixel-/Geometriekern, sichere Formatuntermenge, getrennte Quell-/Zielmetadaten, fünf Arbeitsansichten, explizite Schnittzuordnung, Paketexport und Projektverwaltung. Quellcode, Anleitung, Recherchebefunde, synthetische Beispiele und Prüfprogramme sind beigepackt.

Nach den Fehlerkorrekturen wurde die endgültige HTML-Datei neu gebaut und erneut geprüft: 99 Kern-/Format-Tests und 49 Browser-Prüfungen bestanden. Der Browserbericht ist über SHA-256 an genau diese HTML-Datei gebunden. Tatsächliches altes Beispielprojekt, Originalbyte-Erhalt, maskierte Modausgaben, Schnitt-Roundtrip, maximale Frameanzahl und schmale Oberfläche sind Teil dieser Abnahme.

Die native lokale Wiederherstellung ist implementiert, ihre Dauerhaftigkeit wurde nicht getestet. Direktstart über file://, Betriebssystem-/Spieltests und Prüfung mit Originalassets bleiben ausdrücklich außerhalb des erreichten Prüfnachweises. Die Recherche kennzeichnet den experimentellen Atlasweg und ungesicherte Zuordnungsannahmen. Es gibt kein automatisches „im Spiel geprüft“-Siegel.
