using System;
using UnityEngine;

namespace StrongholdEuropeDE.Diplomatie
{
    /// <summary>
    /// Der eigene, szenenfeste Traeger fuer den Takt der Diplomatie.
    /// </summary>
    /// <remarks>
    /// Gemessen am 26.08.2026: ein Plugin, das auf dem BepInEx-GameObject
    /// sitzt, verliert Update beim Szenenwechsel. Die Erweiterungsbahn braucht
    /// aber jeden Frame ihren TickAll, sonst bemerkt niemand, dass eine
    /// Funktion fail-closed stehengeblieben ist. Deshalb ein eigenes Objekt
    /// mit DontDestroyOnLoad statt des BepInEx-Traegers.
    /// </remarks>
    public sealed class DiplomatiePersistentHost : MonoBehaviour
    {
        private DiplomatiePlugin _owner;
        private bool _applicationQuitting;

        internal void Bind(DiplomatiePlugin owner)
        {
            if (ReferenceEquals(owner, null))
            {
                throw new ArgumentNullException("owner");
            }
            if (!ReferenceEquals(_owner, null))
            {
                throw new InvalidOperationException(
                    "Persistent diplomacy host is already bound");
            }
            _owner = owner;
        }

        private void Update()
        {
            // ReferenceEquals statt ==: Unitys ueberladener Vergleich luegt bei
            // einem absichtlich weiterbenutzten MonoBehaviour.
            DiplomatiePlugin owner = _owner;
            if (!ReferenceEquals(owner, null))
            {
                owner.DiplomatieTick();
            }
        }

        private void OnApplicationQuit()
        {
            _applicationQuitting = true;
            DiplomatiePlugin owner = _owner;
            if (!ReferenceEquals(owner, null))
            {
                owner.DiplomatieApplicationQuit();
            }
        }

        private void OnDestroy()
        {
            DiplomatiePlugin owner = _owner;
            _owner = null;
            if (!ReferenceEquals(owner, null))
            {
                owner.DiplomatieHostDestroyed(_applicationQuitting);
            }
        }
    }
}
