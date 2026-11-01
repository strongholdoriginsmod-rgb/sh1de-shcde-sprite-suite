# SpriteSuite: Native Noesis / BepInEx – Live-Integration und Abnahme

Datum: 1. November 2026
Zweig: feature/native-noesis-live-game-plugin-20261101

## Tatsächliche Implementierung

Die installierte Benutzerkopie wird anhand exakter SHA-256-Werte der
fünf Originalkomponenten (Game DLL, Noesis managed/native, SHCDESE DLL,
FrontendMenus.xaml) geprüft. Eine andere Version wird zurückgewiesen.
Originaldateien bleiben unverändert.

Das neue BepInEx-C#-Plugin liegt in:
runtime/SpriteSuite.Origins.Authoring/OriginsNativeLivePlugin.cs

Es nutzt:
- die echte CrusaderDE.FrontendMenus.ButtonClicked(String)-Schnittstelle
- einen echten Harmony-Prefix, der nur eigene Legacy-Parameter abfängt
- zwei je einmal vorhandene XPath-Ziele der Original-FrontendMenus.xaml
- die native Spielroutine FRONT_StandaloneMission.StartMap für nachgeprüfte
  originale Karten, mit MapFileManager-Schlüssel ohne .map-Endung
- Script Extender R3-Events OnLoadMap / OnPostLoad / OnUnloadMap
- einen Abschlussnachweis erst nach passendem Kartenladeereignis und
  erfolgreichem Postload-Code
- native NoesisView.Texture-Pixel, falls die View direkt in eine
  RenderTexture zeichnet; sonst eine echte fertige Unity-Spielaufnahme

Das C#-Plugin speichert Statusberichte und einzelne echte PNG-Aufnahmen
im Benutzerprofil unter:

%LOCALAPPDATA%\SpriteSuite\NoesisNativeLive

Im Noesis-Originalseiten-Editor sowie in der SpriteSuite-Hauptnavigation
gibt es nun Native Noesis-Live-Pixel (Spiel). Das Fenster zeigt die echten,
vom Plugin aufgenommenen Pixel standardmäßig in 1:1-Größe und kann das
Bild als Referenz in den Editor übernehmen. Es ist KEIN alleinstehender
Python-Noesis-Nachzeichner. Ohne native Frames bleibt es leer.

## Installation und sicherer Rückweg

Das Build-Programm:

python tools/origins_native_live_install.py --build --game "D:\Games\Stronghold Crusader Definitive Edition" --out "E:\SpriteSuite_Origins_Manuell_20261101\work\native-live-meine-abnahme"

Für Installation bei geschlossenem Spiel:

python tools/origins_native_live_install.py --install "E:\SpriteSuite_Origins_Manuell_20261101\work\native-live-meine-abnahme\SpriteSuite_Origins_Live_20261101" --game "D:\Games\Stronghold Crusader Definitive Edition"

Ziel ausschließlich:

D:\Games\Stronghold Crusader Definitive Edition\BepInEx\plugins\SpriteSuite_Origins_Live_20261101

Rückweg, ebenfalls bei geschlossenem Spiel:

python tools/origins_native_live_install.py --rollback --game "D:\Games\Stronghold Crusader Definitive Edition"

Es werden nur die exakt in der Installationsquittung geprüften eigenen
Plugin-Dateien entfernt. Fremde Mods, vom Benutzer nachbearbeitete eigene
Plugin-Dateien und alle Originaldateien bleiben unangetastet.

Der ursprüngliche Plugin-Kandidat wurde tatsächlich installiert und mit
dem Rollback wieder sauber entfernt; alle fünf Original-SHA-256 blieben
unverändert. Der neue Build wird erneut getrennt installiert und geprüft.

## Nach manueller Spielausführung

Ein wirklicher Ingame-Test hat folgende Nachweise einzeln zu erbringen:

1. Spiel manuell starten. Ein durch Benutzer/Windows abgebrochener
   Startvorgang wird NICHT durch einen anderen Aufruf umgangen.
2. In der laufenden Spielinstanz SpriteSuite Origins im Hauptmenü
   öffnen, die neue Seite sehen, eine Mission wählen und Zurück drücken.
3. Einmal Antioch.map starten; der positive Abschluss benötigt echten
   passenden MapLoad- und erfolgreichen MapPostLoad-Callback.
4. Den Noesis-Live-Betrachter öffnen. Aufnahmen aus direkter
   Noesis-RenderTexture sind isolierte native Noesis-Pixel.
   Unity-Screenshots sind echte zusammengesetzte Spielpixel,
   aber nicht die isolierte Noesis-Oberfläche.
5. MapUnload prüfen und Saisonroutenstatus kontrollieren.
6. Den Belegbericht erzeugen:

python tools/origins_native_live_verify.py --game "D:\Games\Stronghold Crusader Definitive Edition" --out "E:\SpriteSuite_Origins_Manuell_20261101\work\native-game-evidence.json"

Die Optionen --require plugin, menu, map und noesis liefern einen
Fehlercode, falls der jeweilige wirkliche Ingame-Nachweis fehlt.

## Ehrliche Freigabegrenzen

Der automatische Spielstart wurde von Windows mit
"Der Vorgang wurde durch den Benutzer abgebrochen" beendet.
Dabei wurde weder ein Spielprozess noch ein tatsächlicher
BepInEx-Ladebeleg noch eine echte native Noesis-Aufnahme erzeugt.

Die Installation als Plugin und die DLL-Kompilierung sind deshalb
getrennt von der tatsächlichen Spielfreigabe zu betrachten.

Auch die R3-Saisonrouten-Events schalten noch keine echten Unity-Atlanten
reversibel um. Für tatsächliche saisonale Grafikwechsel ist eine eigene,
im Spiel getestete SpriteLoader-/Atlas-Restore-Implementierung erforderlich.
Eine bloße SeasonSession-Routenänderung ist dafür kein Beweis.

Das Fenster zeigt wirklich vom Spiel gerenderte Pixel, sobald der Nutzer
ein Spiel manuell startet und das Plugin sie erzeugt. Ein interaktiver,
bidirektionaler Live-XAML-Hot-Reload ist dadurch noch nicht implementiert.

Der QA-Bericht setzt full_in_game_release_approved solange auf false,
bis insbesondere auch der native, sichtbare Saisonatlaswechsel belegt ist.


## Fortsetzung am 2. November 2026: Saison-Hot-Swap-Sicherheitsprüfung

Die wirklich vorhandene SHCDESE-API GameAtlasManagerAPI.ApplySingle()
erzeugt neue Unity-Sprites, ersetzt GM-Arrays, verändert allSprites und
registriert zusätzliche Materialien. GameAtlasManagerAPI.Unload() leert
hingegen nur die Override-Registry; es restauriert keine zuvor geänderten
Unity-Sprites oder Materialeinträge. Das konnte am installierten
SHCDESE.dll rein lesend über Mono.Cecil nachvollzogen werden.

Ein eigener experimenteller, konfliktbewusster Saison-Array-Restore
wurde begonnen. Bei der realen C#-Compilerprüfung zeigte sich, dass
spriteLoader.gmSprites und allSprites privat sind; außerdem war die
vollständige Restaurierung beim Plugin-Unload noch nicht abgesichert.
Ein abschließender Edit dieses Bereiches wurde vom Tool-Sicherheitscheck
blockiert und nicht durch einen alternativen Eingriff umgangen.

Der unfertige Versuch ist ausdrücklich **nicht im Plugin-Build enthalten**
und wurde in den privaten, nicht ausgelieferten QA-Bereich verschoben:

    work/native-live-qa-20261101/experimental-season-restoration-NOT-INCLUDED.cs

Die freigegebene Build-Pipeline und die Native-ABI-Prüfung wurden
daraufhin mit dem unveränderten, sicheren Saisonrouten-Callback erneut
erfolgreich ausgeführt. Native Atlas-Memory-Mutation ist darin
deaktiviert. Eine echte reversible Saisonumschaltung ist somit weiterhin
offen; eine Routenkennung ist kein Bildwechsel.

Der vom Nutzer autorisierte Game-Verzeichnispfad wurde bislang nur für
eine einmalige Plugin-Installation und einen erfolgreichen, geprüften
Rollback genutzt. Alle Originalbibliotheken und die Original-XAML blieben
SHA-256-identisch. Der nächste stabile Build kann ohne diesen
experimentellen Atlas-Modus installiert werden. Für echte Ingame-Abnahme
muss der Spielprozess vom Nutzer manuell gestartet werden, da Windows den
vorherigen automatischen Start ausdrücklich abgebrochen hat.


## Fortgesetzte Prüfung: getrennte Spielkopien und historische Frames

Am 2. November 2026 hat die Erweiterung zwei zusätzliche,
reproduzierbare Negativprüfungen erhalten:

- Die echte Ingame-Freigabe verlangt jetzt nicht nur einen laufenden
  SHCDE-Prozess und den passenden Assembly-CSharp.dll-SHA-256, sondern
  auch die Übereinstimmung des von Unity gemeldeten
  game_installation_root mit der gezielt ausgewählten Spielinstallation.
  Der gleiche Binärstand einer fremden SHCDE-Kopie genügt nicht.
- Eine vollständig aufgenommene Noesis-PNG aus einem mittlerweile
  beendeten Spielprozess darf weiterhin als historischer Dateibeleg
  existieren; das Live-GUI stellt diese Datei nicht als aktuelle
  Renderausgabe dar und aktiviert sie nicht als Live-Referenz.

Die vorherige umfassende Regression umfasste 289 bestandene Tests.
Die danach eingefügten Negativprüfungen werden separat abgenommen,
bevor die aktuellste Pluginversion wieder installiert wird.
