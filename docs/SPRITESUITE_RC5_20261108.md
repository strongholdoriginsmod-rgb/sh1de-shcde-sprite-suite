# SpriteSuite RC5 · Atlas, Startseiten-Chat und freie Grafikabläufe

Dieser Stand führt die Entwicklung auf `main` nach RC4 fort. Die RC4-Dateien und der RC4-Tag bleiben unverändert. RC5 ist eine Vorabversion; eine echte HP-/Feuer-Spielabnahme steht weiterhin aus.

## Geändertes Verhalten

- **SH1 → Crusader:** Gewünschte Elemente direkt auswählen und übertragen. Die frühere Pflichtbegründung, Mindestlänge und manuelle Einzelfreigabe entfallen. Mehrfachauswahl und eigene Zuordnungen sind möglich. Eine passende Größenanpassung kann gewählt werden.
- **Eigene Grafik und KI:** Entwürfe benötigen keine Qualitätsfreigabe, um weiterverarbeitet oder exportiert zu werden. Prüfvermerke beschreiben den Zustand. Technisch lesbare Bilddaten, gültige Zielrechtecke und Dateistrukturen bleiben für den jeweiligen Export erforderlich.
- **Eigene Tile-Raster:** Zusammensetzen und verlustfrei zurückteilen ohne zusätzliche semantische Bestätigung. Ein Katalogeintrag benötigt keinen bestimmten Freigabestempel. Ein eigener Prüfvermerk bleibt optional.
- **Lokale Atlas-Aktionen:** Keine zusätzliche Vorabfreigabe für den gewählten lokalen Build, die Store-Übernahme oder den Profileintrag. Bestehende Ergebnisse werden weiterhin als bestehende Dateien behandelt; die Bedienung benennt eine tatsächliche Ersetzung.
- **Projektnamen:** Kurze Namen wie `X`, Großbuchstaben, Leerzeichen und Umlaute verwenden denselben Namensvertrag wie die Projektsicherung.

## Atlas-PNG samt XAML

Der neue Arbeitsbereich öffnet ein direkt gewähltes PNG/XAML-Paar. **Strg+K → UI-Atlas · PNG + XAML**, **Projekt & Dateien → Mehr → UI-Atlas (PNG + XAML)…** und **Oberfläche → PNG + XAML öffnen…** öffnen denselben projektgebundenen Controller.

Die XAML-Ressourcen liefern die Sprite-Schlüssel und Rechtecke. Eine zweite Atlasquelle kann ausgewählte Sprites liefern. Ersetzen, Rückgängig, Wiederholen und Originalwiederherstellung werden dauerhaft gespeichert. Der PNG-Export behält verdeckte RGBA-Werte; der Paar-Export kopiert die XAML byteidentisch. Relative Unterverzeichnisse des Bild-URI bleiben erhalten.

**Ins Mod-Projekt übernehmen** veröffentlicht das Paar unter `Override/Assets/GUI/Sprites/`. Dateihashes, Exportbeleg und Arbeitsstand-Revision werden vor der Veröffentlichung geprüft. Vorhandene Projektdateien erhalten private Revisionssicherungen. Bei einem Schreibfehler wird die Übernahme zurückgenommen; fremde zwischenzeitliche Änderungen werden erhalten und Wiederherstellungsdaten benannt. Mehrere Zielverzeichnisse bilden keine stromausfallsichere Dateisystem-Transaktion.

Der durchgehende Test verarbeitet einen echten synthetischen 8192 × 8192-PNG-Atlas: Bearbeitung eines Rand-Sprites, native Projektübernahme, pixelgeprüfter Mod-ZIP-Inhalt und Wiederherstellen des bearbeitbaren Atlaszustands aus der Projektsicherung. Der gemeinsame Inspektor weist eine überschrittene Anzeigebudgetgrenze als Hinweis aus und verwechselt sie nicht mit einer beschädigten PNG.

Zusätzliche Bildblätter in derselben XAML werden als fehlende Zusatzquellen ausgewiesen. Die Suite erfindet deren Pixel nicht. Die Zuordnung zwischen einer Atlas-XAML und einem davon unabhängigen HUD-Seitenlayout bleibt getrennt. [Bedienung](UI_ATLAS_PNG_XAML.md).

## Integrierter Chat

Die Startseite enthält einen einklappbaren Chat mit Eingabe, Verlauf und Optionen. Menü und Seitenleiste verwenden denselben Controller. Beim Aufbau des Fensters wird weder eine Anmeldung noch eine Modellabfrage oder Inferenz ausgelöst.

Die Anmeldung und Modellabfrage erfolgen über den offiziellen lokalen Codex-Client mit ChatGPT-Konto, ohne API-Schlüssel. Modelle und Denkstufen werden aus dem tatsächlichen Kontoangebot geladen. Fragen, native Aufträge und Programmierung sind getrennt auswählbar. Die native Schnittstelle umfasst neun Werkzeugtypen: Projektkontext, Katalog, Werkzeugbeschreibung, Werkzeugausführung, Projektoperationen, Tk-Oberfläche, Sprite-Editor, Qt-Sandbox und Projektcode.

Projektcode kann mit SHA-Änderungsprüfung geschrieben werden. Alte Fassungen liegen in privaten Projektmetadaten. Die Voreinstellung **Aufträge** verwendet alle Werkzeuge einschließlich Programmierung ohne zusätzlichen Freigabeschritt. Der Benutzer kann lokale Python-Ausführung in den Optionen abschalten oder den nur lesenden Fragenmodus wählen. Der Assistent kann seine Optionen nicht selbst umstellen. Ausgeführter Code besitzt normale lokale Prozessrechte, keine Betriebssystem-Sandbox. Stop und Schließen behandeln ausstehende UI-Aufrufe, Sitzungen und Prozesse über die Abbruchpfade. Verspätete Ereignisse eines früheren Auftrags dürfen nicht dem nächsten Gespräch zugeschrieben werden.

Lokale Gespräche sind begrenzt und atomar gespeichert. Die Projektsicherung enthält Gespräche, Code-Revisionen und Atlaszustände. Ein installierbares Mod-ZIP enthält diese privaten Metadaten nicht. Es erfolgt keine Synchronisation mit ChatGPT-Webgesprächen. [Bedienung](KI_CHAT_STARTSEITE.md).

## Prüfung und Auslieferung

Die Prüfung umfasst Python 3.13 und 3.14, native Tk-Fenster, Atlas-Verarbeitung und Projektarchive. Ein echter Account-Test hat neun Toolschemas angenommen, Projektkontext gelesen und einen synthetischen Python-Helfer über die nativen Schreib-, Lese- und Ausführungsfunktionen bearbeitet. Die Ergebnisdatei wurde unabhängig geprüft. Ausgeschaltete Ausführung und ein veralteter Codehash wurden abgewiesen.

Das öffentliche Windows-Startpaket enthält Python und installiert die übrigen Abhängigkeiten beim Erststart mit Hashprüfung. Der Erststart benötigt Internet. Das separate Source ZIP enthält den Quellcode desselben Release-Commits. Die vollständige lokale Qt-/FMOD-Offline-Ausgabe wird nicht als öffentliches Release-Asset angeboten.

**Offen:** Die echte SHCDE-HP-/Feuer-Abnahme. Die isolierte Steam-Kopie beendet sich mit `Application load error T:0000065432`. Automatisierte Erfolge sind keine Freigabe unbekannter nativer Sprite-/Gameplay-Bindungen. Alte Zweige und Worktrees werden bis zur vollständigen Abnahme nicht entfernt.
