# SHCDE/Script-Extender/APIShared/Serp – Capability-Matrix und Werkzeugstrategie

Stand: 08.11.2026. Quellen: öffentliches Upstream-Projekt; keine Behauptung,
dass alle APIs **in der lokalen Spielinstallation** verfügbar oder mit
dem aktuellen Runtime-Build ABI-kompatibel sind.

| Oberfläche | Upstream dokumentiert? | Nützliches gemeinsames SpriteSuite-Modul | Live-QA notwendig? |
| --- | --- | --- | --- |
| BepInEx-/SHCDESE-C#-Plugins | Ja: `BaseUnityPlugin`, harte Abhängigkeit `000shcdese`, `LibraryLoaded` | Plugin-Builder + Signaturprüfung + Lifecycle-Guard | **Ja** |
| Spielereignisse | Ja: R3-Hooks für Unit-/Map-Ereignisse | Event/Trigger-Inspector, Event-Logger, Replay | **Ja** |
| Asset-Overrides | Ja: PNG/DDS, Sprite-/Masken-/Atlasdateien, Audio und AssetBundles | Gemeinsamer Asset-/Material-/Bild-Inspector | **Ja** |
| UI-/Noesis-Patches | Ja: XPath-XAML, ViewModels, Lua-/C#-Bindings | Visual HUD Studio, XAML-Diff und Konfliktprüfung | **Ja** |
| AIV/AIC-Overrides | Ja: `.aivjson`, `.baic` plus Decoder-Werkzeuge | AI-Lord/AIV/AIC-Studio mit Roundtrip und Schema | **Ja** |
| Map-Archive und Lua | Ja: `.map` mit angehängtem ZIP, `Scripts/init.lua` | Map-/Lua-Sandbox, Trigger- und Archive-Validator | **Ja** |
| Workshop-Packages | Ja: `.semod`, Workshop-/Map-Pakete | Validierter Publish-Preflight/Provenienzvergleich | **Ja** |
| APIShared (Serpens66) | Öffentliches eigenständiges Shared-API-Projekt, reale APIs nur nach Assemblies-/Quellabgleich | Einstellungs- und Dependency-Adapter, Versionen/Namespace-Scanner | **Ja** |
| Serp/„baseline“-Mods | Mod-Quellen und Beispiele für Gebäudekosten/-limits, Lobby-Settings | Settings-Definitionen und Multiplayer-Sync-Prüfungen | **Ja** |
| HP-/Feuerzustände / dynamisches Gebäuderendering | Teilweise Projekt-eigene QA-/Runtime-Anknüpfungen; kein universeller Render-Hook aus einem einzelnen Dokument ableitbar | Zerstörungsstufen im bestehenden Damage Studio mit isoliertem Runtime-Adapter | **Ja, zwingend** |

## Offizielle, überprüfbare Anknüpfungspunkte

- [SHCDE-SE Upstream-Repository](https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender/-/tree/main) – SDK, Lua, Events, Asset-/XAML-Patching.
- [BepInEx-Mod-Guide](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/bepinex-mod-guide.html) – empfohlenes .NET-Framework-Setup und korrektes `LibraryLoaded`-Event vor Zugriff auf Game-APIs.
- [Asset-API](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html) – transparente Override-Mechanik, private/global Provider, Atlas-Metadaten, Pivots und Unity-AssetBundles.
- [XAML-API](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/xaml-api.html) – XPath-Patches, Noesis-Datenbindung, Lua/C#.
- [Mod-Typen](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html) – Asset-/BepInEx-/Map-/Workshop-Grenzen.
- [Serpens66 Mods](https://github.com/Serpens66/Stronghold-Crusader-DE-Mods) und [APIShared-FORK](https://github.com/Serpens66/SHCDE-APIShared-FORK) – Ausgangspunkte für reale APIShared- und Serp-Signaturen; keine Annahme unveränderter Versionen.
- [Script Extender auf Nexus Mods](https://www.nexusmods.com/strongholdcrusaderdefinitiveedition/mods/35) – die dort gelistete Kompatibilität für Spielversion `2.8.0.2` und Plugin `>=2.7.1` ist eine **öffentliche Momentaufnahme**, keine Diagnose der installierten Version.

Die offizielle Asset- und XAML-Dokumentation kennzeichnet bestimmte
Schnittstellen ausdrücklich als **instabil**. Deshalb muss ein künftiger
Adapter aus der tatsächlich installierten Plugin-Version/API-Signatur
sein Capability-Manifest erzeugen. Nicht unterstützte Hooks deaktivieren,
statt sie in Produktions-Spielständen zu versuchen.

## Zielbild – welche Toolfunktionen noch sinnvoll sind

**P0 · Gemeinsamer Editor (begonnen):** Einheitliche Pixelgeometrie,
Pivot-/Bodenanker, Fangraster, Ebenenüberlagerung, Messung, Original-Diff,
Undo/Redo und PNG-/Projekt-Provenienz. Ein separates Zinnenlineal wird
für neue Arbeiten unnötig; alte Dateien bleiben lesbar. Geprüfte Module:
`extras/sprite-editor/src/{core,io,app,ai_workflow}.js`.

**P0 · Komponenten- und Runtime-Inspektor (begonnen):**
Pfad-/Steam-/Unity-/Python-/BepInEx-/Script-Extender-/APIShared-/Serp-Erkennung
ist read-only umgesetzt. Als nächstes fehlen die versionsgebundene
DLL-Export-/Assembly-Signaturprüfung und aktive QA-Lifecycle-Probes.
Eine Datei-Präsenz ist nicht gleich Ingame-Hook.

**P1 · Visuelles Asset-Studio:** Sprite- und Masken-Werkzeuge, Pixel-
und Alphavergleich, atlas.json, BC7/BC3/BC1, PPU- und Pivot-Validierung,
Material-vs.-Foliage, Unit-/Baum-/Tile-/UI-Profile, batch/undo in einem
Inspektor. Bestehende spezialisierte Exportmodule zunächst als Adapter
behalten.

**P1 · Noesis-/XAML-Studio:** Original-XAML einlesen, XPath-Patches
grafisch prüfen, Konflikte und Lokalisierungen vergleichen, ViewModel-
Anbindungen simulieren und vor C#-/Lua-Deployment prüfen.

**P1 · Script-Extender Capability Explorer:** Reflektionsbasierte
Signatur- und GUID-Matrix aus Assemblies, `LibraryLoaded`-Reihenfolge,
Event-Timings, Fehlerlog-/Lifecycle-Reporter, GameObject-/Entity-/Tile-
inspektion nur im isolierten QA-Klon; ABI-Drift als Blocker anzeigen.

**P1 · Einheiten-/Animationen-Studio:** Richtungsframes, Pose, Teamfarbe,
Pivot, Referenzbild, Bewegungsphasen, Pixel-Änderungsbereich,
Frame-Dauer, PPU/Atlas, Auto-Lint für Sprünge zwischen Frames. Das
KI-Briefing kann vorhandene konsistente Richtungssets als Referenzen
verwenden, doch derzeit gibt es keinen automatischen Animationstest.

**P1 · KI-Bildwerkstatt (begonnen):** Nichtdestruktive, SHA-gebundene
Auftrags-Bundles, 1–4 Varianten, eigener Generator-Adapter, strikte
Größen-/Alpha-/Masken-Prüfung, Review und Undo. Getrennte Freigaben für
HP-/Feuerstufen beibehalten. Sinnvolle folgende Extras: optionale
Bildregionenmasken, Qualitäts-Rankings mit nachvollziehbaren Kriterien,
Serienproduktion pro Richtung/Tier, Prompt-Versionen und QA-History.

**P2 · AIV-/AIC-/Lua- und Lord-Studio:** Die bereits bestehenden Editor-,
Parser- und Build-Skripte in gemeinsame Roundtrip-, Schema-, Diff-,
Undo- und Versionsfunktionen überführen; Lua-Ereignisse reproduzierbar
simulieren und Multiplayer-Settings separat prüfen.

**P2 · Gameplay- und Map-Studio:** Daten-getriebene Gebäude-/Ressourcen-
und Triggerfelder, Laufzeit-Capability-Checks, Änderungsvisualisierung,
Map-Archive-Builder mit Safe-ZIP; nur geprüfte Game-IDs, niemals eine
frei erfundene Funktions-ID.

**P2 · Diagnostik und QA-Matrix:** Automatisierte Testspiel-Schnappschüsse
mit Quell-/Runtime-Hashes, Frame-Overlay, Crash-/Logvergleich,
Savegame-Profilisolation und reproduzierbarem Restore.

## Harte Integrationsregeln

- Aus Spielerkennung niemals „Unity kompatibel“ schlussfolgern.
- Keine C#-Gameplay-Hooks vor dokumentiertem `LibraryLoaded`.
- Keine Modellgenerierung, fremden Dateiexport oder kostenpflichtige
  API-Aufrufe ohne expliziten Auftrag.
- Kein Überschreiben von Original-Grafiken oder Produktion-Saves.
- Für zustandsverändernde Gameplay- und Multiplayer-Mods exakte
  Versionen, Host-Synchronisation und isolierte QA-Protokolle verlangen.
- Historische Spezial-Tools erst nach bewiesener Migration, Tests und
  Backups aus dem produktiven Menü entfernen; Code-/Git-Löschung später.

## Status des vorliegenden Feature-Zweigs

**Implementiert und getestet:** gemeinsamer Geometrie-Editor,
read-only Auto-Discovery, KI-Bundle-/Review-Workflow, isolierter
Generator-Adapter, DE/EN-Editorintegration und Prüfsummen.
**Nicht neu implementiert:** alle oben aufgeführten P1/P2-Module,
native Runtime-ABI-Validierung, C#-Game-Hook-/Unity-Neubau,
Live-Ingame-Grafikabnahme oder der vollständige Diff
aller externen uncommitteten Entwicklungsstände. Diese Punkte
werden nicht als fertig ausgewiesen.
