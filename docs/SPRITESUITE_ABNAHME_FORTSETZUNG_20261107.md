# SpriteSuite – Abnahmefortsetzung vom 7. November 2026

Ausgangspunkt war der Portable-Stand 4f1e09e. Die [Inventur](SPRITESUITE_INVENTUR_20261107.md), der [Konsolidierungsbericht](SPRITESUITE_KONSOLIDIERUNG_20261107.md) und der [Runtime-Bericht](SPRITESUITE_HP_FEUER_RUNTIME_20261107.md) dokumentieren den vorherigen Stand. Der folgende Prüfschritt trennt echte Spielbeobachtung, installationsnahe Tests und Offline-Tests.

## HP und Feuer im Zielspiel

- Für die aktuelle Abnahme wurde E:\SSGame_HPFire_Acceptance_20261107 neu aus der vorhandenen QA-Kopie erstellt. Frühere SpriteSuite-Plugins, Spielprotokolle und BepInEx-Zwischendaten wurden beim Kopieren ausgelassen. Die SHA-256 des übernommenen QA-Spielstands lautet d29716f6fa72fc440607b3910f16eefb0abb8ee0743d060e3e93fd13f1fb24c7.
- Ein Windows-AppContainer mit eigenem LocalLow-Profil und null Netzwerk-Capabilities bestand die Kontrollprobe. Der Prozess schrieb in die neue Kopie. Schreib- und Lesezugriffe auf den vorherigen QA-Spielstand und die externe Kontrolldatei wurden verweigert. Die Host-Loopback-Kontrolle war erreichbar, der Containerprozess konnte die Verbindung nicht aufbauen.
- Der echte Start der unveränderten SHCDE-Datei im Container endete mit Steam-Dialog „Application load error T:0000065432“ und Prozess-Exitcode 53. Die Modulbeobachtung erfasste UnityPlayer.dll, es entstand kein Unity-/BepInEx-Protokoll. Ein erneuter Vergleich von 203 Dateien der relevanten vorhandenen Profile und drei Dateien der früheren QA-Kopie fand keine SHA-256-Abweichung.
- Produktions-DLL, QA-Treiber, ein Paket mit 128 PNGs und 64 Bindings sind in der neuen Kopie bereit. Der Vorschau-Modus ist ausgeschaltet. Der erweiterte Treiber erfasst über die Spiel-API HP, Brand und Gebäudestatus, liest Unity-Tilemap-Sprites zurück und fordert Screenshots an. Der Auswerter korreliert echte Readbacks und nicht im Vorschau-Modus entstandene Rendererereignisse mit Kartenreload, Entfernen, Neubau und Reparatur. Die Runtime setzt ihre Zuordnungen und Brandhistorie beim Kartenladen zurück, auch wenn das Spiel ein GameMap-Objekt wiederverwendet.
- Für den weiteren Start ist eine separate Windows-QA-Sitzung mit einer Steam-Sitzung erforderlich, die SHCDE starten kann. Das lokale Startskript E:\SSGame_HPFire_Acceptance_20261107\Start-SpriteSuite-HPFire-QA.ps1 prüft Profiltrennung, Steam-Prozess, Spiel- und Save-Hashes. Seine Profilprüfung verweigerte den Start im geschützten Profil. Die native Evidenz entsteht erst beim Start aus der separaten Sitzung.

## Origins, Einheiten und gemeinsame Projekte

- Das native Origins-Werkzeug baut jetzt aus der ausgewählten lokalen Installation. XAML-Anker, Compiler und Cecil-Prüfung müssen passen. Der fertige Plugin-Build verifiziert die beim Build gehashten Spiel-, Noesis-, Extender- und XAML-Dateien vor dem Registrieren der Hooks.
- Ein vom Origins-Autorenwerkzeug ausgegebenes campaign-plan.json kann unmittelbar an den nativen Build übergeben werden. Die Missionen werden gegen tatsächlich vorhandene Spieldateien geprüft. Die native Missionsliste lässt sich bei langen Kampagnen scrollen. Installation und Rücknahme vergleichen das vollständige Plugin mit den SHA-256-Belegen.
- Die Einheitenpipeline prüft die Dateipfade der Frame-Indizes und veröffentlicht die Ausgabe erst nach erfolgreichem Rendern. Der geprüfte Ablauf verwendete neun echte SHCDE-Donorbewegungsframes, erzeugte 18 Bild- und Maskendateien und führte sie durch Import, Projektsicherung, Wiederherstellung und Mod-ZIP. Die Charakter-Referenz des Tests war synthetisch.
- Der portable Lauf kann den Handbuch-Spezialisten auch ohne das optionale PDF-Autorenpaket importieren. Die tatsächliche Handbucherstellung verwendet die separaten Autorenabhängigkeiten.

## Bereinigung

Die erneute Prüfung erfasste 45 lokale Zweige und 38 Worktrees in sieben Repositories, einschließlich der neu angelegten QA-Worktrees. Ein verifiziertes Git-Bundle sichert 32 Referenzen des kanonischen Repositories. 22 überprüfte Worktree-Archive sichern 8.638 Dateien. Vier Wiederherstellungen reproduzierten 45 Git-Statuseinträge und 173 lokale Dateien bytegenau. 14 saubere Worktrees und vier Zweige ohne Worktree waren am Ausgangscommit archiviert und vorläufig als redundant verifiziert. Vor einer späteren Entfernung sind HEAD, Arbeitszustand, Bundle und lokale Dateien erneut zu prüfen.

Löschstand in dieser Runde jeweils null. Der HP-/Feuer-Lauf und die visuelle Abnahme im lizenzierten Zielspiel sind Teil der ausstehenden Freigabe.
