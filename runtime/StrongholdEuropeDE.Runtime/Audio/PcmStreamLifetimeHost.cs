using System;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime.Audio
{
    /// <summary>
    /// Main-thread monitor for weak procedural clip leases. Unity components
    /// stay top-level/public so AddComponent can instantiate them reliably.
    /// </summary>
    public sealed class PcmStreamLifetimeHost : MonoBehaviour
    {
        private PcmAudioStreamingLane _owner;

        internal void Bind(PcmAudioStreamingLane owner)
        {
            if (owner == null || _owner != null)
            {
                throw new InvalidOperationException(
                    "PCM stream lifetime host binding is invalid");
            }
            _owner = owner;
        }

        private void Update()
        {
            PcmAudioStreamingLane owner = _owner;
            if (owner != null)
            {
                owner.PumpClipLifetimes();
            }
        }

        private void OnDestroy()
        {
            PcmAudioStreamingLane owner = _owner;
            _owner = null;
            if (owner != null)
            {
                owner.HostDestroyed();
            }
        }
    }
}
