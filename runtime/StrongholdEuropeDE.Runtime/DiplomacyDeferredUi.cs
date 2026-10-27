using System;
using System.Collections.Generic;
using System.Reflection;

namespace StrongholdEuropeDE.Runtime
{
    // COPY's HUD_ConfirmationPopup stores the exact two callbacks passed to
    // ShowConfirmationMessage in private yesAction/noAction instance fields.
    // Both references and the displayed instance are required: a foreign OK
    // popup can replace only yesAction and leave the old noAction behind.
    internal static class DiplomacyPopupOwnership
    {
        private sealed class Fields { internal FieldInfo Yes; internal FieldInfo No; }
        private static readonly Dictionary<Type, Fields> Cache = new Dictionary<Type, Fields>();

        internal static bool Matches(object shownPopup, object currentPopup,
            Action shownYes, Action shownNo)
        {
            if (shownPopup == null || !ReferenceEquals(shownPopup, currentPopup)
                || shownYes == null || shownNo == null) return false;
            try
            {
                Type type = currentPopup.GetType();
                Fields fields;
                lock (Cache)
                {
                    if (!Cache.TryGetValue(type, out fields))
                    {
                        fields = new Fields
                        {
                            Yes = type.GetField("yesAction", BindingFlags.NonPublic | BindingFlags.Instance),
                            No = type.GetField("noAction", BindingFlags.NonPublic | BindingFlags.Instance),
                        };
                        Cache.Add(type, fields);
                    }
                }
                FieldInfo yes = fields.Yes;
                FieldInfo no = fields.No;
                return yes != null && no != null && yes.FieldType == typeof(Action)
                    && no.FieldType == typeof(Action)
                    && ReferenceEquals(yes.GetValue(currentPopup), shownYes)
                    && ReferenceEquals(no.GetValue(currentPopup), shownNo);
            }
            catch { return false; } // Optional presentation cleanup fails closed.
        }
    }

    internal sealed partial class DiplomacyFeature
    {
        // Presentation is expendable, model decisions are not. Only speech is
        // bounded here; unanswered decisions stay in the separate dialog FIFO.
        private sealed class DeferredDiplomacySpeech
        {
            internal string Key;
            internal string CoalitionId;
            internal string MediaTag;
            internal string FileStem;
            internal long Generation;
            internal string Fingerprint;
        }

        private readonly Queue<DeferredDiplomacySpeech> _deferredSpeech =
            new Queue<DeferredDiplomacySpeech>();
        private readonly HashSet<string> _deferredSpeechKeys =
            new HashSet<string>(StringComparer.Ordinal);

        private bool CanPresentDiplomacyUi
        {
            get
            {
                return !IsNativeDiplomacySectionHeld && _frameThreadId != 0
                    && Environment.CurrentManagedThreadId == _frameThreadId;
            }
        }

        private void DeferCoalitionSpeech(CoalitionState coalition, string tag, string stem)
        {
            if (coalition == null || _mapDisabled) return;
            string key = coalition.CoalitionId + "\n" + tag + "\n" + stem;
            if (_deferredSpeech.Count >= 64 || !_deferredSpeechKeys.Add(key)) return;
            _deferredSpeech.Enqueue(new DeferredDiplomacySpeech
            {
                Key = key, CoalitionId = coalition.CoalitionId,
                MediaTag = tag, FileStem = stem,
                Generation = _sessionGeneration, Fingerprint = _mapFingerprint,
            });
        }

        private void ClearDeferredDiplomacyUi()
        {
            _deferredSpeech.Clear();
            _deferredSpeechKeys.Clear();
        }

        private void FlushDeferredDiplomacyUi()
        {
            if (!CanPresentDiplomacyUi) return;
            if (!_mapActive || _mapDisabled) { ClearDeferredDiplomacyUi(); return; }
            while (_deferredSpeech.Count > 0)
            {
                DeferredDiplomacySpeech speech = _deferredSpeech.Peek();
                CoalitionState coalition;
                bool current = speech.Generation == _sessionGeneration
                    && string.Equals(speech.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                    && _coalitions.TryGetValue(speech.CoalitionId, out coalition);
                // A busy engine is a retry, never a reason to run UI inside its lock.
                if (current && !TryPlayCoalitionSpeechNow(
                        _coalitions[speech.CoalitionId], speech.MediaTag, speech.FileStem)) return;
                _deferredSpeech.Dequeue();
                _deferredSpeechKeys.Remove(speech.Key);
                if (current) return; // At most one queued voice per presentation pass.
            }
        }
    }
}
