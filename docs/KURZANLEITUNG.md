# Kurzanleitung

Hier ist die [Sprite Suite](https://gitlab.com/strongholdoriginsmod/sh1de-shcde-sprite-suite). Den Installer aus `releases/1.1.3` herunterladen und installieren. Vorhandene Einstellungen bleiben erhalten.

1. Unter **Einrichten** beide Spielordner, Unity **2021.3.45f2** und ein stabiles .NET SDK **ab 8.0.100** auswählen (10.x empfohlen). **Pfade speichern**, dann **Spiele einlesen**.
2. Unter **Paket bauen** die Vorlage **Kleines Testpaket** oder **Alle Spielsprites** wählen. Eigene Änderungen unter **Sprites bearbeiten** exportieren, bearbeiten, importieren und ins gewählte Profil übernehmen. Dateinamen, Anker und Masken beibehalten.
3. **Paket bauen** drücken. Zum Ausprobieren das Spiel schließen und über **Ausgabe öffnen** den Ordner `StrongholdEuropeDE` nach `BepInEx/plugins` im Spiel kopieren. **Spiel-Modordner öffnen** öffnet das Ziel. Einen vorhandenen gleichnamigen Ordner vorher aus `plugins` herausnehmen. Der Script Extender bleibt unverändert.

Nach einem Spiel- oder SE-Update die Spiele erneut einlesen und das Paket neu bauen. Weitere Funktionen sind über **Erweiterte Werkzeuge anzeigen** erreichbar.
