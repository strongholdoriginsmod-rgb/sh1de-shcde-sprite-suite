#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using BepInEx;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class CompatibilityReport
    {
        internal readonly List<string> MissingAssemblies = new List<string>();
        internal readonly List<string> MissingTypes = new List<string>();
        internal readonly List<string> MissingMembers = new List<string>();
        internal readonly List<string> Unattested = new List<string>();
        // Entscheidung 09.09.2026: der Mod MUSS auf jeder Spielfassung
        // laden. Abweichungen der Spieldateien (Assembly-CSharp, Noesis,
        // UnityEngine*) und der Engine landen deshalb hier statt in
        // Unattested - sie werden gemeldet, sperren aber nicht mehr.
        // Die Extenderseite bleibt hart: dort sitzen Hooks und Detours, also
        // die native ABI, die eine Namenspruefung nicht belegen kann.
        internal readonly List<string> GameSideDrift = new List<string>();
        internal int BindingsChecked;
        internal int BindingsPresent;
        internal int PrerequisitesTotal;
        internal int PrerequisitesAttested;
        // Seit dem 09.09.2026 heisst das nur noch: der Extender ist GELADEN.
        // Welche Fassung es ist, steht in GameSideDrift und sperrt nicht mehr.
        internal bool ExtenderAttested;
        internal bool EngineAttested;
        internal string EngineDigestPrefix = "?";
        internal string EngineFailure;

        internal bool Compatible
        {
            get
            {
                return MissingAssemblies.Count == 0
                    && MissingTypes.Count == 0
                    && MissingMembers.Count == 0
                    && IdentityAttested;
                // Unveraendert: ein fehlendes Mitglied bleibt eine Sperre. Es
                // ist der einzige Befund, der einen Absturz mitten in der
                // Partie sicher vorhersagt.
            }
        }

        internal bool IdentityAttested
        {
            get
            {
                // EngineAttested und die Zaehlergleichheit sind hier
                // absichtlich NICHT mehr gefordert: beide brechen allein durch
                // eine andere Spielfassung, und genau die soll laden duerfen.
                // Unattested enthaelt seit dem 09.09.2026 nur noch die
                // Extenderseite; alles Spielseitige steht in GameSideDrift.
                return ExtenderAttested
                    && PrerequisitesTotal > 0
                    && Unattested.Count == 0;
            }
        }

        internal string FirstProblem
        {
            get
            {
                if (MissingAssemblies.Count > 0)
                {
                    return "assembly:" + MissingAssemblies[0];
                }
                if (MissingTypes.Count > 0)
                {
                    return "type:" + MissingTypes[0];
                }
                if (MissingMembers.Count > 0)
                {
                    return "member:" + MissingMembers[0];
                }
                if (Unattested.Count > 0) return "prerequisite_unattested:" + Unattested[0];
                if (!ExtenderAttested) return "extender_missing:no_loaded_SHCDESE";
                if (!IdentityAttested) return "prerequisite_contract_incomplete";
                return null;
            }
        }
    }

    /// <summary>
    /// Attestiert zuerst Engine und verwaltete Voraussetzungen exakt gegen
    /// den erzeugten Bauvertrag. Erst danach werden Mitglieder aufgeloest.
    /// </summary>
    /// <remarks>
    /// Entscheidung 08.09.2026: unbekannte Versionen bleiben passiv.
    /// Name und Parameterzahl belegen weder eine CLR-Signatur noch native
    /// Layouts. Deshalb ersetzt die Mitgliederliste niemals die Attestation.
    /// Eine spaetere SE-Version braucht einen neu belegten Bauvertrag; ein
    /// erfolgreiches externes Signatur-Preflight allein aktiviert sie nicht.
    ///
    /// Wirft nie: eine Pruefung, die selbst scheitert, zaehlt als fehlend
    /// bzw. unbeglaubigt und wird benannt.
    /// </remarks>
    internal static class DiplomatieCompatibilityGuard
    {
        private const BindingFlags AllMembers =
            BindingFlags.Public
            | BindingFlags.NonPublic
            | BindingFlags.Instance
            | BindingFlags.Static
            | BindingFlags.FlattenHierarchy;

        internal static CompatibilityReport Probe()
        {
            var report = new CompatibilityReport();
            try
            {
                ProbeEngine(report);
            }
            catch (Exception exception)
            {
                report.EngineAttested = false;
                report.EngineFailure = exception.GetType().Name;
            }
            try
            {
                ProbePrerequisites(report);
            }
            catch (Exception exception)
            {
                report.Unattested.Add("probe_failed:" + exception.GetType().Name);
            }
            // Do not resolve native managers/bridges or load arbitrary member
            // assemblies until every expected binary has been attested.
            if (!report.IdentityAttested) return report;
            try
            {
                ProbeBindings(report);
            }
            catch (Exception exception)
            {
                report.MissingMembers.Add(
                    "probe_failed:" + exception.GetType().Name);
            }
            try
            {
                // Die Speicherbruecke steht nicht in der IL (sie nennt
                // absichtlich weder Zhuqiaomon noch RedBird) und damit nicht
                // im Mitgliedervertrag. Sie wird hier aufgeloest, damit ein
                // fehlendes Mitglied vor der Karte auffaellt.
                string bridgeFailure;
                if (!DiplomacyFeature.ScriptExtenderNativeBridge.TryResolve(
                        out bridgeFailure))
                {
                    report.MissingMembers.Add("bridge:" + bridgeFailure);
                }
                else
                {
                    report.BindingsChecked += 5;
                    report.BindingsPresent += 5;
                }
            }
            catch (Exception exception)
            {
                report.MissingMembers.Add(
                    "bridge_probe_failed:" + exception.GetType().Name);
            }
            try
            {
                report.BindingsChecked++;
                string inventoryFailure;
                if (DiplomacyFeature.TryResolveNativeInventoryMonitor(out inventoryFailure))
                    report.BindingsPresent++;
                else
                    report.MissingMembers.Add("inventory_monitor:" + inventoryFailure);
            }
            catch (Exception exception)
            {
                report.MissingMembers.Add(
                    "inventory_monitor_probe_failed:" + exception.GetType().Name);
            }
            return report;
        }

        private static void ProbeBindings(CompatibilityReport report)
        {
            var assemblies = new Dictionary<string, Assembly>(StringComparer.Ordinal);
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name;
                try
                {
                    name = assembly.GetName().Name;
                }
                catch
                {
                    continue;
                }
                if (!string.IsNullOrEmpty(name) && !assemblies.ContainsKey(name))
                {
                    assemblies[name] = assembly;
                }
            }
            var typeCache = new Dictionary<string, Type>(StringComparer.Ordinal);
            var missingAssemblies = new HashSet<string>(StringComparer.Ordinal);
            var missingTypes = new HashSet<string>(StringComparer.Ordinal);
            int count = GeneratedCompatibilityContract.Count;
            for (int index = 0; index < count; index++)
            {
                report.BindingsChecked++;
                string assemblyName = GeneratedCompatibilityContract.Assemblies[index];
                string typeName = GeneratedCompatibilityContract.Types[index];
                string member = GeneratedCompatibilityContract.Members[index];
                int kind = GeneratedCompatibilityContract.Kinds[index];
                int parameters = GeneratedCompatibilityContract.Parameters[index];

                Assembly assembly;
                if (!assemblies.TryGetValue(assemblyName, out assembly))
                {
                    assembly = TryLoad(assemblyName);
                    if (assembly != null)
                    {
                        assemblies[assemblyName] = assembly;
                    }
                }
                if (assembly == null)
                {
                    if (missingAssemblies.Add(assemblyName))
                    {
                        report.MissingAssemblies.Add(assemblyName);
                    }
                    continue;
                }

                string typeKey = assemblyName + "|" + typeName;
                Type type;
                if (!typeCache.TryGetValue(typeKey, out type))
                {
                    try
                    {
                        type = assembly.GetType(typeName, false);
                    }
                    catch
                    {
                        type = null;
                    }
                    typeCache[typeKey] = type;
                }
                if (type == null)
                {
                    if (missingTypes.Add(typeKey))
                    {
                        report.MissingTypes.Add(assemblyName + "/" + typeName);
                    }
                    continue;
                }
                if (kind == 0)
                {
                    report.BindingsPresent++;
                    continue;
                }
                bool present;
                try
                {
                    present = kind == 2
                        ? type.GetField(member, AllMembers) != null
                        : HasMethod(type, member, parameters);
                }
                catch
                {
                    present = false;
                }
                if (present)
                {
                    report.BindingsPresent++;
                }
                else
                {
                    report.MissingMembers.Add(
                        assemblyName + "/" + typeName + "::" + member
                        + (parameters >= 0
                            ? "(" + parameters.ToString(CultureInfo.InvariantCulture) + ")"
                            : string.Empty));
                }
            }
        }

        private static bool HasMethod(Type type, string member, int parameters)
        {
            if (member == ".ctor" || member == ".cctor")
            {
                foreach (ConstructorInfo constructor in type.GetConstructors(AllMembers))
                {
                    if (parameters < 0
                        || constructor.GetParameters().Length == parameters)
                    {
                        return true;
                    }
                }
                return false;
            }
            foreach (MemberInfo candidate in type.GetMember(member, MemberTypes.Method, AllMembers))
            {
                var method = candidate as MethodInfo;
                if (method == null)
                {
                    continue;
                }
                if (parameters < 0 || method.GetParameters().Length == parameters)
                {
                    return true;
                }
            }
            return false;
        }

        private static Assembly TryLoad(string name)
        {
            try
            {
                return Assembly.Load(new AssemblyName(name));
            }
            catch
            {
                return null;
            }
        }

        private static void ProbePrerequisites(CompatibilityReport report)
        {
            int count = GeneratedAudioContract.PrerequisiteIds.Length;
            report.PrerequisitesTotal = count;
            if (count <= 0 || count != GeneratedAudioContract.PrerequisiteCount
                || GeneratedAudioContract.PrerequisiteRelativePaths.Length != count
                || GeneratedAudioContract.PrerequisiteSizes.Length != count
                || GeneratedAudioContract.PrerequisiteSha256.Length != count
                || GeneratedAudioContract.PrerequisiteAssemblyNames.Length != count
                || GeneratedAudioContract.PrerequisiteAssemblyVersions.Length != count
                || GeneratedAudioContract.PrerequisiteMvids.Length != count)
                throw new InvalidDataException("malformed compiled prerequisite contract");
            var ids = new HashSet<string>(StringComparer.Ordinal);
            for (int index = 0; index < count; index++)
            {
                string id = GeneratedAudioContract.PrerequisiteIds[index];
                try
                {
                    if (string.IsNullOrEmpty(id) || !ids.Add(id))
                        throw new InvalidDataException("duplicate or empty prerequisite identifier");
                    string path = Path.Combine(
                        Paths.GameRootPath,
                        GeneratedAudioContract.PrerequisiteRelativePaths[index]
                            .Replace('/', Path.DirectorySeparatorChar));
                    // ANWESENHEIT des Extenders bleibt Pflicht - ohne
                    // geladene SHCDESE gibt es keine API, an der die
                    // Diplomatie haengen koennte. Das ist keine Versions-,
                    // sondern eine Existenzfrage und steht deshalb VOR der
                    // Identitaetspruefung, damit eine fremde Fassung sie
                    // nicht ueberspringt.
                    if (string.Equals(id, "shcdese", StringComparison.Ordinal))
                    {
                        if (!string.Equals(GeneratedAudioContract.PrerequisiteAssemblyNames[index],
                                "SHCDESE", StringComparison.Ordinal))
                            throw new InvalidDataException("invalid extender assembly name");
                        bool loaded = false;
                        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
                            if (string.Equals(assembly.GetName().Name, "SHCDESE", StringComparison.Ordinal))
                                loaded = true;
                        if (!loaded) throw new InvalidDataException("extender is not loaded");
                        report.ExtenderAttested = true;
                    }
                    if (!File.Exists(path))
                    {
                        NoteUnattested(report, id, "absent");
                        continue;
                    }
                    // Existing shared verifier checks stable SHA/size, assembly
                    // name/version and every loaded matching assembly's MVID and
                    // path. It also rejects duplicate loaded names. It performs
                    // no hook registration or native API operation.
                    //
                    // Entscheidung 09.09.2026: die Alpha soll auf JEDER
                    // Installation anlaufen, damit sie ueberall getestet werden
                    // kann. Eine abweichende Identitaet ist deshalb nur noch
                    // eine Meldung - auch beim Extender. Was dabei NICHT
                    // abgesichert ist und in der Anleitung steht: geaenderte
                    // Hook-Layouts und Strukturgroessen. Sie koennen mitten in
                    // der Partie zuschlagen, wo eine Namenspruefung nichts sieht.
                    NoteIdentity(report, id, index);
                }
                catch (Exception exception)
                {
                    // Hier landen seit dem 09.09.2026 nur noch die HARTEN
                    // Faelle: kaputter Vertrag (doppelte/leere Kennung),
                    // falscher Extender-Assemblyname und - der eigentliche
                    // Grund - ein nicht geladener Extender. Jede blosse
                    // Identitaetsabweichung faengt NoteIdentity vorher ab.
                    report.Unattested.Add(id + ":" + PrerequisiteFailureDetail(exception));
                }
            }
        }

        /// <summary>
        /// Die Dateien, die zur Spielfassung gehoeren statt zum Extender.
        /// </summary>
        /// <remarks>
        /// Entscheidung 09.09.2026: der Mod muss auf jeder Spielfassung
        /// laden. Weicht eine dieser Dateien ab, ist das eine andere
        /// Spielfassung - kein Grund, die Diplomatie abzuschalten. Weicht
        /// dagegen eine Extenderdatei ab, sind Hooks und Detours nicht mehr
        /// belegt, und dagegen hilft keine Namenspruefung.
        /// </remarks>
        private static readonly HashSet<string> GameSidePrerequisites =
            new HashSet<string>(StringComparer.Ordinal)
            {
                "assembly_csharp",
                "noesis_gui",
                "unity_engine",
                "unity_engine_core_module",
                "unity_engine_asset_bundle_module",
                "unity_engine_audio_module",
                "unity_engine_image_conversion_module",
            };

        private static void NoteUnattested(
            CompatibilityReport report, string id, string detail)
        {
            // Seit dem 09.09.2026 ist JEDE Identitaetsabweichung nur noch eine
            // Meldung, nicht mehr nur die spielseitige. Die Menge unten bleibt,
            // weil das Protokoll Spiel- und Extenderseite unterscheidbar
            // ausweist: bei einem Fehlerbericht ist das der erste Blick.
            report.GameSideDrift.Add(
                (id != null && GameSidePrerequisites.Contains(id)
                    ? "game:" : "extender:") + id + ":" + detail);
        }

        private static void NoteIdentity(
            CompatibilityReport report, string id, int index)
        {
            try
            {
                RuntimeBuildGuard.VerifyOptional(id);
                report.PrerequisitesAttested++;
            }
            catch (Exception exception)
            {
                NoteUnattested(report, id, PrerequisiteFailureDetail(exception));
            }
        }

        private static string PrerequisiteFailureDetail(Exception exception)
        {
            // Keep the verifier's reason (file SHA, identity, loaded MVID/path)
            // without allowing exception text to add log lines or fields.
            string message = exception.Message ?? string.Empty;
            int length = Math.Min(message.Length, 240);
            var detail = new char[length];
            for (int index = 0; index < length; index++)
            {
                char character = message[index];
                detail[index] = char.IsControl(character) || character == '|'
                    ? ' ' : character;
            }
            return exception.GetType().Name + ":" + new string(detail)
                + (message.Length > length ? "..." : string.Empty);
        }

        private static void ProbeEngine(CompatibilityReport report)
        {
            string path = Path.Combine(
                Paths.GameRootPath,
                GeneratedCompatibilityContract.EngineRelativePath
                    .Replace('/', Path.DirectorySeparatorChar));
            try
            {
                string digest = Hashing.Sha256FileStable(
                    path,
                    GeneratedCompatibilityContract.EngineSize);
                report.EngineDigestPrefix = digest.Length >= 12
                    ? digest.Substring(0, 12)
                    : digest;
                report.EngineAttested = string.Equals(
                    digest,
                    GeneratedCompatibilityContract.EngineSha256,
                    StringComparison.Ordinal);
                if (!report.EngineAttested)
                {
                    report.EngineFailure = "digest";
                }
            }
            catch (Exception exception)
            {
                report.EngineAttested = false;
                report.EngineFailure = exception.GetType().Name;
                try
                {
                    var info = new FileInfo(path);
                    report.EngineDigestPrefix = info.Exists
                        ? "size:" + info.Length.ToString(CultureInfo.InvariantCulture)
                        : "missing";
                }
                catch
                {
                    report.EngineDigestPrefix = "?";
                }
            }
        }
    }
}
#endif
