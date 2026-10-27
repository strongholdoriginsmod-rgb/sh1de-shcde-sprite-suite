# Änderungen gegenüber v0.1

## 1.0.0 — 29.09.2026

Oberfläche und Datenverarbeitung neu aufgebaut. Kompakte Dateiliste, Arbeitsfläche und Inspektor statt erklärungsreicher Startoberfläche. Fünf Arbeitsansichten; responsive Seitenleisten, Tastaturbedienung und virtualisierte Dateiliste.

Neu sind getrennte Quell-/Zielgruppen, Herkunft, Zielreferenzen, Zuordnungs-CSV, Pivot-/PPU-Metadaten, synchrone Materialmasken, Stapeltransformationen, Original-/Ziel-/Differenzansicht, Animationskontrolle, Atlaspacking, formale Portierungsprüfung und Script-Extender-Paketexport.

Der Rückweg wurde um explizite Schnittmasken, manuelle Pixelzuordnung, Zuordnungsprüfung und Übernahme geschnittener Tiles erweitert. Projektdateien enthalten Originale, Bearbeitungen, Referenzen und Schnittdaten mit SHA-256. Legacy-v0.1-Import bleibt enthalten.

Rohdatenbasierte PNG-/ZIP-Codecs ersetzen Canvas als Exportdatenquelle. Ressourcen-, Struktur-, CRC-, Hash-, Pfad- und Kollisionstests; transaktionale Imports und 50 Schritte Undo/Redo. Keine Netzwerkbibliotheken oder Installationszugriffe.

Im Prüfzyklus korrigiert: mehrdeutige Quellmetadaten, Referenzmetadaten vor PNG-Import, Gruppen-Dateikollisionen, Trim-Rücksetzung, große Base64-Eingaben, Atlasgrenzen nach Padding, ZIP-Deskriptorprüfung, Schnitt-Rasteränderungen und Layout bei 390 Pixeln Breite. Sämtliche angegebenen Testzahlen beziehen sich auf den abschließenden erneuten Gesamtlauf.
