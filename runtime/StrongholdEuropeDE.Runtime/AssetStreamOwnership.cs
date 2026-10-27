using System;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    internal struct AssetStreamOwnershipToken : IEquatable<AssetStreamOwnershipToken>
    {
        internal AssetStreamOwnershipToken(string groupId, long epoch, long generation)
        {
            if (string.IsNullOrEmpty(groupId))
            {
                throw new ArgumentNullException("groupId");
            }
            if (epoch < 1)
            {
                throw new ArgumentOutOfRangeException("epoch");
            }
            if (generation < 1)
            {
                throw new ArgumentOutOfRangeException("generation");
            }
            GroupId = groupId;
            Epoch = epoch;
            Generation = generation;
        }

        internal string GroupId { get; private set; }

        internal long Epoch { get; private set; }

        internal long Generation { get; private set; }

        internal bool IsValid
        {
            get
            {
                return !string.IsNullOrEmpty(GroupId)
                    && Epoch > 0
                    && Generation > 0;
            }
        }

        public bool Equals(AssetStreamOwnershipToken other)
        {
            return Epoch == other.Epoch
                && Generation == other.Generation
                && string.Equals(GroupId, other.GroupId, StringComparison.Ordinal);
        }

        public override bool Equals(object obj)
        {
            return obj is AssetStreamOwnershipToken
                && Equals((AssetStreamOwnershipToken)obj);
        }

        public override int GetHashCode()
        {
            unchecked
            {
                int hash = GroupId == null ? 0 : GroupId.GetHashCode();
                hash = (hash * 397) ^ Epoch.GetHashCode();
                return (hash * 397) ^ Generation.GetHashCode();
            }
        }

        public override string ToString()
        {
            return GroupId + "@" + Epoch + ":" + Generation;
        }
    }

    /// <summary>
    /// Immutable vanilla/SHCDE-SE state captured only after the extender has
    /// applied its startup overrides. The controller never destroys this value.
    /// </summary>
    internal sealed class AssetStreamBaseline<TBaseline>
        where TBaseline : class
    {
        internal AssetStreamBaseline(string groupId, long captureGeneration, TBaseline value)
        {
            if (string.IsNullOrEmpty(groupId))
            {
                throw new ArgumentNullException("groupId");
            }
            if (captureGeneration < 1)
            {
                throw new ArgumentOutOfRangeException("captureGeneration");
            }
            GroupId = groupId;
            CaptureGeneration = captureGeneration;
            Value = value ?? throw new ArgumentNullException("value");
        }

        internal string GroupId { get; private set; }

        internal long CaptureGeneration { get; private set; }

        internal TBaseline Value { get; private set; }
    }

    internal sealed class AssetStreamOwnedGroup<TCommitted>
        where TCommitted : class
    {
        internal AssetStreamOwnedGroup(
            AssetStreamOwnershipToken ownership,
            TCommitted value)
        {
            if (!ownership.IsValid)
            {
                throw new ArgumentException("Ownership token is invalid", "ownership");
            }
            Ownership = ownership;
            Value = value ?? throw new ArgumentNullException("value");
        }

        internal AssetStreamOwnershipToken Ownership { get; private set; }

        internal TCommitted Value { get; private set; }
    }

    internal interface IAssetStreamThreadGate
    {
        bool IsMainThread { get; }
    }

    internal sealed class AssetStreamCapturedThreadGate : IAssetStreamThreadGate
    {
        private readonly int _mainThreadId;

        internal AssetStreamCapturedThreadGate()
        {
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
        }

        public bool IsMainThread
        {
            get { return Thread.CurrentThread.ManagedThreadId == _mainThreadId; }
        }
    }

    /// <summary>
    /// One-shot bridge from Unity's asynchronous native cleanup back to the
    /// reservation owner. A backend marks it pending as soon as an AssetBundle
    /// exists and completes it only after UnloadUnusedAssets.isDone.
    /// </summary>
    internal sealed class AssetStreamCleanupCompletion
    {
        private readonly object _gate = new object();
        private bool _pending;
        private bool _completed;
        private Action _continuation;

        internal bool IsPending
        {
            get { lock (_gate) { return _pending && !_completed; } }
        }

        internal void MarkPending()
        {
            lock (_gate)
            {
                if (_completed)
                {
                    throw new InvalidOperationException(
                        "Native cleanup completion is already terminal");
                }
                _pending = true;
            }
        }

        internal void OnCompleted(Action continuation)
        {
            if (continuation == null)
            {
                throw new ArgumentNullException("continuation");
            }
            bool invoke;
            lock (_gate)
            {
                if (!_pending && !_completed)
                {
                    throw new InvalidOperationException(
                        "No native cleanup owns this completion");
                }
                invoke = _completed;
                if (!invoke)
                {
                    _continuation += continuation;
                }
            }
            if (invoke)
            {
                continuation();
            }
        }

        internal void Complete()
        {
            Action continuation;
            lock (_gate)
            {
                if (_completed)
                {
                    return;
                }
                if (!_pending)
                {
                    throw new InvalidOperationException(
                        "Cannot complete cleanup that never acquired a bundle");
                }
                _completed = true;
                continuation = _continuation;
                _continuation = null;
            }
            if (continuation != null)
            {
                continuation();
            }
        }
    }

    /// <summary>
    /// One fully staged load. BeginTransaction must load the atlas.v2 TextAsset,
    /// parse it, load every Texture2D page, create runtime Sprites with
    /// Sprite.Create, and build all page materials without publishing any of
    /// them. Commit may then publish the complete group atomically, but only
    /// after the controller's second resource admission succeeds.
    /// Abort must be idempotent and conditionally detach any owned references
    /// left by a Commit exception. Dispose must not release a successful commit.
    /// </summary>
    internal interface IAssetStreamGroupTransaction<TCommitted> : IDisposable
        where TCommitted : class
    {
        TCommitted Commit();

        void Abort();
    }

    internal enum AssetStreamRestoreDisposition
    {
        RestoredBaseline = 0,
        AlreadyDetached = 1,
        ForeignOwnerPreserved = 2,
        RetryRequired = 3,
        UnsafeToRelease = 4,
    }

    internal struct AssetStreamRestoreResult
    {
        internal AssetStreamRestoreResult(
            AssetStreamRestoreDisposition disposition,
            bool ownedReferencesDetached,
            string detail)
        {
            if (ownedReferencesDetached
                && (disposition == AssetStreamRestoreDisposition.RetryRequired
                    || disposition == AssetStreamRestoreDisposition.UnsafeToRelease))
            {
                throw new ArgumentException(
                    "Unsafe restore dispositions cannot claim detached ownership",
                    "ownedReferencesDetached");
            }
            Disposition = disposition;
            OwnedReferencesDetached = ownedReferencesDetached;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal AssetStreamRestoreDisposition Disposition { get; private set; }

        internal bool OwnedReferencesDetached { get; private set; }

        internal string Detail { get; private set; }

        internal bool ShouldRetry
        {
            get { return Disposition == AssetStreamRestoreDisposition.RetryRequired; }
        }
    }

    internal struct AssetStreamReleaseResult
    {
        internal AssetStreamReleaseResult(bool released, bool retryable, string detail)
            : this(released, retryable, false, detail)
        {
        }

        internal AssetStreamReleaseResult(
            bool released,
            bool retryable,
            bool progressPending,
            string detail)
        {
            if (released && retryable)
            {
                throw new ArgumentException(
                    "A completed release cannot be retryable",
                    "retryable");
            }
            if (progressPending && (released || !retryable))
            {
                throw new ArgumentException(
                    "Pending asynchronous cleanup must be retryable and incomplete",
                    "progressPending");
            }
            Released = released;
            Retryable = retryable;
            ProgressPending = progressPending;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal bool Released { get; private set; }

        internal bool Retryable { get; private set; }

        internal bool ProgressPending { get; private set; }

        internal string Detail { get; private set; }
    }

    /// <summary>
    /// Unity-facing integration boundary. Verify binds the stable external
    /// Runtime/AssetBundles/win64 file to its size/SHA/CRC/Hash128 record.
    /// Implementations must use AssetBundle.Unload(false), destroy only objects
    /// identified by Ownership, and route per-page material sets independently
    /// from gmMaterials[gm].
    /// </summary>
    internal interface IAssetStreamGroupBackend<TBaseline, TCommitted>
        where TBaseline : class
        where TCommitted : class
    {
        void Verify(AssetStreamGroupManifest group);

        IAssetStreamGroupTransaction<TCommitted> BeginTransaction(
            AssetStreamGroupManifest group,
            AssetStreamBaseline<TBaseline> baseline,
            AssetStreamOwnershipToken ownership,
            AssetStreamCleanupCompletion cleanupCompletion);

        AssetStreamRestoreResult RestoreBaseline(
            AssetStreamGroupManifest group,
            AssetStreamBaseline<TBaseline> baseline,
            AssetStreamOwnedGroup<TCommitted> owned);

        AssetStreamReleaseResult Release(
            AssetStreamGroupManifest group,
            AssetStreamOwnedGroup<TCommitted> owned);
    }

    internal sealed class AssetStreamLoadException : Exception
    {
        internal AssetStreamLoadException(string message, bool permanent)
            : base(message)
        {
            Permanent = permanent;
        }

        internal AssetStreamLoadException(
            string message,
            bool permanent,
            Exception innerException)
            : base(message, innerException)
        {
            Permanent = permanent;
        }

        internal AssetStreamLoadException(
            string message,
            bool permanent,
            bool cleanupUnconfirmed,
            Exception innerException)
            : base(message, innerException)
        {
            Permanent = permanent;
            CleanupUnconfirmed = cleanupUnconfirmed;
        }

        internal bool Permanent { get; private set; }

        internal bool CleanupUnconfirmed { get; private set; }
    }

    internal enum AssetStreamEventKind
    {
        BaselineRegistered = 0,
        Queued = 1,
        BudgetDenied = 2,
        LoadStarted = 3,
        SecondAdmissionDenied = 4,
        LoadCommitted = 5,
        LoadFailed = 6,
        RestoreStarted = 7,
        RestoreDeferred = 8,
        ReleaseDeferred = 9,
        ReleaseCompleted = 10,
        ReleaseBlocked = 11,
    }

    internal sealed class AssetStreamEvent
    {
        internal AssetStreamEvent(
            AssetStreamEventKind kind,
            string groupId,
            long epoch,
            string detail)
        {
            Kind = kind;
            GroupId = groupId ?? string.Empty;
            Epoch = epoch;
            Detail = AssetStreamText.Sanitize(detail, 256);
        }

        internal AssetStreamEventKind Kind { get; private set; }

        internal string GroupId { get; private set; }

        internal long Epoch { get; private set; }

        internal string Detail { get; private set; }
    }

    internal interface IAssetStreamEventSink
    {
        void Emit(AssetStreamEvent value);
    }

    internal sealed class NullAssetStreamEventSink : IAssetStreamEventSink
    {
        internal static readonly NullAssetStreamEventSink Instance =
            new NullAssetStreamEventSink();

        private NullAssetStreamEventSink()
        {
        }

        public void Emit(AssetStreamEvent value)
        {
        }
    }

    internal sealed class AssetStreamControllerOptions
    {
        internal AssetStreamControllerOptions(int releaseDelayFrames)
        {
            if (releaseDelayFrames < 2 || releaseDelayFrames > 120)
            {
                throw new ArgumentOutOfRangeException(
                    "releaseDelayFrames",
                    "Release delay must be between two and 120 LateUpdate frames");
            }
            ReleaseDelayFrames = releaseDelayFrames;
        }

        internal int ReleaseDelayFrames { get; private set; }

        internal static AssetStreamControllerOptions SafeDefaults()
        {
            return new AssetStreamControllerOptions(2);
        }
    }
}
