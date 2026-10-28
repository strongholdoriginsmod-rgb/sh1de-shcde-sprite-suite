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
Pfade; dafür ist keine manuelle Freigabe nötig. Neue SHCDE-Versionen
werden beim Registrieren anhand der fünf tatsächlichen Spieldateien
identifiziert und erhalten eine eindeutige Content-Build-ID.
`allow_unknown_builds = true` dokumentiert die versionsoffene Auswahl.
Vor schreibender Aktivierung muss das Mapping **exakt zu dieser Build-ID**
gehören; ein fremdes Mapping wird nicht übernommen.

[Versionen offen, Dateiintegrität erhalten](VERSIONSOFFENE_SH1DE_SHCDE_SE_2026-10-28.md).

Die benötigten Sprite-Gruppen, Masken, Anker, API-Signaturen und nativen
Strukturlayouts müssen weiterhin vorhanden sein. Ändert ein Spielupdate diese
Strukturen, nennt der betroffene Schritt die fehlende Voraussetzung. Eine
Versionsnummer allein wird weder als Fehler noch als Funktionsnachweis behandelt.

## Script Extender: statische Asset-Ausgabe ohne Versionsbindung

Der separate Versionschecker wurde entfernt. HUD-/GUI- und Sprite-Overrides
sowie statische XAML-Patches werden als `Manifest: 0`-Asset-Mod ohne C#-DLL
und ohne SE-Versionsangabe gebaut. Für diesen Weg prüft die Suite
Dateiformate, XAML-Syntax, sichere Pfade und Paketstruktur,
aber keine Versionsnummer des installierten Extenders.

Das ist **keine Zusage**, dass alle früheren und späteren Extender
dieselben Asset-/Noesis-/Atlas-APIs haben. Optionale native C#-Funktionen
bleiben durch ihre ABI- und Game-Assembly-Pins geschützt.
Siehe [Script Extender und Asset-Mods](SCRIPT_EXTENDER.md).
