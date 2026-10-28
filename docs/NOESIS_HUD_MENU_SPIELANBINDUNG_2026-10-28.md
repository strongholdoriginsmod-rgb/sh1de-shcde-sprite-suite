# Noesis: HUD- und Menügrafiken im Spiel zuordnen

**Stand: 28. Oktober 2026.** Die direkte Layout-Vorschau liefert
eine komponierte PNG samt gespeicherten Ebenenpositionen. Die neue
Spielanbindung kann dieses Layout auf einen **wirklich vorhandenen
Noesis-XAML-Container** der installierten Stronghold-Crusader-DE-
Script-Extender-Dateien beziehen.

Offizielle Referenzen:
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/xaml-api.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html

## Benutzerweg

1. **HUD & Menüs → Layout-Designer** öffnen, Grafiken mit der Maus
   bewegen, skalieren und drehen, dann **Speichern**.
2. **Layout → PNG + Positionsdaten** erzeugt das zusammengesetzte
   Bild und das SHA-256-Positionsmanifest.
3. **Spieloberfläche anbinden (Noesis)** anklicken. Den echten
   SHCDE-Spielordner oder den installierten SE-GUI-Ordner wählen:
   BepInEx/plugins/000shcdese/Override/Assets/GUI.
4. **XAML durchsuchen** findet tatsächlich benannte eindeutige
   Grid-Knoten der installierten Menüs und HUD-Dateien.
   Der Nutzer wählt einen realen Bildschirm, z. B.
   FrontendMenus.xaml oder MainHUD.xaml, und dessen Ziel-Grid.
   Auch das nachweislich eindeutige direkte Wurzel-Grid
   wird angeboten; es erhält keinen erfundenen Namen.
5. Die Ausrichtung wählen (oben links, mittig, unten rechts usw.).
   **Patch vorprüfen** kontrolliert die installierte Original-XAML
   erneut anhand ihres SHA-256, den XPath und den Bildpfad.
6. **Spieloberfläche + PNG als Asset-Mod bauen** erzeugt ein
   eigenes Manifest-0-Modpaket (Ordner plus ZIP). Kein
   Script-Extender-Update und keine eigene Runtime-DLL.

Beispiel für eine vorhandene MainHUD.xaml-Grid-Kennung HUD_Main:

    BepInEx/plugins/MEINMOD/
      info.json
      Override/Assets/GUI/Images/MeinMenuBild.png
      Patches/Assets/GUI/XAML/MainHUD.xaml

Der XAML-Patch führt eine Add-Operation auf einem eindeutigen,
vorher nachgewiesenen Grid aus, z. B. XPath
//n:Grid[@x:Name='HUD_Main'].
Die eingebundene Canvas enthält ein Image mit dem tatsächlichen
Pfad /Assets/GUI/Images/MeinMenuBild.png und den
gespeicherten Kompositionsabmessungen. Bei explizit aufgeteilten
Grids werden alle vorhandenen Zeilen und Spalten mit
`Grid.RowSpan`/`Grid.ColumnSpan` überdeckt, statt nur die erste
Zelle zu verwenden. Das Overlay fängt keine vorhandenen
UI-Klicks ab (IsHitTestVisible=False). Bereits existierende
Bildressourcennamen des installierten Spiels dürfen für diese
neue Komposition nicht wiederverwendet werden.

Wenn der Grid-Name fehlt, mehrfach vorkommt oder die
Quell-XAML seit der Auswahl geändert wurde, wird
der Bau nachvollziehbar gestoppt. XAML-Patches werden nur
für das eigene Paket erzeugt, nicht in den Originalen geändert.

## QA-Kopie: installieren, prüfen, zurücknehmen

Drei zusätzliche Knöpfe sind für eine **separate QA-Spielkopie**
vorgesehen, nicht für die Originalinstallation:

- **Nur in QA-Spielkopie installieren:** legt nur einen
  neuen Modordner an, wenn er noch nicht existiert,
  mit SHA-256-Quellprüfung und vollständigem Beleg.
  Seit dem Paketbau veränderte Positionen, Exportbilder,
  Mod-IDs oder XAML-Zielzuordnungen werden abgelehnt.
  Der QA-Testweg akzeptiert absichtlich nur ein Minimalpaket
  aus **einer Kompositions-PNG und einem Ziel-XAML-Patch**;
  zusätzliche Nutzerpatches gehören in einen separaten Test.
- **QA-Spiel starten:** startet das ausgewählte Testspiel erst
  nach Prüfung des Installationsbelegs und sämtlicher installierter
  Datei-Hashes sowie ausdrücklicher Bestätigung. Das
  Arbeitsverzeichnis wird auf die QA-Spielkopie gesetzt.
- **QA-Installation sicher zurücknehmen:** entfernt nur
  die belegte eigene QA-Mod, wenn ihre Dateien seit dem
  Einbau vollständig unverändert geblieben sind.
  Bei Konflikten wird nichts gelöscht.

Die Kopie muss SSGameQA heißen oder die vom Nutzer
bewusst angelegte Markerdatei .sprite-suite-qa-copy.marker
besitzen. Während das Spiel läuft, sind Installation
und Rückbau gesperrt. Kein BepInEx-, Script-Extender-
oder Spielarchiv wird durch das Paketwerkzeug verändert.

## Zwei unterschiedliche Nachweise

**Offline-Nachweis:** realer XAML-Datei-SHA, einmaliger
XPath, erzeugte Add-Operation, XML-/DOM-Simulation,
PNG-Hash, fertige ZIP-/Modpaket-Validierung und
sicherer QA-Rückbau, einschließlich Abwehr veralteter
Paketstände, geänderter XAML-Quellen und Ressourcenkollisionen.

**Ingame-Nachweis:** das betreffende Menü wirklich öffnen,
Sichtbarkeit und Position, Alpha und Skalierung,
Überdeckung sowie die bestehenden Klickbereiche prüfen.
Solange dieser Lauf nicht dokumentiert ist, gilt er als
offener Abnahmeschritt. XML-Validierung allein beweist
keine tatsächlich sichtbare Noesis-Darstellung.

## Versionen und Grenzen

Keine Spiel- oder SE-Versionsnummer ist eine pauschale
Sperre. Maßgeblich sind die aktuell tatsächlich
vorhandenen und passenden Dateien. Der Script Extender
kennzeichnet seine Asset-/XAML-API selbst als eine
veränderliche Schnittstelle. Daher ist identisches
Laufzeitverhalten bei jeder jemals erschienenen
Version nicht ohne Spieltest garantiert.

Die neue Pipeline ist für **statische, visuelle
HUD-/Menü-Overlays**. Sie kann keine neuen funktionalen
Button-Aktionen oder ViewModel-/Lua-/C#-Ereignisbindungen
erfinden. Überdeckte vorhandene Buttons behalten ihre
bisherigen Klickbereiche; deren echte Noesis-Struktur
muss bei einer gewünschten Verschiebung gesondert
angepasst werden.

## Tests

- tests/sandbox/test_hud_menu_noesis_integration.py
- tests/sandbox/test_hud_menu_layout_gui.py
- tests/sandbox/test_hud_menu_layout.py
- tests/sandbox/test_se_asset_package.py

Das GitHub-Repository erhält nur Quellcode, Tests und
Dokumentation, keine Spiel-XAML, Originalbilder oder
Testspielkopien.
