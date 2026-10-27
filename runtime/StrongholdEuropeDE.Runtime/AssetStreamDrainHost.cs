using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Process-local host used only after the gameplay lane has failed closed.
    /// It supplies real LateUpdates for the two-frame detach delay and polls
    /// Unity's asynchronous unused-asset cleanup without leaving hooks active.
    /// </summary>
    internal sealed class AssetStreamDrainHost : MonoBehaviour
    {
        private void LateUpdate()
        {
            if (!AssetStreamRuntimeLane.AdvanceRetainedLateFrames())
            {
                Object.Destroy(gameObject);
            }
        }

        private void OnDestroy()
        {
            AssetStreamRuntimeLane.DrainHostDestroyed(gameObject);
        }
    }
}
