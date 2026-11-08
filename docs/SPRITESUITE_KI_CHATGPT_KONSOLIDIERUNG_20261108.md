# SpriteSuite KI mit dem ChatGPT-Konto

Stand 08.11.2026. Die allgemeine KI-Werkstatt und die vorhandenen Gebäude-/HP-/Feueraufträge verwenden den lokalen Codex-Client mit verwalteter ChatGPT-Anmeldung. Der Browser-Login kann die dort angebotene Google-Anmeldung verwenden. Zugangsdaten verwaltet der offizielle Client. Er prüft den Kontozugriff, die Bildfunktion und die aktuellen Nutzungsgrenzen.

Den Sprite-Editor über SpriteSuite öffnen und im Bereich KI-Werkstatt einen Sprite auswählen. Assetklasse, Gestaltungsziel, Erhaltungsregeln und eine bis vier Varianten festlegen. „Bei ChatGPT anmelden“ startet den verwalteten Browser-Flow. „Varianten mit Codex erstellen“ sendet den Auftragsbund mit der registrierten Bildvorlage an die lokale Codex-Sitzung. Das angegebene historische Bildmodell wird als gewünschte Vorgabe und Herkunftsbehauptung geführt. Der Client bestimmt die tatsächlich verfügbare Bildfunktion.

Jede Variante bekommt ein Rohbild, bei passender Registrierung ein PNG im Originalraster und einen SHA-gebundenen Metadatenbeleg. Der Ergebnisdownload enthält außerdem den Laufstatus. `partial_failure` kennzeichnet einen unterbrochenen Lauf. `alignment_review_required` kennzeichnet nicht passend rückregistrierte Ausgaben. Normale Ergebnisse erscheinen zum Vergleich im Editor. Eine manuelle Abnahme ersetzt anschließend die Arbeitskopie mit Undo und Projektbeleg.

Für die CLI kann der Auftrag zunächst offline geprüft werden.

```powershell
python tools/suite_ai_codex.py --bundle auftrag.zip --output neuer_kandidatenordner --dry-run
```

Mit angemeldeter Codex-Sitzung startet ein bewusst ausgelöster Aufruf die Generierung.

```powershell
python tools/suite_ai_codex.py --bundle auftrag.zip --output neuer_kandidatenordner --execute
```

Die gemeinsame Geometrie verarbeitet `zinnenlineal.versatz.v1`. Historische Leerzeichen-/Bindestrichnamen und das alternative `x`-Suffix werden abgeglichen. Pivotbelege bleiben bildgebunden. Änderungen an Bild oder Pivot machen einen zuvor gespeicherten Beleg ungültig. Pixelrisiko, Silhouettenänderung, Bodenlinie, verdeckte RGB-Werte und Animationssprünge stehen als technische Prüfhilfen bereit.

Die Offline-Tests verwenden synthetische Codex-Antworten und lokale Loopback-Anfragen. Zusätzlich bestand ein echter einzelner ChatGPT-/Codex-Auftrag mit einer eigens erzeugten synthetischen 64×32-Pixel-Vorlage. Die Modellfläche wurde mit Nearest Neighbor auf das Originalraster zurückgeführt. Elf sichtbare Randpixel lagen innerhalb der vorhandenen Registrierungstoleranz und sind im lokalen Beleg erfasst. Rohbild, normalisiertes PNG und Quell-/Auftrags-SHA blieben erhalten. Diese Kontoverfügbarkeit beschreibt den getesteten Aufruf. Native Darstellung, Animationstiming und Gameplay benötigen ihre jeweiligen separaten Abnahmen.

Die Anmeldung und der verwaltete lokale Ablauf folgen der offiziellen Dokumentation.

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [ChatGPT-Authentifizierung](https://learn.chatgpt.com/docs/auth)
