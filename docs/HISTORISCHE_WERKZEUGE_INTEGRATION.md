# Integration der historischen Zinnen- und QA-Werkzeuge

**Stand:** 2026-10-11. Branch: `feature/sandbox-studio`.
Basis: autorisierte lokale Projekte, überprüfte C#-Quelldatei
`Zinnenlineal/src/Ablage.cs` und historisches `E:\SS QA`.

## 1. Pivot-Vermessung (bereits als Teil der Sprite Suite eingebaut)

Unter **Suite starten.cmd → Editor & Austausch → Pivot-Messungen prüfen …**
öffnet sich der neue Messprüfer als Werkzeugfenster im selben Prozess.

1. Die echte Datei `<Spielordner>/Zinnenlineal/zinnen-versatz.json` wählen.
   Solange das Zinnenlineal nicht eingesetzt wurde, ist kein Messlauf
   verfügbar; die Suite installiert das Plugin **nicht automatisch**.
2. Aus einer überprüften Messdatei werden Name, Frame-Nr., Bildgröße,
   Ausgangspivot, rechts/hoch-Versatz und vorgeschlagener Pivot
   **ohne Dateiveränderung** übernommen.
3. Die Suite sucht passende PNGs **zuerst im ausgelieferten Stand**,
   danach im Crusader-Original und schließlich in der Arbeitskopie.
   Gemessene Bildgröße und tatsächlich lesbare PNG-Geometrie werden
   gegengeprüft, ebenso die Pivot-Gleichung
   `neu_pivot_x = pivot_x − rechts / breite` und
   `neu_pivot_y = pivot_y − hoch / hoehe`.
4. Der Vergleich unterscheidet **Bereits passend**, **Korrektur prüfen**,
   **Bildgröße abweichend**, **Pivot/Referenz abweichend** sowie
   **Frame nicht gefunden**. Eine Abweichung der Ausgangswerte wird
   **nicht** stillschweigend auf eine andere Atlasfassung übertragen.
5. Vorher/Nachher stellt dieselben Pixel am gleichen gelben **Weltanker**
   dar, unter Berücksichtigung des Unity-Pivots. Aus den Einträgen
   kannst du den aktuellen Frame im Asset-Katalog bzw. Sandkasten öffnen.
6. **Prüfbericht exportieren** legt eine versionsgebundene,
   SHA-256-dokumentierte JSON-Auswertung unter
   `work/reports/pivot-review/` ab. Messdatei, PNG und der zugehörige
   Sprite-Index werden gehasht. Wenn sich eine dieser Quellen seit der
   Vorschau geändert hat, wird der Export verweigert.
   **Die Grafik, der Atlasindex und die Spielinstallation bleiben unverändert.**
7. **Nach Sichtprüfung freigeben / Vorschlag ablehnen** dokumentiert eine
   ausdrückliche Entscheidung pro Sprite. Der Freigabeknopf ist nur bei
   **Korrektur prüfen** mit passendem Ausgangspivot und tatsächlich
   **ausgelieferter** Quelle aktiv. Die Freigabe erfordert eine gesonderte
   Bestätigung; **Bereits passend** kann niemals nochmals freigegeben werden.
   Alle anderen Vorschläge bleiben **zurückgestellt**, bis sie aktiv geprüft
   oder abgelehnt wurden. **Entscheidung zurücksetzen** ist möglich.
8. **Freigabeprotokoll exportieren** speichert die geprüften Frames samt
   ausdrücklichen Entscheidungen (sonst zurückgestellt bzw. bereits passend)
   in einem inhaltsadressierten JSON-Protokoll
   `stronghold-europe.pivot-approval.v1` unter
   `work/reports/pivot-approval/`. Es enthält den genauen alten und neuen
   Pivot, die Messwerte, Quelle, drei SHA-256-Prüfsummen sowie den Zeitpunkt
   der Entscheidung. Beim Export werden alle Quellen erneut gelesen und
   mit dem Stand bei der Vorschau verglichen; bei Änderungen lautet die
   Antwort **neu laden**, nicht stillschweigend überschreiben.
   Auch ein freigegebenes Protokoll verändert **keinen** Sprite, Index,
   Atlas oder Spielstand. Ein möglicher künftiger Einspieler benötigt einen
   eigenen Freigabe-/Releasevertrag und muss die Hashes erneut prüfen.

### Wichtiger nachgeprüfter Fall

Für die dokumentierte Zinnenlineal-Messung an `anim_castle 002`
(333×165, `hoch = 18`, `pivot_y = 1,109091`,
`neu_pivot_y = 1,0`) wurde mit dem tatsächlich lokal
**ausgelieferten** `anim_castle 002.png`/Index gegengeprüft.
Ergebnis: **Bereits passend**, denn der ausgelieferte Pivot ist
schon `(0,1)`. Eine automatisierte Übernahme wäre fehlerhaft;
**der neue Freigabeknopf ist für diesen Eintrag deaktiviert**.

Prüfbericht und Freigabeprotokoll sind ausschließlich **prüfende
Metadaten**; sie sind weder ein Atlas-Patch noch eine Spielinstallation.
Die aktuelle Änderungs-/BC7-Baupipeline bewertet primär
**veränderte PNG-Pixel** und behandelt eine allein geänderte
Index-Pivotmetadatei noch nicht vollständig als Atlasänderung.
Deshalb gibt es **noch keinen** Knopf, der ohne geprüften
Releasevertrag sofort Pivots ins ausgelieferte Spiel schreibt.

## 2. QA-Altbestand ermitteln (neu in der Diagnose)

Unter **Diagnose & Reparatur → QA-Altbestand vergleichen …** den
Quell-Projektordner, beispielsweise einen älteren Sprite-Suite-Stand,
wählen. Die Liste erscheint in der vorhandenen Diagnose-Tabelle:

- **nur im Altbestand**, **bereits identisch**,
  **abweichende Version** oder **nicht gefunden**;
- SHA-256-Identität, Funktion, Risikostufe und Anpassungshinweise;
- historische und aktuelle Python-Testmodulanzahl;
- reproduzierbarer Bericht unter `work/reports/qa-inventory/`.

Die Inventur liest ausschließlich die existierenden Dateisystemeinträge.
Es gibt keinen versteckten Python-/PowerShell-Start, keine DLL-Installation,
keinen Kopiervorgang und keine Änderungen an Spielbibliotheken.
Doppelklick auf einen Altwerkzeugeintrag kann diesen ausdrücklich
**nicht** als Spritegruppe öffnen oder ein Programm ausführen.

### Reales Ergebnis aus E:\SS QA

- **122** historische Testmodule in `E:\SS QA\tests`;
  der aktuelle `E:\SpriteSuite\tests`-Bestand hatte bei
  dieser Messung **35 Testmodule** (Tests als Dateien, nicht Testfälle).
- Zehn namentlich gesuchte Altprogramme sind in der älteren
  QA-Werkzeugablage vorhanden, aber nicht im aktuellen
  `E:\SpriteSuite\tools`.
- RAM-Protokolle, Full152-Ingame-Abnahme, Asset-Streaming-Kanarie und
  native Auswahl-/Disassemblierungsprobe sind **versionsgebunden**.
- `runtime_install.py`, `install_manifest_abgleichen.py`,
  `system_workflows.py` und `shcdese_install.py` können
  Installations-/Laufzeit-/Nachweisdateien beeinflussen und
  sind daher **schreibend** klassifiziert.

Die Inventur ist die Sicherheitsstufe vor einer möglichen späteren
Übernahme einzelner Prüffunktionen. **Alte Full152-Hardpins können nicht
automatisch als Nachweis für den aktuellen Build gelten.**

## 3. Bereits integrierte und weitere Kandidaten

**Bereits in Sprite Suite:** Sprite-/Pixel-Editor, AtlasBuilder,
OpenRaster-Gebäudeobjekte, der vorhandene Einheiten-Produktionskern,
Hintergrundmasken- und Vergleichswerkzeuge sowie die native
Stronghold-Engine-Sandbox. Diese werden nicht als neue Tools dupliziert.

**Inzwischen zusätzlich eingebaut:** Der
[Pivot-BC7-Stufenentwurf](PIVOT_BC7_STUFENPLAN.md) verbindet die
ausdrücklich bestätigte Messung mit einem vollständig verifizierten
Produktionsstand und zeigt die konkreten betroffenen Gruppen/Bundles.
Die tatsächlichen veröffentlichten Cache-Atlanten werden nur bei
SHA-256-Übereinstimmung mit Bundle und Atlasindex als Quelle akzeptiert.
Schon im BC7 korrekte Pivots werden ausgeschlossen; für übrige wird
der geänderte Cache-Key **ausschließlich projiziert**.
Er ist **nicht direkt anwendbar** und verändert keine Profil- oder
Spieldateien. Ein sicherer späterer Meta-Pivot-Builder muss noch
den kompletten Unity- und Cache-/Geometrieproofvertrag erfüllen.

**Weitere sinnvolle Schritte, noch nicht eingebaut:**

- **EuropaWerkstatt:** zuerst ausschließlich importierte JSON-/Logberichte
  unter `_SE_PERSISTENT` auswerten, Versionspins und Sonde-/Tasten-
  Kollisionen prüfen; keine automatische Plugin-Installation.
- **Projektweiter Release-Abgleich (nun integriert):** Der neue
  [SHA-256-Preflight](RELEASE_PREFLIGHT.md) prüft das vorhandene
  Ausgabemanifest mit allen BC7-Dateien, Profil und Bundleindex sowie
  optional ein ausdrücklich gewähltes Pivot-Freigabeprotokoll.
  Die [native Mapping- und Geometrie-Provenienzprüfung](PIVOT_NATIVE_PROVENANCE.md)
  rekonstruiert inzwischen zusätzlich alle 95 SH1DE- und elf
  beibehaltenen Crusader-Frames der produzierten anim_castle-Gruppe
  mit den vorhandenen unveränderten Geometrie-, Herkunfts-,
  Quell-RGBA- und Review-Digests.
  **Weiterhin offen:** Versionsunabhängige RAM-/Ingame-Tests aus alten
  QA-Ständen neu prüfen und portieren; historische Hardpins niemals als
  Nachweis für einen aktuellen Build übernehmen.
- **Einheiteneditor:** den bereits vorhandenen
  `tools/unit_pipeline.py`-Manifestworkflow als GUI-Assistenten
  innerhalb von `Editor & Austausch` ansprechbar machen.
- **Karten-/Szenarioanalyse:** `StrongholdOrigins/tools/scan-maps.py`
  und die Startburgprüfung nur lesend und versionsgeprüft adaptieren.

## 4. Abnahme / Grenzen

`tests/sandbox/test_pivot_measurements.py` prüft das offizielle
Messschema, Identitäts-/Formelprüfung, Grenzwerte, Größenmismatch,
schädliche PNG-Pfade, Vorher/Nachher-Bild, unveränderte Arbeits-/Spiel-
Ressourcen und die Tk-Oberfläche.

`tests/sandbox/test_pivot_approvals.py` prüft die bestätigungspflichtige
Einzelentscheidung, Herkunft und SHA-256 von ausgeliefertem Index/PNG,
veraltete Mess- und Indexstände, geänderte Bildpixel, doppelte Frame-Namen,
Sperre für bereits korrekte/fremde Quellen, die Tk-Freigabe und den
nicht-schreibenden Export samt Wiederholbarkeit.

`tests/sandbox/test_qa_inventory.py` und
`tests/sandbox/test_integrated_extra_tools.py` prüfen
Quell-/Zielversionen, SHA-Identität, Risikokennzeichnung, Unveränderlichkeit,
reproduzierbare Berichtsausgabe und die Bedienung aus
**Editor & Austausch** beziehungsweise **Diagnose & Reparatur**.

**Diese Runde enthält keine ungefragte externe Toolinstallation
und keine automatischen Mod- oder Atlasänderungen.**
