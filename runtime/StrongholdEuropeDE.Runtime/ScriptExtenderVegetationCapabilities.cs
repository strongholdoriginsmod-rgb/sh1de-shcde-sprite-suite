using System;
using System.Collections;
using System.Reflection;
using System.Threading;
using SHCDESE.API.LowLevel;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Read-only capability attestation for vegetation operations whose Lua
    /// exports call BulkVegetationDetours trampolines or depend on its hooks.
    /// This class never commits, enables, disables, or otherwise mutates a hook.
    /// </summary>
    internal static class ScriptExtenderVegetationCapabilities
    {
        private const string OwnerTypeName =
            "SHCDESE.Detours.BulkVegetationDetours";
        private const string ManagerTypeName =
            "SHCDESE.NativeHooks.DetourManager";
        private const string TileOwnerTypeName =
            "SHCDESE.Detours.BulkTileDetours";
        private const string TileApiTypeName =
            "SHCDESE.API.GameTileManagerAPI";
        private const string VegetationApiTypeName =
            "SHCDESE.API.GameVegetationManagerAPI";
        private const string TilePropertyFlagTypeName =
            "SHCDESE.Interop.Enums.TilePropertyFlag";
        private const string TransactionTypeName =
            "Zhuqiaomon.Hooks.Transaction.HookTransaction";
        private const string ManagedAobTypeName =
            "Zhuqiaomon.Hooks.X64ManagedFunctionAOB`1";

        private static int _probed;
        private static VegetationCapabilityDecision _current =
            ScriptExtenderVegetationCapabilityDecision.Evaluate(
                new VegetationHookSnapshot(
                    false,
                    null,
                    null,
                    null,
                    null,
                    false,
                    "not_probed"));

        internal static VegetationCapabilityDecision Current
        {
            get { return Volatile.Read(ref _current); }
        }

        internal static void ProbeOnce(
            Action<string> information,
            Action<string> warning)
        {
            if (Interlocked.CompareExchange(ref _probed, 1, 0) != 0)
            {
                return;
            }

            VegetationHookSnapshot snapshot;
            bool directApiAttested = false;
            try
            {
                // RuntimeBuildGuard.VerifyCore already attested SHCDE-SE before
                // ScriptExtenderScanBufferRelease is created. The transaction
                // shape additionally depends on this exact Zhuqiaomon binary.
                RuntimeBuildGuard.VerifyOptional("zhuqiaomon");
                Assembly shcdese = typeof(CrusaderLibrary).Assembly;
                directApiAttested = CaptureDirectApi(shcdese);
                snapshot = CaptureSnapshot(shcdese, directApiAttested);
            }
            catch (Exception exception)
            {
                snapshot = new VegetationHookSnapshot(
                    false,
                    null,
                    null,
                    null,
                    null,
                    directApiAttested,
                    "reflection_" + Token(exception.GetType().Name));
            }

            VegetationCapabilityDecision decision =
                ScriptExtenderVegetationCapabilityDecision.Evaluate(snapshot);
            Volatile.Write(ref _current, decision);

            string message =
                "SEDE_RUNTIME_V1|event=vegetation_capability"
                + "|status=" + Status(decision.Status)
                + "|reason=" + Token(decision.Reason)
                + "|active_hooks=" + decision.ActiveHookCount
                + "|expected_hooks="
                + ScriptExtenderVegetationCapabilityDecision.ExpectedActiveHookCount
                + "|create_ex_helpers="
                + HelperStatus(decision.CreateExHelpersReady)
                + "|create_ex_immediate_delete=" + Flag(decision.CreateExAndImmediateDelete)
                + "|growth_control=" + Flag(decision.GrowthControl)
                + "|events=" + Flag(decision.VegetationEvents)
                + "|direct_type_state=" + Flag(decision.DirectStructAccess)
                + "|delete_safe=" + Flag(decision.DeleteSafe);
            Emit(
                decision.Status == VegetationDetourCapabilityStatus.Available
                    ? information
                    : warning,
                message);
        }

        private static VegetationHookSnapshot CaptureSnapshot(
            Assembly shcdese,
            bool directApiAttested)
        {
            Type managerType = shcdese.GetType(
                ManagerTypeName,
                true,
                false);
            PropertyInfo instanceProperty = managerType.GetProperty(
                "Instance",
                BindingFlags.Static | BindingFlags.Public);
            if (instanceProperty == null
                || instanceProperty.GetIndexParameters().Length != 0)
            {
                throw new MissingMemberException(ManagerTypeName, "Instance");
            }
            object manager = instanceProperty.GetValue(null, null);
            if (manager == null)
            {
                throw new InvalidOperationException(
                    "DetourManager singleton is unavailable");
            }
            FieldInfo ownersField = managerType.GetField(
                "nativeDetours",
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (ownersField == null)
            {
                throw new MissingFieldException(ManagerTypeName, "nativeDetours");
            }
            IList owners = ownersField.GetValue(manager) as IList;
            if (owners == null)
            {
                throw new InvalidOperationException(
                    "DetourManager native owner list is unavailable");
            }

            object vegetationOwner = null;
            int matches = 0;
            foreach (object owner in owners)
            {
                if (owner != null
                    && string.Equals(
                        owner.GetType().FullName,
                        OwnerTypeName,
                        StringComparison.Ordinal))
                {
                    vegetationOwner = owner;
                    matches++;
                }
            }
            if (matches != 1 || vegetationOwner == null)
            {
                throw new InvalidOperationException(
                    "Expected exactly one BulkVegetationDetours owner");
            }

            FieldInfo transactionField = vegetationOwner.GetType().GetField(
                "tx",
                BindingFlags.Instance | BindingFlags.NonPublic);
            if (transactionField == null
                || !string.Equals(
                    transactionField.FieldType.FullName,
                    TransactionTypeName,
                    StringComparison.Ordinal))
            {
                throw new MissingFieldException(OwnerTypeName, "tx");
            }
            object transaction = transactionField.GetValue(vegetationOwner);
            if (transaction == null)
            {
                throw new InvalidOperationException(
                    "BulkVegetationDetours transaction is unavailable");
            }

            Type transactionType = transaction.GetType();
            FieldInfo committedField = transactionType.GetField(
                "_committed",
                BindingFlags.Instance | BindingFlags.NonPublic);
            MethodInfo activeHooksMethod = transactionType.GetMethod(
                "GetActiveHooks",
                BindingFlags.Instance | BindingFlags.Public,
                null,
                Type.EmptyTypes,
                null);
            if (committedField == null
                || committedField.FieldType != typeof(bool)
                || activeHooksMethod == null)
            {
                throw new MissingMemberException(
                    TransactionTypeName,
                    "_committed/GetActiveHooks");
            }

            bool committed = (bool)committedField.GetValue(transaction);
            IEnumerable hooks = activeHooksMethod.Invoke(
                transaction,
                null) as IEnumerable;
            if (hooks == null)
            {
                throw new InvalidOperationException(
                    "HookTransaction active-hook list is unavailable");
            }

            int count = 0;
            bool allActive = true;
            foreach (object hook in hooks)
            {
                count++;
                if (count > 64 || hook == null)
                {
                    throw new InvalidOperationException(
                        "HookTransaction active-hook list shape changed");
                }
                PropertyInfo activeProperty = hook.GetType().GetProperty(
                    "IsActive",
                    BindingFlags.Instance | BindingFlags.Public);
                if (activeProperty == null
                    || activeProperty.PropertyType != typeof(bool)
                    || activeProperty.GetIndexParameters().Length != 0)
                {
                    throw new MissingMemberException(
                        hook.GetType().FullName,
                        "IsActive");
                }
                if (!(bool)activeProperty.GetValue(hook, null))
                {
                    allActive = false;
                }
            }

            bool? createExHelpersReady;
            try
            {
                createExHelpersReady = CaptureCreateExHelpers(
                    shcdese,
                    vegetationOwner.GetType());
            }
            catch (Exception)
            {
                // The transaction evidence remains valid even when the
                // separate CreateEx helper shape cannot be reflected exactly.
                createExHelpersReady = null;
            }

            return new VegetationHookSnapshot(
                true,
                committed,
                count,
                allActive,
                createExHelpersReady,
                directApiAttested,
                string.Empty);
        }

        private static bool CaptureCreateExHelpers(
            Assembly shcdese,
            Type vegetationOwnerType)
        {
            Type tileOwnerType = shcdese.GetType(
                TileOwnerTypeName,
                true,
                false);
            bool levelHelper = IsResolvedManagedAob(
                vegetationOwnerType,
                "c_game_get_tree_proximity_area_level_from_type");
            bool proximityHelper = IsResolvedManagedAob(
                vegetationOwnerType,
                "c_game_create_tree_proximity_area");
            bool pathfindingHelper = IsResolvedManagedAob(
                tileOwnerType,
                "c_game_update_pathfinding_pot");
            bool resolved = levelHelper
                && proximityHelper
                && pathfindingHelper;

            return resolved;
        }

        private static bool CaptureDirectApi(Assembly shcdese)
        {
            Type tileApiType = shcdese.GetType(TileApiTypeName, true, false);
            Type vegetationApiType = shcdese.GetType(
                VegetationApiTypeName,
                true,
                false);
            Type tilePropertyFlagType = shcdese.GetType(
                TilePropertyFlagTypeName,
                true,
                false);
            Type vegetationType = shcdese.GetType(
                "SHCDESE.Interop.Enums.VegetationType",
                true,
                false);

            PropertyInfo tileInstance = tileApiType.GetProperty(
                "Instance",
                BindingFlags.Static | BindingFlags.Public);
            if (tileInstance == null
                || tileInstance.PropertyType != tileApiType
                || tileInstance.GetIndexParameters().Length != 0)
            {
                throw new MissingMemberException(TileApiTypeName, "Instance");
            }

            RequireExactMethod(
                tileApiType,
                "GetTileId",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(int),
                typeof(int),
                typeof(int));
            RequireExactMethod(
                tileApiType,
                "HasTilePropertyFlag",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(bool),
                typeof(int),
                tilePropertyFlagType);
            RequireExactMethod(
                tileApiType,
                "RemoveTilePropertyFlag",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(void),
                typeof(int),
                tilePropertyFlagType);
            RequireExactMethod(
                tileApiType,
                "AddTilePropertyFlag",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(void),
                typeof(int),
                tilePropertyFlagType);
            RequireExactMethod(
                tileApiType,
                "SetTileVegetationId",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(void),
                typeof(int),
                typeof(int));
            RequireExactMethod(
                tileApiType,
                "GetTileManager",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(IntPtr));
            RequireExactMethod(
                tileApiType,
                "GetPathfindingContext",
                BindingFlags.Instance | BindingFlags.NonPublic,
                typeof(IntPtr));
            RequireExactMethod(
                vegetationApiType,
                "CreateEx",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(long),
                typeof(ushort),
                typeof(ushort),
                vegetationType,
                typeof(short),
                typeof(int),
                typeof(short),
                typeof(int));
            RequireExactMethod(
                vegetationApiType,
                "DeleteSafe",
                BindingFlags.Instance | BindingFlags.Public,
                typeof(bool),
                typeof(int));
            return true;
        }

        private static bool IsResolvedManagedAob(
            Type ownerType,
            string fieldName)
        {
            FieldInfo helperField = ownerType.GetField(
                fieldName,
                BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
            if (helperField == null
                || !helperField.FieldType.IsGenericType
                || !string.Equals(
                    helperField.FieldType.GetGenericTypeDefinition().FullName,
                    ManagedAobTypeName,
                    StringComparison.Ordinal))
            {
                throw new MissingFieldException(ownerType.FullName, fieldName);
            }
            object helper = helperField.GetValue(null);
            if (helper == null)
            {
                return false;
            }
            Type helperType = helper.GetType();
            FieldInfo initialized = helperType.GetField(
                "InitializedSuccessfully",
                BindingFlags.Instance | BindingFlags.Public);
            FieldInfo function = helperType.GetField(
                "Function",
                BindingFlags.Instance | BindingFlags.Public);
            Type functionType = helperType.GetGenericArguments()[0];
            if (initialized == null
                || initialized.FieldType != typeof(bool)
                || function == null
                || function.FieldType != functionType
                || !typeof(Delegate).IsAssignableFrom(functionType))
            {
                throw new MissingMemberException(
                    helperType.FullName,
                    "InitializedSuccessfully/Function");
            }
            return (bool)initialized.GetValue(helper)
                && function.GetValue(helper) != null;
        }

        private static void RequireExactMethod(
            Type owner,
            string name,
            BindingFlags flags,
            Type returnType,
            params Type[] parameters)
        {
            MethodInfo method = owner.GetMethod(
                name,
                flags,
                null,
                parameters,
                null);
            if (method == null || method.ReturnType != returnType)
            {
                throw new MissingMethodException(owner.FullName, name);
            }
        }

        private static string Status(VegetationDetourCapabilityStatus status)
        {
            switch (status)
            {
                case VegetationDetourCapabilityStatus.Available:
                    return "available";
                case VegetationDetourCapabilityStatus.Unavailable:
                    return "unavailable";
                default:
                    return "unknown";
            }
        }

        private static string Flag(bool value)
        {
            return value ? "available" : "disabled";
        }

        private static string HelperStatus(bool? value)
        {
            if (!value.HasValue)
            {
                return "unknown";
            }
            return value.Value ? "available" : "disabled";
        }

        private static string Token(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "unknown";
            }
            char[] output = value.Trim().ToLowerInvariant().ToCharArray();
            for (int index = 0; index < output.Length; index++)
            {
                char item = output[index];
                if ((item >= 'a' && item <= 'z')
                    || (item >= '0' && item <= '9')
                    || item == '_'
                    || item == '-')
                {
                    continue;
                }
                output[index] = '_';
            }
            return new string(output);
        }

        private static void Emit(Action<string> target, string message)
        {
            try
            {
                if (target != null)
                {
                    target(message);
                }
            }
            catch (Exception)
            {
                // Capability diagnostics never own a runtime lane.
            }
        }
    }
}
