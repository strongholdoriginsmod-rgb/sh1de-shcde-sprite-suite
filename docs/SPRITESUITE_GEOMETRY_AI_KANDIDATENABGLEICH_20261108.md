# Abgleich des zusätzlichen GeometryAI-Kandidaten

Quelle ist `E:\SpriteSuite_GeometryAI_20261108`. Die zwölf dort zusätzlichen Quell- und Testdateien wurden nach der Zusammenführung der gemeinsamen HTML-Werkstatt gesondert gelesen. Ihr Originalbestand bleibt in dieser Arbeitskopie erhalten.

| Kandidat | Zuordnung im gemeinsamen Stand | Entscheidung |
| --- | --- | --- |
| `geometry_workspace.py`, `sprite_geometry_editor.py` und Geometrietests | HTML-Canvas, `core.js`, `pivot_evidence.js`, `legacy_measurements.js`, Projekt-Undo | Die gemeinsame Werkstatt übernimmt den normalen Bedienweg. Der Kandidat legt ein weiteres Szenenformat und ein zusätzliches Tk-Fenster an. |
| `environment_discovery.py` und Discoverytests | `suite_environment_discovery.py` v2 und `suite_toolchain_inventory.py` | Der vorhandene zentrale Einstieg bleibt zuständig. Die erweiterten Runtime-Quellbelege sind aus EditorAI darin ergänzt. |
| `ai_asset_pipeline.py`, `sprite_ai_workflow_gui.py`, `suite_ai_asset.py` und KI-Tests | Allgemeines Request-ZIP, `suite_ai_codex.py`, lokaler Codex-Broker, gemeinsame Kandidatenabnahme und Projektexport | Die gemeinsame Sitzung und deren SHA-/Statusbelege sind bereits integriert. Ein zweites Jobverzeichnisformat und weitere Freigabe-/Exportimplementierungen werden vermieden. |
| `image_registration.py` und Registrierungstests | `SpriteCore.modelRegistrationPlan/modelRegisteredImage` sowie `building_damage_codex.normalize_model_output` | Die gemeinsame verlustfreie Registrierung bleibt maßgeblich. Der Kandidat verwendet eine feste 1024-Arbeitsfläche mit Skalierung höchstens 8 und eigene Schlüsselnamen. Seine `alpha_composite`-Erstellung überschreibt verborgene RGB-Werte bei vollständig transparenten Quellpixeln. |

Der Python-Kandidat hat eine nachvollziehbare Richtung-/Frame-/Elternjobstruktur für einzelne Assets und nutzt ebenfalls die bestehende ChatGPT-Codex-Sitzung. Sein CLI verarbeitet jeweils einen Job. Eine gemeinsame Batchschnittstelle über die bereits benutzten Request-ZIPs wäre eine spätere Erweiterung mit eigenem Auftrag. Der aktuelle allgemeine Generator verarbeitet bereits eine bis vier getrennte Kandidaten, die gemeinsame Werkstatt kann vorhandene Framefolgen auf Anker- und Alphaveränderungen prüfen.

Die zusätzlichen Kandidaten wurden nicht als neue Release-Einstiege registriert. Die aktuellen Prüfbelege stammen aus den gemeinsamen Modulen und den frischen Browserläufen, nicht aus ungeprüft übertragenen Kandidatenberichten.
