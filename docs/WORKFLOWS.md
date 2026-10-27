# Abläufe

Alle Befehle aus dem Suite-Verzeichnis. `python` meint den Interpreter der
eingerichteten `.venv`. Jeder Arbeitsschritt hat zusätzlich `--help`. Die Suite
verwendet den vorhandenen kompatiblen Script Extender. Inventar, Export und
Build lesen die Spielinstallation. Im normalen Ablauf wird das fertige Paket
bei Bedarf von Hand ins Spiel kopiert.

In der Oberfläche: **Einrichten → Spiele einlesen**, dann **Sprites bearbeiten**
und **Paket bauen**. **Paket bauen (mit Vorprüfung)** kontrolliert zuerst
die tatsächlichen gespeicherten Voraussetzungen, verlangt bei einem möglichen
Bauversuch eine ausdrückliche Bestätigung und startet erst dann Build und
verbindliche Validierung. Schlägt die Validierung fehl, gilt der Bau als
fehlgeschlagen – auch im Nachsichtmodus.
Die folgenden Einzelbefehle und Zusatzfunktionen bleiben für gezielte Arbeiten
erhalten; die zusätzlichen GUI-Seiten erscheinen über **Erweiterte Werkzeuge anzeigen**.

### Vor dem Paketbau: Voraussetzungen separat prüfen

Der nachsichtige Standard-Einrichtungscheck kann Warnungen melden,
während der tatsächliche Neubau weiterhin feste Voraussetzungen hat.
Unter **Paket bauen → Bauvoraussetzungen prüfen** wird deshalb
für das aktuell ausgewählte Profil eine **nicht schreibende**
Prüfung von Originalspielpfaden, Mapping, exakt gepinntem Unity
2021.3.45f2, .NET SDK und bestehenden Ausgabedateien angeboten.
Der Ergebnisdialog zeigt Blockaden und direkte Einrichtungsschritte:

~~~powershell
python tools/qa_suite_build_readiness.py --profile sprite-suite-world-bc7-v2
~~~

Mit ausdrücklicher Ersetzen-Wahl kann der Ausgabeordner als
potenzieller Überschreibkonflikt bewusst geprüft werden, aber der
separate Check startet niemals einen Build. Der eigentliche
**Paket bauen (mit Vorprüfung)**-Knopf führt dieselbe frische Prüfung
erneut aus und verlangt anschließend eine gesonderte Bestätigung
(Standardantwort **Nein**). Veränderte Quelldateien oder ein neu
aufgetauchter Ausgabeordner stoppen den Start. Nicht gespeicherte
Spiel-/Unity-/SDK-Pfade sind keine gültigen Builder-Eingaben. **Bereit für einen Bauversuch**
ist nicht gleichbedeutend mit einer BC7-/Spiel-Releasefreigabe.
[Prüfumfang und Grenzen](BUILD_READINESS.md).

### Nach dem Bau: Ergebnis statt bloßem CLI-Erfolg anzeigen

Ein in der Suite tatsächlich gestarteter Build wird nach dem
verpflichtenden Validator zusätzlich **asynchron und unabhängig**
über seinen aktuellen SHA-256-Dateibestand überprüft.
Unter **Paket bauen → Bauergebnis anzeigen** sind Exitcode,
bestätigte Ausgabedateien, Warnungen und der Vergleich zur
bereits vorher vorhandenen Manifestversion sichtbar.
Ein Fehler/Abbruch darf keine positive Nachricht vom
älteren Produktionspaket erben. Selbst bei Offline-Erfolg bleibt
die **Ingame- und Releasefreigabe ausstehend**.
[Prüfergebnis und Statusgrenzen](BUILD_COMPLETION.md).

### Nach dem Neustart: Bau- und Prüfverlauf anzeigen

Im selben Reiter **Paket bauen → Bauverlauf anzeigen** wird bei
jedem Aufruf die lokale, vollständige SHA-256-Ereigniskette
überprüft. Sie zeigt Profil, damalige UTC-Startzeit, CLI-
Abschlussstatus und die seinerzeit bestätigten Prüfdaten.
Nach einem Absturz ohne Endeintrag lautet der Status ausdrücklich
**unbestätigt**. Der Verlauf kann weder Builds noch Installationen
starten und ersetzt keine **erneute** Prüfung der jetzigen
Paketbytes. Kommandozeile:

~~~powershell
python tools/qa_suite_build_history.py --limit 20
~~~

[Dokumentation und Manipulationsgrenzen](BUILD_HISTORY.md).

## 1. Inventar und Zuordnung

```powershell
python suite.py verify
python suite.py inventory --side both
python suite.py map propose
python suite.py map audit
python suite.py map manifest --groups body_woodcutter tree_apple anim_castle
```

Das Inventar enthält Sprite-Namen, PathIDs, Texturzuordnung, Geometrie und
Maskenmetadaten. Das Mapping unterscheidet exakte Übernahme, abgeleitete
Übernahme, unverändertes Crusader und offene manuelle Zuordnung. Gleiche Namen
allein sind keine Freigabe. Ergebnisse liegen unter `work/inventory`,
`work/mapping` und `work/reports`.

## 2. Bestehende Sprites bearbeiten

```powershell
python suite.py tool sprites.py list
python suite.py tool sprites.py export body_gate --game stronghold1 --out work/art
python suite.py tool sprites.py sheet work/art/body_gate
python suite.py tool sprites.py check work/art/body_gate
# PNGs bearbeiten; Namen und index.json erhalten.
python suite.py tool sprites.py import work/art/body_gate --set <freigegebene-ablage> --origin derived --check-only
python suite.py tool sprites.py import work/art/body_gate --set <freigegebene-ablage> --origin derived
python suite.py tool sprites.py profile-add <freigegebene-ablage> --origin derived --profile profiles/sprite-suite-world-bc7-v2.json
python suite.py tool sprites.py profile-add <freigegebene-ablage> --origin derived --profile profiles/sprite-suite-world-bc7-v2.json --write
```

`--game crusader` liefert die Zielgeometrie. Ohne `--game` liest `export` die
**tatsächlich installierte**, manifestgeprüfte Grafik: Atlas, danach Einzel-PNG,
sonst Crusader. Dafür muss eine konsistente Installation vorhanden sein.
Bei Teamfarben gehört zu jedem Farbbild ein `_m.png`.

In der Hauptoberfläche zunächst unter **Paket bauen** das Zielprofil wählen.
**Sprites bearbeiten** trägt die importierte Ablage in dieses Profil ein.
Enthält das Profil die Gruppe bereits als Atlas, beim Profileintrag
**Einzel-PNGs dürfen Gruppenatlas überstimmen** auswählen; auf der Kommandozeile
entspricht das `--allow-atlas-shadow`. Die bearbeiteten Bilder werden als
PNG-Überlagerungen geliefert. Die darunterliegenden `gm_atlases` bleiben BC7;
die Einzelbilder werden durch den Import nicht automatisch BC7-komprimiert.
Die separat gestartete alte Werkstatt und `profile-add` ohne `--profile`
verwenden weiterhin `europe-production.json`.

`<freigegebene-ablage>` ist kein frei erfundener Ordnername: vorhandene Ablagen
sind in `_PROJECT_AUTHORED_SPRITE_SETS` in `mod_builder.py` an Gruppen gebunden.
Neue Ablagen dort ausdrücklich zuordnen. Der Einzel-Sprite-Import verlangt die
Ziel-Leinwand; die Atlaspipeline unterstützt zusätzlich die geprüfte native
Quellgeometrie. Diese beiden Wege haben unterschiedliche Geometrieverträge.

## 3. Mehrteilige Bauwerke

```powershell
python suite.py tool sprites.py export tile_castle --game crusader --out work/tile-source
python suite.py tool tile_objects.py compose work/tile-source/tile_castle --preset tile-castle-keep-1193 --out work/objects/keep-1193
python suite.py tool tile_objects.py check work/objects/keep-1193
python suite.py tool tile_objects.py split work/objects/keep-1193 --out work/art-return/keep-1193
```

Die ORA-Datei enthält getrennte Ebenen. Nach der Bearbeitung wird wieder in die
ursprünglichen Frames zerlegt. Die Presets und die CLI-Hilfe bestimmen zulässige
Layouts; der Weg gilt für eigenständig ladbare, maskenfreie `tile_*`-Gruppen.

## 4. Gruppen aufnehmen und Anker bestimmen

```powershell
python suite.py tool groups.py status
python suite.py tool groups.py list --missing
python suite.py tool groups.py add body_archer body_baker
python suite.py tool groups.py policy tile_castle --upright
python suite.py tool pin_digests.py
```

Aufrechte Motive behalten ihren Quellfußpunkt; flache Bodenkacheln ihren
Zielrasteranker. `pin_digests.py` vermisst nur fehlende Nachweise. Andere Fehler
brechen ab. Vor Freigabe Geometrie und Bildinhalt prüfen; ein Digest bestätigt
Identität, keine gestalterische Richtigkeit. Die historischen Werkzeuge ändern
`europe-production.json`, nicht automatisch die BC7-Suite-Profile.

## 5. BC7 bauen und ins Spiel kopieren

```powershell
python suite.py build --profile profiles/sprite-suite-canary-bc7-v2.json
python suite.py validate --profile-id sprite-suite-canary-bc7-v2
# Modordner von Hand ins Spiel kopieren; siehe unten.
# Nach dem Spieltest:
python suite.py runtime-validate --profile-id sprite-suite-canary-bc7-v2
```

Der Canary enthält `tree_apple`, `body_woodcutter` und `anim_castle`: Foliage,
Teammaske und maskenfreie Geometrie. Der große Sprite-Satz liegt in
`sprite-suite-world-bc7-v2.json`. Ein wiederholter Build braucht `--replace`.
Unveränderte Gruppen werden über den inhaltsadressierten Cache wiederverwendet.

Bei geschlossenem Spiel den fertigen Ordner
`dist/<Profil-ID>/StrongholdEuropeDE` nach `BepInEx/plugins` im Spiel kopieren.
In der Oberfläche öffnen **Ausgabe öffnen** und **Spiel-Modordner öffnen**
die beiden Verzeichnisse. Einen vorhandenen Ordner `StrongholdEuropeDE`
zuerst außerhalb von `plugins` aufbewahren, dann den neuen vollständig kopieren.
So bleiben keine veralteten Dateien im Mod zurück. Das Paket enthält seine
eigene Runtime-DLL; Script Extender und dessen Konfiguration werden nicht ersetzt.

Der ursprüngliche verwaltete Installationsweg bleibt unter den erweiterten
Werkzeugen und in der CLI erhalten. Er setzt voraus, dass Suite und Spiel auf
**demselben Laufwerk** liegen:

```powershell
python suite.py install --profile-id sprite-suite-canary-bc7-v2 --replace
python suite.py tool show_installed.py --expect sprite-suite-canary-bc7-v2
```

Dieser Weg prüft Prozesszustand und Manifeste und tauscht den verwalteten Ordner
transaktional. `suite.py uninstall` entfernt nur unveränderte, manifestgebundene
Dateien. Beide Wege verwenden denselben Modordner; sie erzeugen keinen zweiten
parallel aktiven Sprite-Mod.

### Vor dem manuellen Kopieren: projektweiten Release-Abgleich ausführen

Der vorhandene Produktionsbau lässt sich **ohne Build, Installation oder
Spielprozess** über alle Manifestdateien mit SHA-256 verifizieren:

```powershell
python tools/qa_release_preflight.py --profile sprite-suite-world-bc7-v2 --check-only
python tools/qa_release_preflight.py --profile sprite-suite-world-bc7-v2
```

Dies vergleicht die tatsächlich ausgelieferten Bundle-Dateien gegen Manifest,
Profil und BC7-Index. Ein bisheriger Validierungsbericht wird ausdrücklich
nur als historischer Nachweis gelesen. Optional kann eine einzelne,
ausdrücklich gewählte Pivot-Freigabedatei gegen aktuelle Quellhashes
geprüft werden (Schalter `--approval`). **Offline-Integrität ist kein
Spiel-/Kartenwechseltest und keine Pivot-Installationsfreigabe.**
Ausführliche Sicherheitsgrenzen: [Release-Preflight](RELEASE_PREFLIGHT.md).

### Freigegebene Pivot-Messung auf die BC7-Pipeline vorbereiten

Noch **vor** einer möglichen Freigabe kann man unter **Editor & Austausch →
Pivot-Messungen prüfen** den gewählten Frame mit **Pivot im BC7-Atlas
prüfen** gegen den **tatsächlich veröffentlichten Bundlecache** halten.
Derselbe Nur-Lesen-Abgleich ist ohne Freigabe möglich:

~~~powershell
python tools/qa_bc7_pivot_audit.py --profile sprite-suite-world-bc7-v2 --measurement "work/pivot-review-test-echt/zinnen-versatz.beispiel.json"
~~~

Die genannte Beispielmessung ist synthetisch und kein Spiel-Messlauf;
sie bestätigt am lokalen Build anim_castle 002 mit Pivot (0,1)
**bereits im BC7**.

Unter **Editor & Austausch** eine tatsächlich noch notwendige Abweichung
kontrolliert freigeben, danach unter **Diagnose & Reparatur** das
BC7-Profil wählen, das Freigabeprotokoll hinzufügen und
**Pivot-BC7-Stufenplan** ausführen.
Die ursprüngliche Messdatei muss ausdrücklich nochmals gewählt werden.
Der Stufenplan ordnet exakt passende V2-Cacheobjekte nach Bundle- und
Atlas-SHA zu und berechnet nur für geänderte Frames einen theoretischen
Metadaten-Hash-/Cache-Key-Wechsel.

CLI für zwei **explizit vorliegende** Quellen:

~~~powershell
python tools/pivot_bc7_stage.py --profile sprite-suite-world-bc7-v2 --approval "work/reports/pivot-approval/FREIGABEBERICHT.json" --measurement "C:/Pfad/zinnen-versatz.json" --check-only
~~~

Der Bericht liegt ausschließlich unter work/reports/pivot-bc7-stage und
enthält Änderungen mit aktuellem Index-/Bild-/Bundlehash sowie den
festgeschriebenen Geometrie-/Review-Verträgen. **Er kann noch nicht in
einen BC7-Bau übernommen werden**; hierfür sind zusätzliche abgestimmte
Nachweise, neue Geometrieprüfsummen und ein geprüfter Test-Neubau nötig.
[Siehe Sicherheits- und Prüfvertrag](PIVOT_BC7_STUFENPLAN.md).

### Synthetische BC7-V2-Projektvorbereitung prüfen

Zur sicheren technischen Gegenprobe der Metadaten-/Cache-Logik kann unter
**Diagnose & Reparatur → Synthetische BC7-Pivot-Probe vorbereiten**
der unveränderte bestehende V2-Unity-Projekt-Vorbereiter benutzt werden.
Der Ablauf erzeugt zwei ausdrücklich **synthetische** RGBA-Spritegruppen,
validiert beide separaten Unity-Inputs und beweist, dass nur die
betroffene Gruppe einen neuen Gruppencache-Key erhält:

~~~powershell
python tools/qa_pivot_bc7_rehearsal.py
~~~

Der SHA-gebundene Bericht liegt ausschließlich unter
work/pivot-bc7-rehearsals/. **Kein** Unity-Lauf, keine reale BC7-Encodierung,
kein neues Bundle, keine echte Gruppen-/Spiel-Freigabe. Der gepinnte
Unity-Editor 2021.3.45f2 ist derzeit am Projektwerkzeugpfad nicht vorhanden.
Weitere Prüfverträge: [BC7-V2-Projektprobe](PIVOT_BC7_REHEARSAL.md).

### Originales Mapping und native Zinnen-Geometrie verifizieren

Mit **Diagnose & Reparatur → Nativen Zinnen-Geometriebeweis prüfen**
kann die Suite den bereits publizierten anim_castle-Atlas
aus dem SH1DE-/Crusader-Originalmapping und dem SHA-256-
identifizierten Cacheobjekt rekonstruieren. 95 native
Quell- und 11 beibehaltene Ziel-Frames müssen die
existierenden, eingefrorenen Geometrie-, Herkunfts-, RGBA-
und Review-Digests **exakt** reproduzieren. Das geschieht
zunächst komplett nur lesend:

~~~powershell
python tools/qa_native_pivot_provenance.py
~~~

Nur mit --save-report wird ein zusätzlicher inhaltsadressierter
Prüfbericht unter work/reports/pivot-native-provenance erzeugt.
Kein Quell-/Spielatlas, Bundle, Index oder Profil wird verändert.
Originale Game-Assets wurden dabei nicht erneut dekodiert.
[Prüfgrenzen und Reproduktionsbeweise](PIVOT_NATIVE_PROVENANCE.md).

## 6. UI-Atlanten und UI-BC7

```powershell
python suite.py tool ui_atlas.py list
python suite.py tool ui_atlas.py export --atlas UI-MasterAtlas --out work/ui
python suite.py tool ui_atlas.py check --from work/ui
python suite.py tool ui_atlas.py import --from work/ui --store europa-ui
python suite.py tool ui_atlas.py profile-add europa-ui --write
```

Die Zielrechtecke der Noesis-UI bleiben fest. Ein SH1DE-UI-Atlas wird daher über
die vorhandenen Extraktions-/Layoutwerkzeuge umgesetzt, nicht als ganzes Blatt
blind ausgetauscht. Der aktuelle Namensweg liest die XAML-Wörterbücher aus den
MonoBehaviour-Objekten des Quellspiels:

```powershell
python suite.py tool ui_atlas.py export --out work/ui-cru-voll
python suite.py tool ui_sh1_dict.py --out work/ui-sh1-dict
python suite.py tool ui_sh1_umstellung.py zuordnen --sh1 work/ui-sh1-dict --crusader work/ui-cru-voll --out work/ui-sh1-zuordnung
python suite.py tool ui_sh1_umstellung.py boegen --aus work/ui-sh1-zuordnung
```

Das Unterkommando `anwenden` schreibt nach Sichtprüfung mit `--schreiben` in
den über `--baum` gewählten Exportbaum. `ui_sh1_extract.py` bleibt als bildbasierte
Gegenprobe erhalten. Anschließend:

```powershell
python suite.py tool build_ui_bc7_cache.py --source-mod-root dist/europe-production/StrongholdEuropeDE --output-root work/ui-bc7-standalone/run-01
python suite.py tool compose_ui_bc7_candidate.py --replace
```

Die letzten beiden Befehle gehören zum **vollständigen Produktionsprofil** und
setzen dessen passende PNG-Basis und gebundene UI-Quellen voraus. Der Composer
verwendet vorhandene GM-Bundles und baut sie nicht erneut. Ein reiner
Runtime-Refresh erfolgt separat über `compose_runtime_refresh.py`.

Das mitgelieferte `generate_ui_texture_source_manifest.py` ist der historische
Generator für 114 Einträge. Das aktuelle, geprüfte Manifest enthält 128
Einträge (23 Profilbilder und 105 Arbeitsbilder). Den alten Generator nicht
unverändert über dieses Manifest schreiben.

## 7. Laufzeitabnahme

Laden einer Karte, gemischte Teameinheiten, Vegetation, Türme/Torhäuser,
Speichern/Laden, Rückkehr ins Menü und eine zweite Karte prüfen. Installation
und Buildmanifest vor dem Start abgleichen. `ram_acceptance.py` und
`full152_ingame_acceptance.py` liefern die bisherigen PID-gebundenen Messwege;
letzterer ist ausdrücklich an das historische Produktionsprofil gebunden.
Ein bestandener Offline-Test ersetzt keinen Kartenwechseltest.
