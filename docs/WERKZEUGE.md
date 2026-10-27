# Werkzeugübersicht

| Aufgabe | Bestehendes Werkzeug |
|---|---|
| Grafische Oberfläche | `tools/suite_center.pyw` erweitert die unveränderte `suite.pyw`; Start über `SpriteSuite.exe` oder `suite.py gui` |
| CLI-Builder, Validierung, Installation | `python -m stronghold_europe_de` |
| Export, Kontaktbogen, Import, Profileintrag | `tools/sprites.py` |
| Zusammengesetzte Tile-Objekte und ORA-Rückweg | `tools/tile_objects.py` |
| Gruppenbestand und Geometriepolitik | `tools/groups.py` |
| Platzierungsnachweise | `tools/pin_digests.py` |
| UI-Ausschnitte exportieren/importieren | `tools/ui_atlas.py` |
| SH1DE-UI auslesen und Zielblatt aufbauen | `tools/ui_sh1_dict.py`, `ui_atlas_layout_port.py`, `ui_sh1_umstellung.py`; bildbasierte Gegenprobe `ui_sh1_extract.py` |
| UI-Quellmanifest | `config/ui-textures-bc7-v1.json`; historischer 114er-Generator separat erhalten |
| Inkrementelle UI-BC7-Pakete | `tools/build_ui_bc7_cache.py` |
| UI-Paket ohne GM-Neubau zusammensetzen | `tools/compose_ui_bc7_candidate.py` |
| Runtime ohne Grafik-Neubau erneuern | `tools/compose_runtime_refresh.py` |
| Welt-BC7-Encoder | `tools/unity_asset_bundle/StrongholdEuropeAssetBundleBuilder.cs` |
| UI-BC7-Encoder | `tools/unity_asset_bundle/StrongholdEuropeUiTextureBundleBuilder.cs` |
| Bildvarianten und gezielte Verarbeitung | `vegetation_gen.py`, `stone_recolour.py`, `boar_recolour.py`, `slot_blank.py` |
| Hintergrund- und Symbolbearbeitung | `backgrounds.py`, `background_v2_*.py`, `ui_button_*.py`, `ui_pair.py` |
| Sprite-/Atlaslokalisierung | `tools/locate_unit.py`, `native_geometry_probe.py` |
| Installationsidentität und veraltete Artefakte | `tools/show_installed.py`, `check_stale_artifacts.py` |
| Historische Speicher-/Spielabnahme | In älteren lokalen QA-Projekten vorhanden, **nicht** im aktuellen `tools/`-Bestand. Read-only-Versionsprüfung über **Diagnose & Reparatur → QA-Altbestand vergleichen**; keine Übernahme historischer Buildpins als aktuelle Freigabe. |
| Eigenständige Atlas-/Ankerprüfung | `extras/atlas-contract/atlas_contract` |
| Historischer Windows-EXE-Bau | `build_modding_exe.py` ist aktuell **nicht** im Projektwerkzeugbestand; historisch vorhandener Buildweg benötigt eine neue Versions-/Installationsprüfung. |
| Neue 2D-Einheiten aus Produktionsmanifesten | `tools/unit_pipeline.py` |
| Getrennter Blender-/MPFB-Bootstrap | `tools/blender/bootstrap_human_toolchain.py`; Toolchain in `config/human-toolchain.json` |
| Historische PowerShell-Baufolgen | `system_workflows.py` und die zugehörigen Skripte liegen in älteren Projektständen, sind im aktuellen `tools/`-Ordner nicht verfügbar. Vor Wiederintegration schreibende Schritte explizit absichern. |

Im normalen Ablauf erzeugt **Paket bauen** die Ausgabe zum manuellen Kopieren.
Der frühere verwaltete Installationsweg bleibt ein erweitertes Werkzeug; seine
Laufwerksvoraussetzung steht unter [Abläufe](WORKFLOWS.md#5-bc7-bauen-und-ins-spiel-kopieren).

Die spezialisierten `background_v2_*`, `ui_button_*` und Full152-Werkzeuge
enthalten bewusst konkrete Projektvorgaben. Ihre Hilfe und Eingabepfade vor
Verwendung lesen; sie sind keine beliebigen Bildkonverter.

Der eigenständige Atlasbaustein läuft aus `extras/atlas-contract`:

```powershell
python -m atlas_contract gruppe tree_birch
python -m atlas_contract pruefen tree_birch --spiel '<SHCDE-Datenordner>' --atlas '<Arbeitsatlas>/tree_birch'
```

Er prüft Geometrie, Slotbestand und Maskenpolitik und enthält einen einfachen
PNG-Atlasbauer. Die BC7-Produktion erfolgt weiterhin über die Hauptpipeline.

**Erweiterte Werkzeuge anzeigen** blendet den Werkzeugkatalog ein.
**Alle Werkzeuge** zeigt Formulare für die Sprite-Werkzeuge, die gesamte
Pipeline und die eigenständige Atlasprüfung. Die früheren SE-Installations-
und Wartungsskripte werden dort nicht angeboten. Die Optionen werden aus den
vorhandenen Parsern gelesen; zusätzliche dynamische Argumente haben ein
eigenes Eingabefeld. Historische Messskripte ohne Argumentparser behalten
ihren dokumentierten Aufruf im selben Fenster.

Der separate Blender-Bootstrap läuft innerhalb von Blender 5.2.0 mit bereits
registriertem MPFB 2.0.17 und installiert die hashgebundenen Asset-Pakete in dessen
isoliertes Benutzerverzeichnis. Diese externen Anwendungen sind keine
Voraussetzung für den SH1DE-Sprite-Transfer und nicht im Installer enthalten.
Die Atlas-Messskripte erwarten den ursprünglichen PNG-Produktionsbau unter
`dist/europe-production`. `tabelle_erzeugen.py` liest das lokale Dekompilat
unter `cache/decompiled/shcde28_project`; die fertige Ladetabelle ist enthalten.

Der ursprüngliche PyInstaller-Bauweg `build_modding_exe.py` bleibt erhalten.
Die vollständige Übergabe verwendet den neuen [Installerbau](INSTALLERBAU.md),
weil einige Originalprogramme ausdrücklich `.venv/Scripts/python.exe`
aufrufen. Der Installer stellt diesen Pfad mit einer echten Python-Umgebung her.

`project_inputs.py`: vorhandene profilgebundene Projektgrafiken bündeln oder ein
geprüftes Zusatzpaket importieren; im Werkzeugkatalog mit `pack` und `install`.

Die früheren SE-Installationsskripte `shcdese_current_install.py` und
`shcdese_install.py` sowie `native_crash_handler.py` bleiben im Quellpaket
zur Nachvollziehbarkeit erhalten. Sie gehören nicht zum normalen Sprite-Ablauf
und werden nicht im Werkzeugkatalog angeboten. Eine bereits ausgeführte
SE-Installation lässt sich bei vorhandener Sicherung separat
[zurücknehmen](SCRIPT_EXTENDER.md#früheren-se-wechsel-zurücknehmen).

## Neue geprüfte Werkzeuge im Hauptfenster

- **Paket bauen (mit Vorprüfung):** Führt zunächst dieselbe
  nicht schreibende Bauvoraussetzungsprüfung aus. Bei Blockaden startet
  kein Builder. Nach erfolgreichem Check wird für den konkreten
  Profil-/Ersetzen-Stand separat um Bestätigung gebeten (Standard Nein).
  Quellhashes und Paketausgabe werden vor dem Start erneut geprüft.
  Eine fehlgeschlagene CLI-Nachvalidierung beendet den Bau mit Fehlerstatus.
- **Paket bauen → Bauverlauf anzeigen:** SHA-256-verketteter,
  nur lokaler Verlauf tatsächlicher Suite-Bauversuche, auch nach
  Neustart. Jeder Start/Abschluss hat eigene, unveränderlich
  serialisierte Einträge. Offene Starts bleiben unbestätigt,
  beschädigte Nachweise werden abgelehnt. Kein Build-/Installations-
  oder Freigabe-Button. CLI: `tools/qa_suite_build_history.py`.
  [Verlauf und Grenzen](BUILD_HISTORY.md).
- **Paket bauen → Bauergebnis anzeigen:** Zeigt nach einem tatsächlich
  gestarteten Build den verbindlichen CLI-Exitcode, den davon getrennten
  kompletten SHA-256-Offline-Abgleich, Anzahl der geprüften Dateien,
  Warnungen und den vorherigen Manifeststand. Fehler oder Abbruch werden
  niemals durch ein älteres existierendes Paket schöngefärbt.
  Ingame-/Releasefreigabe ausdrücklich noch **ausstehend**;
  keine automatische Installation.
  [Bauabschluss und Prüffelder](BUILD_COMPLETION.md).
- **Paket bauen → Bauvoraussetzungen prüfen:** Ausgewähltes Profil,
  Originalspielpfade, GZIP-Mapping, Unity-2021.3-Pin, .NET-SDK
  und bestehende Ausgabedateien ohne einen Bauvorgang prüfen.
  Blockaden werden nicht in nachsichtige Warnungen umgewandelt.
  Kein Unity-, dotnet-, Paket- oder Installationsaufruf;
  Status wird nach Änderungen der Auswahl ungültig.
  CLI: `tools/qa_suite_build_readiness.py`. Details:
  [Bauvoraussetzungen](BUILD_READINESS.md).

- **Editor & Austausch → Pivot-Messungen prüfen:** Zinnenlineal-Import, verifizierte PNG-/Index-Pivots und Bildvergleich. Einzelne Änderungen können nach Sichtprüfung explizit freigegeben, abgelehnt oder zurückgestellt werden. Prüfbericht und separates, SHA-256-gebundenes Freigabeprotokoll werden nur als JSON gespeichert – **keine** automatische Atlas- oder Spieländerung.
- **Diagnose & Reparatur → QA-Altbestand vergleichen:** Historische Werkzeuge und Testmodulzahlen mit SHA-256 und Risikoetiketten abgleichen; es wird kein altes Tool gestartet oder installiert.
- **Diagnose & Reparatur → Gesamten Build prüfen (SHA-256):** Komplettprüfung aller ausgelieferten BC7-Dateien gegen Manifest und Profil, inklusive Bundleindex, fremder Dateien und optionaler Pivot-Freigabe. Nur ein separat gespeichertes, manifestgebundenes Offline-Prüfprotokoll entsteht. Auch als `tools/qa_release_preflight.py` ohne GUI nutzbar. Details: [Release-Prüfung](RELEASE_PREFLIGHT.md).

- **Editor & Austausch → Pivot im BC7-Atlas prüfen:** Eine bereits geladene
  Messung mit dem tatsächlich veröffentlichten, per Bundle- und Atlas-SHA
  zugeordneten V2-Cacheatlas vergleichen. Bei bereits korrektem BC7-Pivot
  wird eine erneute Freigabe deaktiviert. CLI ohne Freigabe oder Schreibzugriff:
  `tools/qa_bc7_pivot_audit.py`.
- **Diagnose & Reparatur → Pivot-BC7-Stufenplan:** Eine zuvor bewusst
  freigegebene Messung und die **originale** Messdatei erneut mit
  Katalogindex, PNG, 100 % der gebauten Ausgabedateien und dem
  eingefrorenen BC7-Geometrievertrag vergleichen. Der tatsächliche
  veröffentlichte Atlas wird im exakt zugehörigen, vollverifizierten
  V2-Gruppen-Cache ermittelt. Bereits korrigierte Pivots werden
  ausgeschlossen; für übrige Frames werden Metadatenhash und Cache-Key
  **nur als Projektion** neu berechnet. Das Ergebnis ist
  ausschließlich ein inhaltsadressierter Entwurf; keine Assetänderung.
  Auch per `tools/pivot_bc7_stage.py` ausführbar. Siehe
  [Zinnenlineal/BC7-Stufenplan](PIVOT_BC7_STUFENPLAN.md).

- **Diagnose & Reparatur → Synthetische BC7-Pivot-Probe vorbereiten:** Zwei
  echte V2-Unity-Projektsätze mit künstlichen RGBA-Frames validieren.
  Pivot-bedingte Frame-Metadaten-/Cache-Key-Änderung prüfen,
  unveränderte Kontrollgruppe und identische Atlas-Pixel bestätigen.
  Ausgabe nur unter work/pivot-bc7-rehearsals. **Kein** Unity-/BC7-Encoderlauf,
  weder echte Sprite- noch Spieldaten. CLI:
  `tools/qa_pivot_bc7_rehearsal.py`. Details:
  [Pivot/BC7-V2-Probe](PIVOT_BC7_REHEARSAL.md).

- **Diagnose & Reparatur → Nativen Zinnen-Geometriebeweis prüfen:**
  Vollständiger, SHA-256-gebundener Nachweis des bereits veröffentlichten
  anim_castle-Bundes gegen Original-Mapping, echten BC7-Cacheatlas,
  95 SH1DE-Quellframes, 11 Crusader-Fallbacks und die im Profil
  eingefrorenen Geometrie-/Herkunfts-/RGBA-/Review-Beweise.
  Kein Neuberechnen oder Installieren einer neuen Pivotkorrektur.
  CLI: `tools/qa_native_pivot_provenance.py`.
  [Einzelheiten](PIVOT_NATIVE_PROVENANCE.md).

Ausführliche Prüfung und Grenzen: [Historische Werkzeuge integrieren](HISTORISCHE_WERKZEUGE_INTEGRATION.md).

### Einzelframe-Diagnose für veröffentlichte Zinnen

Der SHA-gebundene Originalgeometrienachweis enthält jetzt
auch **106 einzeln anwählbare Nativ-Frame-Befunde**. Ein
Doppelklick öffnet den geprüften Frame im Asset-Katalog,
einschließlich Quellherkunft und veröffentlichtem
BC7-Pivot. Es handelt sich ausschließlich um eine
Nur-Lesen-Navigation; keine Pivot-Korrektur wird automatisch
angewendet. Einzelheiten und Negativtests:
`docs/PIVOT_NATIVE_PROVENANCE.md`.
