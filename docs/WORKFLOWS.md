# Aktuelle Arbeitsabläufe in SpriteSuite

**Stand: neuer Main-Quellstand, 8. November 2026.** Die neuen PNG/XAML- und
Startseiten-Chat-Funktionen beziehen sich auf diesen Quellstand; ältere
RC4-Downloadpakete enthalten sie noch nicht. Die folgenden Wege
beziehen sich auf die deutsche Oberfläche. Einrichtung und Erststart stehen
in der [Kurzanleitung](KURZANLEITUNG.md). Die frühere CLI- und
Produktionsanleitung bleibt vollständig im
[historischen Archiv bis 7. November 2026](WORKFLOWS_HISTORISCH_BIS_20261107.md).

## Den passenden Bereich öffnen

`Suite starten.cmd` öffnet die Suite. Mit **Strg+K** beziehungsweise
**Suche (Strg+K)** nach einem Bereich suchen und den passenden Treffer
öffnen. Das ist besonders bei Fachseiten hilfreich, die nicht als eigener
Reiter in der kompakten Seitenleiste sichtbar sind. Die Suche navigiert;
sie startet keinen Export oder Build.

| Aufgabe | Einstieg und nächster Schritt |
| --- | --- |
| Eigene Bilder und Mod-Dateien als gemeinsames Projekt bearbeiten | **Mein Mod-Projekt**. Dateien hinzufügen, bearbeiten, prüfen und ein Modpaket oder eine bearbeitbare Projektsicherung erzeugen. [Kurzanleitung](KURZANLEITUNG.md) |
| Eigenen Masteratlas mit XAML öffnen, Ausschnitte ersetzen oder SH1-Grafik übertragen | **UI-Atlas · PNG + XAML**. Ziel-PNG und zugehöriges XAML wählen, dann eine Ersatz-PNG oder einen Ausschnitt aus einem zweiten Atlas zuordnen. [Atlas-Anleitung](UI_ATLAS_PNG_XAML.md) |
| Originale Noesis-UI-Ausschnitte aus einer eigenen Spielinstallation exportieren | **Oberfläche**. Das zum Spiel passende Unterregister wählen; dieser alternative Exportweg folgt unten. |
| Eigene Menügrafik gestalten oder mehrere Bilder frei anordnen | **HUD & Menüs**. Arbeitskopien importieren und im Layout-Designer zusammensetzen. [HUD-/Menüwerkstatt](HUD_MENU_WERKSTATT_2026-10-28.md), [Layout-Designer](HUD_MENU_LAYOUT_DESIGNER_2026-10-28.md) |
| Vorhandene Spiel-Spritegruppen exportieren und prüfen | **Sprites bearbeiten**. Die gewünschte Gruppe und Quelle bestimmen; Metadaten und gegebenenfalls Farbmaske zusammen mit den Bildern erhalten. |
| Sprites, Pivot, Messdaten, Animationen, Schnittbild oder Atlas bearbeiten | **Editor & Austausch**. **Editor oeffnen** startet den gemeinsamen Sprite-Editor; **Gemeinsamen Geometrie-Editor öffnen** öffnet dessen Geometriebereich. [Editor-Anleitung](../extras/sprite-editor/dokumentation/ANLEITUNG.md) |
| Grafikvarianten oder Gebäudeschäden mit Bildreferenz erstellen | **Editor & Austausch → KI-Werkstatt**. Im gemeinsamen Editor Original und Aufgabe wählen, Kandidaten laden und die gewünschte Version übernehmen. [KI-Ablauf](SPRITESUITE_KI_CHATGPT_KONSOLIDIERUNG_20261108.md) |
| Fragen stellen, Suite-Aufträge erledigen oder eigene Projektdateien programmieren | Den Chat auf der **Startseite** oder über **KI-Assistent** öffnen und **Mit ChatGPT anmelden**. **Aufträge (alle Werkzeuge)** ist direkt nutzbar, einschließlich eigener Programmierung; **Optionen ▸** bietet freiwillige Anpassungen. [Chat-Anleitung](KI_CHAT_STARTSEITE.md) |
| Missionen, AIV, Balancing, Audio oder SDK-/Native-Entwürfe bearbeiten | Oben **Modding Studio** öffnen; die zwölf Bereiche arbeiten mit dem aktuellen Projekt. Weitere SHCDE-Fachwerkzeuge stehen unter **Alle Werkzeuge**. [Modding Studio](MODDING_STUDIO_3.md), [SHCDE-Fachwerkzeuge](SHCDE_TOOLS_ANLEITUNG_20261108.md) |
| Eine Szene, Karte oder Animation in der eingebetteten Arbeitsumgebung ansehen | **Sandkasten**. Benötigte eigene Quellen laden; die Sandbox-Vorschau ist eine eigene Prüfung und keine Abnahme im laufenden Spiel. |
| Spielpfade, Werkzeuge oder Kompatibilitätsbefunde prüfen | **Einrichten** beziehungsweise **Diagnose & Reparatur**. Erst die tatsächlich verwendete Installation und verfügbare Werkzeuge klären. |

Die Fachseiten haben unterschiedliche Eingabeformate. Für ein vorhandenes
Atlas-PNG mit passendem XAML den freien Atlas-Arbeitsbereich verwenden. Ein
allgemeiner Bildimport oder ein Sprite-Atlas im HTML-Editor erzeugt noch keine
Zuordnung zu den Noesis-Ressourcenschlüsseln.

<a id="6-ui-atlanten-und-ui-bc7"></a>
## UI-Masteratlas aus PNG und XAML bearbeiten

Der direkte Weg ist **Strg+K → UI-Atlas · PNG + XAML**. Alternativ unter
**Projekt & Dateien → Mehr → UI-Atlas (PNG + XAML)…** oder auf der älteren
Seite **Oberfläche → PNG + XAML öffnen…** öffnen. Dafür sind keine
eingerichtete Spielinstallation und kein vorheriger Suite-Export nötig.

1. Unter **1 · Zielatlas** die eigene **Atlas-PNG** und die dazugehörige
   **Atlas-XAML** auswählen, dann **PNG + XAML als Arbeitsstand öffnen**.
   Der Arbeitsstand erhält unveränderte Quellkopien und eine Liste der
   `ResourceKey`-Einträge mit ihren Rechtecken. Bei abweichendem PNG-Dateinamen
   oder mehrdeutiger Zuordnung vorher den tatsächlichen
   **BitmapImage-Key (optional)** aus dem XAML angeben.
2. Den zu ersetzenden Zieleintrag wählen. Für einen Transfer unter
   **2 · Quellatlas oder Ersatz-PNG** ein zweites PNG/XAML-Paar öffnen,
   etwa den SH1-Atlas, und dort den gewünschten Quellausschnitt wählen.
   Alternativ **Aus einzelner Ersatz-PNG** verwenden.
3. **Größenanpassung** prüfen. `exact` verlangt gleiche Abmessungen;
   `contain` passt mit transparentem Rand ein; `stretch` streckt auf das
   Zielrechteck. **Auswahl ersetzen** schreibt die Änderung in den
   Arbeitsstand. **Rückgängig**, **Wiederholen** und **Original
   wiederherstellen** stehen für die gespeicherten Bearbeitungsschritte bereit.
4. **Aktuellen Ausschnitt als PNG exportieren …** erzeugt eine einzelne
   Arbeitsgrafik, **Aktuellen Atlas als PNG exportieren …** das vollständige
   Blatt in Originalgröße. Der Export benötigt einen neuen Dateinamen.
5. Für die Verwendung im aktuellen Mod-Projekt **Ins Mod-Projekt übernehmen**
   wählen. PNG und unverändertes Ziel-XAML gelangen gemeinsam unter
   `Override/Assets/GUI/Sprites` in das Projekt. Anschließend dort
   **Geprüftes Mod-ZIP bauen** oder **Mod-ZIP speichern unter…** verwenden.
   Die Spielinstallation wird dadurch nicht ersetzt.

Die Zuordnung stammt aus `BitmapImage` und `CroppedBitmap`/`SourceRect` im
passenden XAML; beliebiger XAML-Oberflächencode genügt nicht. Der Transfer
ersetzt Pixel im gewählten Zielrechteck und erhält dessen Koordinaten und
Ressourcenschlüssel. Er überträgt keine SH1-Menülogik nach Crusader.
Die Vorschau ist verkleinert, die exportierten Pixel bleiben in Atlasgröße.
Ein vollständiger 8192-×-8192-Master liegt im eigenen Pixelbudget dieses
Werkzeugs. Die niedrigeren Importgrenzen anderer Editoren sind dafür nicht
maßgeblich. Größen, Transparenz, Arbeitsstände und Wiederöffnen erläutert die
[PNG/XAML-Atlas-Anleitung](UI_ATLAS_PNG_XAML.md).

### Alternative: UI-Ressourcen aus der Spielinstallation exportieren

Die ältere Seite **Oberfläche** bleibt für die quellgebundenen Spiel-Exporte
verfügbar. Ihr Knopf **Bilder laden** lädt einen **Exportordner mit
`index.json` und den zugehörigen Einzel-PNGs**. Für ein selbst vorliegendes
PNG/XAML-Paar stattdessen den neuen Atlas-Arbeitsbereich oben verwenden.

| Spiel | Quelle des passenden Exports | Standard-Arbeitsordner |
| --- | --- | --- |
| **Stronghold Crusader: Definitive Edition (SHCDE)** | Die in der Suite konfigurierte, fingerprint-geprüfte Spielinstallation: deren `globalgamemanagers.assets` und die installierten Script-Extender-XAML-Wörterbücher unter `BepInEx/plugins/000shcdese/Override/Assets/GUI/Sprites` | `work/ui` |
| **Stronghold: Definitive Edition (SH1DE)** | Die ausdrücklich ausgewählte eigene `Stronghold 1 Definitive Edition_Data/globalgamemanagers.assets`; Original-XAML und Texturen werden aus dieser Datei gelesen | `work/sh1-hud-editierbar` |
| **Klassisches Stronghold 1** | Kein Unity-DE-Asset und kein Export dieses SH1DE-HUD-Wegs | Dafür die passenden älteren Formatwerkzeuge verwenden; klassische Ressourcen nicht als SH1DE-Quelle auswählen. |

### Spiel-Export für Crusader DE: UI-MasterAtlas

1. **Strg+K → Oberfläche** öffnen. Im Unterregister
   **Crusader DE · UI-Atlas** bei **Blatt:** `UI-MasterAtlas` wählen.
   **Blätter auflisten** kann die verfügbaren Dictionaries auflisten.
2. **Exportieren** anklicken. Der Knopf verwendet die konfigurierte
   SHCDE-Installation und erzeugt in dieser Oberfläche den Arbeitsordner
   **`work/ui`**. Die Rechtecke und Ressourcennamen stammen aus dem
   passenden SE-XAML; die Pixel aus dem zugehörigen Spielatlas.
   Ein fehlender SE-XAML-Ordner oder eine nicht passende Quelle muss
   zuerst behoben werden. Dieser Spiel-Export verwendet weiterhin seine
   geprüften Originalquellen.
3. Nach erfolgreichem Export wird dieser Ordner automatisch geladen.
   Zum späteren Wiederöffnen **Arbeitsordner:** auf den Exportordner
   setzen oder mit **…** auswählen, dann **Bilder laden**.
   Gemeint ist der Ordner, der `index.json` enthält, nicht nur sein
   Unterordner `UI-MasterAtlas` und nicht das ganze Atlas-PNG.
4. Links unter **Filter:** nach dem Ressourcenschlüssel suchen und einen
   Ausschnitt auswählen. **Crusader-PNG extern bearbeiten** öffnet
   dessen Arbeits-PNG über die Windows-Dateizuordnung. Startet dadurch
   nur ein Bildbetrachter, dieselbe Arbeits-PNG gezielt im gewünschten
   Malprogramm öffnen. Die Suite wählt hier keinen bestimmten externen
   Editor. Dateiname, Pixelabmessungen und Exportindex erhalten.
5. Die Änderung in dieser PNG speichern. Anschließend **Bilder laden**
   und **Alles prüfen** verwenden. Der Prüfer vergleicht auch die
   Original-Unity-/XAML-Nachweise; eine angezeigte Vorschau allein ist
   noch kein bestandener Rückbaucheck.
6. Für eine separate lokale Atlasausgabe **Lose Testausgabe** verwenden.
   Sie baut nach Prüfung nach `dist/ui-override` zurück. Die installierte
   Spieldatei wird dadurch nicht ersetzt. Die Übernahme ins Spiel und
   die sichtbare Darstellung dort sind eigene Schritte.

**Arbeitsstand behalten:** Ein erneuter Export nach `work/ui` kann dortige
Bildbearbeitungen ersetzen und fragt deshalb bei vorhandenem Inhalt nach.
Vor einem erneuten Export den bisherigen Arbeitsordner sichern. Das Feld
**Arbeitsordner:** bestimmt den geladenen Export; es ändert das feste
Ausgabeziel dieses **Exportieren**-Knopfs nicht.

**Produktionsweg für erfahrene Nutzer:** **1. Geprüft übernehmen** schreibt
in die bezeichnete lokale Ablage unter `assets/ui/derived`. **2. Ins
Produktionsprofil** trägt diese Ablage ausdrücklich in
`profiles/europe-production.json` ein. **Profilabschnitt nur zeigen**
zeigt den Eintrag zunächst an. Diese Aktionen sind kein beliebiger
Projekt-PNG-Import und keine automatische Installation. Die aus dem Spiel
abgeleiteten Atlasblätter bleiben lokale Arbeitsdaten.

### Spiel-Export für Stronghold 1 DE: eigene Original-HUD-Basis

1. Unter **Oberfläche** das Unterregister **Stronghold 1 DE · HUD**
   auswählen. **1. Original-HUD exportieren** öffnen und die originale
   `globalgamemanagers.assets` der eigenen **Definitive Edition** wählen.
2. Der Export erzeugt `work/sh1-hud-editierbar` mit `index.json`,
   `sh1_hud_source.json`, den benannten Einzel-PNGs und einer
   **`baseline` mit Originalatlanten und Original-XAML**. Diese XAML-Daten
   werden aus SH1DE selbst extrahiert; hier wird kein Crusader-SE-XAML
   als Ersatz gewählt. Baseline und Herkunftsdateien zusammen erhalten.
3. Nach erfolgreichem Export wird das Projekt geladen. Später
   **2. SH1-HUD laden** verwenden. Eine vollständige exportierte
   Ordnerkopie lässt sich auch über **Arbeitsordner:** und **Bilder laden**
   ansehen; für den Editorweg dieser Seite den vorgesehenen
   Arbeitsordner `work/sh1-hud-editierbar` benutzen.
4. Einen benannten Ausschnitt auswählen und **3. Gewähltes Bild
   bearbeiten** öffnen. Der SH1-HUD-Pixeleditor bearbeitet die ausgewählte
   Arbeitskopie, nicht den vollständigen Masteratlas. Die Größe bleibt
   fest; **Speichern (Strg+S)** sichert diese PNG. Sehr große
   Einzelelemente über zwei Millionen Pixel werden vom Editor abgelehnt.
5. **4. SH1-HUD prüfen**, anschließend **5. SH1-HUD-Atlanten bauen**.
   Die Atlasausgabe liegt unter `dist/sh1-hud-editierte-atlanten`.
   Das erzeugt PNG-Blätter und Prüfdaten, aber noch keinen Einbau ins Spiel.
6. Optional erzeugt **6. Geprüfte Unity-Kopie erzeugen** einen getrennten,
   gegen die Originalquelle geprüften Unity-Kandidaten unter `dist`.
   Die installierte Quelle wird nicht überschrieben. Dieser Kandidat
   ist keine bestätigte Ingame-Abnahme.

Die ursprüngliche SH1DE-Basis hat `UI-MasterAtlas` mit **8192 × 4096**,
`UI-ROL` mit **4096 × 4096** und `UI-CandleAtlas` mit **2048 × 4096** Pixeln.
Ein SH1DE-Export mit geändertem oder fehlendem Baseline-XAML lässt sich
nicht durch Umbenennen in einen Crusader-Export verwandeln.

Als weitere Oberfläche steht **SH1 HUD-Studio** über Strg+K bereit:
**Aus Spiel exportieren ...** beziehungsweise **Laden**, dann
**Bild bearbeiten**. Auch dieses Studio verwendet den quellgebundenen
SH1DE-Export. [SH1DE-HUD-Vertrag](STRONGHOLD1_HUD_SPRITESUITE.md),
[Unity-Kandidat und Grenzen](STRONGHOLD1_UNITY_HUD_KANDIDAT.md).

### Vorhandene SH1- und Crusader-Exportordner direkt verbinden

Im SH1-Unterregister der Seite **Oberfläche** lässt sich das Fenster für die
SH1→Crusader-Übertragung öffnen. Dort **SH1-HUD-Exportordner** und
**Crusader-UI-Zielexport** wählen, einen neuen **Mapping-Plan** angeben und
**Mapping vorschlagen** verwenden. Einen vorhandenen Plan mit **Plan
öffnen/neu lesen** laden.

In der Zuordnungsliste mehrere Zeilen mit Strg/Shift oder **Alle sichtbaren
auswählen** markieren. Unter **Maßregel für die Auswahl** `exact`, `contain`
oder `stretch` wählen und **Auswahl übertragen** anklicken. Eine andere
Verbindung lässt sich mit **SH1-Quelle**, **Crusader-Ziel** und **Zuordnung
übernehmen** anlegen und anschließend in der Liste auswählen. Der Transfer
benötigt weder eine Mindestbegründung noch eine Qualitätsfreigabe.

Die Ausgabe ist ein neuer SHCDE-Exportordner. Ursprüngliche Quell-/Zielordner
und nicht übertragene Zielbilder bleiben erhalten; das Zielraster stammt
weiter aus seinem Index. **Originalquellen zusätzlich prüfen** ist eine
standardmäßig ausgeschaltete Zusatzoption. Nur für diese gewünschte Prüfung
werden die drei Originalpfade gebraucht. Zum normalen Kopieren reichen die
vollständigen Exportordner. Für ein freies PNG/XAML-Paar ohne solche
Exportordner den primären Atlasweg oben verwenden.

### Ganze Masterblätter und andere Editoren

Ein PNG/XAML-Paar kann direkt im oben beschriebenen Atlas-Arbeitsbereich
geöffnet werden. Ein PNG ohne passende Rechteckbeschreibung lässt sich
dadurch noch nicht in benannte UI-Einträge zerlegen. Kleinere freie PNGs
können weiterhin unter **HUD & Menüs** bearbeitet werden. Die Formate und
Einzelbildgrenzen der verschiedenen Werkzeuge bleiben unterschiedlich:

| Weg | Grenze beziehungsweise Mastergröße |
| --- | --- |
| PNG/XAML-Atlas-Arbeitsbereich | höchstens **134.217.728 Pixel** pro PNG; Änderungen als Ausschnitt-Ersetzungen |
| Allgemeiner Bildimport der HUD-/Menüwerkstatt | höchstens **30.000.000 Pixel** pro Bild |
| Gemeinsamer HTML-Sprite-Editor | höchstens **16.777.216 Pixel** pro Einzelbild; zusätzlich ein gesamtes Bildbudget |
| SHCDE `UI-MasterAtlas` | **8192 × 8192 = 67.108.864 Pixel**, im Atlas-Arbeitsbereich unterstützt, über den HUD-/HTML-Einzelbildgrenzen |
| SH1DE `UI-MasterAtlas` | **8192 × 4096 = 33.554.432 Pixel**, im Atlas-Arbeitsbereich unterstützt, ebenfalls über den HUD-/HTML-Grenzen |

Der neue Atlasweg verarbeitet die genannten Mastergrößen, bietet aber keinen
Ganzblatt-Malpinsel. Einen Ausschnitt exportieren, im Bildeditor bearbeiten
und wieder zuordnen, oder direkt aus einem zweiten Atlas übertragen.
Den Master zur Umgehung einer fremden Editorgrenze zu verkleinern würde
seine Pixelkoordinaten und damit den ursprünglichen XAML-Vertrag verändern.

## Weitere Arbeitsabläufe und ihre Grenzen

**Freie Grafik und Layout:** Unter **HUD & Menüs** eigene Bilder als
Arbeitskopien importieren, bearbeiten und im Layout-Designer positionieren.
Der Layout-Export erzeugt eine zusammengesetzte PNG und Positionsdaten.
Ein tatsächliches Spielmenü benötigt weiterhin seine passende
Noesis-/XAML-Anbindung. [Spieloberfläche anbinden](NOESIS_HUD_MENU_SPIELANBINDUNG_2026-10-28.md).

**Sprites und mehrteilige Gebäude:** Den passenden Original-/Arbeitsbestand
unter **Sprites bearbeiten** auswählen. Unter **Editor & Austausch**
verbindet **Fuer Editor verpacken** die gewählte Gruppe beziehungsweise
den Bereich mit dem HTML-Editor; **Ergebnis zurueckholen ...** führt zum
Rückweg. Für vorhandene Kachelobjekte gibt es dort **Als ORA zusammensetzen**
und **ORA zuruecknehmen ...**. Quellraster, Masken, Pivots und Zielnamen
müssen zum gewählten Verfahren passen; ein Bild allein ersetzt diese
Metadaten nicht.

**KI und Varianten:** Die **KI-Werkstatt** verwendet Originalreferenz und
Prompt. Kontoanmeldung erfolgt über die lokale Codex-/ChatGPT-Sitzung,
ohne API-Schlüssel. Rohbilder und registrierte Kandidaten sind von der
manuellen Übernahme getrennt. Bei Gebäudeschäden bleiben Art, Stufen,
Geometrie und gewünschte Änderungen Teil des Auftrags. Ein erzeugter
Kandidat ist noch kein bestätigter Spritewechsel im Spiel.

**Assistent und Fachmodule:** Der Startseiten-Chat startet mit
**Aufträge (alle Werkzeuge)**. Dieser Modus umfasst die vorhandenen
Projekt-, GUI-, Fach- und Codewerkzeuge einschließlich eigener Programmierung.
**Programmieren (Projektdateien)** ist eine optionale Arbeitsausrichtung;
**Fragen (nur lesen)** beschränkt auf lesende Funktionen. **Lokalen
Pythonlauf erlauben** ist zunächst eingeschaltet und kann zum Begrenzen
solcher Läufe ausgeschaltet werden. Ein Python-Prozess besitzt normale
Benutzerrechte, keine Betriebssystem-Sandbox. Modelle und Denkstufen stammen aus dem Konto,
Gespräche werden begrenzt und projektgebunden lokal gespeichert.
Für den lokalen Browsereditor wird der gewünschte Tab ausdrücklich verbunden.
[Chat, Optionen und Verlauf](KI_CHAT_STARTSEITE.md),
[neun native Werkzeuge](SPRITESUITE_NATIVE_ASSISTANT_TOOLS.md).
**Modding Studio** bietet zwölf
Offline-Arbeitsbereiche. **Alle Werkzeuge** bietet die vorhandenen
Fachformulare und ihre Hilfe; erst eine konkrete Ausführung startet das
Werkzeug. Diese Wege ersetzen nicht die benötigten eigenen Quellen,
SDK-Bibliotheken oder eine native ABI-Prüfung.

**Export, Paketbau und Spieltest:** Ein bearbeitbares Projektarchiv erhält
Arbeitsdaten, ein Modpaket ist eine Auslieferungsform, ein BC7-/Unity-Bau
hat zusätzliche Werkzeug- und Quellenanforderungen. Unter **Paket bauen**
bleibt deshalb der spezialisierte Profilbau mit seinen Prüfungen erhalten.
Die alten Produktionsbefehle stehen im [historischen Ablaufarchiv](WORKFLOWS_HISTORISCH_BIS_20261107.md),
die fachlichen Verträge in [Bauvoraussetzungen](BUILD_READINESS.md),
[Bauergebnis](BUILD_COMPLETION.md) und [Release-Preflight](RELEASE_PREFLIGHT.md).
Dateiintegrität, Sandbox-Vorschau und Darstellung im laufenden Spiel sind
getrennte Nachweise. Der [RC4-Prüfstand](SPRITESUITE_RC4_QA_20261108.md)
nennt die tatsächlich geprüften Abläufe und die weiterhin offene
HP-/Feuer-Spielabnahme.
