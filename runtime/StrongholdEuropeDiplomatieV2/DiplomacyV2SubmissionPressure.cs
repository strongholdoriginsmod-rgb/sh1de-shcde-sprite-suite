#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private sealed class V2MilitaryPosition
        {
            internal int Owner, X, Y;
            internal long Value;
        }

        private V2MilitaryPosition[] _v2MilitaryPositions;
        private Dictionary<int, int> _v2MilitaryTeams;
        private long _v2MilitaryByPlayerTick = long.MinValue;
        private long _v2MilitaryGeneration = -1;
        private long _v2MilitaryEpoch = -1;
        private long _v2MilitaryFailedTick = long.MinValue;
        private long _v2MilitaryFailedGeneration = -1;
        private long _v2MilitaryFailedEpoch = -1;
        private int _v2MilitaryFailedDay = -1;
        private long _v2SubmissionQuoteReviewTick = long.MinValue;
        private readonly Dictionary<string, int> _v2SubmissionVerifiedQuotes =
            new Dictionary<string, int>(StringComparer.Ordinal);

        private void ClearV2SubmissionPressure()
        {
            _v2MilitaryPositions = null;
            _v2MilitaryTeams = null;
            _v2MilitaryByPlayerTick = long.MinValue;
            _v2MilitaryGeneration = _v2MilitaryEpoch = -1;
            _v2MilitaryFailedTick = long.MinValue;
            _v2MilitaryFailedGeneration = _v2MilitaryFailedEpoch = -1;
            _v2MilitaryFailedDay = -1;
            _v2SubmissionQuoteReviewTick = long.MinValue;
            _v2SubmissionVerifiedQuotes.Clear();
        }

        // This is an engine observation, not the persisted diplomacy pressure
        // history. Never reuse positions after Load, a map change, or movement
        // during a later simulation tick when taking a new decision.
        private bool TryV2SubmissionPressureBand(int player, int lord, int day, out int band)
        {
            try { return CaptureV2SubmissionPressureBand(player, lord, day, out band); }
            catch (Exception exception)
            {
                band = 0;
                V2NoteVassalOrderFault("submission_pressure", exception);
                return false;
            }
        }

        private bool CaptureV2SubmissionPressureBand(int player, int lord, int day, out int band)
        {
            RequireNativeDiplomacySection();
            band = 0;
            if (player < 1 || player > 8 || player == _localPlayer) return false;
            // An unfinished castle scan cannot masquerade as an empty castle.
            // In particular it must not omit allied defenders. The completed
            // snapshot is what guarantees that: _v2CastleBoundaries is only
            // ever replaced by a finished scan, and _v2CastleSnapshotReady is
            // only cleared when the map changes.
            //
            // 08.09.2026: this used to also reject a running rescan and a
            // pending refresh request, which made the whole feature
            // unreachable in a real game. Every building, wall, demolition and
            // bulldoze sets _v2CastleRefreshRequested, and it is only cleared
            // when the NEXT scan starts - at which point _v2CastleBuilder is
            // non-null. A full scan needs 800*800/4096 = 157 ticks plus the
            // geometry pass, so in any live map with eight builders the three
            // conditions were never simultaneously true and the answer was
            // permanently "still being assessed". A rescan means the data may
            // age, not that there is no data.
            if (!_v2CastleSnapshotReady || _v2CastleEpoch != _mapEpoch)
                return false;
            long tick = ReadSimulationTick();
            if (_v2MilitaryFailedTick == tick && _v2MilitaryFailedDay == day
                && _v2MilitaryFailedGeneration == _sessionGeneration && _v2MilitaryFailedEpoch == _mapEpoch)
                return false;
            V2WorldForceUnit keep;
            if (!V2TryGetFixedKeepCenter(player, out keep)) return false;
            Dictionary<int, long> military;
            try { military = V2MilitaryByPlayer(day, true); }
            catch
            {
                // Only the shared unit/team observation is negatively cached.
                // A missing target keep must not poison other rulers' answers.
                // This suppresses repeated full failed scans in one simulation
                // tick while automatically retrying the next tick/map/session.
                _v2MilitaryFailedTick = tick;
                _v2MilitaryFailedDay = day;
                _v2MilitaryFailedGeneration = _sessionGeneration;
                _v2MilitaryFailedEpoch = _mapEpoch;
                throw;
            }
            if (_v2MilitaryPositions == null || _v2MilitaryTeams == null) return false;
            int targetTeam;
            if (!_v2MilitaryTeams.TryGetValue(player, out targetTeam)) return false;
            DiplomacyCastleBoundary boundary = null;
            DiplomacyCastleBoundary[] boundaries = Volatile.Read(ref _v2CastleBoundaries);
            if (boundaries != null && player < boundaries.Length)
                boundary = boundaries[player];
            var zone = new V2TreatyZone { Owner = player, X = keep.X, Y = keep.Y, Boundary = boundary };
            int attackingUnits = 0;
            long attacking = 0, defending = 0;
            foreach (V2MilitaryPosition unit in _v2MilitaryPositions)
            {
                if (!V2InsideTreatyZone(zone, unit.X, unit.Y)) continue;
                if (unit.Owner == _localPlayer)
                {
                    attackingUnits++;
                    attacking = SaturatingAdd(attacking, unit.Value);
                }
                else
                {
                    int unitTeam;
                    // Team0 denotes independent players, not a mutual alliance.
                    // Only actual native allies physically in this castle add
                    // to its defense; distant third-party forces count nowhere.
                    if (unit.Owner == player || targetTeam > 0
                        && _v2MilitaryTeams.TryGetValue(unit.Owner, out unitTeam)
                        && unitTeam == targetTeam)
                        defending = SaturatingAdd(defending, unit.Value);
                }
            }
            long own, target;
            military.TryGetValue(_localPlayer, out own);
            military.TryGetValue(player, out target);
            band = DiplomacyV2Submission.PressureBand(lord, own, target,
                attackingUnits, attacking, defending);
            return true;
        }

        // No native inventory operation is discarded to remove old support.
        // The frame caller holds _gate; live/loaded journals finish first.
        private void NormalizeV2VassalDemands()
        {
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null) return;
            foreach (RelationState relation in _relations.Values)
            {
                if (relation.V2 != null && DiplomacyV2Vassalage.IsActive(relation.V2))
                    DiplomacyV2StateMachine.SuspendVassalMaintenance(relation);
                WithdrawV2LegacyAllianceSubjugation(relation);
            }
        }

        private void WithdrawV2LegacyAllianceSubjugation(RelationState relation)
        {
            if (_inventoryRestorePending || _nativeTransferProbe != null
                || _pendingPackage != null || _pendingTeamTransition != null
                || relation == null || relation.V2 == null
                || DiplomacyV2Vassalage.IsActive(relation.V2)
                || relation.V2.PendingVassalOverlordPlayerId == 0) return;
            DiplomacyV2Vassalage.ClearPendingOffer(relation.V2);
            CancelDiplomacyDialog("subjugation:" + relation.CoalitionId);
            Log("vassalage", "coalition=" + relation.CoalitionId
                + "|status=legacy_alliance_submission_withdrawn|reason=no_hostile_siege");
        }
    }
}
#endif
