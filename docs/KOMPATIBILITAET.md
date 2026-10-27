# Kompatibilität

Stand: 24. September 2026, Suite 1.1.3, Windows x64.

| Bestandteil | Auswahl und Grund |
|---|---|
| .NET SDK | Stabile SDKs ab 8.0.100; automatisch das höchste installierte SDK über `latestMajor`. 10.x empfohlen, 10.0.401 als Buildreferenz. |
| Runtime-Ziel | `net481`: vom Spiel und Script Extender benötigte Laufzeit; unabhängig von der SDK-Version. |
| SHCDE-SE | Vorhandene kompatible Installation; 2.10.0 ist der geprüfte Referenzstand. Die benötigten Schnittstellen werden an den installierten DLLs geprüft. |
| Unity Editor | 2021.3.45f2, Revision 88f88f591b2e, anhand der EXE-Produktversion geprüft. Der tatsächliche EXE-Hash bindet den Cache; ein alter Referenzhash ist keine Zulassungssperre. |
| Python | 3.13.15, aktueller Wartungsstand der 3.13-Reihe. Im Installer enthalten, keine eigene Python-Installation nötig. |
| Python-Pakete | Hashgebundener, bereits geprüfter Paketstand. Die Bilddecoder und Encoder gehören zum bestehenden Grafikvertrag. |

Die SDK-Auswahl gilt für Oberfläche, CLI und Runtime-Bau. Der unter **Einrichten**
ausgewählte SDK-Ordner hat Vorrang; ohne Auswahl wird `dotnet` aus `PATH` verwendet.
**.NET SDK herunterladen** öffnet Microsofts Downloadseite. Nach einem SDK-Wechsel
das Modpaket neu bauen; unveränderte Grafikgruppen bleiben im Cache.

Die SDK-Zulassung ist keine Vorabprüfung jeder Version. Ein realer Runtime-Build
liegt für SDK 10.0.401 vor; weitere zugelassene SDKs sind nicht alle einzeln getestet. Für bitgenaue Wiederholung eines früheren Builds dessen konkretes
SDK verwenden. Die historischen Cold-A-/Full152-Abnahmen behalten ihre damaligen
Hash-Pins und benötigen den zugehörigen früheren Quellstand.

[.NET SDK](https://dotnet.microsoft.com/download/dotnet/10.0) ·
[SDK-Auswahl](https://learn.microsoft.com/dotnet/core/tools/global-json) ·
[Python-Releases](https://www.python.org/downloads/) ·
[Script Extender](https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender/-/releases/v2.10.0)

## Spiele und Bibliotheken

SH1DE und SHCDE benötigen keine hinterlegte Versionsnummer oder identische
Referenzhashes. Das gilt auch für die Auswahl einer SHCDE-2.8.2-Installation.
Die Suite liest das aktuelle Inventar und prüft die Ressourcen und Schnittstellen,
die der gewählte Arbeitsablauf benötigt. Die Dateien in `supported-builds.json`
und `runtime-prerequisites.json` dokumentieren Referenzstände.

Die Suite lädt oder installiert keinen Script Extender im normalen Arbeitsablauf.
Eine ältere oder neuere SE-Version ist nicht allein wegen ihrer Versionsnummer
gesperrt, muss aber die benötigten Schnittstellen bereitstellen. Daraus folgt
keine pauschale Unterstützung aller früheren SE-Versionen.

Die Runtime wird gegen die tatsächlich installierten Bibliotheken gebaut.
Deren Hashes, Assembly-Identitäten und MVIDs werden im Ergebnis festgehalten und
beim Laden geprüft. Nach einem Spiel- oder SE-Update daher Inventar und Mapping
erneuern und neu bauen. So werden auch alte Cache- und Modstände erkannt.

`work/reports/build-compatibility.json` dokumentiert Unterschiede ohne lokale
Pfade; dafür ist keine manuelle Freigabe nötig. Das frühere
`allow_unknown_builds` bleibt nur zum Lesen vorhandener Konfigurationen erhalten.

Die benötigten Sprite-Gruppen, Masken, Anker, API-Signaturen und nativen
Strukturlayouts müssen weiterhin vorhanden sein. Ändert ein Spielupdate diese
Strukturen, nennt der betroffene Schritt die fehlende Voraussetzung. Eine
Versionsnummer allein wird weder als Fehler noch als Funktionsnachweis behandelt.

## Script Extender v2.14.3 (27. Oktober 2026)

**Offizieller letzter GitLab-Tag:** `v2.14.3`, veröffentlicht am
19. Oktober 2026; Quellcommit
`4014ca67c96974a5e6d697665baf5351cbfebde6`.

Das ursprüngliche **Stronghold-1-DE-HUD** benötigt den Crusader Script
Extender nicht. Erst der SH1-zu-SHCDE-Atlas- und Modpaketweg verwendet ihn.

Die **read-only** Vorprüfung wird im Reiter Ziel & SE 2.11 über
**Script Extender 2.14.3 prüfen (nur lesen)** gestartet oder per:

```powershell
.venv\Scripts\python.exe tools\shcdese_compat_check.py --game "D:\Games\Stronghold Crusader Definitive Edition"
```

Sie liest ausschließlich den tatsächlich installierten PE-DLL-Stand, das
SE-`info.json`, BepInEx 5, einen Spiel-Build-Hash, die vom Extender
deklarierten Spielversionen sowie die Sicherheitsoption
`RequireSignedBepInExPlugins`. `--require-latest` lehnt
jede Version außer v2.14.3 ab. Kein Download, keine Installation.

**Statische Noesis-HUD-Kompatibilität:** Der geprüfte offizielle
v2.14.3-Code verarbeitet die bisherigen XAML-Patch-Wurzeln
`<Patch>` und `<XamlPatch>` mit
`<Operation>` und die bestehenden Sprite-Override-Pfade.
Das ist kein Nachweis eines erfolgreichen Spielstarts.

**Runtime-ABI noch offen:** Der bisherige C#-Runtime-Bau in dieser
Repository-Fassung ist auf die SE-2.11.0-DLL mit konkreten
MVID-/SHA-256-Werten gepinnt. Für SE v2.14.3 muss die eigene Runtime
gegen die echte neue DLL neu kompiliert und im Spiel getestet werden.
Eine Versionsnummer oder ein erfolgreicher HUD-PNG-Export reicht nicht.

Die alte SE-2.11-Installationsfunktion ist nur noch ein
**historisches Werkzeug**. Ein abweichender Paket-Hash und das
unbeabsichtigte Downgrade einer neueren Installation werden verweigert.
Die seit v2.13 optionale Signaturpflicht für BepInEx-Plugins lässt
sich nicht anhand vorhandener Manifestdateien allein freigeben.

Quellen:
- https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender/-/releases/v2.14.3
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/bepinex-mod-guide.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html
