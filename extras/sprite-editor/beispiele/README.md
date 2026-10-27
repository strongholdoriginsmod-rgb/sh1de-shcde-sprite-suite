# Beispiele

Alle Bilder in diesem Ordner sind synthetische Testgrafiken, keine extrahierten Spielassets. Die Quell- und Zielnamen der Portierungsbeispiele sind keine gültig recherchierten SHDE-/SHCDE-IDs. Sie dienen dazu, die Bedienung und Dateiausgaben ohne eine Spielinstallation nachvollziehen zu können.

## Gebäude

`Steinhof.shsprite` über **Projekt → Öffnen** laden. Das Projekt enthält 25 Tiles mit unterschiedlich hohen hinteren Mauern. `Steinhof.png` ist das tatsächlich im Browser ausgegebene Gesamtbild. `Steinhof_Tiles.zip` enthält die zugehörigen Originale. `Steinhof.ora` hält getrennte Ebenen. `Steinhof_Schnitt.zip` und `Steinhof_Schnittmaske.png` demonstrieren eine neue, disjunkte Zerlegung desselben Gesamtbilds, nicht die Rekonstruktion verdeckter Originalebenen.

## Portierungsablauf

Ein neues Projekt anlegen und `Quelldaten_Beispiel.zip` als **PNG-Serie / ZIP** mit Herkunft **Stronghold: Definitive Edition** importieren. Die Bezeichnung markiert den demonstrierten Quellweg; die Bilder sind trotzdem ausschließlich synthetisch. Das ZIP enthält Farbbilder, Masken und Quellmetadaten.

`Zielreferenzen_Beispiel.zip` als **SHCDE-Zielreferenzen (PNG / ZIP)** importieren. Anschließend `Zielzuordnung.csv` als **Zielzuordnung (CSV)** importieren. In den Projekteinstellungen einen Autor und eine Mod-ID eintragen. Unter **Ziel** das Material **TeamColour** wählen und die formalen Prüfungen betrachten. Die synthetischen Masken zeigen Kanaltransport, keine nachgewiesene Teamfarbenbelegung eines echten Shaders.

`Portierung.shsprite` enthält einen bereits vorbereiteten Stand dieses Ablaufs. Zum Prüfen der Atomisierung oder des Layouts kann ein Modpaket ausgegeben werden. **Das Beispielpaket nicht als echten Spielmod installieren**: Die Zielnamen wurden nur für den automatisierten Exporttest gewählt. Für reale Ports eigene extrahierte Referenzen und bestätigte Ziel-IDs verwenden.
