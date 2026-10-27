# Recherche, Portierungsmodell und Fallstricke

**Prüfstand: 29.09.2026.** Arbeitsgrundlagen waren die hochgeladene ODT-Vorlage, der Quellcode und das Beispielprojekt der Version 0.1 sowie öffentlich zugängliche Primärquellen. Es lagen keine extrahierten Originalserien, Spielinstallation oder verbindliche Zuordnungstabelle zwischen SHDE und SHCDE vor.

Dieser Bericht trennt dokumentierte Fremdformate von den Entscheidungen des Editors. Ein Name wie `body_target-0` in den Tests ist ein synthetischer Platzhalter, kein Rechercheergebnis zu einer realen Spiel-ID. Produktnamen allein belegen weder Dateiformat noch Kompatibilität bestimmter Asset-Bundles.

## 1. Nachprüfbare technische Grundlagen

| Gegenstand | Befund aus der Quelle | Konsequenz im Editor |
|---|---|---|
| Nutzer-Vorlage | Gebäude-Tiles bis 64 Pixel Breite, variable Höhe; Beispielnummerierung diagonal von vorn nach hinten. [U1] | Konfigurierbares isometrisches Raster; keine allgemeine Breitenbegrenzung aller Assettypen. |
| Einzelersatz | Exakte Sprite-Namen und passende Originalabmessungen sind erforderlich. [R1] | Zielzuordnung getrennt speichern; Einzelersatz ohne Dimensionsreferenz sperren. |
| Atlasersatz | Atlas-API experimentell; Pivots und Rechtecke beginnen unten links. [R1] | Export ausdrücklich auf den dokumentierten Erweiterungsweg beschränken; Koordinaten testen. |
| Masken/Material | `_m` ist materialrelevant, detaillierte Kanalbelegung nicht dokumentiert. [R1] | Kanäle erhalten und anzeigen, keine universelle automatische Maskengenerierung. |
| Auslieferung | Asset-only-Mods verwenden Manifest 0; `.semod` ist eine gepackte Modwurzel. [R2] | Keine ausführbare Mod-DLL erzeugen; unterschiedliche ZIP-/SEMOD-Wurzeln prüfen. |
| Extraktion | Sprite Previewer beschreibt die Rekonstruktion gepackter Unity-Sprites; AssetRipper extrahiert Unity-Assets. [R3, R4] | Mit sauber extrahierten Einzelbildern beginnen, nicht Mesh-Atlanten rechteckig erraten. |
| Unity-Sprite | Rechteck, normalisierter Pivot, Pixels-per-Unit und Mesh sind getrennte Parameter. [R5] | Größe, Verankerung und Quellmetadaten separat führen. Die zitierte Unity-Handbuchversion belegt keine SHCDE-Engineversion. |
| PNG | Straight Alpha, mehrere Farb-/Bittiefen, Filter, Adam7 und CRC sind Teil der Spezifikation. [R6] | Eigener Rohdaten-Codec; Originalbytes und Bearbeitungen trennen. |
| TexturePacker | Exporter können oben oder unten beginnen sowie Rotation, Trimming und Polygonpacking verwenden. [R7] | Pivot-Ursprung bei Bedarf ausdrücklich verlangen; nicht unterstützte Packing-Varianten ablehnen. |
| ZIP / ORA | ZIP besitzt unterschiedliche Kompressions- und Sicherheitsmerkmale; ORA spezifiziert Archiv- und Ebenenstruktur. [R8–R10] | Eingeschränkte, validierte ZIP-Untermenge; ORA-Ausgabe mit separaten Ebenen. |

## 2. Warum es keinen ungesicherten „Konvertieren“-Knopf gibt

**Implementierungsentscheidung:** Portierung wird als nachvollziehbare Zuordnung modelliert, nicht als Dateiumbenennung. Ein Quellframe hat Dateiname, Quellgruppe, Herkunft, Index, Pixel, Maske, Pivot und PPU. Sein SHCDE-Zielname wird separat zugewiesen und bestätigt. Für Einzelersatz werden Zielabmessungen benötigt; für Größen- und Materialabgleich sind zusätzliche Referenzinformationen sinnvoll.

**Nicht belegt:** Eine universelle Tabelle „SHDE-Index X entspricht SHCDE-Index Y“, eine automatisch gültige Footprint-Konfiguration für jedes Gebäude oder ein verlässlicher Standardablauf zum Entpacken aller SHDE-Versionen wurde aus den herangezogenen Quellen nicht gewonnen. Die Anwendung gibt solche Annahmen deshalb nicht als Fakten aus.

Ein formal gültiger Zielname verrät noch nicht die Bedeutung des Frames. Für eine belastbare Portierung müssen Perspektive, Bewegungsphase, Arbeitszustand, Rotationsrichtung, Gebäudeteil und gegebenenfalls Alternativzustände aus den Zielreferenzen hervorgehen. Dies ist eine logische Anforderung des gewählten Ersetzungsmodells, keine vom Editor entdeckte Gameplay-Datenbank. Das Vorschau-Animationsband ist eine Prüfhilfe, kein automatischer Re-Animator.

## 3. Gebäudegeometrie und Rückweg

Die ODT-Abbildung zeigt im 5×5-Fall horizontale Diagonalen mit 1, 2, 3, 4, 5, 4, 3, 2, 1 Rasterplätzen. Diese konkrete Reihenfolge wird getestet. Die Sprite-Höhe ist nicht gleich der Höhe der Bodenraute. Hintere Wände dürfen höher reichen und vorher gezeichnete Bereiche verdecken. [U1]

**Entscheidung:** Rasterplatz, Pixelversatz und Zeichenreihenfolge bleiben unabhängig. 64×32 und der untere mittige PNG-Anker sind Startwerte, keine behauptete Universalgeometrie beider Spiele. Pivots können stattdessen die Ankerbasis bilden.

**Informationsgrenze:** Beim Zusammenführen überlappender Ebenen wird aus mehreren möglichen Originalbelegungen dasselbe sichtbare Bild. Die Rückrechnung ist dann nicht eindeutig. Deshalb enthält das Projekt die Originale. Der Schnitt erzeugt neue, disjunkte Teilbilder; eine Rautenmaske allein wird nicht als Wiederherstellung verlorener Ebenen bezeichnet. Die manuelle Pixelzuordnung ist nötig, wenn ein Custom Asset nicht zur automatisch erzeugten Silhouette passt.

Bei zusammengesetzten Materialmasken kommt ein zweites Problem hinzu: Ein Kanalwert kann eine Shadergröße statt einer Deckkraft repräsentieren. Ein normaler Farb-Alpha-Compositor wäre dann keine begründete Zusammenführungsregel. Der Editor sperrt entsprechend die automatische Aufbau→Schnitt-Übernahme maskierter Gruppen, anstatt eine scheinbar korrekte Flachmaske zu erfinden.

## 4. Verankerung, Auflösung und Metadaten

**Editorvertrag:** Bearbeitungen arbeiten intern mit oben links beginnenden PNG-Pixelkoordinaten. Das Zielatlas-JSON verwendet unten links. Für ein oben beginnendes Rechteck `(x,y,w,h)` und die Atlas-Höhe `H` lautet die Umrechnung `y_ziel = H - y - h`. Der Pivot wird nicht noch einmal versehentlich invertiert, wenn er bereits im Zielkoordinatensystem vorliegt.

PPU und Pixelmaße werden getrennt gespeichert. Der Editor bietet beim Skalieren die gemeinsame Anpassung von Pixelmaßen und PPU an. Dies erhält das Verhältnis von Pixelmaß zu Weltmaß, abgesehen von notwendiger Ganzzahlrundung. Ein gleicher PPU-Wert allein garantiert keine passende Ausgangsgröße.

Unity-/AssetRipper-Metadaten dürfen Pivots liefern, auch wenn ein gepacktes Quellrechteck nicht sicher ausgeschnitten werden kann. Für den tatsächlichen Atlasimport akzeptiert der Editor nur rechteckige, ganzzahlige, nicht rotierte und nicht getrimmte Frames. Meshpacking und gebrochene Rechteckwerte werden nicht automatisch gerundet. TexturePacker-Pivotmetadaten ohne eindeutigen Ursprung erfordern eine Benutzereinstellung. [R5, R7]

Eine Beschneidung muss mehr als den sichtbaren Alphabereich berücksichtigen: Sie darf den Pivot nicht aus seinem normalisierten Wertebereich verschieben, keine Maskendaten verlieren und nicht den Bildstand im Gebäude versetzen. Diese Bedingungen sind sowohl in Geometrietests als auch über den Bedienablauf Trim→Originalzustand abgesichert.

## 5. Farben, Transparenz und Masken

PNG-Farbwerte werden vom Editor direkt aus dem Datenstrom dekodiert. Eine Canvas-Vorschau darf das Bild darstellen, ist aber nicht der Rücklesepfad für Exportpixel. Das verhindert, dass eine Vorschau-Rundung bei kleinen Alphawerten unbemerkt zur neuen Originaldatei wird. Die Tests enthalten Alpha 0, 1, 2, 3, 7, 31, 64, 127, 254 und 255 sowie RGB-Werte bei Alpha 0.

**Bewusste Formatgrenze:** Unterstützte PNGs werden als RGBA8 bearbeitet. 16-Bit-PNGs und APNG werden mit einer Fehlermeldung abgewiesen, nicht still auf 8 Bit oder den ersten Frame reduziert. Profile und Gamma-/Farbraumhinweise werden erkannt, aber nicht als vollständiges Farbmanagement interpretiert. Original-PNGs behalten ihre Bytes; neu erzeugte PNGs enthalten keine automatische Profilkonvertierung. Die visuelle Übereinstimmung zwischen Malprogramm, Browser und Spielshader bleibt separat zu prüfen. [R6]

**Konservative Prüfung:** Für ausdrücklich gewähltes TeamColour oder Foliage verlangt der Editor passende Masken auch im Einzelbildmodus. Das ist strenger als das in der Maintainer-Dokumentation beschriebene transparente Fallback beim Einzelersatz. Teilweise maskierte Atlasgruppen werden nicht mit geratenen Standardwerten aufgefüllt. [R1]

## 6. Ausgabeweg und verbleibende Installationsfragen

Der Editor schreibt ausschließlich neue Dateien. Sein Modexport ist eine vorbereitete Asset-Ausgabe für den Script Extender. Die Erweiterung und die passende Laufzeit müssen getrennt vorhanden sein. Gleichzeitige globale Ersetzungen können abhängig von der Ladefolge kollidieren; die App sieht die tatsächlich installierten anderen Mods nicht. Atlas-PNG ist für Iteration vorgesehen, DDS für die Veröffentlichung laut Maintainer empfohlen. DDS benötigt dort den dokumentierten Format-/Zeilenorientierungsweg; ein PNG darf nicht pauschal vorab gespiegelt werden. [R1, R2]

**Entscheidung:** Kein Download eines unbekannten Modloaders, keine Änderung fremder Installationsverzeichnisse, keine automatische Workshop-Veröffentlichung und kein Erzeugen von Unity-Bundles mit geratenen Versionsparametern. Die Anwendung definiert weder neue Einheiten noch Baukosten, Kollisionsflächen, Spielregeln oder Animationszustandsautomaten. Eine Asset-Ausgabe ersetzt keine solchen Gameplay-Definitionen.

Die genaue von einer Installation verwendete Script-Extender-/Spielversion ist nicht bekannt. Die Exportstruktur folgt den am angegebenen Datum gelesenen Dokumenten, nicht einer dauerhaft versprochenen API-Version. Native Unity-Bundles sind zudem kein bloßer Bildcontainer; ihre Referenzen und Abhängigkeiten erfordern einen getrennten, versionsbezogenen Workflow. [R11]

## 7. Risiko- und Prüfmatrix

| Beobachtung | Zu prüfende Ursache | Schutz oder Untersuchung |
|---|---|---|
| Falscher Gebäudeteil erscheint | Quellnummer als Zielnummer übernommen | Explizite Zielreferenz und Zuordnung; keine automatische ID-Übersetzung. |
| Sprite „schwimmt“ | Pivot, PPU oder transparenter Rand verändert | Pivotvergleich; gemeinsame PPU-Skalierung; trimbedingte Versatzkompensation. |
| Animation springt | Reihenfolge, Pivot oder Rolle einzelner Frames passt nicht | Gemeinsamer Anker, vorheriger Frame, Einzelschritt; anschließend Spieltest. |
| Helle/dunkle Säume | RGB/Alpha, Profil oder Randinterpolation | Rohkanäle und Originalvergleich; kein automatisches Premultiplizieren. |
| Teamfarbe/Vegetation fehlt | Maske oder Material ungeeignet | Maskenansicht, Größenprüfung, explizite Materialwahl; Referenz im Spiel prüfen. |
| Atlas erscheint gespiegelt | Koordinaten- oder DDS-Zeilenursprung falsch | Getrennte PNG-/Metadatenumrechnung; DDS extern nach zugehöriger Dokumentation. |
| Raster schneidet Überstände ab | Zu kleine oder falsch verankerte Schnittflächen | Verlängerte hintere Flächen, Pinsel, Zuordnungs- und Breitenprüfung. |
| Import halb übernommen | Fehler in einem Archiv oder PNG | Transaktionaler Import: kompletter Erfolg oder unveränderter Projektstand. |
| Export überschreibt falsche Dateien | Pfad-/Namenskollision | Kein Installationszugriff; sichere relative Archivpfade; Kollisionen blockieren. |
| Browser wird langsam | Große Pixelmengen oder viele Bearbeitungen | Pixelbudget, virtualisierte Liste, Historie leeren; keine unbegrenzte Leistung versprochen. |
| Andere Mod verschwindet optisch | Gemeinsame Zielpfade/Ladereihenfolge | Isolierte Testinstallation; eigene Mod-ID; Kollisionsprüfung außerhalb des Editors. |
| Prüfung zeigt 0 Fehler, Spielbild trotzdem falsch | Formale Regeln sind erfüllt, Semantik/Shader nicht | „0 Fehler“ nie als In-Game-Siegel verwenden; Prüfbericht kennzeichnet diesen Unterschied. |

## 8. Praktische Abnahme eines echten Ports

Zuerst die tatsächliche Quelle und die zu ersetzenden SHCDE-Referenzen sichern, einschließlich Extraktionsweg und verwendeter Versionen. Nur eine kleine, eindeutig zugeordnete Serie vorbereiten. Originale und bearbeitete Bilder vergleichen; bei Animationen jede relevante Richtung und Phase kontrollieren. Den Prüfbericht mit exportieren.

Das Ergebnis in einer getrennten, gesicherten Mod-Konfiguration mit der dazu passenden Erweiterung prüfen. Auf richtiger Größe, Verankerung, Schatten-/Transparenzrändern, Überlappungen, Materialmasken und nicht ersetzten Fallback-Frames bestehen. Andere Overrides derselben Zielgruppe für diesen Test ausschließen. Erst danach weitere Serien hinzufügen und gegebenenfalls den dokumentierten DDS-Schritt in ein eigenes Ausgabeverzeichnis durchführen.

Dieser Ablauf ist ein vorgeschlagenes Abnahmeverfahren, **kein bereits durchgeführter Spieltest**. Die beigepackten Beispiele enthalten keine Spielgrafiken. Das Herkunftsfeld dokumentiert Angaben des Bearbeiters, prüft aber keine Nutzungs- oder Weitergaberechte.

## Quellenverzeichnis

Alle Onlinequellen am 29.09.2026 eingesehen. Quelltexte oder ausführbare Fremdprogramme wurden nicht in die Anwendung eingebunden.

- **U1:** Nutzerdatei „Tool zum Zusammensetzen von Sprites.odt“, Seite 1, Text und nummeriertes 5×5-Bild.
- **R1:** SHCDE Script Extender, Maintainer-Dokumentation „Asset API“, insbesondere Sprite-/Atlas-Ersatz, Masken, DDS und Provider Modes. `https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html`
- **R2:** Derselbe Maintainer, „Mod Types Overview“. `https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html`
- **R3:** SHCDE Sprite Previewer, Projekt-README. `https://gitlab.com/rawra-stronghold-crusader/shcde-sprite-previewer/-/raw/main/README.md`
- **R4:** AssetRipper, Projekt-README. `https://github.com/AssetRipper/AssetRipper`
- **R5:** Unity, Scripting API „Sprite.Create“. `https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Sprite.Create.html`
- **R6:** W3C, PNG Specification, Third Edition. `https://www.w3.org/TR/png-3/`
- **R7:** CodeAndWeb, „TexturePacker Custom Data Format“, Exporterfähigkeiten und Koordinatenkonventionen. `https://www.codeandweb.com/texturepacker/documentation/custom-exporter`
- **R8:** PKWARE, ZIP APPNOTE. `https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT`
- **R9:** OpenRaster, File Layout Specification. `https://www.openraster.org/baseline/file-layout-spec.html`
- **R10:** OpenRaster, Layer Stack Specification. `https://www.openraster.org/baseline/layer-stack-spec.html`
- **R11:** Unity Manual, AssetBundle Dependencies. `https://docs.unity3d.com/Manual/AssetBundles-Dependencies.html`
- **R12:** MDN, DecompressionStream-Konstruktor; Unterscheidung zlib/deflate und raw deflate. `https://developer.mozilla.org/en-US/docs/Web/API/DecompressionStream/DecompressionStream`

Zur historischen Abgrenzung wurde außerdem die Sourcehold-GM1-Beschreibung geprüft: `https://github.com/sourcehold/Sourcehold/wiki/Gm1-file`. Sie dient ausdrücklich nicht als Binärspezifikation eines DE-PNG- oder Unity-Assetimports.
