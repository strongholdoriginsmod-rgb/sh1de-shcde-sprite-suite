# C#-Runtime: Script-Extender-ABI-Matrix (28.10.2026)

**Status: Quellcode und Assemblies gegen SHCDE-SE 2.10.4 und 2.14.3 geprüft; kein vollständiger Ingame-Freigabenachweis.**

Die gesamte C#-Runtime kompiliert mit net481 gegen (1) die
installierten SE-2.10.4-Referenzen aus D:\Games und (2) das originale,
SHA-/CRC-geprüfte SE-2.14.3-Release zusammen mit den Steam-Game-Assemblies.
Beide Builds: 0 Compilerfehler. Sie wurden im separaten QA-Ordner erstellt
und **nicht installiert**.

Die neue Interop-Schicht `SeInteropFieldAliases.cs` erlaubt die
geänderten Symbolnamen nur bei geprüftem Feldtyp, Offset und
Strukturgröße. Der früheren Miliz-Einheitensteuerung werden bei der
modernen Struktur Zugriffe verweigert, deren Bedeutung sich geändert
hat. Der unveränderte Speicherplatz allein beweist keine gleiche
Semantik. Die weiterhin direkt benutzten nativen Hooks, ABI-Layouts,
Spielzustände, Save/Load und deren Nebenwirkungen benötigen weiterhin
echte Spielsitzungen.

`runtime_reference_capture.py` erstellt für die ausgewählte
Installation einen **strikten v3-Referenzvertrag** mit 16 Assemblies,
Hashes und MVIDs sowie einer ABI-Layoutkontrolle. Die nachgelagerte
Validierung erkennt die neue Vertragsidentität samt im C#-DLL
eingebetteter MVIDs, ohne den alten v2-Vertrag stillschweigend
zu ersetzen. Andere Versionen sind nur dann Quellbau-Kandidaten,
wenn ihre tatsächlichen Layouts einem der nachgewiesenen
Interop-Schemata entsprechen.

**Ausstehend:** Die tatsächliche C#-Modpaket-Erstellung mit einem
vollständigen Grafik-/Audioprofil, Laden in einer isolierten
SHCDE-Installation, R3-Event-Hooks, Miliz, Diplomatie,
Save/Load, Deinstallation und Rückbau. Die Steam-Installation
wurde nicht verändert; im untersuchten Steam-Spielordner
war kein Script Extender installiert. Es wäre falsch,
aktuell »alle SE-Versionen vollständig kompatibel« zu behaupten.
