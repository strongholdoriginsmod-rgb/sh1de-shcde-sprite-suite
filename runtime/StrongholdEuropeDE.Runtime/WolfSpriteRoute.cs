using System;
using System.Reflection;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Leitet den Ladeplatz des Loewen auf Crusaders eigene, ungenutzte
    /// Wolfsgrafik um.
    ///
    /// Crusader registriert beide Gruppen nebeneinander (spriteLoader.cs):
    ///
    ///   :308  addGMFile( 943, "body_lion", GM_BODY_LION  /*  92 */, dashFormat: true, plainShader: true)
    ///   :373  addGMFile(1055, "body_wolf", GM_BODY_WOLF  /* 203 */, dashFormat: true, plainShader: true)
    ///
    /// GM 203 wird von nichts angefordert - `CHIMP_TYPE_WOLF` existiert nicht,
    /// und Crusaders eigenes XAML traegt ueber dem Wolfsknopf des Editors den
    /// Kommentar "Wolf - really lion" mit `CommandParameter="MAPPER_LION"`.
    /// Die 1.440 Wolfsframes liegen also fertig im Spiel und werden nie
    /// gezeichnet.
    ///
    /// Statt Pixel zu kopieren wird hier nur der Dateiname getauscht, den der
    /// Lader fuer GM 92 sucht. Das ist aus drei gemessenen Gruenden richtig
    /// (docs/WILDTIERE.md):
    ///
    /// * **Die Blockstruktur stimmt ueberein.** Auf den Kontaktboegen 0-95
    ///   beider Gruppen Frame fuer Frame verglichen: 16 Richtungen, gleiche
    ///   Abfolge. Ein Index-Tausch ist semantisch richtig, nicht bloss
    ///   zahlenmaessig moeglich.
    /// * **Die Frames reichen.** Der Loewe tastet bis 943 ab, der Wolf hat
    ///   1.056 luecklose Basisframes.
    /// * **Kopieren waere schlechter.** Nur 12 von 128 Wolfsframes des
    ///   Laufzyklus passen in die Loewenleinwand (Median-Faktor 0,833). Ueber
    ///   den Bildweg muesste jeder Frame anders gestaucht werden; hier behaelt
    ///   der Wolf seine eigene Geometrie, weil die Sprites ihre Metadaten
    ///   selbst mitbringen.
    ///
    /// Die Hyaene kann so **nicht** behandelt werden: Sie laeuft mit
    /// `plainShader: false` und `animalColours` und braucht ihre Teammaske.
    /// </summary>
    internal static class WolfSpriteRoute
    {
        internal const string LionGroup = "body_lion";
        internal const string WolfGroup = "body_wolf";

        /// <summary>Der GM-Wert, den Crusader fuer den Loewen fuehrt.</summary>
        internal const int GmBodyLion = 92;

        /// <summary>Wie oft der Prefix den Namen tatsaechlich getauscht hat.</summary>
        internal static int Rerouted;

        /// <summary>
        /// Harmony-Prefix auf <c>spriteLoader.addGMFile</c>.
        ///
        /// Harmony bindet einen Prefix-Parameter ueber den **Namen** an den
        /// Zielparameter. Deshalb heisst er hier zwingend <c>fileName</c>; die
        /// Installationsseite prueft diesen Namen vorher am echten Ziel und
        /// bricht ab, statt still nichts zu tun.
        ///
        /// Bewusst wird nur <c>fileName</c> entgegengenommen und nicht
        /// zusaetzlich <c>fileID</c>: Dessen Typ ist das spielinterne
        /// <c>Enums.GM</c>, das diese Assembly nicht statisch kennt. Der
        /// Gruppenname ist eindeutig genug - er kommt in der ganzen
        /// Ladetabelle genau einmal vor.
        /// </summary>
        private static void AddGmFilePrefix(ref string fileName)
        {
            if (string.Equals(fileName, LionGroup, StringComparison.Ordinal))
            {
                fileName = WolfGroup;
                Rerouted++;
            }
        }

        /// <summary>
        /// Haengt den Prefix ein. Wirft, wenn das Ziel nicht exakt so aussieht
        /// wie gemessen - ein stiller Fehlschlag waere hier besonders teuer,
        /// weil er sich erst im Spiel als "der Loewe ist immer noch ein Loewe"
        /// zeigt.
        /// </summary>
        internal static void Install(object harmony, Func<string, Type> typeResolver)
        {
            if (harmony == null)
            {
                throw new ArgumentNullException("harmony");
            }
            if (typeResolver == null)
            {
                throw new ArgumentNullException("typeResolver");
            }

            Type loader = typeResolver("spriteLoader");
            if (loader == null)
            {
                throw new MissingMemberException("spriteLoader was not found");
            }

            MethodInfo target = loader.GetMethod(
                "addGMFile",
                BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            if (target == null || target.ReturnType != typeof(void))
            {
                throw new MissingMethodException(
                    "Exact spriteLoader.addGMFile target returning void was not found");
            }

            ParameterInfo[] parameters = target.GetParameters();
            if (parameters.Length != 8
                || parameters[1].ParameterType != typeof(string)
                || !string.Equals(parameters[1].Name, "fileName", StringComparison.Ordinal))
            {
                throw new MissingMethodException(
                    "spriteLoader.addGMFile does not expose the expected 'fileName' parameter");
            }

            MethodInfo prefix = typeof(WolfSpriteRoute).GetMethod(
                "AddGmFilePrefix",
                BindingFlags.NonPublic | BindingFlags.Static);
            if (prefix == null)
            {
                throw new MissingMethodException("Wolf sprite route Harmony prefix is missing");
            }

            PatchThrough(harmony, target, prefix);
        }

        /// <summary>
        /// Ruft <c>Harmony.Patch(target, prefix)</c> ueber Reflection auf,
        /// damit diese Datei keine harte Bindung an den Harmony-Typ braucht und
        /// unabhaengig von der Aufrufseite testbar bleibt.
        /// </summary>
        private static void PatchThrough(object harmony, MethodInfo target, MethodInfo prefix)
        {
            Type harmonyMethodType = AppDomainTypeByName("HarmonyLib.HarmonyMethod");
            if (harmonyMethodType == null)
            {
                throw new MissingMemberException("HarmonyLib.HarmonyMethod was not found");
            }
            ConstructorInfo ctor = harmonyMethodType.GetConstructor(new[] { typeof(MethodInfo) });
            if (ctor == null)
            {
                throw new MissingMethodException("HarmonyMethod(MethodInfo) was not found");
            }
            object harmonyPrefix = ctor.Invoke(new object[] { prefix });

            MethodInfo patch = harmony.GetType().GetMethod(
                "Patch",
                new[]
                {
                    typeof(MethodBase),
                    harmonyMethodType,
                    harmonyMethodType,
                    harmonyMethodType,
                    harmonyMethodType,
                    harmonyMethodType,
                });
            if (patch == null)
            {
                throw new MissingMethodException("Harmony.Patch with six patch slots was not found");
            }
            patch.Invoke(
                harmony,
                new object[] { target, harmonyPrefix, null, null, null, null });
        }

        private static Type AppDomainTypeByName(string fullName)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type found = assembly.GetType(fullName, false);
                if (found != null)
                {
                    return found;
                }
            }
            return null;
        }
    }
}
