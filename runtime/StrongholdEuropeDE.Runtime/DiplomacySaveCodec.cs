using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal static class DiplomacySaveCodec
    {
        private static readonly byte[] Magic =
            Encoding.ASCII.GetBytes("SEDE-DIP-V1C\0");
        // Original 2026-08 V1 writer (verified against the archived runtime DLL):
        // identical core body, ending immediately after PendingTeamTransition.
        // It wrote neither the OTM1 baseline extension nor a SHA2 trailer.
        private static readonly byte[] OriginalLegacyMagic =
            Encoding.ASCII.GetBytes("SEDE-DIP-V1\0");
        private static readonly byte[] OriginalTeamsMagic =
            Encoding.ASCII.GetBytes("OTM1");
        private static readonly byte[] ChecksumMagic =
            Encoding.ASCII.GetBytes("SHA2");
        private static readonly byte[] InactiveMagic = Encoding.ASCII.GetBytes("SEDE-DIP-INACTIVE\0");
        private const int ChecksumLength = 32;
        private const int MaximumPayloadBytes = 64 * 1024;
        private static readonly HashSet<int> SendableGoods =
            new HashSet<int>
            {
                2, 3, 4, 6, 7,
                9, 10, 11, 12, 13, 14, 15, 16,
                17, 18, 19, 20, 21, 22, 23, 24,
            };

        internal static byte[] SerializeInactive(string reason)
        {
            byte[] detail = Encoding.UTF8.GetBytes((reason ?? "inactive").Substring(0, Math.Min(128, (reason ?? "inactive").Length)));
            byte[] data = new byte[InactiveMagic.Length + detail.Length];
            Buffer.BlockCopy(InactiveMagic, 0, data, 0, InactiveMagic.Length);
            Buffer.BlockCopy(detail, 0, data, InactiveMagic.Length, detail.Length);
            using (SHA256 sha = SHA256.Create())
            {
                byte[] checksum = sha.ComputeHash(data);
                return data.Concat(checksum).ToArray();
            }
        }

        internal static bool IsInactive(byte[] payload)
        {
            if (payload == null || payload.Length < InactiveMagic.Length + ChecksumLength
                || payload.Length > InactiveMagic.Length + 512 + ChecksumLength
                || !payload.Take(InactiveMagic.Length).SequenceEqual(InactiveMagic)) return false;
            using (SHA256 sha = SHA256.Create())
                return sha.ComputeHash(payload, 0, payload.Length - ChecksumLength)
                    .SequenceEqual(payload.Skip(payload.Length - ChecksumLength));
        }

        internal static byte[] Serialize(
            DiplomacySaveV1 state,
            DiplomacyRules rules = null,
            bool allowV2SubmissionJournal = false)
        {
            Validate(state, rules, allowV2SubmissionJournal);
            using (var stream = new MemoryStream())
            using (var writer = new BinaryWriter(stream, Encoding.UTF8, true))
            {
                writer.Write(Magic);
                writer.Write(state.SchemaVersion);
                WriteText(writer, state.MapFingerprint);
                WriteText(writer, state.RosterFingerprint);
                writer.Write(state.LocalPlayerId);
                writer.Write(state.LastProcessedDay);
                WritePairs(writer, state.FrozenPrices);
                WritePairs(writer, state.TeamPartition);
                writer.Write(state.Coalitions.Count);
                foreach (CoalitionState coalition in state.Coalitions
                    .OrderBy(value => value.CoalitionId, StringComparer.Ordinal))
                {
                    WriteText(writer, coalition.CoalitionId);
                    WriteInts(writer, coalition.MemberPlayerIds);
                    WriteInts(writer, coalition.OriginalTeams);
                    writer.Write(coalition.SendGoodsMargin);
                    writer.Write(coalition.Economy);
                    writer.Write(coalition.Military);
                    writer.Write(coalition.Target);
                    writer.Write(coalition.StartingAlly);
                    writer.Write(coalition.Allied);
                }
                writer.Write(state.Relations.Count);
                foreach (RelationState relation in state.Relations
                    .OrderBy(value => value.CoalitionId, StringComparer.Ordinal))
                {
                    WriteText(writer, relation.CoalitionId);
                    WriteDecimal(writer, relation.Goodwill);
                    writer.Write(relation.LastGiftDay);
                    writer.Write(relation.LastProcessedDay);
                    writer.Write(relation.LastOfferAttemptDay);
                    writer.Write(relation.OfferAttemptCounter);
                    WriteDecimal(writer, relation.GiftValueSinceOfferAttempt);
                    writer.Write(relation.SpontaneousOfferBlockedUntilDay);
                    writer.Write(relation.RelationshipBlockedUntilDay);
                    writer.Write(relation.AllianceGraceUntilDay);
                    writer.Write(relation.Allied);
                    writer.Write(relation.StartingAlliance);
                    writer.Write(relation.PendingOffer);
                    writer.Write(relation.PendingOfferIssuedDay);
                    WriteDemand(writer, relation.Demand);
                }
                WritePendingTransfer(writer, state.PendingTransfer);
                WritePendingTeamTransition(
                    writer,
                    state.PendingTeamTransition);
                writer.Write(OriginalTeamsMagic);
                WritePairs(writer, state.OriginalTeamPartition);
                writer.Flush();
                byte[] canonical = stream.ToArray();
                byte[] checksum;
                using (SHA256 sha = SHA256.Create())
                {
                    checksum = sha.ComputeHash(canonical);
                }
                writer.Write(ChecksumMagic);
                writer.Write(checksum);
                writer.Flush();
                if (stream.Length > MaximumPayloadBytes)
                {
                    throw new InvalidDataException("diplomacy save payload is oversized");
                }
                return stream.ToArray();
            }
        }

        internal static DiplomacySaveV1 Deserialize(
            byte[] payload,
            DiplomacyRules rules = null,
            bool allowV2SubmissionJournal = false)
        {
            if (IsInactive(payload)) throw new InvalidDataException("diplomacy save is explicitly inactive");
            if (payload == null || payload.Length < OriginalLegacyMagic.Length + 4
                || payload.Length > MaximumPayloadBytes)
            {
                throw new InvalidDataException("diplomacy save payload size is invalid");
            }
            bool originalLegacy = IsOriginalLegacyPayload(payload);
            byte[] expectedMagic = originalLegacy ? OriginalLegacyMagic : Magic;
            using (var stream = new MemoryStream(payload, false))
            using (var reader = new BinaryReader(stream, new UTF8Encoding(false, true), true))
            {
                byte[] magic = reader.ReadBytes(expectedMagic.Length);
                if (!magic.SequenceEqual(expectedMagic))
                {
                    throw new InvalidDataException("diplomacy save magic mismatch");
                }
                var state = new DiplomacySaveV1
                {
                    SchemaVersion = reader.ReadInt32(),
                    MapFingerprint = ReadText(reader),
                    RosterFingerprint = ReadText(reader),
                    LocalPlayerId = reader.ReadInt32(),
                    LastProcessedDay = reader.ReadInt32(),
                    FrozenPrices = ReadPairs(reader, 24),
                    TeamPartition = ReadPairs(reader, 8),
                };
                int coalitionCount = ReadCount(reader, 8, "coalitions");
                for (int index = 0; index < coalitionCount; index++)
                {
                    state.Coalitions.Add(new CoalitionState
                    {
                        CoalitionId = ReadText(reader),
                        MemberPlayerIds = ReadInts(reader, 8),
                        OriginalTeams = ReadInts(reader, 8),
                        SendGoodsMargin = reader.ReadInt32(),
                        Economy = reader.ReadInt64(),
                        Military = reader.ReadInt64(),
                        Target = reader.ReadInt32(),
                        StartingAlly = ReadBoolean(reader),
                        Allied = ReadBoolean(reader),
                    });
                }
                int relationCount = ReadCount(reader, 8, "relations");
                for (int index = 0; index < relationCount; index++)
                {
                    state.Relations.Add(new RelationState
                    {
                        CoalitionId = ReadText(reader),
                        Goodwill = ReadDecimal(reader),
                        LastGiftDay = reader.ReadInt32(),
                        LastProcessedDay = reader.ReadInt32(),
                        LastOfferAttemptDay = reader.ReadInt32(),
                        OfferAttemptCounter = reader.ReadInt32(),
                        GiftValueSinceOfferAttempt = ReadDecimal(reader),
                        SpontaneousOfferBlockedUntilDay = reader.ReadInt32(),
                        RelationshipBlockedUntilDay = reader.ReadInt32(),
                        AllianceGraceUntilDay = reader.ReadInt32(),
                        Allied = ReadBoolean(reader),
                        StartingAlliance = ReadBoolean(reader),
                        PendingOffer = ReadBoolean(reader),
                        PendingOfferIssuedDay = reader.ReadInt32(),
                        Demand = ReadDemand(reader),
                    });
                }
                state.PendingTransfer = ReadPendingTransfer(reader);
                state.PendingTeamTransition =
                    ReadPendingTeamTransition(reader);
                if (originalLegacy)
                {
                    if (stream.Position != stream.Length)
                        throw new InvalidDataException("original diplomacy V1 save has trailing data");
                    RestoreOriginalLegacyBaseline(state);
                    Validate(state, rules);
                    return state;
                }
                byte[] originalTeamsMagic = reader.ReadBytes(
                    OriginalTeamsMagic.Length);
                if (!originalTeamsMagic.SequenceEqual(
                    OriginalTeamsMagic))
                {
                    throw new InvalidDataException(
                        "diplomacy save original-team extension is missing");
                }
                state.OriginalTeamPartition = ReadPairs(reader, 8);
                long canonicalLength = stream.Position;
                long remaining = stream.Length - canonicalLength;
                if (remaining != ChecksumMagic.Length + ChecksumLength)
                {
                    throw new InvalidDataException(
                        "diplomacy save checksum trailer is missing");
                }
                byte[] checksumMagic = reader.ReadBytes(
                    ChecksumMagic.Length);
                byte[] savedChecksum = reader.ReadBytes(ChecksumLength);
                byte[] expectedChecksum;
                using (SHA256 sha = SHA256.Create())
                {
                    expectedChecksum = sha.ComputeHash(
                        payload,
                        0,
                        checked((int)canonicalLength));
                }
                if (!checksumMagic.SequenceEqual(ChecksumMagic)
                    || savedChecksum.Length != ChecksumLength
                    || !savedChecksum.SequenceEqual(expectedChecksum))
                {
                    throw new InvalidDataException(
                        "diplomacy save checksum mismatch");
                }
                Validate(state, rules, allowV2SubmissionJournal);
                return state;
            }
        }

        internal static bool IsOriginalLegacyPayload(byte[] payload)
        {
            return payload != null && payload.Length >= OriginalLegacyMagic.Length
                && payload.Take(OriginalLegacyMagic.Length).SequenceEqual(OriginalLegacyMagic);
        }

        private static void RestoreOriginalLegacyBaseline(DiplomacySaveV1 state)
        {
            if (state.LocalPlayerId < 1 || state.LocalPlayerId > 8)
                throw new InvalidDataException("original diplomacy V1 local player is invalid");
            var baseline = new Dictionary<int, int>();
            int localOriginalTeam = 0;
            foreach (CoalitionState coalition in state.Coalitions)
            {
                if (coalition.MemberPlayerIds.Length == 0
                    || coalition.MemberPlayerIds.Length != coalition.OriginalTeams.Length)
                    throw new InvalidDataException("original diplomacy V1 coalition baseline is invalid");
                for (int index = 0; index < coalition.MemberPlayerIds.Length; index++)
                {
                    int member = coalition.MemberPlayerIds[index];
                    if (member == state.LocalPlayerId || baseline.ContainsKey(member))
                        throw new InvalidDataException("original diplomacy V1 coalition roster overlaps");
                    baseline.Add(member, coalition.OriginalTeams[index]);
                }
                if (coalition.StartingAlly)
                {
                    int team = coalition.OriginalTeams[0];
                    if (team < 1 || team > 8 || coalition.OriginalTeams.Any(value => value != team)
                        || localOriginalTeam != 0 && localOriginalTeam != team)
                        throw new InvalidDataException("original diplomacy V1 starting alliance is inconsistent");
                    localOriginalTeam = team;
                }
            }
            // The old writer never stored the local player's original team.
            // A starting ally proves its positive team. Otherwise only the
            // original singleton relationship is known: normalize its rollback
            // baseline to neutral team 0, never borrow a present allied team's
            // identity. This is a documented normalization, not recovered data.
            // TeamPartition and every currently active alliance remain untouched.
            baseline.Add(state.LocalPlayerId, localOriginalTeam);
            state.OriginalTeamPartition = baseline;
        }

        internal static void Validate(
            DiplomacySaveV1 state,
            DiplomacyRules rules = null,
            bool allowV2SubmissionJournal = false)
        {
            rules = rules ?? new DiplomacyRules();
            string rulesFailure = rules.Validate();
            if (rulesFailure != null)
            {
                throw new InvalidDataException(
                    "diplomacy save rules are invalid: " + rulesFailure);
            }
            if (state == null || state.SchemaVersion != DiplomacyRules.SchemaVersion)
            {
                throw new InvalidDataException("diplomacy save schema mismatch");
            }
            ValidateText(state.MapFingerprint, "map fingerprint");
            ValidateText(state.RosterFingerprint, "roster fingerprint");
            if (state.LocalPlayerId < 1 || state.LocalPlayerId > 8
                || !DiplomacyLogicalClock.IsValidSavedDay(
                    state.LastProcessedDay)
                || state.FrozenPrices == null
                || state.FrozenPrices.Count < 1
                || state.FrozenPrices.Count > 24
                || state.TeamPartition == null
                || state.TeamPartition.Count < 2
                || state.TeamPartition.Count > 8
                || state.OriginalTeamPartition == null
                || state.OriginalTeamPartition.Count < 2
                || state.OriginalTeamPartition.Count > 8
                || state.Coalitions == null
                || state.Coalitions.Count < 1
                || state.Coalitions.Count > 7
                || state.Relations == null
                || state.Relations.Count != state.Coalitions.Count)
            {
                throw new InvalidDataException("diplomacy save top-level shape is invalid");
            }
            if (!SendableGoods.SetEquals(state.FrozenPrices.Keys)
                || !state.TeamPartition.ContainsKey(state.LocalPlayerId)
                || !new HashSet<int>(state.OriginalTeamPartition.Keys)
                    .SetEquals(state.TeamPartition.Keys))
            {
                throw new InvalidDataException(
                    "diplomacy save price or local-team roster is incomplete");
            }
            foreach (KeyValuePair<int, int> price in state.FrozenPrices)
            {
                if (price.Key < 1 || price.Key > 24 || price.Value < 1
                    || price.Value > 100000)
                {
                    throw new InvalidDataException("diplomacy price is invalid");
                }
            }
            foreach (KeyValuePair<int, int> team in state.TeamPartition)
            {
                if (team.Key < 1 || team.Key > 8 || team.Value < 0 || team.Value > 8)
                {
                    throw new InvalidDataException("diplomacy team partition is invalid");
                }
            }
            foreach (KeyValuePair<int, int> team
                in state.OriginalTeamPartition)
            {
                if (team.Key < 1 || team.Key > 8
                    || team.Value < 0 || team.Value > 8)
                {
                    throw new InvalidDataException(
                        "diplomacy original team partition is invalid");
                }
            }
            var coalitionIds = new HashSet<string>(StringComparer.Ordinal);
            var coalitionMembers = new HashSet<int>();
            foreach (CoalitionState coalition in state.Coalitions)
            {
                if (coalition == null)
                {
                    throw new InvalidDataException("diplomacy coalition is null");
                }
                ValidateText(coalition.CoalitionId, "coalition id");
                if (!coalitionIds.Add(coalition.CoalitionId)
                    || coalition.MemberPlayerIds == null
                    || coalition.OriginalTeams == null
                    || coalition.MemberPlayerIds.Length < 1
                    || coalition.MemberPlayerIds.Length > 7
                    || coalition.OriginalTeams.Length != coalition.MemberPlayerIds.Length
                    || coalition.MemberPlayerIds.Distinct().Count()
                        != coalition.MemberPlayerIds.Length
                    || coalition.MemberPlayerIds.Any(value => value < 1 || value > 8)
                    || coalition.OriginalTeams.Any(value => value < 0 || value > 8)
                    || coalition.SendGoodsMargin < 0
                    || coalition.SendGoodsMargin > 100
                    || coalition.Economy < 0
                    || coalition.Military < 0
                    || coalition.Target < rules.TargetMinimum
                    || coalition.Target > rules.TargetMaximum
                    || coalition.Target != DiplomacyBalance.CalculateTarget(
                        coalition.Economy,
                        coalition.Military,
                        coalition.SendGoodsMargin,
                        rules))
                {
                    throw new InvalidDataException("diplomacy coalition shape is invalid");
                }
                foreach (int player in coalition.MemberPlayerIds)
                {
                    if (player == state.LocalPlayerId
                        || !coalitionMembers.Add(player)
                        || !state.TeamPartition.ContainsKey(player))
                    {
                        throw new InvalidDataException(
                            "diplomacy coalition player partition is invalid");
                    }
                }
                for (int index = 0;
                    index < coalition.MemberPlayerIds.Length;
                    index++)
                {
                    if (state.OriginalTeamPartition[
                            coalition.MemberPlayerIds[index]]
                        != coalition.OriginalTeams[index])
                    {
                        throw new InvalidDataException(
                            "diplomacy coalition original teams differ from "
                            + "the saved baseline");
                    }
                }
                int originalLocalTeam = state.OriginalTeamPartition[
                    state.LocalPlayerId];
                bool originallyAllied = originalLocalTeam > 0
                    && coalition.OriginalTeams.All(
                        team => team == originalLocalTeam);
                if (coalition.StartingAlly != originallyAllied)
                {
                    throw new InvalidDataException(
                        "diplomacy starting alliance differs from the saved "
                        + "original team baseline");
                }
                ValidateCoalitionIdentity(coalition);
            }
            if (coalitionMembers.Count + 1 != state.TeamPartition.Count)
            {
                throw new InvalidDataException(
                    "diplomacy coalition roster is incomplete");
            }
            var relationIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (RelationState relation in state.Relations)
            {
                if (relation == null)
                {
                    throw new InvalidDataException("diplomacy relation is null");
                }
                ValidateText(relation.CoalitionId, "relation coalition id");
                if (!relationIds.Add(relation.CoalitionId)
                    || relation.Goodwill < 0m
                    || relation.GiftValueSinceOfferAttempt < 0m
                    || relation.OfferAttemptCounter < 0
                    || relation.LastGiftDay < -1
                    || relation.LastProcessedDay < -1
                    || relation.LastOfferAttemptDay < -1
                    || relation.LastProcessedDay != state.LastProcessedDay
                    || relation.LastGiftDay > state.LastProcessedDay
                    || relation.LastOfferAttemptDay > state.LastProcessedDay
                    || relation.SpontaneousOfferBlockedUntilDay < 0
                    || relation.RelationshipBlockedUntilDay < 0
                    || relation.AllianceGraceUntilDay < 0
#if DIPLOMACY_V2
                    || relation.SpontaneousOfferBlockedUntilDay
                        > state.LastProcessedDay + 365
                    || relation.RelationshipBlockedUntilDay
                        > state.LastProcessedDay + 365
#else
                    || relation.SpontaneousOfferBlockedUntilDay
                        > state.LastProcessedDay + rules.BreakLockDays
                    || relation.RelationshipBlockedUntilDay
                        > state.LastProcessedDay + rules.BreakLockDays
#endif
                    || relation.AllianceGraceUntilDay
                        > state.LastProcessedDay
                            + rules.StartingAllianceGraceDays
                    || relation.StartingAlliance && !relation.Allied
                    || relation.PendingOffer
                        && (relation.Allied
                            || relation.Demand != null
                            || relation.OfferAttemptCounter < 1
                            || relation.PendingOfferIssuedDay < 0
                            || relation.PendingOfferIssuedDay
                                > state.LastProcessedDay
                            || relation.LastOfferAttemptDay
                                != relation.PendingOfferIssuedDay)
                    || !relation.PendingOffer
                        && relation.PendingOfferIssuedDay != -1
                    || relation.Demand != null
                        && relation.Demand.IsUltimatum != relation.Allied)
                {
                    throw new InvalidDataException("diplomacy relation shape is invalid");
                }
                ValidateDemand(
                    relation.Demand,
                    state.LastProcessedDay,
                    state.FrozenPrices,
                    rules,
                    state.PendingTeamTransition != null
                        && state.PendingTeamTransition.Kind
                            == DiplomacyTeamTransitionKind.FormAlliance
                        && string.Equals(
                            state.PendingTeamTransition.CoalitionId,
                            relation.CoalitionId,
                            StringComparison.Ordinal),
                    state.PendingTeamTransition != null
                        && state.PendingTeamTransition.Kind
                            == DiplomacyTeamTransitionKind.AiBreak
                        && string.Equals(
                            state.PendingTeamTransition.CoalitionId,
                            relation.CoalitionId,
                            StringComparison.Ordinal));
            }
            if (!coalitionIds.SetEquals(relationIds))
            {
                throw new InvalidDataException("diplomacy relation roster mismatch");
            }
            var coalitionsById = state.Coalitions.ToDictionary(
                coalition => coalition.CoalitionId,
                StringComparer.Ordinal);
            foreach (RelationState relation in state.Relations)
            {
                CoalitionState coalition =
                    coalitionsById[relation.CoalitionId];
                if (coalition.Allied != relation.Allied
                    || relation.StartingAlliance
                        && !coalition.StartingAlly)
                {
                    throw new InvalidDataException(
                        "diplomacy coalition relation state is inconsistent");
                }
            }
            if (state.PendingPackage != null)
                throw new InvalidDataException("V1 cannot represent a package recovery journal");
            if (state.PendingTransfer != null
                && state.PendingTeamTransition != null)
            {
                throw new InvalidDataException(
                    "diplomacy save cannot contain concurrent native operations");
            }
            ValidateCurrentTeamPartition(state, coalitionsById);
            ValidatePendingTransfer(state, coalitionsById);
            ValidatePendingTeamTransition(state, coalitionsById, allowV2SubmissionJournal);
        }

        private static void ValidateCurrentTeamPartition(
            DiplomacySaveV1 state,
            IReadOnlyDictionary<string, CoalitionState> coalitionsById)
        {
            int localTeam = state.TeamPartition[state.LocalPlayerId];
            var hostilePositiveTeams = new HashSet<int>();
            foreach (RelationState relation in state.Relations)
            {
                CoalitionState coalition =
                    coalitionsById[relation.CoalitionId];
                int[] teams = coalition.MemberPlayerIds.Select(
                    player => state.TeamPartition[player]).ToArray();
                if (teams.Distinct().Count() != 1)
                {
                    throw new InvalidDataException(
                        "saved team partition splits an original coalition");
                }
                bool nativeAllied = localTeam > 0
                    && teams[0] > 0
                    && teams[0] == localTeam;
                if (nativeAllied != relation.Allied)
                {
                    throw new InvalidDataException(
                        "saved native teams contradict diplomacy relations");
                }
                if (!relation.Allied
                    && teams[0] > 0
                    && !hostilePositiveTeams.Add(teams[0]))
                {
                    throw new InvalidDataException(
                        "saved native teams merge hostile coalitions");
                }
            }
        }

        private static void WritePendingTeamTransition(
            BinaryWriter writer,
            DiplomacyPendingTeamTransition transition)
        {
            writer.Write(transition != null);
            if (transition == null)
            {
                return;
            }
            writer.Write((int)transition.Kind);
            WriteText(
                writer,
                string.IsNullOrEmpty(transition.CoalitionId)
                    ? "-"
                    : transition.CoalitionId);
            writer.Write(transition.GameDay);
            WriteText(
                writer,
                string.IsNullOrEmpty(transition.Reason)
                    ? "unspecified"
                    : transition.Reason);
            WritePairs(writer, transition.ExpectedPartition);
            WritePairs(writer, transition.TargetPartition);
        }

        private static DiplomacyPendingTeamTransition
            ReadPendingTeamTransition(BinaryReader reader)
        {
            if (!ReadBoolean(reader))
            {
                return null;
            }
            DiplomacyTeamTransitionKind kind =
                (DiplomacyTeamTransitionKind)reader.ReadInt32();
            string coalitionId = ReadText(reader);
            int gameDay = reader.ReadInt32();
            string reason = ReadText(reader);
            return new DiplomacyPendingTeamTransition
            {
                Kind = kind,
                CoalitionId = coalitionId == "-" ? null : coalitionId,
                GameDay = gameDay,
                Reason = reason,
                ExpectedPartition = ReadPairs(reader, 8),
                TargetPartition = ReadPairs(reader, 8),
            };
        }

        private static void ValidatePendingTeamTransition(
            DiplomacySaveV1 state,
            IReadOnlyDictionary<string, CoalitionState> coalitionsById,
            bool allowV2SubmissionJournal)
        {
            DiplomacyPendingTeamTransition transition =
                state.PendingTeamTransition;
            if (transition == null)
            {
                return;
            }
            if (!Enum.IsDefined(
                    typeof(DiplomacyTeamTransitionKind),
                    transition.Kind)
                || transition.GameDay < 0
                || transition.GameDay != state.LastProcessedDay
                || transition.ExpectedPartition == null
                || transition.TargetPartition == null
                || !new HashSet<int>(transition.ExpectedPartition.Keys)
                    .SetEquals(state.TeamPartition.Keys)
                || !new HashSet<int>(transition.TargetPartition.Keys)
                    .SetEquals(state.TeamPartition.Keys)
                || transition.ExpectedPartition.Any(entry =>
                    entry.Value < 0 || entry.Value > 8)
                || transition.TargetPartition.Any(entry =>
                    entry.Value < 1 || entry.Value > 8)
                || !transition.ExpectedPartition.OrderBy(entry => entry.Key)
                    .SequenceEqual(state.TeamPartition
                        .OrderBy(entry => entry.Key)))
            {
                throw new InvalidDataException(
                    "diplomacy pending team transition is invalid");
            }
            ValidateText(transition.Reason, "pending transition reason");
            if (transition.Kind
                    == DiplomacyTeamTransitionKind.PlayerBreakAll)
            {
                if (!string.IsNullOrEmpty(transition.CoalitionId))
                {
                    throw new InvalidDataException(
                        "player break transition has a coalition");
                }
                if (!state.Relations.Any(relation => relation.Allied))
                {
                    throw new InvalidDataException(
                        "player break transition has no alliance to end");
                }
            }
            else if (string.IsNullOrEmpty(transition.CoalitionId)
                || !coalitionsById.ContainsKey(transition.CoalitionId))
            {
                throw new InvalidDataException(
                    "diplomacy pending transition coalition is invalid");
            }
            if (transition.Kind != DiplomacyTeamTransitionKind.PlayerBreakAll)
            {
                RelationState relation = state.Relations.Single(value =>
                    string.Equals(
                        value.CoalitionId,
                        transition.CoalitionId,
                        StringComparison.Ordinal));
                if ((transition.Kind
                        == DiplomacyTeamTransitionKind.FormAlliance
                        && relation.Allied)
                    || (transition.Kind
                            == DiplomacyTeamTransitionKind.AiBreak
                        && !relation.Allied)
#if DIPLOMACY_V2
                    || (transition.Kind
                            == DiplomacyTeamTransitionKind.PlayerBreakOne
                        && !relation.Allied)
#endif
                    )
                {
                    throw new InvalidDataException(
                        "diplomacy pending transition relation is inconsistent");
                }
                CoalitionState coalition =
                    coalitionsById[transition.CoalitionId];
                bool submissionAuthorized = false;
#if DIPLOMACY_V2
                // The V2 envelope reads this base BEFORE its advanced state.
                // Only that explicit schema-9 path may provisionally accept
                // the journal; its outer validator must then validate the
                // complete accepted quote. Standalone V1C never opts in.
                submissionAuthorized = allowV2SubmissionJournal
                    && transition.Reason == "submission_offer"
                    && (relation.V2 == null || DiplomacyV2Submission.CanCommitOffer(relation));
#endif
                if (transition.Reason == "submission_offer" && !submissionAuthorized)
                    throw new InvalidDataException("submission journal requires its V2 envelope");
                if (transition.Kind
                        == DiplomacyTeamTransitionKind.FormAlliance
                    && (!state.Relations.Any(candidate =>
                            !candidate.Allied
                            && !string.Equals(
                                candidate.CoalitionId,
                                transition.CoalitionId,
                                StringComparison.Ordinal))
                        || !(relation.PendingOffer
                            || relation.Goodwill >= coalition.Target
                            || relation.Demand != null
                                && !relation.Demand.IsUltimatum
                                && relation.Demand.Complete
                            || submissionAuthorized)))
                {
                    throw new InvalidDataException(
                        "pending alliance transition is not authorized");
                }
                if (transition.Kind
                        == DiplomacyTeamTransitionKind.AiBreak
#if DIPLOMACY_V2
                    && transition.Reason != "tribute_default"
                    && transition.Reason != "vassal_rebellion"
#endif
                    && (relation.Demand == null
                        || !relation.Demand.IsUltimatum
                        || relation.Demand.Complete
                        || transition.GameDay < relation.Demand.ExpiresDay))
                {
                    throw new InvalidDataException(
                        "pending AI break has no expired ultimatum");
                }
            }
            ValidatePendingTransitionTarget(state, transition);
        }

        private static void ValidatePendingTransitionTarget(
            DiplomacySaveV1 state,
            DiplomacyPendingTeamTransition transition)
        {
            int localTeam = transition.TargetPartition[state.LocalPlayerId];
            var relations = state.Relations.ToDictionary(
                relation => relation.CoalitionId,
                StringComparer.Ordinal);
            var hostileTeams = new HashSet<int>();
            foreach (CoalitionState coalition in state.Coalitions)
            {
                int[] memberTeams = coalition.MemberPlayerIds.Select(
                    player => transition.TargetPartition[player]).ToArray();
                if (memberTeams.Distinct().Count() != 1)
                {
                    throw new InvalidDataException(
                        "pending transition splits an original coalition");
                }
                bool shouldBeAllied =
                    relations[coalition.CoalitionId].Allied;
                if (transition.Kind
                        == DiplomacyTeamTransitionKind.FormAlliance
                    && string.Equals(
                        transition.CoalitionId,
                        coalition.CoalitionId,
                        StringComparison.Ordinal))
                {
                    shouldBeAllied = true;
                }
                if (transition.Kind
                        == DiplomacyTeamTransitionKind.PlayerBreakAll
                    || (transition.Kind
                            == DiplomacyTeamTransitionKind.AiBreak
                        && string.Equals(
                            transition.CoalitionId,
                            coalition.CoalitionId,
                            StringComparison.Ordinal))
#if DIPLOMACY_V2
                    || (transition.Kind
                            == DiplomacyTeamTransitionKind.PlayerBreakOne
                        && string.Equals(
                            transition.CoalitionId,
                            coalition.CoalitionId,
                            StringComparison.Ordinal))
#endif
                    )
                {
                    shouldBeAllied = false;
                }
                bool targetIsAllied = memberTeams[0] == localTeam;
                if (targetIsAllied != shouldBeAllied)
                {
                    throw new InvalidDataException(
                        "pending transition target contradicts relation state");
                }
                if (!shouldBeAllied && !hostileTeams.Add(memberTeams[0]))
                {
                    throw new InvalidDataException(
                        "pending transition merges hostile coalitions");
                }
            }
        }

        private static void WritePendingTransfer(
            BinaryWriter writer,
            DiplomacyPendingTransfer transfer)
        {
            writer.Write(transfer != null);
            if (transfer == null)
            {
                return;
            }
            writer.Write(transfer.TargetPlayer);
            writer.Write(transfer.GoodId);
            writer.Write(transfer.Amount);
            writer.Write(transfer.SenderBefore);
            writer.Write(transfer.RecipientBefore);
            writer.Write(transfer.AlliedNativeTransfer);
        }

        private static DiplomacyPendingTransfer ReadPendingTransfer(
            BinaryReader reader)
        {
            if (!ReadBoolean(reader))
            {
                return null;
            }
            return new DiplomacyPendingTransfer
            {
                TargetPlayer = reader.ReadInt32(),
                GoodId = reader.ReadInt32(),
                Amount = reader.ReadInt32(),
                SenderBefore = reader.ReadInt32(),
                RecipientBefore = reader.ReadInt32(),
                AlliedNativeTransfer = ReadBoolean(reader),
            };
        }

        private static void ValidatePendingTransfer(
            DiplomacySaveV1 state,
            IReadOnlyDictionary<string, CoalitionState> coalitionsById)
        {
            DiplomacyPendingTransfer transfer = state.PendingTransfer;
            if (transfer == null)
            {
                return;
            }
            if (transfer.TargetPlayer < 1
                || transfer.RollbackPending || transfer.Progress != null
                || transfer.Purpose != DiplomacyTransferPurpose.Gift
                || transfer.SenderPlayer < 0
                || transfer.SenderPlayer > 0 && transfer.SenderPlayer != state.LocalPlayerId
                || transfer.TargetPlayer > 8
                || transfer.TargetPlayer == state.LocalPlayerId
                || !SendableGoods.Contains(transfer.GoodId)
                || transfer.Amount < 1
                || transfer.Amount > 1000000
                || transfer.SenderBefore < transfer.Amount
                || transfer.RecipientBefore < 0
                || transfer.RecipientBefore > int.MaxValue - transfer.Amount)
            {
                throw new InvalidDataException(
                    "diplomacy pending transfer is invalid");
            }
            CoalitionState targetCoalition = coalitionsById.Values
                .SingleOrDefault(coalition => coalition.MemberPlayerIds
                    .Contains(transfer.TargetPlayer));
            if (targetCoalition == null)
            {
                throw new InvalidDataException(
                    "diplomacy pending transfer target is not in the roster");
            }
            RelationState relation = state.Relations.Single(value =>
                string.Equals(
                    value.CoalitionId,
                    targetCoalition.CoalitionId,
                    StringComparison.Ordinal));
            if (transfer.AlliedNativeTransfer != relation.Allied)
            {
                throw new InvalidDataException(
                    "diplomacy pending transfer relation is inconsistent");
            }
        }

        private static void WriteDemand(BinaryWriter writer, GoodsDemand demand)
        {
            writer.Write(demand != null);
            if (demand == null)
            {
                return;
            }
            writer.Write(demand.IssuedDay);
            writer.Write(demand.ExpiresDay);
            writer.Write(demand.IsUltimatum);
            writer.Write(demand.Items.Length);
            foreach (DemandItem item in demand.Items)
            {
                writer.Write(item.GoodId);
                writer.Write(item.UnitValue);
                writer.Write(item.RequiredAmount);
                writer.Write(item.DeliveredAmount);
            }
        }

        private static GoodsDemand ReadDemand(BinaryReader reader)
        {
            if (!ReadBoolean(reader))
            {
                return null;
            }
            var demand = new GoodsDemand
            {
                IssuedDay = reader.ReadInt32(),
                ExpiresDay = reader.ReadInt32(),
                IsUltimatum = ReadBoolean(reader),
            };
            int count = ReadCount(reader, 3, "demand items");
            if (count < 1)
            {
                throw new InvalidDataException("diplomacy demand is empty");
            }
            demand.Items = new DemandItem[count];
            for (int index = 0; index < count; index++)
            {
                demand.Items[index] = new DemandItem
                {
                    GoodId = reader.ReadInt32(),
                    UnitValue = reader.ReadInt32(),
                    RequiredAmount = reader.ReadInt32(),
                    DeliveredAmount = reader.ReadInt32(),
                };
            }
            return demand;
        }

        private static void ValidateDemand(
            GoodsDemand demand,
            int lastProcessedDay,
            IReadOnlyDictionary<int, int> frozenPrices,
            DiplomacyRules rules,
            bool allowCompleteForPendingAlliance,
            bool allowExpiredForPendingBreak)
        {
            if (demand == null)
            {
                return;
            }
            if (demand.IssuedDay < 0
                || demand.IssuedDay > lastProcessedDay
                || lastProcessedDay >= demand.ExpiresDay
                    && !allowExpiredForPendingBreak
#if DIPLOMACY_V2
                || demand.ExpiresDay <= demand.IssuedDay
                || demand.ExpiresDay > demand.IssuedDay + 365
#else
                || demand.ExpiresDay
                    != demand.IssuedDay + (demand.IsUltimatum
                        ? rules.UltimatumLifetimeDays
                        : rules.DemandLifetimeDays)
#endif
                || demand.Items == null
                || demand.Items.Length < 1
                || demand.Items.Length > 3
                || demand.Items.Any(item => item == null
                    || !SendableGoods.Contains(item.GoodId)
                    || item.UnitValue < 1
                    || !frozenPrices.ContainsKey(item.GoodId)
                     || frozenPrices[item.GoodId] != item.UnitValue
                     || item.RequiredAmount < 1
                     || item.RequiredAmount > rules.TargetMaximum
                     || item.DeliveredAmount < 0
                     || item.DeliveredAmount > item.RequiredAmount)
                || demand.Items.Select(item => item.GoodId).Distinct().Count()
                    != demand.Items.Length
                || demand.Complete && !allowCompleteForPendingAlliance)
            {
                throw new InvalidDataException("diplomacy demand shape is invalid");
            }
        }

        private static void ValidateCoalitionIdentity(
            CoalitionState coalition)
        {
            const string TeamPrefix = "team:";
            const string PlayerPrefix = "player:";
            int parsed;
            if (coalition.CoalitionId.StartsWith(
                    TeamPrefix,
                    StringComparison.Ordinal)
                && int.TryParse(
                    coalition.CoalitionId.Substring(TeamPrefix.Length),
                    out parsed)
                && parsed >= 1
                && parsed <= 8
                && coalition.OriginalTeams.All(team => team == parsed))
            {
                return;
            }
            if (coalition.CoalitionId.StartsWith(
                    PlayerPrefix,
                    StringComparison.Ordinal)
                && int.TryParse(
                    coalition.CoalitionId.Substring(PlayerPrefix.Length),
                    out parsed)
                && coalition.MemberPlayerIds.Length == 1
                && coalition.MemberPlayerIds[0] == parsed
                && coalition.OriginalTeams[0] == 0)
            {
                return;
            }
            throw new InvalidDataException(
                "diplomacy coalition identity is inconsistent");
        }

        private static void WritePairs(
            BinaryWriter writer,
            IReadOnlyDictionary<int, int> values)
        {
            writer.Write(values.Count);
            foreach (KeyValuePair<int, int> value in values.OrderBy(item => item.Key))
            {
                writer.Write(value.Key);
                writer.Write(value.Value);
            }
        }

        private static Dictionary<int, int> ReadPairs(BinaryReader reader, int maximum)
        {
            int count = ReadCount(reader, maximum, "integer pairs");
            var values = new Dictionary<int, int>();
            for (int index = 0; index < count; index++)
            {
                int key = reader.ReadInt32();
                int value = reader.ReadInt32();
                if (values.ContainsKey(key))
                {
                    throw new InvalidDataException("diplomacy save repeats a key");
                }
                values.Add(key, value);
            }
            return values;
        }

        private static void WriteInts(BinaryWriter writer, int[] values)
        {
            writer.Write(values.Length);
            foreach (int value in values)
            {
                writer.Write(value);
            }
        }

        private static int[] ReadInts(BinaryReader reader, int maximum)
        {
            int count = ReadCount(reader, maximum, "integer array");
            var values = new int[count];
            for (int index = 0; index < count; index++)
            {
                values[index] = reader.ReadInt32();
            }
            return values;
        }

        private static void WriteDecimal(BinaryWriter writer, decimal value)
        {
            foreach (int part in decimal.GetBits(value))
            {
                writer.Write(part);
            }
        }

        private static bool ReadBoolean(BinaryReader reader)
        {
            byte value = reader.ReadByte();
            if (value > 1) throw new InvalidDataException("diplomacy save boolean is not canonical");
            return value == 1;
        }
        private static decimal ReadDecimal(BinaryReader reader)
        {
            return new decimal(new[]
            {
                reader.ReadInt32(),
                reader.ReadInt32(),
                reader.ReadInt32(),
                reader.ReadInt32(),
            });
        }

        private static void WriteText(BinaryWriter writer, string value)
        {
            ValidateText(value, "text");
            writer.Write(value);
        }

        private static string ReadText(BinaryReader reader)
        {
            string value = reader.ReadString();
            ValidateText(value, "text");
            return value;
        }

        private static void ValidateText(string value, string label)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 128
                || value.Any(character => char.IsControl(character) || character == '|'))
            {
                throw new InvalidDataException(label + " is not canonical");
            }
        }

        private static int ReadCount(BinaryReader reader, int maximum, string label)
        {
            int count = reader.ReadInt32();
            if (count < 0 || count > maximum)
            {
                throw new InvalidDataException(label + " count is invalid");
            }
            return count;
        }
    }
}
