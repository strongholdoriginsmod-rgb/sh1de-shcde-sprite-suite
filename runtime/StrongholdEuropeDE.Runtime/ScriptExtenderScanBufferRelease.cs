using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using BepInEx;
using SHCDESE.API.LowLevel;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Releases duplicate module snapshots retained by completed Zhuqiaomon
    /// HookTransactions. The active hooks retain their trampolines and original
    /// bytes independently; HookTransaction._memory is only the synchronous AOB
    /// scan input used by Commit().
    /// </summary>
    /// <remarks>
    /// The one CrusaderLibrary.LibrarySnapshot is deliberately retained. It is
    /// the public late-subscriber contract for CrusaderLibrary.LibraryLoaded and
    /// is therefore also the extensibility-safe source for future hook owners.
    /// </remarks>
    internal sealed class ScriptExtenderScanBufferRelease
    {
        private const int ExpectedModuleBytes = 0x08902000;
        private const int ExpectedShcdeseUnpatchedCommittedTransactions =
            ScriptExtenderScanBufferTopologyDecision
                .ExpectedUnpatchedCommittedTransactions;
        private const int ExpectedShcdesePatchedCommittedTransactions =
            ScriptExtenderScanBufferTopologyDecision
                .ExpectedPatchedCommittedTransactions;
        private const int ExpectedFixesCommittedTransactions = 2;
        private const int ExpectedMaximumReleasedTransactions =
            ExpectedShcdesePatchedCommittedTransactions
            + ExpectedFixesCommittedTransactions;
        private const string VegetationOwnerTypeName =
            "SHCDESE.Detours.BulkVegetationDetours";

        private const string FixesAssemblyName = "fixes";
        private const string FixesAssemblyVersion = "1.7.1.0";
        private const string FixesMvid =
            "eb03b201-0fd9-4d47-bea1-290e1833c40f";
        private const string FixesRelativePath =
            "BepInEx/plugins/fixes/fixes.dll";
        private const long FixesFileSize = 58368;
        private const string FixesSha256 =
            "5d526ca3b3bfde11ffe377c418d688769ada03cac2bc7dd94a1a3fab836b5c89";

        private static readonly OwnerShape[] ShcdeseOwners =
        {
            new OwnerShape("SHCDESE.Detours.BulkTribeDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkUnitDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkBuildingDetours", true, true),
            // Exactly two source-attested 1.44 shapes are accepted here. The
            // upstream constructor leaves this transaction uncommitted; the
            // repository source patch adds its sole final tx.Commit(). All
            // other owner identities and commit states remain exact.
            new OwnerShape(
                VegetationOwnerTypeName,
                true,
                null),
            new OwnerShape("SHCDESE.Detours.BulkMapLoaderDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkProjectileDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkPlayerDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkSoundDetours", false, false),
            new OwnerShape("SHCDESE.Detours.BulkTileDetours", false, false),
            new OwnerShape("SHCDESE.Detours.BulkTimeDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkMapEditorDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkAIDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkChoreDetours", true, true),
            new OwnerShape("SHCDESE.Detours.BulkVEHDetours", true, true),
        };

        private static readonly OwnerShape[] FixesOwners =
        {
            new OwnerShape("Fixes.Detours.FixesBuildingDetours", true, true),
            new OwnerShape("Fixes.Detours.FixesAIDetours", true, true),
        };

        private readonly Action<string> _information;
        private readonly Action<string> _warning;
        private int _state;
        private long _managedBeforeBytes;
        private long _privateBeforeBytes;
        private long _workingSetBeforeBytes;
        private long _releasedBytes;
        private int _releasedTransactions;
        private int _validatedTransactions;
        private int _alreadyClearedTransactions;
        private int _committedActiveLeaseRetainedTransactions;
        private int _uncommittedActiveLeaseRetainedTransactions;
        private int _releasedCopyTransactions;
        private int _clearedSnapshotViews;
        private string _fixesStatus = "not_checked";

        internal ScriptExtenderScanBufferRelease(
            Action<string> information,
            Action<string> warning)
        {
            _information = information;
            _warning = warning;
        }

        /// <summary>
        /// Phase one runs on the first Update after BepInEx finished creating
        /// every plugin. Phase two collects on the following Update, after all
        /// rollback boxes containing the old ReadOnlyMemory values have left
        /// the stack.
        /// </summary>
        internal void Tick()
        {
            int state = Volatile.Read(ref _state);
            if (state == 0
                && Interlocked.CompareExchange(ref _state, 1, 0) == 0)
            {
                ReleasePhase();
                return;
            }
            if (state == 2
                && Interlocked.CompareExchange(ref _state, 3, 2) == 2)
            {
                CollectionPhase();
            }
        }

        private void ReleasePhase()
        {
            try
            {
                ScriptExtenderVegetationCapabilities.ProbeOnce(
                    _information,
                    _warning);
                _managedBeforeBytes = GC.GetTotalMemory(false);
                CaptureProcessMemory(
                    out _privateBeforeBytes,
                    out _workingSetBeforeBytes);

                ReleaseResult result = ReleaseCommittedBuffers();
                _releasedBytes = result.ReleasedBytes;
                _releasedTransactions = result.ReleasedTransactions;
                _validatedTransactions = result.ValidatedTransactions;
                _alreadyClearedTransactions =
                    result.AlreadyClearedTransactions;
                _committedActiveLeaseRetainedTransactions =
                    result.CommittedActiveLeaseRetainedTransactions;
                _uncommittedActiveLeaseRetainedTransactions =
                    result.UncommittedActiveLeaseRetainedTransactions;
                _releasedCopyTransactions =
                    result.ReleasedCopyTransactions;
                _clearedSnapshotViews = result.ClearedSnapshotViews;
                _fixesStatus = result.FixesStatus;
                Emit(
                    _information,
                    "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                    + "|status=references_released"
                    + "|transactions=" + Integer(_releasedTransactions)
                    + "|validated_transactions="
                    + Integer(_validatedTransactions)
                    + "|already_cleared_transactions="
                    + Integer(_alreadyClearedTransactions)
                    + "|committed_active_lease_retained_transactions="
                    + Integer(_committedActiveLeaseRetainedTransactions)
                    + "|uncommitted_active_lease_retained_transactions="
                    + Integer(_uncommittedActiveLeaseRetainedTransactions)
                    + "|released_copy_transactions="
                    + Integer(_releasedCopyTransactions)
                    + "|cleared_snapshot_views="
                    + Integer(_clearedSnapshotViews)
                    + "|released_bytes=" + Integer(_releasedBytes)
                    + "|snapshot_retained_bytes=" + Integer(ExpectedModuleBytes)
                    + "|vegetation_retained_bytes="
                    + Integer(result.VegetationRetainedBytes)
                    + "|vegetation_topology="
                    + Token(result.VegetationTopology)
                    + "|fixes=" + Token(_fixesStatus));
                Volatile.Write(ref _state, 2);
            }
            catch (Exception exception)
            {
                Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                    + "|status=retained"
                    + "|reason=" + Token(exception.GetType().Name));
                Volatile.Write(ref _state, 3);
            }
        }

        private void CollectionPhase()
        {
            try
            {
                long managedAfterBytes = GC.GetTotalMemory(true);
                long privateAfterBytes;
                long workingSetAfterBytes;
                CaptureProcessMemory(
                    out privateAfterBytes,
                    out workingSetAfterBytes);
                Emit(
                    _information,
                    "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                    + "|status=collected"
                    + "|transactions=" + Integer(_releasedTransactions)
                    + "|released_bytes=" + Integer(_releasedBytes)
                    + "|managed_before_bytes=" + Integer(_managedBeforeBytes)
                    + "|managed_after_bytes=" + Integer(managedAfterBytes)
                    + "|private_before_bytes=" + Integer(_privateBeforeBytes)
                    + "|private_after_bytes=" + Integer(privateAfterBytes)
                    + "|working_set_before_bytes="
                    + Integer(_workingSetBeforeBytes)
                    + "|working_set_after_bytes="
                    + Integer(workingSetAfterBytes)
                    + "|fixes=" + Token(_fixesStatus));
            }
            catch (Exception exception)
            {
                // Reference release already succeeded. A diagnostic/collection
                // failure must never disable any gameplay or graphics lane.
                Emit(
                    _warning,
                    "SEDE_RUNTIME_V1|event=script_extender_scan_buffers"
                    + "|status=collection_unavailable"
                    + "|transactions=" + Integer(_releasedTransactions)
                    + "|released_bytes=" + Integer(_releasedBytes)
                    + "|reason=" + Token(exception.GetType().Name));
            }
        }

        private static ReleaseResult ReleaseCommittedBuffers()
        {
            // Core file/MVID/path attestation already completed in Probe().
            // Verify Zhuqiaomon as a loaded assembly as well before changing a
            // field whose lifetime semantics come from that exact binary.
            RuntimeBuildGuard.VerifyOptional("zhuqiaomon");

            CrusaderLibrary library = CrusaderLibrary.Instance;
            Type libraryType = typeof(CrusaderLibrary);
            FieldInfo snapshotField = RequireField(
                libraryType,
                "LibrarySnapshot",
                BindingFlags.Instance | BindingFlags.NonPublic);
            FieldInfo moduleHandleField = RequireField(
                libraryType,
                "LibraryModuleHandle",
                BindingFlags.Instance | BindingFlags.NonPublic);
            byte[] snapshot = snapshotField.GetValue(library) as byte[];
            if (snapshot == null || snapshot.Length != ExpectedModuleBytes)
            {
                throw new InvalidDataException(
                    "Pinned CrusaderLibrary snapshot has an unexpected size");
            }
            IntPtr moduleHandle = (IntPtr)moduleHandleField.GetValue(library);
            if (moduleHandle == IntPtr.Zero)
            {
                throw new InvalidOperationException(
                    "Pinned CrusaderLibrary module handle is unavailable");
            }
            ulong imageBase = unchecked((ulong)moduleHandle.ToInt64());

            Assembly zhuqiaomon = FindUniqueLoadedAssembly("Zhuqiaomon", true);
            Type transactionType = zhuqiaomon.GetType(
                "Zhuqiaomon.Hooks.Transaction.HookTransaction",
                true,
                false);
            FieldInfo memoryField = RequireField(
                transactionType,
                "_memory",
                BindingFlags.Instance | BindingFlags.NonPublic);
            FieldInfo imageBaseField = RequireField(
                transactionType,
                "_imageBase",
                BindingFlags.Instance | BindingFlags.NonPublic);
            FieldInfo committedField = RequireField(
                transactionType,
                "_committed",
                BindingFlags.Instance | BindingFlags.NonPublic);
            Type memoryType = memoryField.FieldType;
            if (memoryType != typeof(ReadOnlyMemory<byte>)
                || !memoryType.IsValueType
                || !memoryType.IsGenericType
                || !string.Equals(
                    memoryType.GetGenericTypeDefinition().FullName,
                    "System.ReadOnlyMemory`1",
                    StringComparison.Ordinal)
                || memoryType.GetGenericArguments().Length != 1
                || memoryType.GetGenericArguments()[0] != typeof(byte)
                || imageBaseField.FieldType != typeof(ulong)
                || committedField.FieldType != typeof(bool))
            {
                throw new InvalidDataException(
                    "Pinned HookTransaction field contract changed");
            }
            PropertyInfo memoryLengthProperty = memoryType.GetProperty(
                "Length",
                BindingFlags.Instance | BindingFlags.Public);
            PropertyInfo memoryIsEmptyProperty = memoryType.GetProperty(
                "IsEmpty",
                BindingFlags.Instance | BindingFlags.Public);
            if (memoryLengthProperty == null
                || memoryLengthProperty.PropertyType != typeof(int)
                || memoryIsEmptyProperty == null
                || memoryIsEmptyProperty.PropertyType != typeof(bool))
            {
                throw new InvalidDataException(
                    "Pinned ReadOnlyMemory field contract changed");
            }

            var candidates = new List<ReleaseCandidate>(
                ExpectedMaximumReleasedTransactions);
            var census = new ReleaseCensus();

            Assembly shcdese = libraryType.Assembly;
            bool vegetationCommitted;
            int beforeShcdese = census.ValidatedCommittedTransactions;
            CollectManagerCandidates(
                shcdese,
                "SHCDESE.NativeHooks.DetourManager",
                ShcdeseOwners,
                transactionType,
                memoryField,
                imageBaseField,
                committedField,
                memoryLengthProperty,
                imageBase,
                snapshot.Length,
                snapshot,
                false,
                VegetationOwnerTypeName,
                out vegetationCommitted,
                census,
                candidates);
            int expectedShcdeseTransactions = vegetationCommitted
                ? ExpectedShcdesePatchedCommittedTransactions
                : ExpectedShcdeseUnpatchedCommittedTransactions;
            int shcdeseTransactions =
                census.ValidatedCommittedTransactions - beforeShcdese;
            if (shcdeseTransactions != expectedShcdeseTransactions
                || !ScriptExtenderScanBufferTopologyDecision
                    .IsAttestedReleaseTopology(
                        shcdeseTransactions,
                        vegetationCommitted))
            {
                throw new InvalidDataException(
                    "Pinned SHCDE-SE committed transaction count changed");
            }

            string fixesStatus;
            Assembly fixes = FindAttestedFixesAssembly(out fixesStatus);
            if (fixes != null)
            {
                int beforeFixes = census.ValidatedCommittedTransactions;
                bool ignoredVariableCommitState;
                CollectManagerCandidates(
                    fixes,
                    "Fixes.Detours.DetourManager",
                    FixesOwners,
                    transactionType,
                    memoryField,
                    imageBaseField,
                    committedField,
                    memoryLengthProperty,
                    imageBase,
                    snapshot.Length,
                    snapshot,
                    true,
                    null,
                    out ignoredVariableCommitState,
                    census,
                    candidates);
                if (census.ValidatedCommittedTransactions - beforeFixes
                    != ExpectedFixesCommittedTransactions)
                {
                    throw new InvalidDataException(
                        "Pinned Fixes committed transaction count changed");
                }
            }

            int expectedCount = fixes == null
                ? expectedShcdeseTransactions
                : expectedShcdeseTransactions
                    + ExpectedFixesCommittedTransactions;
            if (census.ValidatedCommittedTransactions != expectedCount
                || census.ValidatedCommittedTransactions
                    != census.AlreadyClearedTransactions
                        + census.CommittedActiveLeaseRetainedTransactions
                        + census.ReleasedCopyTransactions
                        + census.ClearedSnapshotViews
                || candidates.Count
                    != census.ReleasedCopyTransactions
                        + census.ClearedSnapshotViews)
            {
                throw new InvalidDataException(
                    "Validated scan-buffer release set is incomplete");
            }

            ApplyAtomically(
                memoryField,
                memoryLengthProperty,
                memoryIsEmptyProperty,
                candidates);
            long releasedBytes = 0;
            for (int index = 0; index < candidates.Count; index++)
            {
                releasedBytes = checked(
                    releasedBytes + candidates[index].ReleasedBytes);
            }
            long expectedReleasedBytes = checked(
                (long)census.ReleasedCopyTransactions
                * ExpectedModuleBytes);
            if (releasedBytes != expectedReleasedBytes)
            {
                throw new InvalidDataException(
                    "Pinned scan-buffer release byte count changed");
            }
            return new ReleaseResult(
                candidates.Count,
                releasedBytes,
                fixesStatus,
                census.ValidatedCommittedTransactions,
                census.AlreadyClearedTransactions,
                census.CommittedActiveLeaseRetainedTransactions,
                census.UncommittedActiveLeaseRetainedTransactions,
                census.ReleasedCopyTransactions,
                census.ClearedSnapshotViews,
                census.VegetationRetainedBytes,
                vegetationCommitted
                    ? "committed_12"
                    : "unpatched_11");
        }

        private static void CollectManagerCandidates(
            Assembly assembly,
            string managerTypeName,
            OwnerShape[] expectedOwners,
            Type transactionType,
            FieldInfo memoryField,
            FieldInfo imageBaseField,
            FieldInfo committedField,
            PropertyInfo memoryLengthProperty,
            ulong expectedImageBase,
            int expectedMemoryBytes,
            byte[] librarySnapshot,
            bool allowLibrarySnapshotView,
            string variableCommitOwnerType,
            out bool variableCommitState,
            ReleaseCensus census,
            List<ReleaseCandidate> candidates)
        {
            variableCommitState = false;
            bool variableCommitOwnerFound = false;
            Type managerType = assembly.GetType(
                managerTypeName,
                true,
                false);
            PropertyInfo instanceProperty = managerType.GetProperty(
                "Instance",
                BindingFlags.Static | BindingFlags.Public);
            if (instanceProperty == null
                || instanceProperty.GetIndexParameters().Length != 0)
            {
                throw new MissingMemberException(
                    managerTypeName,
                    "Instance");
            }
            object manager = instanceProperty.GetValue(null, null);
            if (manager == null)
            {
                throw new InvalidOperationException(
                    managerTypeName + " singleton is unavailable");
            }
            FieldInfo ownersField = RequireField(
                managerType,
                "nativeDetours",
                BindingFlags.Instance | BindingFlags.NonPublic);
            IList owners = ownersField.GetValue(manager) as IList;
            if (owners == null || owners.Count != expectedOwners.Length)
            {
                throw new InvalidDataException(
                    managerTypeName + " owner list shape changed");
            }

            for (int index = 0; index < expectedOwners.Length; index++)
            {
                OwnerShape expected = expectedOwners[index];
                object owner = owners[index];
                if (owner == null
                    || !string.Equals(
                        owner.GetType().FullName,
                        expected.TypeName,
                        StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        managerTypeName + " owner order changed");
                }

                FieldInfo transactionField = owner.GetType().GetField(
                    "tx",
                    BindingFlags.Instance | BindingFlags.NonPublic);
                if (!expected.HasTransaction)
                {
                    if (transactionField != null)
                    {
                        throw new InvalidDataException(
                            expected.TypeName + " unexpectedly owns a transaction");
                    }
                    continue;
                }
                if (transactionField == null
                    || transactionField.FieldType != transactionType)
                {
                    throw new MissingFieldException(expected.TypeName, "tx");
                }
                object transaction = transactionField.GetValue(owner);
                if (transaction == null)
                {
                    throw new InvalidOperationException(
                        expected.TypeName + " transaction is unavailable");
                }

                bool committed = (bool)committedField.GetValue(transaction);
                if (expected.Committed.HasValue
                    && committed != expected.Committed.Value)
                {
                    throw new InvalidDataException(
                        expected.TypeName + " commit state changed");
                }
                if (!expected.Committed.HasValue)
                {
                    if (variableCommitOwnerFound
                        || !string.Equals(
                            expected.TypeName,
                            variableCommitOwnerType,
                            StringComparison.Ordinal))
                    {
                        throw new InvalidDataException(
                            managerTypeName
                            + " variable commit owner contract changed");
                    }
                    variableCommitOwnerFound = true;
                    variableCommitState = committed;
                }
                ulong actualImageBase =
                    (ulong)imageBaseField.GetValue(transaction);
                if (actualImageBase != expectedImageBase)
                {
                    throw new InvalidDataException(
                        expected.TypeName + " image base changed");
                }
                object memory = memoryField.GetValue(transaction);
                ScriptExtenderScanBufferMemoryShape memoryShape = ClassifyMemory(
                    memory,
                    memoryLengthProperty,
                    expectedMemoryBytes,
                    librarySnapshot);
                ScriptExtenderScanBufferTrackedMemoryState trackedState =
                    ScriptExtenderScanBufferBorrowPatch
                        .GetTrackedMemoryState(transaction);
                bool vegetationOwner = string.Equals(
                    expected.TypeName,
                    VegetationOwnerTypeName,
                    StringComparison.Ordinal);
                ScriptExtenderScanBufferReleaseAction action =
                    ScriptExtenderScanBufferReleaseDecision.Evaluate(
                        committed,
                        vegetationOwner,
                        allowLibrarySnapshotView,
                        trackedState,
                        memoryShape);
                ScriptExtenderScanBufferRetentionCensus.Record(
                    action,
                    ref census.CommittedActiveLeaseRetainedTransactions,
                    ref census.UncommittedActiveLeaseRetainedTransactions);
                if (committed)
                {
                    census.ValidatedCommittedTransactions++;
                }
                switch (action)
                {
                    case ScriptExtenderScanBufferReleaseAction.AlreadyCleared:
                        census.AlreadyClearedTransactions++;
                        break;
                    case ScriptExtenderScanBufferReleaseAction.RetainActiveLease:
                        if (vegetationOwner)
                        {
                            census.VegetationRetainedBytes =
                                ExpectedModuleBytes;
                        }
                        break;
                    case ScriptExtenderScanBufferReleaseAction.ReleaseArrayCopy:
                        census.ReleasedCopyTransactions++;
                        candidates.Add(new ReleaseCandidate(
                            expected.TypeName,
                            transaction,
                            memory,
                            ExpectedModuleBytes));
                        break;
                    case ScriptExtenderScanBufferReleaseAction
                        .ClearLibrarySnapshotView:
                        census.ClearedSnapshotViews++;
                        candidates.Add(new ReleaseCandidate(
                            expected.TypeName,
                            transaction,
                            memory,
                            0));
                        break;
                    case ScriptExtenderScanBufferReleaseAction
                        .RetainUncommittedActiveLease:
                        census.VegetationRetainedBytes = ExpectedModuleBytes;
                        break;
                    case ScriptExtenderScanBufferReleaseAction.RetainUncommitted:
                        census.VegetationRetainedBytes = ExpectedModuleBytes;
                        break;
                    default:
                        throw new InvalidDataException(
                            expected.TypeName
                            + " scan-buffer lifetime shape is not attested");
                }
            }
            if ((variableCommitOwnerType != null) != variableCommitOwnerFound)
            {
                throw new InvalidDataException(
                    managerTypeName + " variable commit topology changed");
            }
        }

        private static ScriptExtenderScanBufferMemoryShape ClassifyMemory(
            object boxedMemory,
            PropertyInfo memoryLengthProperty,
            int expectedMemoryBytes,
            byte[] librarySnapshot)
        {
            if (!(boxedMemory is ReadOnlyMemory<byte>))
            {
                throw new InvalidDataException(
                    "Pinned scan-buffer memory type changed");
            }
            ReadOnlyMemory<byte> memory =
                (ReadOnlyMemory<byte>)boxedMemory;
            int reflectedLength =
                (int)memoryLengthProperty.GetValue(boxedMemory, null);
            if (reflectedLength != memory.Length)
            {
                throw new InvalidDataException(
                    "Pinned scan-buffer length reflection changed");
            }
            if (memory.IsEmpty)
            {
                if (memory.Length != 0)
                {
                    throw new InvalidDataException(
                        "Empty scan-buffer reports a non-zero length");
                }
                return ScriptExtenderScanBufferMemoryShape.Empty;
            }
            if (memory.Length != expectedMemoryBytes)
            {
                throw new InvalidDataException(
                    "Pinned scan-buffer size changed");
            }

            ArraySegment<byte> segment;
            if (!MemoryMarshal.TryGetArray(memory, out segment))
            {
                return ScriptExtenderScanBufferMemoryShape.UnmanagedLease;
            }
            if (segment.Array == null
                || segment.Offset != 0
                || segment.Count != expectedMemoryBytes
                || segment.Array.Length != expectedMemoryBytes)
            {
                throw new InvalidDataException(
                    "Pinned array-backed scan-buffer shape changed");
            }
            return ReferenceEquals(segment.Array, librarySnapshot)
                ? ScriptExtenderScanBufferMemoryShape.LibrarySnapshotView
                : ScriptExtenderScanBufferMemoryShape.ArrayCopy;
        }

        private static void ApplyAtomically(
            FieldInfo memoryField,
            PropertyInfo memoryLengthProperty,
            PropertyInfo memoryIsEmptyProperty,
            List<ReleaseCandidate> candidates)
        {
            object emptyMemory = Activator.CreateInstance(memoryField.FieldType);
            for (int index = 0; index < candidates.Count; index++)
            {
                ReleaseCandidate candidate = candidates[index];
                object current = memoryField.GetValue(candidate.Transaction);
                if (ScriptExtenderScanBufferBorrowPatch
                        .GetTrackedMemoryState(candidate.Transaction)
                        != ScriptExtenderScanBufferTrackedMemoryState.Untracked
                    || current == null
                    || !current.Equals(candidate.PreviousMemory))
                {
                    throw new InvalidDataException(
                        candidate.OwnerType
                        + " scan-buffer changed before atomic release");
                }
            }
            int applied = 0;
            try
            {
                for (; applied < candidates.Count; applied++)
                {
                    memoryField.SetValue(
                        candidates[applied].Transaction,
                        emptyMemory);
                }
                for (int index = 0; index < candidates.Count; index++)
                {
                    object current = memoryField.GetValue(
                        candidates[index].Transaction);
                    if (current == null
                        || !(bool)memoryIsEmptyProperty.GetValue(current, null))
                    {
                        throw new InvalidOperationException(
                            candidates[index].OwnerType
                            + " scan-buffer release did not read back empty");
                    }
                }
            }
            catch (Exception mutationFailure)
            {
                Exception rollbackFailure = null;
                for (int index = applied - 1; index >= 0; index--)
                {
                    try
                    {
                        memoryField.SetValue(
                            candidates[index].Transaction,
                            candidates[index].PreviousMemory);
                        object restored = memoryField.GetValue(
                            candidates[index].Transaction);
                        if (restored == null
                            || (int)memoryLengthProperty.GetValue(restored, null)
                            != ExpectedModuleBytes)
                        {
                            throw new InvalidOperationException(
                                candidates[index].OwnerType
                                + " scan-buffer rollback did not restore length");
                        }
                    }
                    catch (Exception exception)
                    {
                        rollbackFailure = exception;
                    }
                }
                if (rollbackFailure != null)
                {
                    throw new AggregateException(
                        "Scan-buffer release and rollback both failed",
                        mutationFailure,
                        rollbackFailure);
                }
                throw;
            }
        }

        private static Assembly FindAttestedFixesAssembly(out string status)
        {
            Assembly match = null;
            foreach (Assembly candidate in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!string.Equals(
                        candidate.GetName().Name,
                        FixesAssemblyName,
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null && !ReferenceEquals(match, candidate))
                {
                    status = "multiple_loaded";
                    return null;
                }
                match = candidate;
            }
            if (match == null)
            {
                status = "not_loaded";
                return null;
            }

            try
            {
                AssemblyName identity = match.GetName();
                Guid expectedMvid;
                if (!Guid.TryParseExact(FixesMvid, "D", out expectedMvid)
                    || !string.Equals(
                        identity.Version.ToString(),
                        FixesAssemblyVersion,
                        StringComparison.Ordinal)
                    || match.ManifestModule.ModuleVersionId != expectedMvid)
                {
                    status = "identity_mismatch";
                    return null;
                }
                string expectedPath = Path.GetFullPath(Path.Combine(
                    Paths.GameRootPath,
                    FixesRelativePath.Replace(
                        '/',
                        Path.DirectorySeparatorChar)));
                string location;
                try
                {
                    location = Path.GetFullPath(match.Location);
                }
                catch (Exception)
                {
                    status = "path_unavailable";
                    return null;
                }
                if (!string.Equals(
                        expectedPath,
                        location,
                        StringComparison.OrdinalIgnoreCase))
                {
                    status = "path_mismatch";
                    return null;
                }
                string digest = Hashing.Sha256FileStable(
                    expectedPath,
                    FixesFileSize);
                if (!string.Equals(
                        digest,
                        FixesSha256,
                        StringComparison.Ordinal))
                {
                    status = "digest_mismatch";
                    return null;
                }
            }
            catch (Exception)
            {
                status = "attestation_unavailable";
                return null;
            }

            status = "attested";
            return match;
        }

        private static Assembly FindUniqueLoadedAssembly(
            string assemblyName,
            bool required)
        {
            Assembly match = null;
            foreach (Assembly candidate in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (!string.Equals(
                        candidate.GetName().Name,
                        assemblyName,
                        StringComparison.Ordinal))
                {
                    continue;
                }
                if (match != null && !ReferenceEquals(match, candidate))
                {
                    throw new InvalidDataException(
                        "Multiple loaded assemblies named " + assemblyName);
                }
                match = candidate;
            }
            if (match == null && required)
            {
                throw new FileNotFoundException(
                    "Required loaded assembly is unavailable",
                    assemblyName);
            }
            return match;
        }

        private static FieldInfo RequireField(
            Type type,
            string name,
            BindingFlags flags)
        {
            FieldInfo field = type.GetField(name, flags);
            if (field == null)
            {
                throw new MissingFieldException(type.FullName, name);
            }
            return field;
        }

        private static void CaptureProcessMemory(
            out long privateBytes,
            out long workingSetBytes)
        {
            using (Process process = Process.GetCurrentProcess())
            {
                process.Refresh();
                privateBytes = process.PrivateMemorySize64;
                workingSetBytes = process.WorkingSet64;
            }
        }

        private static string Integer(long value)
        {
            return value.ToString(CultureInfo.InvariantCulture);
        }

        private static string Token(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "none";
            }
            char[] output = value.ToCharArray();
            for (int index = 0; index < output.Length; index++)
            {
                char item = output[index];
                if ((item >= 'a' && item <= 'z')
                    || (item >= 'A' && item <= 'Z')
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
                // Diagnostics cannot own or disable a runtime lane.
            }
        }

        private sealed class OwnerShape
        {
            internal OwnerShape(
                string typeName,
                bool hasTransaction,
                bool? committed)
            {
                TypeName = typeName;
                HasTransaction = hasTransaction;
                Committed = committed;
            }

            internal string TypeName { get; private set; }
            internal bool HasTransaction { get; private set; }
            internal bool? Committed { get; private set; }
        }

        private sealed class ReleaseCensus
        {
            internal int ValidatedCommittedTransactions;
            internal int AlreadyClearedTransactions;
            internal int CommittedActiveLeaseRetainedTransactions;
            internal int UncommittedActiveLeaseRetainedTransactions;
            internal int ReleasedCopyTransactions;
            internal int ClearedSnapshotViews;
            internal long VegetationRetainedBytes;
        }

        private sealed class ReleaseCandidate
        {
            internal ReleaseCandidate(
                string ownerType,
                object transaction,
                object previousMemory,
                long releasedBytes)
            {
                OwnerType = ownerType;
                Transaction = transaction;
                PreviousMemory = previousMemory;
                ReleasedBytes = releasedBytes;
            }

            internal string OwnerType { get; private set; }
            internal object Transaction { get; private set; }
            internal object PreviousMemory { get; private set; }
            internal long ReleasedBytes { get; private set; }
        }

        private sealed class ReleaseResult
        {
            internal ReleaseResult(
                int releasedTransactions,
                long releasedBytes,
                string fixesStatus,
                int validatedTransactions,
                int alreadyClearedTransactions,
                int committedActiveLeaseRetainedTransactions,
                int uncommittedActiveLeaseRetainedTransactions,
                int releasedCopyTransactions,
                int clearedSnapshotViews,
                long vegetationRetainedBytes,
                string vegetationTopology)
            {
                ReleasedTransactions = releasedTransactions;
                ReleasedBytes = releasedBytes;
                FixesStatus = fixesStatus;
                ValidatedTransactions = validatedTransactions;
                AlreadyClearedTransactions = alreadyClearedTransactions;
                CommittedActiveLeaseRetainedTransactions =
                    committedActiveLeaseRetainedTransactions;
                UncommittedActiveLeaseRetainedTransactions =
                    uncommittedActiveLeaseRetainedTransactions;
                ReleasedCopyTransactions = releasedCopyTransactions;
                ClearedSnapshotViews = clearedSnapshotViews;
                VegetationRetainedBytes = vegetationRetainedBytes;
                VegetationTopology = vegetationTopology;
            }

            internal int ReleasedTransactions { get; private set; }
            internal long ReleasedBytes { get; private set; }
            internal string FixesStatus { get; private set; }
            internal int ValidatedTransactions { get; private set; }
            internal int AlreadyClearedTransactions { get; private set; }
            internal int CommittedActiveLeaseRetainedTransactions
            {
                get;
                private set;
            }
            internal int UncommittedActiveLeaseRetainedTransactions
            {
                get;
                private set;
            }
            internal int ReleasedCopyTransactions { get; private set; }
            internal int ClearedSnapshotViews { get; private set; }
            internal long VegetationRetainedBytes { get; private set; }
            internal string VegetationTopology { get; private set; }
        }
    }
}
