# SpriteSuite – technische Qualitätsprüfung

**Stand:** 29. Oktober 2026 · **Ziel:** bestehende benutzbare Funktionen
prüfen und konkrete Fehler beseitigen, nicht nur die Oberfläche umgestalten.

## Prüfumfang und Änderungen

| Bereich | Feststellung | Änderung und Prüfmethode |
| --- | --- | --- |
| Layouts nach Wechsel des Installationsordners | Bisherige Metadatenkennung beruhte auf einem absoluten Rechnerpfad | Relative, projektbezogene Metadatenkennung; Importbilder, Szenen und Exportbelege nach Ordnerumzug erneut geöffnet und mit SHA-256 verglichen |
| Bestehende Projekte | Alte Metadaten dürfen nicht verloren gehen oder überschrieben werden | Erstzugriff kopiert alte Metadaten in eine geprüfte neue Ablage; alte Ordner bleiben unverändert; Verknüpfungen und veränderte Quelldateien werden abgelehnt |
| Übertragung auf andere Computer | Ein PNG-Export allein bewahrt keine editierbaren Ebenen | Vollständiges SpriteSuite-Projektarchiv (ZIP) mit Ressourcen, Layouts, Positionen, Baselines, Revisionen und Exportbelegen |
| Import fremder Archive | ZIP-Einträge könnten absolute Pfade, doppelte Namen, verknüpfte Dateien oder verdächtige Größen enthalten | Pfad- und Dateitypprüfung, Mengenlimits, SHA-256 pro Datei, beschränkte Dekompression; nur neue Arbeitsordner |
| Bedienung | „Projekt speichern“ und „Modpaket bauen“ waren schwer zu unterscheiden | Deutlich beschriftete Schaltflächen „Projekt sichern“ und „Projekt aus ZIP öffnen“, freien Projektnamen vorschlagen, deutsche Fehlertexte |
| Spielinstallationen | Projektübertragung darf keine Installation oder Spiel-QA-Zuordnung reproduzieren | Spielinstallationen, globale Einstellungen und QA-Installationsbelege aus Archiven ausgeschlossen |
| Verifikation bei künftigen Änderungen | Bislang fehlte ein verpflichtender Windows-Testworkflow | GitHub Actions: Python 3.13 auf Windows x64, Syntaxprüfung und gezielte Daten-/Layout-/Export-Tests |

Der Projektarchiv-Export liest Arbeitsdateien und schreibt nur die
ausdrücklich angegebene ZIP. Der Import erstellt neue Projekt- und
Metadatenordner. **Weder Export noch Import installieren Mods.**

## Was ein bestandener Test tatsächlich belegt

- **Synthetischer Datentransfer:** Erzeugen und Wiederherstellen mit
  eigenen PNG-Dateien, exakten Positionen, Ebenen und Exportmanifesten.
- **Integrität:** Prüfung sowohl der vollständigen Archivdatei als auch
  jedes einzelnen entpackten Dateiinhalts.
- **Schutz von Originalen:** Absichtliche Fehlerfälle dürfen vorhandene
  Projekte und Ausgangsbilder nicht verändern.
- **Kompatibilität:** Alte Metadaten werden auf dem ursprünglichen
  Rechner kopiert; die neue Kennung bleibt nach Verschieben des
  gesamten Arbeitsordners gültig.
- **Grafische Bedienung:** Archiv-Export und -Import wurden in einer
  echten Tk-Instanz mit Testbildern durchgeführt, einschließlich
  kleiner Fensterbreite.
- **CI:** Prüft die betreffenden Kernmodule auf Windows. Ein
  erfolgreicher Testlauf garantiert nicht automatisch alle Spezialwerkzeuge.

## Bekannte Grenzen und nächste Abnahmeschritte

1. **Bereits ohne Migration verschobene Altbestände:** Fehlt der ursprüngliche
   Installationspfad, lässt sich eine alte Hash-Kennung unter Umständen
   nicht eindeutig einem Projekt zuordnen. Nicht raten; originale
   Installation und deren `work`-Ordner aufbewahren.
2. **Externe Werkzeuge:** Unity, .NET, Drittanbieter-Encoder und
   Script-Extender-Installationen benötigen jeweils eigene Tests.
3. **Noesis-Ingame-Verhalten:** Ein statisches Overlay ist noch keine
   echte Verschiebung oder Neudefinition anklickbarer Spielschaltflächen.
   Dazu sind tatsächliche XAML-/ViewModel-Definitionen und ein
   Ingame-Test erforderlich.
4. **Anderer Windows-Rechner:** Die portable Laufzeit und der ZIP-Transfer
   benötigen eine separate Abnahme auf mindestens einem zweiten
   Windows-10-/11-x64-Rechner ohne vorhandenes Python.
5. **Weitere Bereiche:** Atlasbearbeitung, native Mod-Builds und alle
   Spezialeditoren wurden in diesem Teilschritt nicht einzeln
   vollständig regressionsgetestet.

## Bedienung

[Projektarchive: ausführliche Anleitung](PROJEKTARCHIVE_2026-10-29.md)

Die neue Windows-Komplettausgabe wird als separater GitHub-Release
veröffentlicht; frühere Ausgaben bleiben erhalten.
