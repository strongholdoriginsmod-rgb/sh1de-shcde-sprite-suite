#if DIPLOMACY_V2
using System;

namespace StrongholdEuropeDE.Runtime
{
    // Versioned semantic names, not audio filenames or native hook names.
    internal enum DiplomacyPresentationEventKind
    {
        AllianceOffered = 1,
        AllianceFormed = 2,
        AllianceBroken = 3,
        TruceFormed = 4,
        TradePactFormed = 5,
        SupportRequested = 6,
        SupportFulfilled = 7,
        UltimatumIssued = 8,
        UltimatumFulfilled = 9,
        SubmissionOffered = 10,
        SubmissionDeclined = 11,
        FealtyEstablished = 12,
        FealtyReleased = 13,
        EqualityRequested = 14,
        EqualityGranted = 15,
        EqualityRefused = 16,
        TributePaid = 17,
        TributeDefaulted = 18,
        RestitutionAccepted = 19,
    }

    // Values are copied from a completed model operation. Missing historical
    // values remain null; this is a reference, not a new gameplay contract.
    internal sealed class DiplomacyPresentationReference
    {
        internal readonly string Kind;
        internal readonly int? StartedDay;
        internal readonly int? Sequence;
        internal readonly int? GoodId;
        internal readonly int? Amount;
        internal readonly int? IntervalDays;
        internal readonly int? DueDay;
        internal readonly int? OtherPlayerId;
        internal readonly int? PayerPlayerId;
        internal readonly int? RecipientPlayerId;

        internal DiplomacyPresentationReference(string kind, int? startedDay = null,
            int? sequence = null, int? goodId = null, int? amount = null,
            int? intervalDays = null, int? dueDay = null, int? otherPlayerId = null,
            int? payerPlayerId = null, int? recipientPlayerId = null)
        {
            Kind = kind; StartedDay = startedDay; Sequence = sequence;
            GoodId = goodId; Amount = amount; IntervalDays = intervalDays;
            DueDay = dueDay; OtherPlayerId = otherPlayerId;
            PayerPlayerId = payerPlayerId; RecipientPlayerId = recipientPlayerId;
        }

        internal bool Valid
        {
            get
            {
                return !string.IsNullOrWhiteSpace(Kind)
                    && (!StartedDay.HasValue || StartedDay.Value >= 0)
                    && (!Sequence.HasValue || Sequence.Value >= 0)
                    && (!GoodId.HasValue || GoodId.Value >= 0)
                    && (!Amount.HasValue || Amount.Value >= 0)
                    && (!IntervalDays.HasValue || IntervalDays.Value > 0)
                    && (!DueDay.HasValue || DueDay.Value >= 0)
                    && (!OtherPlayerId.HasValue
                        || (OtherPlayerId.Value >= 1 && OtherPlayerId.Value <= 8))
                    && (!PayerPlayerId.HasValue
                        || (PayerPlayerId.Value >= 1 && PayerPlayerId.Value <= 8))
                    && (!RecipientPlayerId.HasValue
                        || (RecipientPlayerId.Value >= 1 && RecipientPlayerId.Value <= 8));
            }
        }
    }

    internal sealed class DiplomacyPresentationEvent
    {
        internal const int ContractVersion = 1;
        internal readonly DiplomacyPresentationEventKind Kind;
        internal readonly string Name;
        internal readonly long SessionGeneration;
        internal readonly int LogicalDay;
        internal readonly int SpeakerPlayerId;
        // Null means identity was not captured. Never infer a lord from a slot,
        // portrait index, coalition name, or a legacy PrimaryLordId.
        internal readonly int? SpeakerLordId;
        internal readonly int AudiencePlayerId;
        internal readonly string CoalitionId;
        internal readonly string Reason;
        internal readonly DiplomacyPresentationReference Reference;

        private DiplomacyPresentationEvent(DiplomacyPresentationEventKind kind,
            string name, long session, int day, int speaker, int? lord,
            int audience, string coalition, string reason,
            DiplomacyPresentationReference reference)
        {
            Kind = kind; Name = name; SessionGeneration = session; LogicalDay = day;
            SpeakerPlayerId = speaker; SpeakerLordId = lord; AudiencePlayerId = audience;
            CoalitionId = coalition; Reason = reason; Reference = reference;
        }

        internal static DiplomacyPresentationEvent Create(
            DiplomacyPresentationEventKind kind, long session, int day,
            int speakerPlayerId, int? speakerLordId, int audiencePlayerId,
            string coalitionId, string reason, DiplomacyPresentationReference reference)
        {
            string name = CanonicalName(kind);
            if (name == null || session <= 0 || day < 0
                || speakerPlayerId < 1 || speakerPlayerId > 8
                || (speakerLordId.HasValue && speakerLordId.Value <= 0)
                || audiencePlayerId < 1 || audiencePlayerId > 8
                || string.IsNullOrWhiteSpace(coalitionId)
                || string.IsNullOrWhiteSpace(reason)
                || reference == null || !reference.Valid) return null;
            return new DiplomacyPresentationEvent(kind, name, session, day,
                speakerPlayerId, speakerLordId, audiencePlayerId, coalitionId, reason, reference);
        }

        internal static string CanonicalName(DiplomacyPresentationEventKind kind)
        {
            switch (kind)
            {
                case DiplomacyPresentationEventKind.AllianceOffered: return "alliance.offered";
                case DiplomacyPresentationEventKind.AllianceFormed: return "alliance.formed";
                case DiplomacyPresentationEventKind.AllianceBroken: return "alliance.broken";
                case DiplomacyPresentationEventKind.TruceFormed: return "truce.formed";
                case DiplomacyPresentationEventKind.TradePactFormed: return "trade_pact.formed";
                case DiplomacyPresentationEventKind.SupportRequested: return "support.requested";
                case DiplomacyPresentationEventKind.SupportFulfilled: return "support.fulfilled";
                case DiplomacyPresentationEventKind.UltimatumIssued: return "ultimatum.issued";
                case DiplomacyPresentationEventKind.UltimatumFulfilled: return "ultimatum.fulfilled";
                case DiplomacyPresentationEventKind.SubmissionOffered: return "submission.offered";
                case DiplomacyPresentationEventKind.SubmissionDeclined: return "submission.declined";
                case DiplomacyPresentationEventKind.FealtyEstablished: return "fealty.established";
                case DiplomacyPresentationEventKind.FealtyReleased: return "fealty.released";
                case DiplomacyPresentationEventKind.EqualityRequested: return "equality.requested";
                case DiplomacyPresentationEventKind.EqualityGranted: return "equality.granted";
                case DiplomacyPresentationEventKind.EqualityRefused: return "equality.refused";
                case DiplomacyPresentationEventKind.TributePaid: return "tribute.paid";
                case DiplomacyPresentationEventKind.TributeDefaulted: return "tribute.defaulted";
                case DiplomacyPresentationEventKind.RestitutionAccepted: return "restitution.accepted";
                default: return null;
            }
        }
    }

    internal sealed partial class DiplomacyFeature
    {
        // Deliberately NO implementation in this release. C# removes each call
        // AND every argument evaluation from the built assembly. There is no
        // subscriber, runtime flag, queue, log, renderer, or asset to activate.
        // A future version must implement fault isolation and post-lease Unity
        // presentation explicitly. Null metadata and unknown LordId must skip
        // ruler-specific media. Tests may implement this only in a separate EXE.
        partial void OnDiplomacyPresentationCommitted(DiplomacyPresentationEvent committedEvent);
    }
}
#endif
