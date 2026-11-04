# SpriteSuite - Geführte Anleitung, PDF und Kompatibilität

Stand: 04.11.2026. Gilt für SpriteSuite 2.0.0 (lokaler Windows-x64-Release-Kandidat).

## Direkt in der Oberfläche

Die linke Navigation enthält jetzt immer **Anleitung (Strg+F1)**. Dadurch öffnet sich ein **nicht modaler** Lernassistent. Er zeigt real existierende Bedienfelder an und markiert sie vorübergehend. **Zurück**, **Weiter** und **Bedienelement zeigen** ändern weder Projektbilder noch installierte Spiele. Der Lernfortschritt und der abgeschlossene Lernpfad werden nutzerlokal gespeichert, soweit die Windows-Profilordner beschreibbar sind. Ein abgeschlossener Lernpfad kann erneut ab Schritt 1 durchgegangen werden. Die Hervorhebung lässt den Tastaturfokus beim Lernassistenten und aktiviert keine echten Datei- oder Exportbefehle.

Fünf Lernpfade sind verfügbar:

1. **Projekt bis Mod-ZIP:** Import, Vorschau, Editoren, Prüfung, statischer Export und bearbeitbare Sicherung.
2. **Pixel und Ebenen:** HUD-Werkstatt, Layout-Designer und überprüfbare Komposition.
3. **Spielvorschau:** Kartenöffnung, eingebettete Qt-Vorschau und Einrichtungsgrenzen.
4. **Demo-Module:** Zugang zu den 26 ausführbaren Modul-Demos; nur ein ausdrücklicher Ausführen-Klick startet Verarbeitung.
5. **Kompatibilität und Sicherheit:** Prüfungen, versionsoffene Steam-Diagnose, sichere Exporte und Freigabegrenzen.

Die Anleitung ist in Deutsch/Englisch verfügbar und aktualisiert bereits offene Schritte unmittelbar beim Sprachwechsel. Eine geöffnete Tutorial-Ansicht kann verschoben werden; sie blockiert die übrige Anwendung nicht. Schrittstand wird unter dem lokalen Windows-Profil abgelegt und **nicht** im Spiel, im Git-Quellbaum oder im Mod-Projekt.

## Illustriertes PDF

**[SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf](SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf)** ist ein 14-seitiges Handbuch im A4-Querformat mit zehn eingebetteten Originalaufnahmen aus der isolierten Windows-QA-Oberfläche. Es behandelt Projektwerkbank, sicheren Import, Ebenen-/Layout-Editor, den neuen Anleitungsmodus, Demo-Modulwahl, Spielvorschau, Kompatibilitätsbefund, Projektarchiv vs. Mod-ZIP, Deutsch/Englisch, Tastatur und Release-Grenzen.

In SpriteSuite unter **Werkzeuge > PDF-Handbuch** oder über die Schaltfläche im geöffneten Anleitungsmodus öffnen. Es verwendet den am Gerät eingestellten Standard-PDF-Betrachter; ReportLab wird **nur zur PDF-Erstellung durch Entwickler**, nicht zum Ausführen der Software benötigt.

## Kompatibilität maximal sinnvoll absichern

**Werkzeuge > Kompatibilität prüfen** öffnet eine nicht blockierende, **nur lesende** Diagnose mit deutsch-/englischsprachigen Befunden. Sie erkennt unvollständig entpackte Tcl/Tk-Portable-Pakete auch dann als eingeschränkt, wenn auf dem Prüf-PC ein vollständiges System-Python vorhanden ist. ARM64-Systeme werden nicht fälschlich als natives Windows x64 eingeordnet; das PDF wird auf einen plausiblen Dateikopf und ein gültiges Dateiende geprüft. Sie unterscheidet streng zwischen:

- **Windows x64 und CPython 3.13/3.14:** unterstützte Host-/Quelllaufzeiten. Das veröffentlichbare lokale Portable-Paket bündelt CPython 3.13; die Quellvariante besitzt zusätzliche versionierte Python-3.14-Lockdateien.
- **Tcl/Tk:** vorhandene Scriptdateien der Version 8.6 oder die native Tcl/Tk-9-ZIPFS-Laufzeit; keine globalen Änderungen.
- **PySide6 / Qt:** eigener kurzlebiger Unterprozess prüft den QtWidgets-Import samt Offscreen-Plattform-Plugin und beendet sich sofort. Das ersetzt weder GPU-Treiber- noch Ingame-Renderingtests.
- **Python-Abhängigkeiten:** jede installierte Paketversion wird gegen die passende **hashgesicherte Windows-Lockdatei** geprüft; Mischinstallationen gelten als eingeschränkt.
- **PDF und Startdateien:** Anwesenheit im Portable-Ordner.
- **.NET SDK:** optional für C#-Entwicklungswerkzeuge; fehlendes SDK ist keine Blockade des normalen PNG-/XAML-Projektworkflows.
- **Steam:** auf ausdrücklichen Wunsch werden lokale Libraries ausschließlich gelesen. Eine gefundene oder neuere Version **beweist keine native Unity-/Noesis-/Script-Extender-ABI-Sicherheit**.

Die Statusfelder heißen *Bereit*, *Eingeschränkt*, *Blockiert* oder *Nicht bestätigt*. Ein erkannter Spiel-Build hebt keine Sicherheitsgates auf. Der Bericht kann optional als JSON exportiert werden; ohne Nutzeraktion wird er nicht als Datei in Spiel- oder Projektordner geschrieben.

Kommandozeile für Entwickler/QA:

    python tools/suite_compatibility_preflight.py --json
    python tools/suite_compatibility_preflight.py --steam --json

Die Qt-Prüfung startet einen Offscreen-Unterprozess und die Steam-Prüfung liest ausschließlich lokale Metadaten. Es werden keine Abhängigkeiten heruntergeladen oder automatisch installiert.

## Bei Problemen

- Die Windows-Portable-ZIP **vollständig in einen kurzen Ordner** wie `C:/SpriteSuite` oder `E:/SS` entpacken. Eine gezielte Belastungsprobe schlug bei einem vollständigen Qt-Dateipfad von 260 Zeichen fehl, während die Entpackung in `E:/SS QA äöü 20261104` erfolgreich war. Tief verschachtelte Downloads- oder Archivordner vermeiden. Danach `SpriteSuite\Suite starten.cmd` starten.
- Bei fehlendem Qt oder Tcl/Tk die eingebettete Python-Laufzeit prüfen. **Keine** ungeprüften DLLs oder Script-Extender-Dateien aus anderen Spielen einfügen.
- Bei fehlendem Spielstand/Mapping nur lesende Inventur ausführen. Native Prüfungen und Atlas-Rollback gehören in eine autorisierte QA-Spielkopie.
- Demodaten liegen getrennt unter dem jeweiligen `work/demo-sessions`-Bereich; sie sind keine Originalspielgrafiken.

## Veröffentlichungsgrenze

Der lokale GUI-/PDF-/Portable-Erfolg ist **keine öffentliche Stable- oder Ingame-Freigabe**. Vor einer solchen Veröffentlichung fehlen ein unabhängiger zweiter Windows-PC, echte native ABI-/Spieltests, nachvollziehbarer Rollback, Screenreader-/Hardware-DPI-Abnahme und Rechteprüfung privater Spielassets.
