# Zinnenlineal → BC7: quellgebundener Stufenentwurf

**Stand:** 11. Oktober 2026. Entwicklungszweig: feature/sandbox-studio.

## Warum kein direktes Schreiben?

Eine durch Zinnenlineal gemessene Pivotkorrektur beschreibt **einen
Verschiebungsvorschlag**. Die ausgelieferte Sprite Suite verwendet für BC7
hingegen echte Unity-Sprite-Metadaten aus SH1DE und SHCDE sowie
gruppenbezogene, festgeschriebene Geometrie-Nachweise. Änderungen nur in
work/katalog/geliefert/<gruppe>/index.json würden diese Pipeline nicht
ändern und könnten den Geometrieprüfsummen widersprechen.

**Reales Beispiel:** anim_castle 002 misst 333×165 px, hoch +18 px, alter
Pivot ungefähr (0, 1.109091), neuer Pivot (0, 1.0). Im tatsächlich
ausgelieferten Katalogindex steht **bereits (0, 1.0)**.
Der Frame ist **Bereits passend**; es darf keine zweite Korrektur geben.

Das aktuelle Produktionsprofil sprite-suite-world-bc7-v2 verwendet für
anim_castle den Geometriemodus native_source_reanchored_v1 mit eingefrorenem
Geometrie-/Herkunftsnachweis und zusätzlich eine geprüft abgegrenzte
Review-Frame-Partition. Der Stufenentwurf übernimmt diese Vertragsfelder
als Referenz, ändert sie aber niemals.

## Zwei explizite Eingaben, kein Autoimport

1. Unter **Editor & Austausch → Pivot-Messungen prüfen** die echte
   Zinnenlineal-Messung öffnen und eine Abweichung visuell vergleichen.
   Nur Einträge „Korrektur prüfen“ aus der ausgelieferten Quelle dürfen
   ausdrücklich freigegeben werden. Export der Freigabeentscheidung
   erzeugt ein JSON in work/reports/pivot-approval/.
2. Unter **Diagnose & Reparatur** das Ziel-BC7-Profil auswählen und
   **Pivot-Protokoll wählen …** benutzen. Danach
   **Pivot-BC7-Stufenplan** drücken und **dieselbe Originalmessdatei**
   ausdrücklich nochmals auswählen.
3. Der asynchrone Prüfer verifiziert die Messungsformel, alle Zeilen des
   ursprünglichen Freigabeprotokolls, Entscheidung/Zeitpunkt,
   Quelldateinamen und SHA-256 von Messung, PNG und Katalogindex.
   Er prüft außerdem **alle** Dateien des aktuell fertigen Produktions-
   Builds gegen Manifest, Profil, Gruppen und BC7-Bundleindex.
4. Nur dann entsteht ein versionsgebundener **Stufenentwurf**:
   work/reports/pivot-bc7-stage/<profil>-<inhaltshash>.json.
   Die Tabelle zeigt, welche Gruppen betroffen wären und welche
   weiteren Nachweise zwingend neu zu berechnen wären.

Es werden **keine** Sprite-Indizes, Quell-/Ziel-PNGs, GM-Atlanten, Unity-
Bundles, Cacheobjekte, Produktionsprofile oder Spiele überschrieben.
Identischer Stufenentwurf lässt sich ohne Duplikate erneut exportieren;
ein geänderter Build oder eine geänderte Quellmessung wird abgelehnt.

## CLI

Aus dem Sprite-Suite-Projektverzeichnis:

~~~powershell
.\.venv\Scripts\python.exe tools\pivot_bc7_stage.py --profile sprite-suite-world-bc7-v2 --approval "work\reports\pivot-approval\<echte-freigabe>.json" --measurement "C:\Pfad\zur\urspruenglichen\zinnen-versatz.json" --check-only
.\.venv\Scripts\python.exe tools\pivot_bc7_stage.py --profile sprite-suite-world-bc7-v2 --approval "work\reports\pivot-approval\<echte-freigabe>.json" --measurement "C:\Pfad\zur\urspruenglichen\zinnen-versatz.json"
~~~

Die Option --check-only schreibt **nichts**. Ohne diese Option schreibt
das Werkzeug ausschließlich den inhaltsadressierten Stufenbericht.

## Sicherheits- und Vertragserfordernisse

- Gemessene alte und neue Pivots, Bildgröße und Pixeloffset müssen
  vollständig und exakt zum erneut gemessenen Original passen.
- Eine Freigabe ist nur bei unverändertem **alten** ausgelieferten Pivot
  zulässig. Bereits korrigierte, fehlende, mehrdeutige oder geänderte
  Frames werden nicht übernommen. Abgelehnte und zurückgestellte Frames
  erzeugen keine Korrekturzeile.
- Der Freigabebericht muss direkt aus dem vorgesehenen privaten
  Berichtsordner stammen und inhaltsadressiert unverändert sein.
  Eine explizit gewählte Messdatei wird gegen Namen, Pfad und SHA-256
  des früheren Messlaufs geprüft. Eine selbst gefälschte JSON-Freigabe
  ist dadurch nicht kryptografisch signiert; sie führt aber trotzdem
  **niemals** zu einer automatischen Änderung.
- Das angegebene BC7-Profil muss tatsächlich fertig gebaut, vollständig
  manifestgebunden und als lokale Quelle hash-identisch sein.
  Ein bloßer alter Testbericht kann diese Identität nicht belegen.
- Jeder freigegebene Frame erhält:
  requires_proof_recalculation=true,
  requires_bundle_rebuild=true und application_allowed=false.
  Der Gesamtentwurf enthält installation_allowed=false.
- Ein separater zukünftiger Builder-Vertrag muss Quell- und Zielpivots,
  nativen Anker, Gruppen-Geometrie- und Review-Proofs, Frame-Metadatenhashes,
  Cache-Invalidierung, BC7-Roundtrip und einen echten Test-Neubau
  vor einer Freigabe behandeln. Ein einfacher Index-Schreibknopf
  wäre keine korrekte Integration.
- Für die echte Ingame-Abnahme müssen zusätzlich Unity-Grafik und
  Sprite-Pivot im Spiel getestet werden. Shader-/HUD-Parität bleibt separat.

## Abnahme

tests/sandbox/test_pivot_build_stage.py enthält Gegenproben gegen
geänderte Messungen/PNG/Index/Manifest/Bundles/Profile, manipulierte
Entscheidungen, boolesche Zahlenarten, unzulässige Berichtspfade,
verlinkte Ausgabeordner und veränderte Quellen vor dem Export.
Ein gemischter Test mit bereits richtigem anim_castle 002 und
noch abweichendem anim_castle 003 stellt sicher, dass nur der
tatsächlich freigegebene zweite Frame im Entwurf erscheint.

tests/sandbox/test_pivot_build_stage_gui.py prüft Auswahl,
asynchrone GUI-Bedienung und dass Diagnosebefunde keine Spriteprogramme
starten. Der reale Windows-Hauptfenster-Test
tools/qa_suite_embedded.py prüft die Erreichbarkeit des Buttons
zusammen mit Pivot-, Katalog- und Sandbox-Integration.

**Separat verfügbar:** Die
[synthetische BC7-V2-Projektprobe](PIVOT_BC7_REHEARSAL.md)
bestätigt bereits mit zwei echten V2-Projektvorbereitungen,
dass eine reine Pivotänderung nur den betroffenen Frame-
Metadaten- und Gruppencache-Key verändert. Ihre Testgrafiken
und synthetischen Cache-Keys dürfen **nicht** als Freigaben für
echte Spielsprites ausgegeben werden.

**Grenze dieses Schritts:** Der Stufenentwurf ist der vorbereitende
Eingangsvertrag, **kein** fertiger BC7-Metadatenbuilder und keine
Autorisierung für Installations- oder Spieldateischreibzugriffe.


## Nachvollziehbarer Originalmapping-Beweis

Als ergänzende Prüfstufe kann die Suite inzwischen die
[komplette native Zinnen-Provenienz](PIVOT_NATIVE_PROVENANCE.md)
aus dem generierten SH1DE-/Crusader-Mapping,
dem unveränderten Produktprofil und dem
veröffentlichten BC7-Cache rekonstruieren.
Alle 95 nativen anim_castle-Quellframes und
11 unveränderten Crusader-Fallbacks erfüllen exakt
die alten eingefrorenen Produktionsnachweise.
Eine neue Pixel- oder Metadatenänderung wird dadurch
**nicht** freigegeben.

## Erweiterung: tatsächlichen veröffentlichten BC7-Atlas prüfen

Der zuvor gespeicherte Grafikindex ist nicht allein die Quelle der
BC7-Grafikmetadaten. Der neue Prüfer gleicht deshalb zusätzlich den
**tatsächlich publizierten BC7-Bundleindex** mit einem unveränderlichen
Gruppencacheobjekt ab:

1. Das vollständige Release-Preflight muss zuerst sämtliche ausgelieferten
   Dateien per Manifest, Größe und SHA-256 bestätigen.
2. Pro betroffener Gruppe werden nur Cache-Referenzen unter
   cache/asset-stream-group-cache-v1/refs/<gruppe> betrachtet.
   Referenzen auf andere Bundleversionen werden ignoriert.
   Ein Treffer muss **gleichzeitig** die aktuelle Bundle-SHA-256 und die
   im veröffentlichten Index festgelegte Atlas-SHA-256 besitzen.
3. Der Cache-Lader validiert anschließend die vollständige Identität des
   unveränderlichen Objekts einschließlich Atlas.v3, Bundle, Framequalität,
   Referenzbindung und ursprünglichem Gruppencache-Eingang.
   Manipulierte/verlinkte oder mehrdeutige Nachweise blockieren.
   Ist kein entsprechendes Objekt vorhanden, wird dies ausdrücklich als
   **nicht verifizierbar** ausgewiesen, niemals als Freigabe.
4. Der wirkliche BC7-Frame-Pivot und die Quellgeometrie werden erst danach
   gegen gemessenen alten und vorgeschlagenen neuen Pivot geprüft.
   Stimmt der neue Wert bereits im BC7-Atlas, kommt der Frame auf die
   Liste **bereits im veröffentlichten BC7** und erzeugt **keinen** neuen
   Buildvorschlag. Ein fremder Pivot oder eine andere Geometrie blockiert.
5. Für noch nötige Pivots errechnet der Prüfer gruppenweise den
   hypothetischen **V2-Frame-Metadatenhash** und den daraus folgenden
   **Gruppencache-Key**, mit exakt dem vorhandenen V2-Cacheeingangsparser.
   Pixel-, Masken- und Frame-Namenshash müssen unverändert bleiben.
   Dies ist eine **Cache-Schlüssel-Projektion, kein echter Unity- oder
   BC7-Neubau**; die im Produktionsprofil eingefrorenen Geometrieproofs
   dürfen dadurch nicht ersetzt werden.

Das Stufenformat enthält dazu
already_in_published_bc7, already_in_published_bc7_count,
verified_cache_group_impacts und unverified_cache_groups.
Bei einem nicht nachgewiesenen Cache wird weiterhin **kein**
anwendbarer BC7-Bauauftrag erteilt.

### Echte lokale Gegenprobe an anim_castle 002

Im Produktionsstand sprite-suite-world-bc7-v2 wurde das Cacheobjekt
mit Key-Präfix **f069eb9187a0** ausgewählt, dessen Bundle-SHA-256
mit **73faca0ecb09** und dessen Atlas-SHA-256 mit
**1f6b2b9f25de** beginnt. Andere historische Cacheobjekte derselben
Spritegruppe hatten **abweichende** Bundle-/Atlas-SHA-256-Werte
und wurden ausdrücklich nicht als veröffentlichter Stand interpretiert.

Der zugehörige BC7-Atlasframe anim_castle 002 hat **333×165 Pixel**
und den Unity-Pivot **(0, 1)**. Genau dieser Wert steht bereits im
ausgelieferten Katalogindex und ist der Zielwert der dokumentierten
Zinnenlineal-Messung; eine neue Korrektur wäre falsch.
Die reinen PNG-/RGBA-Hashes des Katalogbildes können wegen
BC7-Dekodierung, Pixeltransformationen oder PNG-Serialisierung von den
im Atlas genannten Quell-RGBA-Hashes abweichen und werden deshalb
**nicht** ohne geprüfte Provenienz gleichgesetzt.

### Bedienung

- Im Werkzeug **Editor & Austausch → Pivot-Messungen prüfen**
  steht nach dem Laden eines verifizierten, ausgelieferten Frames der
  Schalter **Pivot im BC7-Atlas prüfen** bereit. Er liest den ganzen
  Build im Hintergrund und zeigt das veröffentlichte BC7-Ergebnis direkt
  neben der Vorher-/Nachher-Vorschau. Ist das Ziel bereits im BC7,
  wird eine neue Freigabe für diesen Frame deaktiviert.
- Der unabhängige **Nur-Lesen-CLI-Aufruf** benötigt keine
  Freigabeentscheidung und erzeugt keinen Bericht:

~~~powershell
.\.venv\Scripts\python.exe tools\qa_bc7_pivot_audit.py --profile sprite-suite-world-bc7-v2 --measurement "work\pivot-review-test-echt\zinnen-versatz.beispiel.json"
~~~

  Die genannte lokale Beispieldatei ist ausdrücklich eine **synthetische
  Dokumentationsmessung, kein echter gespeicherter Ingame-Messlauf**.
  Ihr Ergebnis lautet: ein Frame geprüft, einer im BC7 bereits richtig,
  kein Neubau und kein ungeklärter Frame.

### Weitere Sicherheitsgrenzen

- Ein Cacheobjekt ist nur Nachweis für den entsprechenden Build, nicht
  Autorisierung für einen neuen Bundle- oder Installationsvorgang.
- Die projected_cache_key-Werte unterscheiden geänderte
  Frame-Metadaten von unveränderten Pixeln. Der zukünftige echte Builder
  muss dennoch den frisch erzeugten Atlas, die vollständigen
  Geometrie- und Review-Quellen, alle Frame-/Qualitäts-Digests und den
  tatsächlichen BC7-Roundtrip unabhängig verifizieren.
- Fehlende Cacheprovenienz, unterschiedliche Atlas-/Bundle-Hashes,
  doppelte Frame-Namen und fremde Ausgangspivots werden niemals
  automatisch als schon korrigiert interpretiert.
- Tests:
  tests/sandbox/test_pivot_bc7_cache.py,
  tests/sandbox/test_pivot_bc7_review_gui.py,
  tests/sandbox/test_pivot_build_stage.py
  und der reale Windows-Hauptfenster-Smoke-Test.
