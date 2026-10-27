#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private sealed class V2DeferredBreachNotice
        {
            internal string CoalitionId, Fingerprint, FirstDetail, LastDetail, Key;
            internal int[] Members;
            internal int FirstDay, LastDay, FirstCounter, LastCounter, Count;
            internal long Generation, Epoch;
            internal bool Enqueued;
        }

        // Only existing relation/coalition keys can enter this buffer: at most
        // seven AI coalitions on the eight-player map. Repeated genuine breaks
        // of one coalition are counted, not appended indefinitely or overwritten.
        // One additional frozen batch may be waiting in the shared dialog FIFO.
        private readonly List<V2DeferredBreachNotice> _v2DeferredBreachNotices =
            new List<V2DeferredBreachNotice>();
        private readonly Dictionary<string, int> _v2BreachNoticeCounters =
            new Dictionary<string, int>(StringComparer.Ordinal);
        private V2DeferredBreachNotice _v2BreachNoticeInFlight;

        // Called under _gate after the model commits. No UI, native read, speech
        // or logger is reached here, including when called by the native adapter.
        private void QueueV2BreachNotice(string coalitionId, int targetPlayer, string detail)
        {
            RelationState relation;
            CoalitionState coalition;
            if (!_mapActive || _mapDisabled || string.IsNullOrEmpty(coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation) || relation.V2 == null
                || !_coalitions.TryGetValue(coalitionId, out coalition)
                || coalition.MemberPlayerIds == null
                || !coalition.MemberPlayerIds.Contains(targetPlayer)) return;
            int counter = relation.V2.BrokenAgreements;
            int previous;
            if (counter <= 0 || _v2BreachNoticeCounters.TryGetValue(coalitionId, out previous)
                && counter <= previous) return;
            int day = Math.Max(0, _lastProcessedDay);
            V2DeferredBreachNotice pending = _v2DeferredBreachNotices.Find(
                item => item.CoalitionId == coalitionId
                    && item.Generation == _sessionGeneration && item.Epoch == _mapEpoch);
            if (pending == null)
            {
                pending = new V2DeferredBreachNotice
                {
                    CoalitionId = coalitionId, Members = coalition.MemberPlayerIds
                        .Where(player => player >= 1 && player <= 8).Distinct().OrderBy(player => player).ToArray(),
                    Generation = _sessionGeneration, Epoch = _mapEpoch, Fingerprint = _mapFingerprint,
                    FirstDay = day, LastDay = day, FirstCounter = counter, LastCounter = counter,
                    FirstDetail = detail, LastDetail = detail, Count = 1,
                };
                _v2DeferredBreachNotices.Add(pending);
            }
            else
            {
                pending.LastDay = day;
                pending.LastCounter = counter;
                pending.LastDetail = detail;
                if (pending.Count < int.MaxValue) pending.Count++;
            }
            _v2BreachNoticeCounters[coalitionId] = counter;
        }

        private bool IsCurrentV2BreachNotice(V2DeferredBreachNotice notice)
        {
            RelationState relation;
            return notice != null && _mapActive && !_mapDisabled
                && notice.Generation == _sessionGeneration && notice.Epoch == _mapEpoch
                && string.Equals(notice.Fingerprint, _mapFingerprint, StringComparison.Ordinal)
                && _relations.TryGetValue(notice.CoalitionId, out relation) && relation.V2 != null
                // A later agreement must not erase the historical message. A
                // rollback that removed this break, however, invalidates it.
                && relation.V2.BrokenAgreements >= notice.LastCounter;
        }

        private void CompleteV2BreachNotice(V2DeferredBreachNotice notice)
        {
            lock (_gate)
            {
                if (ReferenceEquals(_v2BreachNoticeInFlight, notice))
                    _v2BreachNoticeInFlight = null;
            }
        }

        private void ClearV2DeferredNotices()
        {
            V2DeferredBreachNotice old = _v2BreachNoticeInFlight;
            _v2BreachNoticeInFlight = null;
            _v2DeferredBreachNotices.Clear();
            _v2BreachNoticeCounters.Clear();
            if (old != null && old.Key != null) CancelDiplomacyDialog(old.Key);
        }

        private void FlushV2DeferredNotice()
        {
            V2DeferredBreachNotice notice = _v2BreachNoticeInFlight;
            if (notice != null && !IsCurrentV2BreachNotice(notice))
            {
                _v2BreachNoticeInFlight = null;
                if (notice.Key != null) CancelDiplomacyDialog(notice.Key);
                notice = null;
            }
            _v2DeferredBreachNotices.RemoveAll(item => !IsCurrentV2BreachNotice(item));
            if (!CanPresentDiplomacyUi || !_mapActive || _mapDisabled) return;
            if (notice != null && notice.Enqueued)
            {
                if (_dialogQueue.ContainsKey(notice.Key)) return;
                // An external cancellation/completed callback must not block
                // every later notice merely because our callback did not run.
                _v2BreachNoticeInFlight = null;
                notice = null;
            }
            if (notice == null)
            {
                if (_v2DeferredBreachNotices.Count == 0) return;
                notice = _v2DeferredBreachNotices[0];
                _v2DeferredBreachNotices.RemoveAt(0);
                notice.Key = "breach_notice:" + notice.Generation.ToString(CultureInfo.InvariantCulture)
                    + ":" + notice.Epoch.ToString(CultureInfo.InvariantCulture) + ":" + notice.CoalitionId
                    + ":" + notice.FirstCounter.ToString(CultureInfo.InvariantCulture)
                    + ":" + notice.LastCounter.ToString(CultureInfo.InvariantCulture);
                _v2BreachNoticeInFlight = notice;
            }
            if (_dialogQueue.ContainsKey(notice.Key))
            {
                // Enqueue may have succeeded before a presentation exception.
                notice.Enqueued = true;
                return;
            }
            V2DeferredBreachNotice captured = notice;
            try
            {
                string names = string.Join(", ", notice.Members.Select(V2PlayerName).ToArray());
                string message = notice.Count == 1
                    ? string.Format(CultureInfo.InvariantCulture,
                        Text("Euer Angriff hat das Abkommen mit {0} gebrochen (Tag {1}).",
                            "Your attack broke the agreement with {0} (day {1})."), names, notice.FirstDay)
                    : string.Format(CultureInfo.InvariantCulture,
                        Text("Eure Angriffe haben {0} Abkommen mit {1} gebrochen (Tag {2}–{3}).",
                            "Your attacks broke {0} agreements with {1} (days {2}–{3})."),
                        notice.Count, names, notice.FirstDay, notice.LastDay);
                bool queued = EnqueueDiplomacyDialog(
                    Text("Abkommen gebrochen", "Agreement broken"),
                    delegate { CompleteV2BreachNotice(captured); },
                    delegate { CompleteV2BreachNotice(captured); },
                    message, true, null, notice.Key,
                    delegate { lock (_gate) return IsCurrentV2BreachNotice(captured); });
                notice.Enqueued = queued || _dialogQueue.ContainsKey(notice.Key);
                if (notice.Enqueued)
                    Log("agreement", "coalition=" + notice.CoalitionId
                        + "|status=broken|actor=player_attack|events=" + notice.Count.ToString(CultureInfo.InvariantCulture)
                        + "|first_counter=" + notice.FirstCounter.ToString(CultureInfo.InvariantCulture)
                        + "|last_counter=" + notice.LastCounter.ToString(CultureInfo.InvariantCulture)
                        + (string.IsNullOrEmpty(notice.FirstDetail) ? "" : "|first=" + notice.FirstDetail)
                        + (string.IsNullOrEmpty(notice.LastDetail) ? "" : "|last=" + notice.LastDetail));
            }
            catch
            {
                // Keep the same frozen batch and key. A pre-enqueue failure is
                // retried; an already inserted dialog is never duplicated.
                notice.Enqueued = _dialogQueue.ContainsKey(notice.Key);
            }
        }
    }
}
#endif
