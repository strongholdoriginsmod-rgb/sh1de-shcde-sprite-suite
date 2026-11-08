# RC4 – Prüfstand vom 8. November 2026

Dieser Release-Kandidat baut auf dem veröffentlichten RC3 auf. Die Quellübernahme
wurde anhand von Git-Historie, physischen Dateibeständen und Inhalts-Hashes
abgeglichen. [Übernahmematrix](SPRITESUITE_RELEASE_KONSOLIDIERUNG_20261108.md)
und [Inventar](CONSOLIDATION_20261108_INVENTORY.md) dokumentieren die Herkunft.

## Automatisierte und praktische Prüfungen

Die folgenden Gates sind getrennte Prüfgruppen mit möglichen Überschneidungen.
Sie werden nicht zu einer künstlich erhöhten Gesamtzahl addiert.

| Prüfgruppe | Ergebnis |
| --- | --- |
| Sandbox-Regression, pro Datei isoliert | 185 Module, 1.966 Fälle: 1.828 bestanden, 138 übersprungen, keine offenen Fehler oder Timeouts. |
| Runtime- und übrige Python-Regression | 106 bestanden. |
| SHCDE-Erweiterung | 43 bestanden; keine Spielinstallation vorgenommen. |
| Native Projekt-/Fachwerkzeuge des Assistenten | 26 bestanden, einschließlich echtem synthetischem Import, Änderung, Mod-ZIP und Projektwiederherstellung. |
| Native Qt-Sandbox | 20 bestanden, einschließlich Szenenänderung und gemeinsamer Undo-Historie. |
| Codex-Assistentensitzung und lokaler Editorclient | 28 bestanden: Protokoll, Wiederholungen, Zustandsprüfung, Abbruch, Ausgabebegrenzung, Loopback und Dateitransfer. |
| Letzte Tk-Assistenten-/Layoutkorrekturen | 20 Hostfälle sowie vier Workarea-Fälle und ein Labelumbruch-Fall bestanden: GUI-Dispatch und abgebrochene Warteschlange, echte Pixel-/Layoutgesten mit Undo, realer Texteditor mit Dirty-/Undo, Listen/Skalen, deaktivierte Menüs, Recovery nach fehlgeschlagener nativer Geste, Fokus/Mausrad und Textbreite nach Größenänderung. |
| Windows-Startpaket-Builder | 11 bestanden, einschließlich Unicode-Ziel, leerem PATH, frischer Umgebung und Wiederholung nach unterbrochener Einrichtung. |
| Windows-Launcher und Readiness | 15 bestanden, darunter reale Qt-Starts bei fehlendem und leerem `PATH` sowie Erhaltung eines vorhandenen Benutzerpfads. |
| Native C#-Prüfung | 59 Assertions; drei optionale native DLLs gegen lokal vorhandene SDK-Bibliotheken kompiliert. Die DLLs bleiben lokale QA-Ergebnisse. |
| Physische Windows-Layoutprüfung | Hauptansicht bei 1020×680 und 1280×720 mit vergrößerter Darstellung; untere Felder und Scrollleisten erreichbar. Letzter nativer Wheel-Test bestätigte Scrollanfang und Scrollende. |
| Browserlayout | Ansichten, Panels und Dialoge auch bei 1280×480, 1024×540, 800×500 und 640×360 geprüft. |
| Gebauter HTML-Editor | 179 Datei-Hashes; 49 Bestands-, 16 Schadens-, 12 KI-, 9 Codex- und 16 native Browserprüfungen bestanden. |
| Native Browsergesten | Deutsch und Englisch je acht echte Edge-Fälle: Drag/Undo/Redo, Pan/Fit, Messung, Pivot, Pinsel, Abbruch, konkurrierender Benutzerdrag und ungültige Eingaben. Keine Seitenfehler. |
| Browserprotokoll/-client | 41 HTTP-/Client-/KI-Prüfungen bestanden, einschließlich echtem Desktopclient → Broker → Browser. Neun native JavaScript-Unitprüfungen bestanden. |

Die 138 übersprungenen Sandbox-Fälle betreffen externe Voraussetzungen:
fünf historische Original-Szenen, eine optionale `fitz`-Umgebung und 132 weitere
private Original-/Spielruntime-Voraussetzungen. Sie sind keine bestandenen Tests.
Lange GUI-Prüfgruppen wurden mit passender Laufzeit erneut ausgeführt; der
abschließende Abgleich enthält keine ungelösten Timeouts.

## Reales ChatGPT-/Codex-Konto

Die verwaltete Kontoanmeldung wurde mit dem tatsächlich installierten lokalen
Codex-Client geprüft. Ein Bildauftrag aus der allgemeinen KI-Werkstatt erzeugte
aus einer eigenen synthetischen 64×32-Referenz einen Kandidaten. Rohbild,
Registrierung auf die Referenzmaße und SHA-256 wurden geprüft.

Ein separater echter Assistentendurchlauf nutzte zehn native Werkzeugaufrufe,
erstellte ein transparentes 16×16-PNG und baute ein Modpaket. Zwei Aufruffehler
wurden vom Assistenten anhand der Werkzeugantworten korrigiert. Der unabhängige
ZIP-Test bestätigte CRC, exakte PNG-Bytes und die angeforderten Metadaten.
Die Tests verwendeten eigene synthetische Daten, keine fremde Spielgrafik und
keinen API-Schlüssel. Kontolimits werden vom Dienst bestimmt.

## Echte Spielabnahme bleibt offen

Der vorhandene HP-/Feuer-Nachweis enthält HP-Änderungen, aber keine bestätigte
Zuordnung der geprüften Sprite-Zellen. Die isolierte Steam-Spielkopie startete
zuletzt mit `Application load error T:0000065432` nicht. Eine getrennte lizenzierte
QA-Sitzung steht nach Rückmeldung des Nutzers nicht zur Verfügung.

Damit sind tatsächlicher HP-/Feuer-Grafikwechsel und Rendererfreigabe im Spiel
weiterhin nicht abgenommen. Kompilierung, synthetische Szenen und lesende
Runtime-Diagnostik ersetzen diese Abnahme nicht. Der Release wird als
**Vorabversion** veröffentlicht. Alte Zweige und Worktrees bleiben bis zur
bestandenen vollständigen Abnahme erhalten.

## Pakete

Das öffentliche Windows-Startpaket enthält CPython und den exakt archivierten
Release-Quellcommit. Es benötigt kein separat installiertes Python. Beim ersten
Start installiert es zusätzliche Abhängigkeiten lokal anhand des SHA-256-Locks;
dafür ist Internet erforderlich. Ein abgebrochener Erststart wird wiederholt.
Die ZIPs und ihre separaten SHA-256-Dateien werden vor Veröffentlichung geprüft.
Das vollständige Offline-Portable mit Drittanbieter-Laufzeiten bleibt ein lokaler
Kandidat und wird nicht als öffentliches GitHub-Asset hochgeladen.

Die echte frische Windows-Ersteinrichtung deckte nach erfolgreicher
Paketinstallation einen Qt-Importfehler bei vollständig fehlendem `PATH` auf.
Der Launcher ergänzt nun ausschließlich für seine Kindprozesse den minimalen
Windows-Systempfad, wenn `PATH` fehlt oder leer ist. Ein vorhandener Benutzerpfad
bleibt erhalten. Reale Qt-Regressionen prüfen beide fehlenden Pfadvarianten;
die Auslieferungspakete werden aus dem korrigierten Commit neu gebaut.

Die konkrete Commit-ID, Paket-Hashes, CRC- und Startprüfungen werden im externen
Release-Prüfbeleg zusammen mit den ZIPs ausgegeben. Das vermeidet selbstbezügliche
Commit-/Archiv-Hashes in der archivierten Quelle.
