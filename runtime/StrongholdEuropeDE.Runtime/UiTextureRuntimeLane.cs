using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace StrongholdEuropeDE.Runtime
{
    internal enum UiTextureInterceptDisposition
    {
        ContinueOriginal = 0,
        SuppliedOwnedTexture = 1,
        RejectedOwnedTexture = 2,
    }

    internal enum UiTextureSlotState
    {
        Unseen = 0,
        Loading = 1,
        Loaded = 2,
        Rejected = 3,
    }

    /// <summary>
    /// Lazy direct-BC7 UI loader. Only manifest-owned virtual paths and exact
    /// legacy /Override/&lt;Noesis path&gt; suffixes enter this lane. Once a path is
    /// owned, every failure returns null and skips SHCDE-SE's PNG loader.
    /// </summary>
    internal sealed class UiTextureRuntimeLane
    {
        private readonly UiTextureManifest _manifest;
        private readonly UiTextureBudgetLedger _budget;
        private readonly IAssetStreamMemoryProbe _memoryProbe;
        private readonly int _mainThreadId;
        private readonly Dictionary<string, UiTextureSlot> _slots;
        private readonly Action<string> _information;
        private readonly Action<string> _warning;

        internal UiTextureRuntimeLane(
            UiTextureManifest manifest,
            UiTextureBudgetLedger budget,
            IAssetStreamMemoryProbe memoryProbe,
            Action<string> information,
            Action<string> warning)
        {
            _manifest = manifest ?? throw new ArgumentNullException("manifest");
            _budget = budget ?? throw new ArgumentNullException("budget");
            _memoryProbe = memoryProbe
                ?? throw new ArgumentNullException("memoryProbe");
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
            _information = information;
            _warning = warning;
            _slots = new Dictionary<string, UiTextureSlot>(StringComparer.Ordinal);
            for (int index = 0; index < manifest.Entries.Count; index++)
            {
                UiTextureManifestEntry entry = manifest.Entries[index];
                _slots.Add(entry.NoesisPath, new UiTextureSlot(entry));
            }
        }

        internal UiTextureManifest Manifest
        {
            get { return _manifest; }
        }

        internal UiTextureBudgetSnapshot BudgetSnapshot
        {
            get { return _budget.Snapshot(); }
        }

        internal bool IsMainThread
        {
            get { return Thread.CurrentThread.ManagedThreadId == _mainThreadId; }
        }

        internal bool TryGetLoadedTexture(
            string noesisPath,
            out Texture2D texture)
        {
            texture = null;
            if (string.IsNullOrEmpty(noesisPath)) return false;
            UiTextureSlot slot;
            return _slots.TryGetValue(noesisPath, out slot)
                && slot.TryGetLoaded(out texture);
        }

        internal void RequireInstallationThread()
        {
            if (!IsMainThread)
            {
                throw new InvalidOperationException(
                    "UI texture lane must be installed on its captured Unity main thread");
            }
        }

        internal UiTextureInterceptDisposition Intercept(
            string filePath,
            TextureFormat format,
            bool mipChain,
            out Texture2D texture)
        {
            texture = null;
            UiTextureSlot slot;
            if (!TryFindSlot(filePath, out slot))
            {
                return UiTextureInterceptDisposition.ContinueOriginal;
            }

            try
            {
                if (!IsMainThread)
                {
                    RejectIfUnseen(
                        slot,
                        "owned UI BC7 texture was requested outside the captured Unity main thread");
                    return UiTextureInterceptDisposition.RejectedOwnedTexture;
                }
                if (format != TextureFormat.RGBA32 || mipChain)
                {
                    RejectIfUnseen(
                        slot,
                        "owned UI BC7 texture was requested through an unexpected SHCDE-SE loader signature");
                    return UiTextureInterceptDisposition.RejectedOwnedTexture;
                }

                UiTextureSlotBeginDisposition begin = slot.TryBegin(out texture);
                if (begin == UiTextureSlotBeginDisposition.UseCached)
                {
                    return UiTextureInterceptDisposition.SuppliedOwnedTexture;
                }
                if (begin != UiTextureSlotBeginDisposition.BeginLoad)
                {
                    texture = null;
                    return UiTextureInterceptDisposition.RejectedOwnedTexture;
                }
                return LoadOwned(slot, out texture);
            }
            catch (OutOfMemoryException)
            {
                slot.Reject("out of memory before an owned BC7 texture was published");
                WarnOnce(slot);
                texture = null;
                return UiTextureInterceptDisposition.RejectedOwnedTexture;
            }
            catch (Exception exception)
            {
                slot.Reject("unexpected " + Describe(exception));
                WarnOnce(slot);
                texture = null;
                return UiTextureInterceptDisposition.RejectedOwnedTexture;
            }
        }

        private UiTextureInterceptDisposition LoadOwned(
            UiTextureSlot slot,
            out Texture2D result)
        {
            result = null;
            UiTextureBudgetReservation reservation;
            string budgetFailure;
            if (!_budget.TryReserve(
                    slot.Entry.ResidentChargeBytes,
                    out reservation,
                    out budgetFailure))
            {
                slot.Reject("budget before AssetBundle load: " + budgetFailure);
                WarnOnce(slot);
                return UiTextureInterceptDisposition.RejectedOwnedTexture;
            }

            Texture2D candidate = null;
            using (reservation)
            {
                try
                {
                    RequireTransientAdmission(
                        slot.Entry,
                        "before verified AssetBundle load");
                    if (!SystemInfo.SupportsTextureFormat(TextureFormat.BC7))
                    {
                        throw new UiTextureContractException(
                            "the current graphics device does not support BC7");
                    }

                    using (AssetStreamPinnedBundle pinned =
                        UiTextureBundleVerifier.OpenVerified(
                            _manifest.PluginRoot,
                            slot.Entry.Bundle))
                    {
                        AssetBundle bundle = null;
                        try
                        {
                            pinned.VerifyIdentityStillMatches();
                            pinned.Stream.Position = 0;
                            // Manifest crc32 is the raw IEEE/zlib file CRC and
                            // has already been verified. Unity's crc argument is
                            // a different content contract, so it remains zero.
                            bundle = AssetBundle.LoadFromStream(
                                pinned.Stream,
                                0U,
                                0U);
                            if (bundle == null)
                            {
                                throw new UiTextureContractException(
                                    "Unity rejected the verified UI AssetBundle");
                            }
                            candidate = bundle.LoadAsset<Texture2D>(
                                slot.Entry.Address);
                            ValidateTexture(candidate, slot.Entry);
                            pinned.VerifyIdentityStillMatches();
                            bundle.Unload(false);
                            bundle = null;
                            pinned.VerifyIdentityStillMatches();
                        }
                        catch
                        {
                            if (bundle != null)
                            {
                                try { bundle.Unload(true); }
                                catch { }
                            }
                            DestroyUnpublished(candidate);
                            candidate = null;
                            throw;
                        }
                    }

                    // The bundle is already unloaded and SHCDE-SE locks each
                    // URI to a single load attempt per process, so a destroyed
                    // override can never be reacquired. Make every
                    // Any process-global Resources.UnloadUnusedAssets call -
                    // for example the AssetStream backend's or the game's -
                    // is therefore structurally unable to take it.
                    // A later eviction stage must clear this flag deliberately.
                    candidate.hideFlags |= HideFlags.DontUnloadUnusedAsset;

                    reservation.Commit();
                    slot.Commit(candidate);
                    result = candidate;
                    candidate = null;
                    Info(
                        "UI BC7 texture loaded lazily: "
                        + slot.Entry.NoesisPath
                        + " storage="
                        + slot.Entry.StorageWidth.ToString(CultureInfo.InvariantCulture)
                        + "x"
                        + slot.Entry.StorageHeight.ToString(CultureInfo.InvariantCulture)
                        + " resident_charge_bytes="
                        + slot.Entry.ResidentChargeBytes.ToString(
                            CultureInfo.InvariantCulture));
                    return UiTextureInterceptDisposition.SuppliedOwnedTexture;
                }
                catch (OutOfMemoryException)
                {
                    DestroyUnpublished(candidate);
                    candidate = null;
                    slot.Reject(
                        "out of memory before an owned BC7 texture was published");
                    WarnOnce(slot);
                    return UiTextureInterceptDisposition.RejectedOwnedTexture;
                }
                catch (Exception exception)
                {
                    DestroyUnpublished(candidate);
                    candidate = null;
                    slot.Reject(Describe(exception));
                    WarnOnce(slot);
                    return UiTextureInterceptDisposition.RejectedOwnedTexture;
                }
            }
        }

        private static void ValidateTexture(
            Texture2D texture,
            UiTextureManifestEntry entry)
        {
            FilterMode expectedFilter = entry.SamplingMode
                == UiTextureSamplingMode.Point
                ? FilterMode.Point
                : FilterMode.Bilinear;
            if (texture == null
                || texture.width != entry.StorageWidth
                || texture.height != entry.StorageHeight
                || texture.format != TextureFormat.BC7
                || texture.mipmapCount != 1
                || texture.isReadable
                || !texture.isDataSRGB
                || texture.filterMode != expectedFilter
                || texture.wrapMode != TextureWrapMode.Clamp
                || texture.wrapModeU != TextureWrapMode.Clamp
                || texture.wrapModeV != TextureWrapMode.Clamp
                || texture.wrapModeW != TextureWrapMode.Clamp
                || texture.anisoLevel != 0
                || !string.Equals(
                    texture.name,
                    entry.ExpectedTextureName,
                    StringComparison.Ordinal))
            {
                throw new UiTextureContractException(
                    "Texture2D runtime BC7/storage/sampling contract mismatch at "
                    + entry.Address);
            }
        }

        private void RequireTransientAdmission(
            UiTextureManifestEntry entry,
            string phase)
        {
            AssetStreamMemorySnapshot snapshot;
            try
            {
                snapshot = _memoryProbe.Capture();
            }
            catch (Exception exception)
            {
                throw new UiTextureBudgetDeniedException(
                    phase + ": memory probe failed: "
                    + exception.GetType().Name);
            }
            string failure = null;
            if (snapshot == null
                || !UiTextureTransientAdmission.TryAdmit(
                    entry.TransientPeakBytes,
                    snapshot == null ? null : snapshot.ProcessPrivateBytes,
                    snapshot == null ? null : snapshot.GlobalAvailableCommitBytes,
                    snapshot == null ? null : snapshot.AvailablePhysicalBytes,
                    out failure))
            {
                throw new UiTextureBudgetDeniedException(
                    phase + ": "
                    + (failure ?? "memory probe returned no snapshot"));
            }
        }

        private static void DestroyUnpublished(Texture2D candidate)
        {
            if (candidate == null) return;
            try { UnityObject.Destroy(candidate); }
            catch { }
        }

        private bool TryFindSlot(string filePath, out UiTextureSlot slot)
        {
            slot = null;
            UiTextureManifestEntry entry;
            if (!_manifest.TryFindOwnedLoadPath(filePath, out entry))
            {
                return false;
            }
            if (!_slots.TryGetValue(entry.NoesisPath, out slot))
            {
                throw new UiTextureContractException(
                    "owned UI path resolved without a runtime slot");
            }
            return true;
        }

        private void RejectIfUnseen(UiTextureSlot slot, string reason)
        {
            if (slot.RejectIfUnseen(reason)) WarnOnce(slot);
        }

        private void WarnOnce(UiTextureSlot slot)
        {
            string message;
            if (slot.TryTakeWarning(out message))
            {
                Warn(
                    "UI BC7 texture rejected fail-closed: "
                    + slot.Entry.NoesisPath
                    + " reason="
                    + message);
            }
        }

        private void Info(string message)
        {
            InvokeLog(_information, message);
        }

        private void Warn(string message)
        {
            InvokeLog(_warning, message);
        }

        private static void InvokeLog(Action<string> sink, string message)
        {
            if (sink == null) return;
            try { sink(message); }
            catch { }
        }

        private static string Describe(Exception exception)
        {
            if (exception == null) return "unknown failure";
            string message = exception.GetType().Name;
            if (!string.IsNullOrWhiteSpace(exception.Message))
            {
                message += ": " + exception.Message;
            }
            message = message.Replace('|', '/').Replace('\r', ' ').Replace('\n', ' ');
            return message.Length <= 256 ? message : message.Substring(0, 256);
        }
    }

    internal static class UiTextureBundleVerifier
    {
        internal static AssetStreamPinnedBundle OpenVerified(
            string pluginRoot,
            UiTextureBundleManifestEntry bundle)
        {
            if (bundle == null) throw new ArgumentNullException("bundle");
            FileStream stream = null;
            try
            {
                string resolvedPath;
                stream = AssetStreamBundleVerifier.OpenReadOnlyNoFollowUnderRoot(
                    pluginRoot,
                    bundle.PluginRelativePath,
                    out resolvedPath);
                if (!string.Equals(
                        resolvedPath,
                        bundle.AbsolutePath,
                        StringComparison.OrdinalIgnoreCase)
                    || stream.Length != bundle.SizeBytes)
                {
                    throw new UiTextureContractException(
                        "UI AssetBundle path or size differs from the manifest");
                }

                string sha256;
                uint crcState = UiTextureCrc32.InitialState;
                using (SHA256 algorithm = SHA256.Create())
                {
                    byte[] buffer = new byte[1024 * 1024];
                    int read;
                    while ((read = stream.Read(buffer, 0, buffer.Length)) != 0)
                    {
                        algorithm.TransformBlock(buffer, 0, read, null, 0);
                        UiTextureCrc32.Update(
                            ref crcState,
                            buffer,
                            0,
                            read);
                    }
                    algorithm.TransformFinalBlock(new byte[0], 0, 0);
                    sha256 = UiTextureHash.Hex(algorithm.Hash);
                }
                string crc32 = UiTextureCrc32.Finish(crcState).ToString(
                    "x8",
                    CultureInfo.InvariantCulture);
                if (!string.Equals(
                        sha256,
                        bundle.Sha256,
                        StringComparison.Ordinal)
                    || !string.Equals(
                        crc32,
                        bundle.Crc32,
                        StringComparison.Ordinal)
                    || stream.Length != bundle.SizeBytes)
                {
                    throw new UiTextureContractException(
                        "UI AssetBundle SHA-256/CRC32/size verification failed");
                }
                stream.Position = 0;
                var result = new AssetStreamPinnedBundle(
                    resolvedPath,
                    bundle.SizeBytes,
                    stream);
                stream = null;
                return result;
            }
            finally
            {
                if (stream != null) stream.Dispose();
            }
        }
    }

    internal enum UiTextureSlotBeginDisposition
    {
        BeginLoad = 0,
        UseCached = 1,
        RejectOwned = 2,
    }

    internal sealed class UiTextureSlot
    {
        private readonly object _gate = new object();
        private UiTextureSlotState _state;
        private Texture2D _texture;
        private string _failure;
        private bool _warningTaken;

        internal UiTextureSlot(UiTextureManifestEntry entry)
        {
            Entry = entry ?? throw new ArgumentNullException("entry");
            _state = UiTextureSlotState.Unseen;
        }

        internal UiTextureManifestEntry Entry { get; private set; }

        internal UiTextureSlotBeginDisposition TryBegin(out Texture2D texture)
        {
            lock (_gate)
            {
                texture = null;
                if (_state == UiTextureSlotState.Loaded)
                {
                    texture = _texture;
                    return UiTextureSlotBeginDisposition.UseCached;
                }
                if (_state != UiTextureSlotState.Unseen)
                {
                    return UiTextureSlotBeginDisposition.RejectOwned;
                }
                _state = UiTextureSlotState.Loading;
                return UiTextureSlotBeginDisposition.BeginLoad;
            }
        }

        internal bool TryGetLoaded(out Texture2D texture)
        {
            lock (_gate)
            {
                texture = _texture;
                return _state == UiTextureSlotState.Loaded
                    && texture != null;
            }
        }

        internal void Commit(Texture2D texture)
        {
            if (texture == null) throw new ArgumentNullException("texture");
            lock (_gate)
            {
                if (_state != UiTextureSlotState.Loading || _texture != null)
                {
                    throw new InvalidOperationException(
                        "UI texture slot is not in its loading state");
                }
                _texture = texture;
                _state = UiTextureSlotState.Loaded;
            }
        }

        internal bool RejectIfUnseen(string failure)
        {
            lock (_gate)
            {
                if (_state != UiTextureSlotState.Unseen) return false;
                _failure = failure;
                _state = UiTextureSlotState.Rejected;
                return true;
            }
        }

        internal void Reject(string failure)
        {
            lock (_gate)
            {
                if (_state == UiTextureSlotState.Loaded) return;
                if (_state != UiTextureSlotState.Rejected)
                {
                    _failure = failure;
                    _state = UiTextureSlotState.Rejected;
                }
            }
        }

        internal bool TryTakeWarning(out string failure)
        {
            lock (_gate)
            {
                failure = _failure ?? "terminal rejection";
                if (_warningTaken || _state != UiTextureSlotState.Rejected)
                {
                    return false;
                }
                _warningTaken = true;
                return true;
            }
        }
    }

    internal sealed class UiTextureBudgetDeniedException : Exception
    {
        internal UiTextureBudgetDeniedException(string message)
            : base(message)
        {
        }
    }
}
