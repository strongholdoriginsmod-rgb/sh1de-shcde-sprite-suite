# Sprite Suite – Brauchbarkeits- und Korrektheitsprüfung

**Stand:** 11. Oktober 2026
**Projekt:** E:\\SpriteSuite
**Branch:** feature/sandbox-studio
**Fokus:** Die Sandbox gehört fest in die Universal-Suite, ohne Verlust der
Editorfunktionen, mit korrekter Katalogauswahl und sicherem Schließen.

## Nachgeprüfte, behobene Defekte

| Priorität | Festgestellter Defekt | Umsetzung / Regression |
| --- | --- | --- |
| P1 | Die in Qt vorhandene Animation-/Frame-Test-Palette wurde beim Einbetten als Bottom-Dock versteckt; in der Hauptanwendung war sie nicht nutzbar | Animation-Dock jetzt als rechter Qt-Reiter eingebunden, mit eigenem Tk-Kurzbefehl **Animation / Frames** und Qt-Erreichbarkeitstest |
| P1 | **Originalgrafik im Katalog** lieferte bei früherem Engine-Hit auch nach manueller Frame-Auswahl die veraltete Grafik | Die aktuelle zentrale Spritevorschau ist nun maßgeblich; Einbringen eines neuen Katalogsprites verwirft die vorherige Trefferidentität |
| P1 | Qt-Schließen/Alt+F4 konnte nur das native Qt-Kindfenster schließen und einen leeren Sandkasten-Reiter im Tk-Hauptfenster hinterlassen | Schließen wird an das Tk-Hauptfenster weitergereicht; Qt schließt nur kontrolliert beim gemeinsamen Beenden und fragt weiterhin bei ungespeicherten Overlays/Szenen nach. Qt- und Tk-Testfälle prüfen auch Abbruch |
| P2 | Die unkonfigurierte Suite verwendete den ursprünglich fest codierten Entwicklerpfad E:/SSGameQA | Stattdessen: benutzergewählter Sandbox-Kartenordner, dann gültiger Zielspielordner aus TOML, andernfalls leerer Kartenkatalog mit **Kartenordner wählen** |
| P2 | Ein neu gewählter Kartenordner war nach Neustart vergessen und `find_maps` erkannte nicht jeden beliebigen Ordner mit Original-`.map`-Dateien | Kartenordner bleibt atomisch im ignorierten lokalen `config/sandbox-maps.local.json` gespeichert. Auch direkt ausgewählte Ordner mit `.map`-Dateien werden gelesen und die ursprüngliche Datei bleibt unverändert |

## Bedienablauf (realer Windows-Rechner)

1. **`Suite starten.cmd`** normal ausführen.
2. In der Hauptanwendung auf **Sandkasten** wechseln.
3. **Originalkarte öffnen** oder **Kartenordner wählen** (nur bei Bedarf).
4. Im **Asset-Katalog** eine Grafik auswählen und **Im Sandkasten zeigen**
   drücken – das Sprite wird in derselben Anwendung auf der Karte platziert.
5. Über **Animation / Frames** oder **Spiel-HUD** ohne Dock-Suche direkt zu
   den entsprechenden Werkzeugen springen.
6. **Originalgrafik im Katalog** führt zur **aktuellen**, nicht zur
   veralteten Frame-Auswahl zurück.
7. Beim Beenden über das Qt-Menü oder Alt+F4 bleibt kein leerer Tk-Reiter
   zurück. Ungespeicherte Szene/Overlay-Dateien behalten den
   gewohnten Bestätigungsdialog.

## Datei-/Sicherheitsgrenzen

- Die Original-`.map`-, Spiel-GM- und Unity-Daten werden **nicht** überschrieben.
- Ein lokal gewählter Kartenordner wird ausschließlich in
  `config/sandbox-maps.local.json` gesichert; diese Datei ist
  über die Projekt-`.gitignore` privat und wird **nicht** committed.
- Kartenwahl vor Schließen oder Wechsel prüft vorhandene ungespeicherte
  Bearbeitungen.
- Dateipfade werden vor Speicherung auf tatsächliche Spielordner,
  `Maps`-Ordner oder vorhandene `.map`-Dateien geprüft.
- Editor-Projektdateien und gespeicherte Overlays folgen weiterhin ihrer
  vorherigen, getrennten sicheren Persistenz.
- Die Qt/Tk-Nativeinbettung ist **Windows-spezifisch**;
  vollständige Unity-Shader- und Gameplay-HUD-Parität ist nicht abgenommen.

## Regression / Abnahme

- `tests/sandbox/test_suite_integration.py`: Einbetten, Animation,
  Katalog-/Tab-Wechsel, aktuelle Frame-Auswahl, Lebensdauer/Abbruch.
- `tests/sandbox/test_maps_configuration.py`: portable Spielordnerwahl,
  gespeicherte Auswahl, TOML-Konfiguration, fehlerhafte Speicherdateien,
  Originaldateischutz und beliebige Kartendateiverzeichnisse.
- `tools/qa_suite_embedded.py`: echter Windows-Tk-Hauptfensterstart,
  Qt-Kind-HWND und identische Fenstergrößen, sichtbare Animation und
  Spiel-HUD, bidirektionale Katalogroute, Qt-Schließen statt leerem Tab.
- `python -m pytest -q tests`: alle verfügbaren Tests.

**Weiter offen:** Ein echter Langzeittest (mehrstündiges Wechseln,
Hunderte Bearbeitungen) sowie pixelgenaue Unity-Sondermaterialien,
Original-Spielsimulation und das vollständige Gameplay-HUD.


## Abschließender Prüfstatus (11.10.2026)

- **Vollständige Python-Regression:** `215 passed in 78.93s`
  mit `.venv\\Scripts\\python.exe -m pytest -q tests`.
- **Realer Windows-Hauptfenster-Test:** `QA_PASS` mit
  `.venv\\Scripts\\python.exe tools\\qa_suite_embedded.py`.
  Gemessen wurden echte Qt-/Tk-HWND-Elternschaft und identische
  Abmessungen `1460×623`, Originalkarte `Antioch.map`,
  zugängliches Animation-/Spiel-HUD, Hin-/Rücknavigation des
  Asset-Katalogs sowie korrekte Weitergabe des Qt-Schließbefehls
  an das Hauptfenster.
- **Statische Syntaxprüfung:** über alle geänderten GUI-/Importer-
  Module erfolgreich.
- **Python-Umgebung:** `pip check` meldet keine defekten
  Abhängigkeiten.
- **Datensicherheit:** Die gewählte, bereits bekannte
  Originalkarteninstallation auf dem autorisierten PC wurde nur in
  `config/sandbox-maps.local.json` hinterlegt (Git-ignoriert).
  Ein Benutzer kann diese Auswahl jederzeit über **Kartenordner
  wählen** ändern. Kein Originalspiel wurde beschrieben.

Ein mehrstündiger interaktiver Langzeittest und vollständige
Unity-Shader-/Gameplay-HUD-Parität sind weiterhin **nicht abgenommen**.


## Neue Werkzeuge aus großen Altbeständen (11. Oktober 2026)

Die bisherigen zusätzlichen historischen Programme liegen in separaten
Projekten; der neue Prüf-/Importweg ist **in die aktuelle Sprite Suite**
integriert, ohne ganze alte Toolketten aus anderen Versionen zu kopieren.

- **Pivot-Messung aus Zinnenlineal:** Der Editor-&-Austausch-Reiter
  kann `zinnenlineal.versatz.v1`-Dateien lesen, Sprite-Anker und
  gemessene Ziel-Pivots miteinander vergleichen und Bild-/Framewerte
  anhand echter Originalgrafik-Indizes verifizieren. Die Vorschau
  führt direkt zum aktuellen Frame im Katalog bzw. Sandkasten.
  Nur ein getrennt gespeicherter, SHA-256-dokumentierter
  **Korrekturvorschlag** wird exportiert. Eine nach Sichtprüfung separat
  bestätigte Freigabe oder Ablehnung kann jetzt ohne Assetänderung in
  `work/reports/pivot-approval/` protokolliert werden. Der Export
  verweigert veränderte Messdateien, Indizes und Bildinhalte.
- **Alte QA-Werkzeuge inventarisieren:** Diagnose & Reparatur
  vergleicht eine gewählte historische Projektwurzel ausschließlich
  lesend. SHA-256, Versionsabweichung, Risikoklasse und Testmodulzahl
  werden sichtbar. **Kein** Altinstallierer wird automatisch ausgeführt.
- **Realer Fenster-Smoke-Test:** `tools/qa_suite_embedded.py`
  meldet **PIVOT_REVIEW_INTEGRATED**, **LEGACY_QA_INVENTORY_INTEGRATED**
  und `QA_PASS`, nachdem das Hauptfenster, der eingebettete Sandkasten,
  die neuen Tk-Werkzeuge und der sichere Schließweg geprüft wurden.
- **Echter lokaler Vergleich:** `anim_castle 002`, Quellbild
  333×165 Pixel mit aktuellem ausgeliefertem Pivot 0/1,
  wurde als **Bereits passend** zur Zinnenlineal-Zielkorrektur
  klassifiziert. Kein Eingriff in Atlas-, Arbeits- oder Spieldateien.

**Ablauf, Prüfschritte, Sicherheitsgrenzen:**
`docs/HISTORISCHE_WERKZEUGE_INTEGRATION.md`.

## Projektweiter Release-Abgleich (11. Oktober 2026)

Der neue Prüfweg unter **Diagnose & Reparatur → Gesamten Build prüfen (SHA-256)**
sichert den kompletten Produktionsbestand unabhängig vom alten
Validierungsbericht ab. Er läuft asynchron, ohne einen Installer aufzurufen.

- **Produktionsprofil `sprite-suite-world-bc7-v2`:** 154/154 Dateien
  inklusive 149 Bundlegruppen mit manifestgebundenen SHA-256-Werten geprüft;
  675.908.516 Bytes gelesen, 0 Abweichungen.
- Der vorhandene Bericht nennt **1009 erfolgreiche Prüfungen**, ist aber
  kein SHA-256-gebundener Nachweis für den jetzt gelesenen Buildstand.
- Manipulierte Dateien, zusätzliche Artefakte, unsichere relative Pfade,
  ungültige Gruppen oder unreferenzierte Bundles werden blockiert.
- Eine optionale ausdrücklich gewählte Pivot-Freigabe bleibt ein
  dokumentierter Prüfentscheid und löst **keine** Metadaten-/BC7-Änderung aus.

**CLI, Bedienweg und Abgrenzung gegenüber echter Ingame-Abnahme:**
`docs/RELEASE_PREFLIGHT.md`.


### Projektweiter SHA-256-Releaseabgleich – Abnahme

- **Gesamtregression:** `265 passed` mit `.venv\\Scripts\\python.exe -m pytest -q tests`.
- **Gezielte Release-/GUI-Regression nach Sprachpflege:** `19 passed`.
- **Realer Windows-Tk-/Qt-Hauptfenstertest:** `RELEASE_PREFLIGHT_ACCESSIBLE`
  und `QA_PASS`; Sandkasten, Sprite-Katalog, Pivotprüfung und QA-Altbestand
  blieben ohne separate Hauptfenster bedienbar.
- **Echter Produktionskandidat:** 154 Dateien / 675.908.516 Bytes
  vollständige SHA-256-Übereinstimmung, 149 BC7-Spritegruppen, keine
  fremden Dateien oder Ordner. Reproduzierbarer Bericht in
  `work/reports/release-preflight/`.
- **CLI-/Profil-Schutz:** unsichere Pfade, unreferenzierte Bundles und
  fehlende/manipulierte Dateien führen zu einem blockierenden Ergebnis.
- **Gegenprobe:** keine Installations-, Sprite-, Atlas- oder
  Spieldatei wurde durch diese Prüfung verändert. Eine echte Ingame- und
  Pivot-Metadaten-Releaseabnahme bleibt gesondert erforderlich.

Dokumentation: `docs/RELEASE_PREFLIGHT.md`.


## Pivot → BC7-Stufenentwurf (11. Oktober 2026)

- **Eingangsvertrag:** Ein vorher ausdrücklich gespeichertes
  `stronghold-europe.pivot-approval.v1`-Protokoll und die **wirkliche,
  unveränderte Originalmessdatei** sind erforderlich. Der Entwurf prüft
  nochmals Quelle, Bildgeometrie, Versatzformel, alte/neue Pivots und
  individuelle SHA-256-Werte.
- **Projektbindung:** Das bestehende BC7-Profil, das komplette
  Auslieferungsmanifest, alle Bundles und der Bundleindex müssen vor
  Erstellung des Stufenentwurfs hash-konsistent sein. Betroffene Gruppen
  enthalten die aktuellen Geometrie- und Review-Proof-Pins als Referenz.
- **Regression:** `tests/sandbox/test_pivot_build_stage.py` und
  `tests/sandbox/test_pivot_build_stage_gui.py` prüfen Manipulation,
  geänderte Quellen, Wiederholung, unzulässige Pfade, fehlende Build-
  Artefakte, Mischfälle mit bereits korrekten Sprites und die
  asynchrone Bedienung.
- **Gesamtregression:** `286 passed, 1 skipped` (ein einzelner
  Tcl/Tk-Initialisierungsfehler des GUI-Testharness; derselbe Test
  separat danach `1 passed`). Keine Python-Testfehler.
- **Echter Windows-Hauptfenstertest:** `PIVOT_BC7_STAGE_ACCESSIBLE` und
  `QA_PASS`; zugleich `PIVOT_REVIEW_INTEGRATED`,
  `RELEASE_PREFLIGHT_ACCESSIBLE` und `LEGACY_QA_INVENTORY_INTEGRATED`.
- **Unverändert:** Keine BC7-Pakete, Spiel-, Profil- oder Katalogindex-
  Dateien wurden durch den Stufenentwurf geschrieben. Eine spätere
  produktive Metadaten-Korrektur erfordert das Neuberechnen der
  ursprünglichen, eingefrorenen Geometrie- und Cache-/Bundlebeweise.

Bedienung und Sicherheitsgrenzen: `docs/PIVOT_BC7_STUFENPLAN.md`.


## Realer veröffentlichter BC7-Atlas-Pivot (11. Oktober 2026)

- **Echtprüfung statt bloßem Katalogwert:** Der neue Atlasprüfer
  verwendet den aktuellen Bundleindex und wählt aus mehreren
  historischen V2-Cacheobjekten ausschließlich dasjenige, dessen
  **Bundle-SHA und Atlas-SHA** exakt zum ausgelieferten Produktionsstand
  passen. Die gesamte Cache-Objekt-/Ref-/Qualitätsbindung wird über
  den vorhandenen Cachelader erneut validiert.
- **anim_castle 002:** Veröffentlichtes Objekt
  f069eb9187a0…, Gruppe anim_castle; Atlasframe 333×165 px,
  Pivot **(0, 1)**. Messziel und ausgelieferter Katalog sind bereits
  (0, 1). Daher keine weitere Korrektur und kein notwendiger
  BC7-Neubau für diesen Frame.
- **Nur-Lesen-CLI:** tools/qa_bc7_pivot_audit.py meldet anhand der
  dokumentierten **synthetischen** Beispielmessung:
  1 verifiziert, 1 bereits richtig, 0 potenzielle Neuprüfung,
  0 unbekannt; keinerlei Dateiänderung.
- **GUI:** Pivot im BC7-Atlas prüfen innerhalb des Zinnenlineal-
  Prüfens kontrolliert asynchron den tatsächlich publizierten Frame;
  bei bereits richtigem BC7-Zielpivot bleibt der Freigabeknopf
  deaktiviert. Die geschützte Aktion verweigert eine erneute Freigabe
  auch bei direktem Funktionsaufruf.
- **Stufenplan:** already_in_published_bc7 führt erledigte
  Änderungen separat. Für tatsächlich noch nötige Korrekturen
  werden V2-Frame-Metadatenhash und veränderter Gruppencache-Key
  **nur rechnerisch projiziert**, niemals publiziert. Bei fehlender
  Cacheprovenienz erfolgt kein freigegebener Buildauftrag.
  Manipulierte Bundle-/Indexdaten auch **während** der Prüfung
  stoppen den Entwurf.
- **Reale Fensterabnahme:** PUBLISHED_BC7_PIVOT_MATCHES,
  PIVOT_BC7_STAGE_ACCESSIBLE, RELEASE_PREFLIGHT_ACCESSIBLE
  und QA_PASS. Originale Spiel-, Katalog- und Produktionsartefakte
  wurden weder überarbeitet noch neu gebaut.

Siehe docs/PIVOT_BC7_STUFENPLAN.md sowie
tests/sandbox/test_pivot_bc7_cache.py und
tests/sandbox/test_pivot_bc7_review_gui.py.


### Abschließende Gesamtregression der BC7-Cache-Gegenprüfung

- Vollständiger detaillierter Projekttest mit dem aktuellen Quellstand:
  **310 passed in 94.63s**, Exitcode 0.
- Ein vorangegangener Komplettlauf endete einmal ohne reguläre
  pytest-Zusammenfassung mit Prozess-Exitcode 1. Der Wiederholungslauf
  mit Einzeltestprotokoll konnte diesen Prozessabbruch nicht reproduzieren;
  er enthält **keinen** übersprungenen oder fehlgeschlagenen Test.
- Reale Hauptfenster-Abnahme:
  **PUBLISHED_BC7_PIVOT_MATCHES**, **QA_PASS**.
- Es wurde kein realer Unity-/BC7-Produktionsneubau und kein
  Ingame-Kartenwechseltest ausgeführt; die neuen Metadaten- und
  Cache-Schlüssel sind bei Änderungen nur hypothetisch.


## Isolierte synthetische BC7-V2-Projektprobe (11. Oktober 2026)

Die echte V2-Gruppen-/Projektvorbereitung wird jetzt über
**Diagnose & Reparatur → Synthetische BC7-Pivot-Probe vorbereiten**
ausgeführt. Zwei bewusst künstliche RGBA-Framegruppen testen den
geänderten Pivot und eine unveränderte Kontrollgruppe.

- Beide Unity-Eingabeprojekte werden mit dem echten
  V2-Preflight, Atlaspacking, Unity-Project-Preparer und dem
  V2-Prepared-Project-Validator erfolgreich geprüft.
- Für anim_castle wird ausschließlich der Pivot von
  (0, 1.1090909242630005) auf (0, 1.0) geändert.
  Die eigentliche Seiten-PNG und die Eingangs-RGBA-Hashes
  bleiben identisch, während Build-Seed, Atlas-Metadaten,
  Frame-Digest und synthetischer Gruppencache-Key wechseln.
- Die unveränderte Kontrollgruppe anim_drawbridge behält ihren
  Metadatenhash, ihre Atlasdatei und ihren Cache-Eingangsschlüssel.
- Ein SHA-256-gebundenes, unveränderliches Attest wird nur
  unter work/pivot-bc7-rehearsals/ veröffentlicht.
  Es beschreibt ausdrücklich einen künstlichen Unity-Executable-
  Cache-Platzhalter und keine echten produktionsfähigen Cache-Keys.
- Die echte Produktionskonfiguration verlangt Unity 2021.3.45f2;
  diese gepinnte Version ist am vorgesehenen Werkzeugpfad nicht
  vorhanden. Weder ein Unity-Editorlauf noch eine neue BC7-
  Bundlekompression oder Ingame-Abnahme wurde durchgeführt.
- Der native Windows-Hauptfenster-Smoke-Test bestätigte
  SYNTHETIC_BC7_V2_PREPARED und QA_PASS neben der
  bereits integrierten Pivot- und Sandbox-Diagnose.

Tests und Bedienung: docs/PIVOT_BC7_REHEARSAL.md.


### Abschlussabnahme der synthetischen V2-Probe

- **Vollständige Python-Regression:** 332 passed in 113.01s,
  Exitcode 0 (keine fehlgeschlagenen oder übersprungenen Tests).
- **Gezielte Pivot-/V2-Vorbereitungs- und Tk-GUI-Tests:**
  23 passed, inklusive wiederholbarer, unveränderlicher
  Attestdateien, manipulierten Quellen, fehlerhaften Unity-Versionpins
  und geänderter/konstanter Cache-Schlüssel.
- **Realer Windows-Tk-/Qt-Test:** SYNTHETIC_BC7_V2_PREPARED
  und QA_PASS. Die Probe blieb im Hauptfenster bedienbar,
  während die echten zwei Unity-Projekt-Inputs vorbereitet wurden.
- **Erneuter Produktionsintegritätscheck:** 154/154 Dateien,
  675.908.516 Bytes und 149 Gruppen unverändert,
  0 Fehler, 0 Warnungen. Der bestehende
  Validierungsbericht mit 1.009 Erfolgen ist nur historisch.
- **Isoliertes Belegverzeichnis:**
  work/pivot-bc7-rehearsals/5ae44b2e86dbcc9f1aca/
  mit einem SHA-256-gebundenen evidence-Bericht.
  Der identische Folgeaufruf wurde vollständig verifiziert
  wiederverwendet.
- **Grenze:** exact_editor_missing für Unity 2021.3.45f2.
  Keine Unity-Komprimierung, kein neuer realer BC7-AssetBundle-
  Build, keine Anwendung freigegebener Zinnen-Pivots,
  keine Ingame-Prüfung oder Installationsänderung.


## Originalmapping und publizierter nativer Zinnen-Geometriebeweis

**Stand 11. Oktober 2026, nur lesender Herkunfts-/Produktionsabgleich.**

- Das private Mapping work/mapping/proposals.json.gz wurde mit
  SHA-256 60c4b823d183876f304d8ebd9d3ec3d7563dece89326853fc81d283ca79c6dab
  in seinem echten Schema gelesen und mit den im Produktionsmanifest
  aufgeführten SH1DE-/SHCDE-Build-IDs abgeglichen.
- Die exakt zum veröffentlichten anim_castle-Bundle passende
  V2-Cachefassung wurde per Bundle- und Atlas-SHA ausgewählt.
  Historische Fassungen wurden nicht ersatzweise vertraut.
- Sämtliche 106 Loader-Frames wurden in ihrer ursprünglichen Reihenfolge
  aus dem nativen Mapping gegen die aktuelle BC7-Atlasmetadaten geprüft:
  95 Quellframes aus SH1DE sowie 11 unveränderte Crusader-Fallbacks.
- Alle 95 Ausgabepivots erfüllen die originale
  native_source_reanchored_v1-Formel einschließlich float32-Rundung.
  Für anim_castle 002 stimmen Originalmapping und veröffentlichter
  BC7-Atlas bereits beim Zielpivot (0,1) überein.
- Der neu berechnete Geometriebeweis
  f0be1cb1beb096ff4d518bd48dfa4ee23ec86382a1e7ea14edd1b07a8dd88152,
  SH1DE-Herkunftsnachweis
  7fc71756f809738686a270b71d3a107e7eae97dfd913c729bd3ad5be72468298,
  Quell-RGBA-Nachweis
  4a08b4309e74089447d082b75411fe31956a9a2107bfc809cda4ebb7d590cf20
  und Review-Partition
  dfede86203e0ac0aed794bdc9ab73a70da0663b7034ad4151f5e88d293c5e39c
  stimmen sämtlich **exakt** mit dem veröffentlichten Profil überein.
- Die neu eingeführten Tests weisen mutierte Herkunftsaktionen,
  Quell-/Zielpivots, Abmessungen, RGBA-Nachweise, Frame-Reihenfolgen,
  falsche GZIP-Inhalte und veraltete Berichtsausgaben zurück.

**Neue Abnahmen:** 26 gezielte Modul-/GUI-Tests bestanden;
anschließende vollständige Projektsuite **362 passed in 93.49s**.
Der echte Windows-Tk-/Qt-Hauptfensterlauf meldete
PUBLISHED_NATIVE_GEOMETRY_RECONSTRUCTED und QA_PASS,
gleichzeitig wurden Sandbox-, Katalog-, BC7- und bisherige
Pivot-/QA-Werkzeuge erfolgreich geprüft.

Ein inhaltsadressierter Bericht liegt unter
work/reports/pivot-native-provenance/.
Die Quell-RGBA-Nachweise sind aus dem bereits veröffentlichten
Cache rekonstruiert; die ursprünglichen resources.assets wurden
nicht erneut dekodiert. Kein Unity-Neubau, keine neue BC7-Kompression,
keine Änderung der Produktions-/Spieldateien.

Dokumentation: docs/PIVOT_NATIVE_PROVENANCE.md.


## UI-Gesamtprüfung vom 13. Oktober 2026

Für die vollständige Sprite Suite wurden jetzt alle **14 Tk-Arbeitsbereiche**
bei zwei Fenstergrößen und in beiden Oberflächensprachen erfasst
(**56 Ansichtsprüfungen**). Horizontal abgeschnittene sichtbare
Steuerungen: **0**.

Der eingebettete Qt-Sandkasten hat zusätzlich überprüfte
Menü-/QAction-Lebensdauer, Werkzeugauswahl, Tastaturnavigation,
reversible DE/EN-Beschriftungen und unterscheidbare Accessible Names.
Die englische Oberfläche ändert keine maschinenlesbaren Spritegruppen,
Teamkennungen oder Overlaydaten. Dynamische Zähler und weitere
Hilfetexte des Tk-Hauptfensters wurden nachübersetzt.

Abnahmeumfang und verbleibende Probleme:
`docs/SPRITESUITE_UI_GESAMTPRUEFUNG_2026-10-13.md`.
