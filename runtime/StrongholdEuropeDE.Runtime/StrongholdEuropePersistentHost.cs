using System;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime
{
    public sealed class StrongholdEuropePersistentHost : MonoBehaviour
    {
        private StrongholdEuropeRuntimePlugin _owner;
        private bool _applicationQuitting;

        internal void Bind(StrongholdEuropeRuntimePlugin owner)
        {
            if (ReferenceEquals(owner, null))
            {
                throw new ArgumentNullException(nameof(owner));
            }
            if (!ReferenceEquals(_owner, null))
            {
                throw new InvalidOperationException("Persistent runtime host is already bound");
            }
            _owner = owner;
        }

        private void Update()
        {
            StrongholdEuropeRuntimePlugin owner = _owner;
            if (!ReferenceEquals(owner, null))
            {
                owner.RuntimeTick();
            }
        }

        private void LateUpdate()
        {
            StrongholdEuropeRuntimePlugin owner = _owner;
            if (!ReferenceEquals(owner, null))
            {
                owner.RuntimeLateUpdate();
            }
        }

        private void OnApplicationQuit()
        {
            _applicationQuitting = true;
            StrongholdEuropeRuntimePlugin owner = _owner;
            if (!ReferenceEquals(owner, null))
            {
                owner.RuntimeApplicationQuit();
            }
        }

        private void OnDestroy()
        {
            StrongholdEuropeRuntimePlugin owner = _owner;
            _owner = null;
            if (!ReferenceEquals(owner, null))
            {
                owner.RuntimeHostDestroyed(_applicationQuitting);
            }
        }
    }
}
