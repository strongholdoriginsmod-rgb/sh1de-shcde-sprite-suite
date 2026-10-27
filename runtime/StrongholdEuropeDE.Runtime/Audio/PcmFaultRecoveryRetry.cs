using System;
using System.Collections.Generic;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime.Audio
{
    /// <summary>
    /// One-shot recovery retained after a faulted procedural clip has already
    /// been detached. Only route metadata and short-lived clip identities are
    /// held; the reader and its buffer lease can be disposed immediately.
    /// </summary>
    internal sealed class PcmFaultRecoveryRetry
    {
        internal PcmFaultRecoveryRetry(
            long duePump,
            string request,
            PcmOriginalMusicRoute originalRoute,
            AudioClip[] faultedClips,
            string[] faultedRequests)
        {
            DuePump = duePump;
            Request = request ?? string.Empty;
            OriginalRoute = originalRoute
                ?? throw new ArgumentNullException("originalRoute");
            FaultedClips = faultedClips
                ?? throw new ArgumentNullException("faultedClips");
            FaultedRequests = faultedRequests
                ?? throw new ArgumentNullException("faultedRequests");
        }

        internal long DuePump { get; private set; }
        internal string Request { get; private set; }
        internal PcmOriginalMusicRoute OriginalRoute { get; private set; }
        internal AudioClip[] FaultedClips { get; private set; }
        internal string[] FaultedRequests { get; private set; }
    }

    /// <summary>
    /// Single bounded delayed retry for the one music route MyAudioManager can
    /// own at a time. Scheduling for currentPump + 1 prevents two restart calls
    /// from running in the same failed manager state.
    /// </summary>
    internal sealed class PcmFaultRecoveryRetrySlot
    {
        private readonly object _gate = new object();
        private PcmFaultRecoveryRetry _pending;

        internal bool HasPending
        {
            get
            {
                lock (_gate)
                {
                    return _pending != null;
                }
            }
        }

        internal bool TrySchedule(
            long currentPump,
            string request,
            PcmOriginalMusicRoute originalRoute,
            IList<AudioClip> faultedClips,
            IList<string> faultedRequests)
        {
            if (currentPump < 0
                || originalRoute == null
                || faultedClips == null
                || faultedRequests == null)
            {
                return false;
            }
            var clipCopy = new AudioClip[faultedClips.Count];
            var requestCopy = new string[faultedRequests.Count];
            for (int index = 0; index < clipCopy.Length; index++)
            {
                clipCopy[index] = faultedClips[index];
            }
            for (int index = 0; index < requestCopy.Length; index++)
            {
                requestCopy[index] = faultedRequests[index];
            }
            var candidate = new PcmFaultRecoveryRetry(
                checked(currentPump + 1),
                request,
                originalRoute,
                clipCopy,
                requestCopy);
            lock (_gate)
            {
                if (_pending != null)
                {
                    return false;
                }
                _pending = candidate;
                return true;
            }
        }

        internal bool TryTakeDue(
            long currentPump,
            out PcmFaultRecoveryRetry retry)
        {
            lock (_gate)
            {
                retry = null;
                if (_pending == null || currentPump < _pending.DuePump)
                {
                    return false;
                }
                retry = _pending;
                _pending = null;
                return true;
            }
        }

        internal void Clear()
        {
            lock (_gate)
            {
                _pending = null;
            }
        }
    }
}
