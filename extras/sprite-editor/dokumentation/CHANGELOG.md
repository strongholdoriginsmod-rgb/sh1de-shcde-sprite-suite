# Änderungen gegenüber v0.1

## 1.0.0 – Schnitt-/Nahtkorrektur vom 06.11.2026

Der Sprite Editor verwendet für neue Schnitte eine 1-Pixel-Überlappung innerhalb der unveränderten maximal 64 Pixel breiten Tiles. Sämtliche hinteren Reihen teilen die bereits vorhandenen halben Tileflächen; vorletzte Reihen sind nicht mehr ausgenommen. Wiederholte Ownership-Kopieraufrufe für identische Nachbarn wurden zugunsten großer Bilder entfernt. Die Ownership-Maske und die Positionen werden nicht verändert. Vollständig deckende RGBA-Samples werden für Nachbarn dupliziert; teiltransparente Pixel und bedeutungstragende Materialmasken bleiben eindeutig. RGB-Farbwerte angrenzender transparenter Pixel werden bei Alpha 0 sicher ausgefüllt, um dunkles Texture-Bleeding zu mindern.

Alte Projektdateien behalten die disjunkte Verarbeitung. Zwei UI-Parameter steuern die neue Schnittlogik; Projektdatei, Schnitt-ZIP und Übernahme in die Sprite-Gruppe erhalten die Einstellungen. Core-, PNG-, Browser-, Export- und Rückwärtskompatibilitätstests wurden ergänzt.

## 1.0.0 — 29.09.2026

Oberfläche und Datenverarbeitung neu aufgebaut. Kompakte Dateiliste, Arbeitsfläche und Inspektor statt erklärungsreicher Startoberfläche. Fünf Arbeitsansichten; responsive Seitenleisten, Tastaturbedienung und virtualisierte Dateiliste.

Neu sind getrennte Quell-/Zielgruppen, Herkunft, Zielreferenzen, Zuordnungs-CSV, Pivot-/PPU-Metadaten, synchrone Materialmasken, Stapeltransformationen, Original-/Ziel-/Differenzansicht, Animationskontrolle, Atlaspacking, formale Portierungsprüfung und Script-Extender-Paketexport.

Der Rückweg wurde um explizite Schnittmasken, manuelle Pixelzuordnung, Zuordnungsprüfung und Übernahme geschnittener Tiles erweitert. Projektdateien enthalten Originale, Bearbeitungen, Referenzen und Schnittdaten mit SHA-256. Legacy-v0.1-Import bleibt enthalten.

Rohdatenbasierte PNG-/ZIP-Codecs ersetzen Canvas als Exportdatenquelle. Ressourcen-, Struktur-, CRC-, Hash-, Pfad- und Kollisionstests; transaktionale Imports und 50 Schritte Undo/Redo. Keine Netzwerkbibliotheken oder Installationszugriffe.

Im Prüfzyklus korrigiert: mehrdeutige Quellmetadaten, Referenzmetadaten vor PNG-Import, Gruppen-Dateikollisionen, Trim-Rücksetzung, große Base64-Eingaben, Atlasgrenzen nach Padding, ZIP-Deskriptorprüfung, Schnitt-Rasteränderungen und Layout bei 390 Pixeln Breite. Sämtliche angegebenen Testzahlen beziehen sich auf den abschließenden erneuten Gesamtlauf.
