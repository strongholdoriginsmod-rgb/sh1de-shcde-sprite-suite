#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Linq;

namespace StrongholdEuropeDE.Runtime
{
    internal enum DiplomacyV2PersonalityKind
    {
        Honorable = 0,
        Mercantile = 1,
        Wary = 2,
        Warlike = 3,
        Opportunistic = 4,
        Loyal = 5,
        Demanding = 6,
    }

    internal enum DiplomacyV2NegotiationStage
    {
        Hostile = 0,
        Contact = 1,
        Negotiating = 2,
        Trusted = 3,
        AllianceReady = 4,
        Allied = 5,
        Ultimatum = 6,
        Blocked = 7,
    }

    internal enum DiplomacyV2AgreementKind
    {
        None = 0,
        Truce = 1,
        TradePact = 2,
        Alliance = 3,
        /// <summary>
        /// Lehnsverhaeltnis (07.09.2026). Wer von beiden Lehnsherr ist, sagt
        /// <see cref="DiplomacyV2VassalRole"/> - die Abkommensart allein
        /// wuerde die Richtung offenlassen.
        /// </summary>
        // Wird seit dem 07.09.2026 NICHT MEHR GESCHRIEBEN: ein Vasall ist
        // ein Verbuendeter mit Pflichten, kein eigener Vertragstyp (die Rolle
        // steht in `VassalRole`). Der Wert bleibt nur bestehen, damit ein
        // Spielstand aus der Zwischenfassung lesbar ist; `Normalize` bildet
        // ihn auf `Alliance` bzw. `None` zurueck.
        Vassalage = 4,
    }

    /// <summary>
    /// Wer ist in dieser Beziehung Lehnsherr?
    /// </summary>
    /// <remarks>
    /// WIDERRUFEN am 07.09.2026. Hier stand: "Eine Spielerkennung waere eine
    /// zweite Wahrheit neben der Koalitionszugehoerigkeit und liefe
    /// auseinander." Das war falsch. Vorgabe des Benutzers: ein Mitglied des
    /// Buendnisses kann Vasall eines ANDEREN Mitglieds sein und schuldet
    /// diesem den Tribut. Ohne benannte Spieler waehlte der Tributweg den
    /// Empfaenger als "das erste lebende Mitglied, das nicht ich bin" - bei
    /// drei Bundesgenossen zahlte er an einen beliebigen.
    ///
    /// Beide Seiten stehen jetzt in `VassalPlayerId` und
    /// `VassalOverlordPlayerId`; diese Rolle ist nur noch die Sicht des
    /// oertlichen Spielers darauf und wird aus beiden abgeleitet
    /// (`RoleFor`). `Normalize` haelt die drei zusammen.
    /// </remarks>
    internal enum DiplomacyV2VassalRole
    {
        None = 0,
        /// <summary>Der oertliche Spieler ist Lehnsherr.</summary>
        CoalitionIsVassal = 1,
        /// <summary>Der oertliche Spieler ist Vasall.</summary>
        LocalIsVassal = 2,
        /// <summary>
        /// Zwei Bundesgenossen unter sich - der oertliche Spieler sieht zu.
        /// </summary>
        WithinCoalition = 3,
    }

    internal enum DiplomacyV2DemandPurpose
    {
        None = 0,
        Courtship = 1,
        TradeProof = 2,
        AllianceTerms = 3,
        Support = 4,
        Ultimatum = 5,
        Restitution = 6,
    }

    internal enum DiplomacyV2DemandResolution
    {
        None = 0,
        TruceFormed = 1,
        TradePactFormed = 2,
        AllianceReady = 3,
        SupportFulfilled = 4,
        UltimatumFulfilled = 5,
        RestitutionAccepted = 6,
        AllianceTermsAccepted = 7,
    }

    internal enum DiplomacyV2EventKind
    {
        None = 0,
        GiftReceived = 1,
        DemandIssued = 2,
        DemandFulfilled = 3,
        DemandMissed = 4,
        TruceFormed = 5,
        TradePactFormed = 6,
        AgreementExpired = 7,
        AllianceFormed = 8,
        SupportRequested = 9,
        AllianceWarned = 10,
        AllianceBroken = 11,
        AgreementBrokenByPlayer = 12,
        OfferRejected = 13,
        HostileAct = 14,
        RestitutionDemanded = 15,
        RestitutionAccepted = 16,
        ProactiveSupportRecognized = 17,
        AgreementEndedPeacefully = 18,
        NegotiationPressed = 19,
        StrategicReassessment = 20,
        MilitaryIncursion = 21,
        AllianceBetrayalObserved = 22,
    }

    internal enum DiplomacyV2GoodCategory
    {
        Materials = 0,
        Food = 1,
        Luxury = 2,
        Weapons = 3,
        Gold = 4,
    }

    internal enum DiplomacyV2BreachKind
    {
        ManualTreatyEnd = 0,
        TreacherousAttack = 1,
        PlayerAllianceAbandonment = 2,
        FailedSupportUltimatum = 3,
        MilitaryIncursion = 4,
        /// <summary>
        /// Zwei Zahlungszeitraeume ohne Tribut (07.09.2026).
        /// </summary>
        /// <remarks>
        /// Wird im Buendnisbruchpfad verarbeitet. Grundschwere 24 vor der
        /// Persoenlichkeitsgewichtung, wie beim versaeumten Hilfsultimatum.
        /// </remarks>
        TributeDefault = 5,
        /// <summary>
        /// Ein Vasall bricht weg, nachdem sein Antrag auf Gleichberechtigung
        /// abgelehnt wurde (07.09.2026).
        /// </summary>
        /// <remarks>
        /// Wird im Buendnisbruchpfad verarbeitet. Grundschwere 38 vor der
        /// Persoenlichkeitsgewichtung; die freiwillige Aufkuendigung hat 45.
        /// </remarks>
        VassalRebellion = 6,
    }

    internal sealed class DiplomacyV2PersonalitySignal
    {
        internal int LordId;
        internal int SendGoodsMargin;
        internal int CommerceOrientation;
        internal int MilitaryOrientation;
        internal int Aggression;
        internal int Caution;
    }

    internal sealed class DiplomacyV2Personality
    {
        internal DiplomacyV2PersonalityKind Kind;
        internal int TrustWeight;
        internal int GratitudeWeight;
        internal int RespectWeight;
        internal int GrudgeWeight;
        internal int InitialTrust;
        internal int InitialRespect;
        internal int InitialGrudge;
        internal int GiftBasisPoints;
        internal int DemandBasisPoints;
        internal int RepeatedGiftFloorPercent;
        internal int MaterialsGiftPercent;
        internal int FoodGiftPercent;
        internal int LuxuryGiftPercent;
        internal int WeaponsGiftPercent;
        internal int GoldGiftPercent;
        internal int TrustResponsePercent;
        internal int GratitudeResponsePercent;
        internal int RespectResponsePercent;
        internal int GrudgeReliefPercent;
        internal int AllianceThreshold;
        internal int MinimumAllianceTrust;
        internal int MaximumAllianceGrudge;
        internal int CourtshipDemandPercent;
        internal int TradeDemandPercent;
        internal int AllianceDemandPercent;
        internal int TruceDays;
        internal int TradePactDays;
        internal int NegotiationDeadlineDays;
        internal int MaintenanceIntervalDays;
        internal int SupportDeadlineDays;
        internal int UltimatumDeadlineDays;
        internal int SupportDemandPercent;
        internal int UltimatumDemandPercent;
        internal int ProactiveSupportPercent;
        internal int RequestPatienceDays;
        internal int BreachSensitivityPercent;
        internal int GratitudeDecayBasisPoints;
        internal int TrustDecayBasisPoints;
        internal int GrudgeRecoveryBasisPoints;
        internal int ThreatWeightPercent;
        internal int DependencyWeightPercent;
        internal int OfferChanceAdjustmentTenthsPercent;
    }

    internal static class DiplomacyV2PersonalityCatalog
    {
        // Durations deliberately use campaign-scale time. Even the most
        // impatient ruler grants more than a month of truce and more than two
        // months between alliance-maintenance requests.
        private static readonly DiplomacyV2Personality[] Profiles =
        {
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Honorable,
                TrustWeight = 39, GratitudeWeight = 15,
                RespectWeight = 24, GrudgeWeight = 22,
                InitialTrust = 15, InitialRespect = 25, InitialGrudge = 8,
                GiftBasisPoints = 9600, DemandBasisPoints = 9000,
                RepeatedGiftFloorPercent = 55,
                MaterialsGiftPercent = 105, FoodGiftPercent = 100,
                LuxuryGiftPercent = 85, WeaponsGiftPercent = 105,
                GoldGiftPercent = 90,
                TrustResponsePercent = 125, GratitudeResponsePercent = 90,
                RespectResponsePercent = 105, GrudgeReliefPercent = 85,
                AllianceThreshold = 76, MinimumAllianceTrust = 58,
                MaximumAllianceGrudge = 30,
                CourtshipDemandPercent = 12, TradeDemandPercent = 16,
                AllianceDemandPercent = 20,
                TruceDays = 75, TradePactDays = 180,
                NegotiationDeadlineDays = 42,
                MaintenanceIntervalDays = 150,
                SupportDeadlineDays = 42, UltimatumDeadlineDays = 35,
                SupportDemandPercent = 9, UltimatumDemandPercent = 14,
                ProactiveSupportPercent = 8, RequestPatienceDays = 28,
                BreachSensitivityPercent = 125,
                GratitudeDecayBasisPoints = 28,
                TrustDecayBasisPoints = 9, GrudgeRecoveryBasisPoints = 10,
                ThreatWeightPercent = 90, DependencyWeightPercent = 100,
                OfferChanceAdjustmentTenthsPercent = 80,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Mercantile,
                TrustWeight = 22, GratitudeWeight = 40,
                RespectWeight = 17, GrudgeWeight = 21,
                InitialTrust = 10, InitialRespect = 20, InitialGrudge = 10,
                GiftBasisPoints = 12400, DemandBasisPoints = 9200,
                RepeatedGiftFloorPercent = 42,
                MaterialsGiftPercent = 115, FoodGiftPercent = 105,
                LuxuryGiftPercent = 125, WeaponsGiftPercent = 90,
                GoldGiftPercent = 120,
                TrustResponsePercent = 90, GratitudeResponsePercent = 135,
                RespectResponsePercent = 80, GrudgeReliefPercent = 105,
                AllianceThreshold = 77, MinimumAllianceTrust = 50,
                MaximumAllianceGrudge = 35,
                CourtshipDemandPercent = 14, TradeDemandPercent = 15,
                AllianceDemandPercent = 20,
                TruceDays = 60, TradePactDays = 210,
                NegotiationDeadlineDays = 35,
                MaintenanceIntervalDays = 120,
                SupportDeadlineDays = 35, UltimatumDeadlineDays = 30,
                SupportDemandPercent = 10, UltimatumDemandPercent = 16,
                ProactiveSupportPercent = 7, RequestPatienceDays = 21,
                BreachSensitivityPercent = 100,
                GratitudeDecayBasisPoints = 38,
                TrustDecayBasisPoints = 10, GrudgeRecoveryBasisPoints = 13,
                ThreatWeightPercent = 85, DependencyWeightPercent = 115,
                OfferChanceAdjustmentTenthsPercent = 110,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Wary,
                TrustWeight = 42, GratitudeWeight = 13,
                RespectWeight = 20, GrudgeWeight = 25,
                InitialTrust = 6, InitialRespect = 22, InitialGrudge = 20,
                GiftBasisPoints = 8500, DemandBasisPoints = 11200,
                RepeatedGiftFloorPercent = 62,
                MaterialsGiftPercent = 110, FoodGiftPercent = 110,
                LuxuryGiftPercent = 75, WeaponsGiftPercent = 100,
                GoldGiftPercent = 90,
                TrustResponsePercent = 70, GratitudeResponsePercent = 85,
                RespectResponsePercent = 95, GrudgeReliefPercent = 65,
                AllianceThreshold = 85, MinimumAllianceTrust = 68,
                MaximumAllianceGrudge = 20,
                CourtshipDemandPercent = 16, TradeDemandPercent = 20,
                AllianceDemandPercent = 25,
                TruceDays = 45, TradePactDays = 150,
                NegotiationDeadlineDays = 45,
                MaintenanceIntervalDays = 135,
                SupportDeadlineDays = 42, UltimatumDeadlineDays = 35,
                SupportDemandPercent = 10, UltimatumDemandPercent = 17,
                ProactiveSupportPercent = 8, RequestPatienceDays = 35,
                BreachSensitivityPercent = 145,
                GratitudeDecayBasisPoints = 25,
                TrustDecayBasisPoints = 8, GrudgeRecoveryBasisPoints = 6,
                ThreatWeightPercent = 135, DependencyWeightPercent = 85,
                OfferChanceAdjustmentTenthsPercent = -90,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Warlike,
                TrustWeight = 15, GratitudeWeight = 10,
                RespectWeight = 53, GrudgeWeight = 22,
                InitialTrust = 8, InitialRespect = 30, InitialGrudge = 13,
                GiftBasisPoints = 8800, DemandBasisPoints = 11400,
                RepeatedGiftFloorPercent = 48,
                MaterialsGiftPercent = 95, FoodGiftPercent = 90,
                LuxuryGiftPercent = 70, WeaponsGiftPercent = 135,
                GoldGiftPercent = 95,
                TrustResponsePercent = 75, GratitudeResponsePercent = 75,
                RespectResponsePercent = 145, GrudgeReliefPercent = 75,
                AllianceThreshold = 82, MinimumAllianceTrust = 45,
                MaximumAllianceGrudge = 30,
                CourtshipDemandPercent = 15, TradeDemandPercent = 19,
                AllianceDemandPercent = 24,
                TruceDays = 40, TradePactDays = 120,
                NegotiationDeadlineDays = 30,
                MaintenanceIntervalDays = 90,
                SupportDeadlineDays = 30, UltimatumDeadlineDays = 24,
                SupportDemandPercent = 13, UltimatumDemandPercent = 21,
                ProactiveSupportPercent = 10, RequestPatienceDays = 21,
                BreachSensitivityPercent = 110,
                GratitudeDecayBasisPoints = 36,
                TrustDecayBasisPoints = 13, GrudgeRecoveryBasisPoints = 10,
                ThreatWeightPercent = 75, DependencyWeightPercent = 125,
                OfferChanceAdjustmentTenthsPercent = -40,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Opportunistic,
                TrustWeight = 17, GratitudeWeight = 23,
                RespectWeight = 43, GrudgeWeight = 17,
                InitialTrust = 8, InitialRespect = 24, InitialGrudge = 12,
                GiftBasisPoints = 10500, DemandBasisPoints = 10600,
                RepeatedGiftFloorPercent = 42,
                MaterialsGiftPercent = 100, FoodGiftPercent = 95,
                LuxuryGiftPercent = 105, WeaponsGiftPercent = 115,
                GoldGiftPercent = 115,
                TrustResponsePercent = 80, GratitudeResponsePercent = 105,
                RespectResponsePercent = 125, GrudgeReliefPercent = 100,
                AllianceThreshold = 79, MinimumAllianceTrust = 44,
                MaximumAllianceGrudge = 40,
                CourtshipDemandPercent = 14, TradeDemandPercent = 18,
                AllianceDemandPercent = 22,
                TruceDays = 45, TradePactDays = 135,
                NegotiationDeadlineDays = 30,
                MaintenanceIntervalDays = 80,
                SupportDeadlineDays = 28, UltimatumDeadlineDays = 21,
                SupportDemandPercent = 12, UltimatumDemandPercent = 20,
                ProactiveSupportPercent = 9, RequestPatienceDays = 21,
                BreachSensitivityPercent = 85,
                GratitudeDecayBasisPoints = 42,
                TrustDecayBasisPoints = 15, GrudgeRecoveryBasisPoints = 16,
                ThreatWeightPercent = 80, DependencyWeightPercent = 145,
                OfferChanceAdjustmentTenthsPercent = 35,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Loyal,
                TrustWeight = 46, GratitudeWeight = 20,
                RespectWeight = 16, GrudgeWeight = 18,
                InitialTrust = 13, InitialRespect = 20, InitialGrudge = 8,
                GiftBasisPoints = 10000, DemandBasisPoints = 8600,
                RepeatedGiftFloorPercent = 58,
                MaterialsGiftPercent = 100, FoodGiftPercent = 115,
                LuxuryGiftPercent = 95, WeaponsGiftPercent = 100,
                GoldGiftPercent = 90,
                TrustResponsePercent = 135, GratitudeResponsePercent = 105,
                RespectResponsePercent = 85, GrudgeReliefPercent = 115,
                AllianceThreshold = 75, MinimumAllianceTrust = 60,
                MaximumAllianceGrudge = 33,
                CourtshipDemandPercent = 11, TradeDemandPercent = 15,
                AllianceDemandPercent = 19,
                TruceDays = 90, TradePactDays = 240,
                NegotiationDeadlineDays = 45,
                MaintenanceIntervalDays = 180,
                SupportDeadlineDays = 49, UltimatumDeadlineDays = 42,
                SupportDemandPercent = 8, UltimatumDemandPercent = 12,
                ProactiveSupportPercent = 7, RequestPatienceDays = 35,
                BreachSensitivityPercent = 135,
                GratitudeDecayBasisPoints = 20,
                TrustDecayBasisPoints = 6, GrudgeRecoveryBasisPoints = 8,
                ThreatWeightPercent = 95, DependencyWeightPercent = 90,
                OfferChanceAdjustmentTenthsPercent = 90,
            },
            new DiplomacyV2Personality
            {
                Kind = DiplomacyV2PersonalityKind.Demanding,
                TrustWeight = 23, GratitudeWeight = 36,
                RespectWeight = 18, GrudgeWeight = 23,
                InitialTrust = 7, InitialRespect = 22, InitialGrudge = 14,
                GiftBasisPoints = 11400, DemandBasisPoints = 13000,
                RepeatedGiftFloorPercent = 38,
                MaterialsGiftPercent = 105, FoodGiftPercent = 95,
                LuxuryGiftPercent = 115, WeaponsGiftPercent = 110,
                GoldGiftPercent = 125,
                TrustResponsePercent = 80, GratitudeResponsePercent = 120,
                RespectResponsePercent = 85, GrudgeReliefPercent = 75,
                AllianceThreshold = 82, MinimumAllianceTrust = 54,
                MaximumAllianceGrudge = 27,
                CourtshipDemandPercent = 17, TradeDemandPercent = 22,
                AllianceDemandPercent = 28,
                TruceDays = 40, TradePactDays = 120,
                NegotiationDeadlineDays = 28,
                MaintenanceIntervalDays = 75,
                SupportDeadlineDays = 28, UltimatumDeadlineDays = 21,
                SupportDemandPercent = 15, UltimatumDemandPercent = 24,
                ProactiveSupportPercent = 11, RequestPatienceDays = 21,
                BreachSensitivityPercent = 115,
                GratitudeDecayBasisPoints = 48,
                TrustDecayBasisPoints = 16, GrudgeRecoveryBasisPoints = 9,
                ThreatWeightPercent = 110, DependencyWeightPercent = 115,
                OfferChanceAdjustmentTenthsPercent = -25,
            },
        };

        internal static DiplomacyV2Personality Get(
            DiplomacyV2PersonalityKind kind)
        {
            int index = (int)kind;
            if (index < 0 || index >= Profiles.Length)
            {
                throw new ArgumentOutOfRangeException("kind");
            }
            return Profiles[index];
        }

        internal static DiplomacyV2Personality SelectForLord(
            int lordId,
            int sendGoodsMargin)
        {
            int margin = DiplomacyBalance.ClampMargin(sendGoodsMargin);
            if (margin >= 80)
            {
                return Get((lordId & 1) == 0
                    ? DiplomacyV2PersonalityKind.Demanding
                    : DiplomacyV2PersonalityKind.Wary);
            }
            if (margin <= 20)
            {
                return Get((lordId & 1) == 0
                    ? DiplomacyV2PersonalityKind.Honorable
                    : DiplomacyV2PersonalityKind.Mercantile);
            }
            int stable = lordId % Profiles.Length;
            if (stable < 0)
            {
                stable += Profiles.Length;
            }
            return Profiles[stable];
        }

        internal static DiplomacyV2Personality SelectForLord(
            DiplomacyV2PersonalitySignal signal)
        {
            if (signal == null)
            {
                throw new ArgumentNullException("signal");
            }
            int margin = ClampSignal(signal.SendGoodsMargin);
            int commerce = ClampSignal(signal.CommerceOrientation);
            int military = ClampSignal(signal.MilitaryOrientation);
            int aggression = ClampSignal(signal.Aggression);
            int caution = ClampSignal(signal.Caution);
            if (aggression >= 70 && military >= 55
                && aggression >= caution + 10)
            {
                return Get(DiplomacyV2PersonalityKind.Warlike);
            }
            if (margin >= 76)
            {
                return Get(DiplomacyV2PersonalityKind.Demanding);
            }
            if (caution >= 72 && caution >= aggression + 12)
            {
                return Get(DiplomacyV2PersonalityKind.Wary);
            }
            if (commerce >= 72 && military < 68)
            {
                return Get(DiplomacyV2PersonalityKind.Mercantile);
            }
            if (caution >= 60 && margin <= 36 && aggression < 58)
            {
                return Get(DiplomacyV2PersonalityKind.Loyal);
            }
            if (aggression >= 55 && commerce >= 52)
            {
                return Get(DiplomacyV2PersonalityKind.Opportunistic);
            }
            if (margin <= 35)
            {
                return Get(DiplomacyV2PersonalityKind.Honorable);
            }
            int stable = signal.LordId % Profiles.Length;
            if (stable < 0)
            {
                stable += Profiles.Length;
            }
            return Profiles[stable];
        }

        private static int ClampSignal(int value)
        {
            return Math.Max(0, Math.Min(100, value));
        }
    }

    internal sealed class DiplomacyV2GiftMemory
    {
        internal int GoodId;
        internal int LastGiftDay = -1;
        internal int ConsecutiveCount;
        internal decimal RecentRawValue;
        internal decimal LifetimeCreditedValue;

        internal DiplomacyV2GiftMemory Clone()
        {
            return (DiplomacyV2GiftMemory)MemberwiseClone();
        }
    }

    internal sealed class DiplomacyV2RelationState
    {
        internal DiplomacyV2PersonalityKind Personality;
        internal int PrimaryLordId = -1;
        internal decimal Trust;
        internal decimal Gratitude;
        internal decimal Respect;
        internal decimal Grudge;
        internal DiplomacyV2NegotiationStage Stage;
        internal DiplomacyV2AgreementKind Agreement;
        internal int AgreementUntilDay;
        internal int LastStrategicDay = -1;
        internal int LastInteractionDay = -1;
        internal int LastHostileActDay = -1;
        internal int LastGiftGoodId;
        internal int RepeatedGiftCount;
        internal int FulfilledDemands;
        internal int MissedDemands;
        internal int BrokenAgreements;
        internal int MaintenanceDueDay;
        internal int MaintenanceWarningLevel;
        internal decimal StrategicLeverage;
        internal decimal LastCreditedGiftValue;
        internal DiplomacyV2EventKind LastEvent;
        internal int LastEventDay = -1;
        internal decimal Reliability;
        internal decimal TrustCeiling = 100m;
        internal decimal PositiveMomentum;
        internal decimal NegativeMomentum;
        internal int LastPositiveEventDay = -1;
        internal int LastNegativeEventDay = -1;
        internal int LastNegotiationRequestDay = -1;
        internal int NegotiationRequestsWithoutGift;
        internal int FailedNegotiations;
        internal int ConsecutiveMissedDemands;
        internal int HostileActs;
        internal int ManualTreatyEnds;
        internal int TreacherousAttacks;
        internal int MilitaryIncursions;
        internal int AllianceAbandonments;
        internal int ObservedAllianceAbandonments;
        internal int BreachPoints;
        internal int LastMilitaryIncursionDay = -1;
        internal decimal RestitutionOutstandingValue;
        internal bool AllianceTermsFulfilled;
        internal decimal StrategicThreat;
        internal decimal StrategicDependency;
        internal decimal CoalitionValue;
        internal int CommonEnemyCoalitions;
        internal int HostileCoalitions;
        internal int PlayerAllianceCount;
        internal decimal MaintenanceCredit;
        internal decimal SupportValueSinceMaintenance;
        internal int LastSupportDay = -1;
        internal int FulfilledSupportStreak;
        internal int UltimatumsIssued;
        internal int VariedGiftStreak;
        internal DiplomacyV2GoodCategory LastGiftCategory;
        internal decimal LifetimeCreditedGiftValue;
        // Tribut (07.09.2026). Ein Gut von 0 heisst "keine Pflicht"; die
        // Faelligkeit ist ein absoluter Spieltag, kein Restzaehler - ein
        // Zaehler liefe beim Laden eines aelteren Spielstands falsch weiter.
        internal int TributeGoodId;
        internal int TributeAmount;
        internal int TributeIntervalDays;
        internal int TributeNextDueDay = -1;
        internal int TributeMissedCycles;
        internal int TributePaidCycles;
        internal int TributeDefaults;
        internal bool TributeReassessmentPending;
        // Lehnsverhaeltnis (07.09.2026). Tage sind absolut, keine Restzaehler.
        internal DiplomacyV2VassalRole VassalRole;
        // Beide Seiten ausdruecklich benannt (07.09.2026). Vorher waehlte der
        // Tributweg den Empfaenger als "das erste lebende Mitglied, das nicht
        // ich bin" - bei drei Bundesgenossen zahlte er an einen beliebigen.
        internal int VassalPlayerId = -1;
        internal int VassalOverlordPlayerId = -1;
        internal int VassalSinceDay = -1;
        internal int VassalEqualityRequestedDay = -1;
        internal int VassalEqualityNextAllowedDay;
        // Schema 9: retain the historical request day, but charge only days
        // when this mod's actual confirmation is visible to the player.
        internal int VassalEqualityResponseDaysRemaining;
        internal int VassalEqualityLastResponseDay = -1;
        internal int VassalStrengthEdgeDays;
        internal int VassalReleases;
        internal int VassalRebellions;
        internal int PendingVassalOverlordPlayerId;
        internal int PendingVassalTributeAmount;
        internal int PendingVassalOfferDay = -1;
        // Schema 9: an AI offers submission only after sustained pressure.
        // Response time is saved as remaining presented days so a FIFO/load
        // cannot consume an invisible decision's deadline.
        internal int SubmissionPressureDays;
        internal int SubmissionPressureRuleVersion;
        internal int SubmissionLastComparedDay = -1;
        internal int SubmissionNextOfferDay;
        internal int SubmissionNextDemandDay;
        internal int SubmissionOfferPlayerId;
        internal int SubmissionOfferLordId;
        internal int SubmissionOfferTributeAmount;
        internal int SubmissionOfferCreatedDay = -1;
        internal int SubmissionResponseDaysRemaining;
        internal bool SubmissionOfferAccepted;
        internal bool SubmissionAcceptancePending;
        internal DiplomacyV2SubmissionOfferOrigin SubmissionOfferOrigin;
        internal DiplomacyV2VassalActionKind PendingVassalAction;
        internal int PendingVassalActionVassalPlayerId;
        internal int PendingVassalActionOverlordPlayerId;
        internal int PendingVassalActionSinceDay = -1;
        internal int PendingVassalActionRequestDay = -1;
        internal int PendingVassalActionQuoteAmount;
        internal int PendingVassalActionReleaseCount;
        // Schema 11: a clicked relationship decision survives native contention.
        internal DiplomacyV2RelationshipDecisionKind PendingRelationshipDecision;
        internal int PendingRelationshipDecisionPlayerId;
        internal int PendingRelationshipDecisionDay = -1;
        internal string PendingRelationshipDecisionContract;

        internal bool ImportedFromV1;
        internal int MigrationSourceVersion;
        internal List<DiplomacyV2GiftMemory> GiftMemory =
            new List<DiplomacyV2GiftMemory>();

        internal DiplomacyV2RelationState Clone()
        {
            DiplomacyV2RelationState clone =
                (DiplomacyV2RelationState)MemberwiseClone();
            clone.GiftMemory = GiftMemory == null
                ? new List<DiplomacyV2GiftMemory>()
                : GiftMemory.Select(memory => memory.Clone()).ToList();
            return clone;
        }
    }

    internal enum DiplomacyV2VassalActionKind
    {
        None = 0, Release = 1, ClaimEquality = 2, GrantEquality = 3,
        RefuseEquality = 4, AcceptSubjugation = 5, RefuseSubjugation = 6,
    }

    // Saved user intent, never a native operation. Its immutable contract
    // anchors prevent a delayed answer from acting on a replacement role.
    internal static class DiplomacyV2VassalActions
    {
        internal static bool IsSubjugation(DiplomacyV2VassalActionKind kind)
        { return kind == DiplomacyV2VassalActionKind.AcceptSubjugation || kind == DiplomacyV2VassalActionKind.RefuseSubjugation; }
        internal static bool IsEquality(DiplomacyV2VassalActionKind kind)
        { return kind == DiplomacyV2VassalActionKind.GrantEquality || kind == DiplomacyV2VassalActionKind.RefuseEquality; }
        internal static bool HasPending(DiplomacyV2RelationState s)
        { return s != null && s.PendingVassalAction != DiplomacyV2VassalActionKind.None; }
        internal static void Clear(DiplomacyV2RelationState s)
        {
            if (s == null) return;
            s.PendingVassalAction = DiplomacyV2VassalActionKind.None;
            s.PendingVassalActionVassalPlayerId = 0;
            s.PendingVassalActionOverlordPlayerId = 0;
            s.PendingVassalActionSinceDay = -1;
            s.PendingVassalActionRequestDay = -1;
            s.PendingVassalActionQuoteAmount = 0;
            s.PendingVassalActionReleaseCount = 0;
        }
        internal static bool Matches(RelationState relation, int local)
        {
            DiplomacyV2RelationState s = relation == null ? null : relation.V2;
            if (!HasPending(s) || !relation.Allied || s.Agreement != DiplomacyV2AgreementKind.Alliance
                || s.PendingVassalActionVassalPlayerId < 1 || s.PendingVassalActionVassalPlayerId > 8
                || s.PendingVassalActionOverlordPlayerId < 1 || s.PendingVassalActionOverlordPlayerId > 8
                || s.PendingVassalActionVassalPlayerId == s.PendingVassalActionOverlordPlayerId
                || s.PendingVassalActionReleaseCount != s.VassalReleases) return false;
            var kind = s.PendingVassalAction;
            if (IsSubjugation(kind))
                return !DiplomacyV2Vassalage.IsActive(s)
                    && s.PendingVassalActionVassalPlayerId == local
                    && s.PendingVassalActionSinceDay == -1
                    && s.PendingVassalActionOverlordPlayerId == s.PendingVassalOverlordPlayerId
                    && s.PendingVassalActionRequestDay == s.PendingVassalOfferDay
                    && s.PendingVassalActionQuoteAmount == s.PendingVassalTributeAmount
                    && s.PendingVassalActionRequestDay >= 0
                    && s.PendingVassalActionQuoteAmount >= DiplomacyV2Vassalage.MinimumTributeAmount
                    && s.PendingVassalActionQuoteAmount <= DiplomacyV2Vassalage.MaximumTributeAmount
                    && !DiplomacyV2StateMachine.HasOutstandingUltimatum(relation);
            if (!DiplomacyV2Vassalage.IsActive(s)
                || s.PendingVassalActionVassalPlayerId != s.VassalPlayerId
                || s.PendingVassalActionOverlordPlayerId != s.VassalOverlordPlayerId
                || s.PendingVassalActionSinceDay != s.VassalSinceDay
                || s.PendingVassalActionQuoteAmount != 0) return false;
            if (IsEquality(kind))
                return s.VassalOverlordPlayerId == local
                    && DiplomacyV2Vassalage.EqualityRequestOpen(s)
                    && s.PendingVassalActionRequestDay == s.VassalEqualityRequestedDay;
            return s.PendingVassalActionRequestDay == -1
                && (kind == DiplomacyV2VassalActionKind.Release && s.VassalOverlordPlayerId == local
                    || kind == DiplomacyV2VassalActionKind.ClaimEquality && s.VassalPlayerId == local);
        }
        internal static bool Stage(RelationState relation, int local, DiplomacyV2VassalActionKind kind)
        {
            DiplomacyV2RelationState s = relation == null ? null : relation.V2;
            if (s == null || HasPending(s) || kind == DiplomacyV2VassalActionKind.None) return false;
            s.PendingVassalAction = kind;
            s.PendingVassalActionVassalPlayerId = IsSubjugation(kind) ? local : s.VassalPlayerId;
            s.PendingVassalActionOverlordPlayerId = IsSubjugation(kind) ? s.PendingVassalOverlordPlayerId : s.VassalOverlordPlayerId;
            s.PendingVassalActionSinceDay = IsSubjugation(kind) ? -1 : s.VassalSinceDay;
            s.PendingVassalActionRequestDay = IsSubjugation(kind) ? s.PendingVassalOfferDay
                : IsEquality(kind) ? s.VassalEqualityRequestedDay : -1;
            s.PendingVassalActionQuoteAmount = IsSubjugation(kind) ? s.PendingVassalTributeAmount : 0;
            s.PendingVassalActionReleaseCount = s.VassalReleases;
            if (Matches(relation, local)) return true;
            Clear(s); return false;
        }
        internal static void Validate(RelationState relation, int local, int day)
        {
            DiplomacyV2RelationState s = relation.V2;
            if (!HasPending(s))
            {
                if (s.PendingVassalActionVassalPlayerId != 0 || s.PendingVassalActionOverlordPlayerId != 0
                    || s.PendingVassalActionSinceDay != -1 || s.PendingVassalActionRequestDay != -1
                    || s.PendingVassalActionQuoteAmount != 0 || s.PendingVassalActionReleaseCount != 0)
                    throw new InvalidOperationException("inactive vassal action retains contract anchors");
                return;
            }
            if (!Matches(relation, local) || s.PendingVassalActionSinceDay > day
                || s.PendingVassalActionRequestDay > day)
                throw new InvalidOperationException("pending vassal action does not match its contract");
        }
    }

    // Presentation-only reasons. They describe already observed state and
    // never authorize a quote or replace the workflow's live eligibility check.
    internal enum DiplomacyV2SubmissionAvailability
    {
        Unavailable,
        ActiveFealty,
        OfferPending,
        OfferCommitting,
        OtherDecisionPending,
        CoalitionHasMultipleMembers,
        EqualAlliance,
        ActiveTreaty,
        NegotiationPending,
        RelationshipBlocked,
        LordUnknown,
        LordNeverSubmits,
        LordNotEligible,
        NoRemainingOpponent,
        OfferCooldown,
        AwaitingDailyAssessment,
        PressureNotEstablished,
        PressureDeveloping,
        AwaitingOffer,
    }

    internal enum DiplomacyV2SubmissionOfferOrigin
    {
        None = 0,
        AiOffer = 1,
        PlayerDemand = 2,
    }

    internal enum DiplomacyV2SubmissionTemperament
    {
        Yielding = 0,
        Adaptable = 1,
        Steadfast = 2,
        Proud = 3,
        Unyielding = 4,
    }

    internal enum DiplomacyV2SubmissionAttemptResult
    {
        Blocked = 0,
        Refused = 1,
        Offered = 2,
    }

    internal sealed class DiplomacyV2SubmissionProfile
    {
        internal readonly int LordId;
        internal readonly DiplomacyV2SubmissionTemperament Temperament;
        internal readonly int MinimumPressureBand;
        internal readonly int RequiredPressureDays;
        internal readonly int ChanceBonusPercent;

        internal DiplomacyV2SubmissionProfile(int lordId,
            DiplomacyV2SubmissionTemperament temperament, int days, int bonus = 0)
        {
            LordId = lordId;
            Temperament = temperament;
            RequiredPressureDays = days;
            ChanceBonusPercent = bonus;
            MinimumPressureBand = temperament == DiplomacyV2SubmissionTemperament.Unyielding ? 4
                : temperament == DiplomacyV2SubmissionTemperament.Proud ? 3
                : temperament == DiplomacyV2SubmissionTemperament.Steadfast ? 2 : 1;
        }
    }

    internal sealed class DiplomacyV2SubmissionAssessment
    {
        internal DiplomacyV2SubmissionProfile Profile;
        internal DiplomacyV2SubmissionAvailability Availability;
        internal int PressureBand;
        internal int PressureDays;
        internal int RequiredPressureDays;
        internal int ChancePercent;
        internal int NextAttemptDay;
        internal bool CanAttempt;
    }

    internal static class DiplomacyV2Submission
    {
        // Benutzervorgabe 09.09.2026: ein Angebot steht sieben Spieltage, und
        // zwar UNANTASTBAR - auch wenn der Druck in dieser Zeit nachlaesst oder
        // ganz einbricht. Erst am Fristende entscheidet der Druck wieder:
        // haelt er an, faellt ein Wurf zwischen Nachbessern und Rueckzug
        // (siehe ElapseResponseDay), sonst laeuft das Angebot aus.
        internal const int ResponseDays = 7;
        /// <summary>Aufschlag auf den Tribut, wenn ein Angebot nachgebessert wird.</summary>
        internal const int OfferImprovementPercent = 25;
        /// <summary>Wahrscheinlichkeit in Zehntelprozent, dass nachgebessert statt zurueckgezogen wird.</summary>
        internal const int OfferRenewalChanceTenths = 500;
        internal const int OfferCooldownDays = 20;
        internal const int AutomaticRetryDays = 5;
        internal const int MaximumPressureDays = 8;
        internal const int CurrentPressureRuleVersion = 1;
        internal const int MinimumBesiegingUnits = 12;
        internal const long MinimumBesiegingMilitary = 750L;
        internal const long MinimumTotalMilitary = 1500L;

        // Deliberate mod balance, approved 2026-09-08. These are not measured
        // vanilla surrender probabilities. Identity comes from GetAILord,
        // never the UI/AIC profile index or its former modulo-seven fallback.
        // Current COPY names28/29 Surgeon/Baibars; SE1.45 calls them DLC4A/B.
        private static readonly DiplomacyV2SubmissionProfile[] Profiles =
        {
            null,
            new DiplomacyV2SubmissionProfile(1, DiplomacyV2SubmissionTemperament.Yielding, 5, 10), // Rat
            new DiplomacyV2SubmissionProfile(2, DiplomacyV2SubmissionTemperament.Adaptable, 5), // Snake
            new DiplomacyV2SubmissionProfile(3, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Pig
            new DiplomacyV2SubmissionProfile(4, DiplomacyV2SubmissionTemperament.Unyielding, 0), // Wolf
            new DiplomacyV2SubmissionProfile(5, DiplomacyV2SubmissionTemperament.Unyielding, 0), // Saladin
            new DiplomacyV2SubmissionProfile(6, DiplomacyV2SubmissionTemperament.Proud, 8), // Caliph
            new DiplomacyV2SubmissionProfile(7, DiplomacyV2SubmissionTemperament.Yielding, 5), // Sultan
            new DiplomacyV2SubmissionProfile(8, DiplomacyV2SubmissionTemperament.Unyielding, 0), // Richard
            new DiplomacyV2SubmissionProfile(9, DiplomacyV2SubmissionTemperament.Proud, 8), // Frederick
            new DiplomacyV2SubmissionProfile(10, DiplomacyV2SubmissionTemperament.Steadfast, 6), // Phillip
            new DiplomacyV2SubmissionProfile(11, DiplomacyV2SubmissionTemperament.Adaptable, 6), // Wazir
            new DiplomacyV2SubmissionProfile(12, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Emir
            new DiplomacyV2SubmissionProfile(13, DiplomacyV2SubmissionTemperament.Proud, 8), // Nizar
            new DiplomacyV2SubmissionProfile(14, DiplomacyV2SubmissionTemperament.Steadfast, 6), // Sheriff
            new DiplomacyV2SubmissionProfile(15, DiplomacyV2SubmissionTemperament.Proud, 8), // Marshal
            new DiplomacyV2SubmissionProfile(16, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Abbot
            new DiplomacyV2SubmissionProfile(17, DiplomacyV2SubmissionTemperament.Adaptable, 6), // Jewel
            new DiplomacyV2SubmissionProfile(18, DiplomacyV2SubmissionTemperament.Proud, 8), // Sentinel
            new DiplomacyV2SubmissionProfile(19, DiplomacyV2SubmissionTemperament.Adaptable, 6), // Nomad
            new DiplomacyV2SubmissionProfile(20, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Kahin
            new DiplomacyV2SubmissionProfile(21, DiplomacyV2SubmissionTemperament.Adaptable, 5), // Canary
            new DiplomacyV2SubmissionProfile(22, DiplomacyV2SubmissionTemperament.Adaptable, 5), // Trader
            new DiplomacyV2SubmissionProfile(23, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Sergeant
            new DiplomacyV2SubmissionProfile(24, DiplomacyV2SubmissionTemperament.Proud, 8), // Lioness
            new DiplomacyV2SubmissionProfile(25, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Crocodile
            new DiplomacyV2SubmissionProfile(26, DiplomacyV2SubmissionTemperament.Proud, 8), // Baldwin
            new DiplomacyV2SubmissionProfile(27, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Bullseye
            new DiplomacyV2SubmissionProfile(28, DiplomacyV2SubmissionTemperament.Steadfast, 7), // Surgeon
            new DiplomacyV2SubmissionProfile(29, DiplomacyV2SubmissionTemperament.Proud, 8), // Baibars
        };

        internal static DiplomacyV2SubmissionProfile ProfileFor(int lordId)
        {
            return lordId > 0 && lordId < Profiles.Length ? Profiles[lordId] : null;
        }

        // Actual SE1.45 SHCDESE.Interop.AILords: RAT=1, WOLF=4,
        // SALADIN=5, SULTAN=7, RICHARD=8. Never infer a lord from a slot
        // or the diplomacy personality. Unknown/custom lords are not opted in.
        internal static bool CanAiSubmit(int lordId)
        {
            return ProfileFor(lordId) != null && !NeverSubmits(lordId);
        }

        internal static bool NeverSubmits(int lordId)
        {
            return lordId == 4 || lordId == 5 || lordId == 8;
        }

        internal static int PressureBand(int lordId, long localMilitary,
            long targetMilitary, int besiegingUnits, long besiegingMilitary,
            long defendingMilitary)
        {
            if (!CanAiSubmit(lordId) || targetMilitary < 0L
                || defendingMilitary < 0L || localMilitary < MinimumTotalMilitary
                || besiegingUnits < MinimumBesiegingUnits
                || besiegingMilitary < MinimumBesiegingMilitary
                || besiegingMilitary > localMilitary)
                return 0;
            // Both gates are necessary. Only the requesting player's physical
            // force at this castle counts; map wealth, distant armies or a
            // third party's siege never substitute for that force.
            // Decimal avoids overflowing even when the source long is maximal.
            decimal strong = localMilitary;
            decimal weak = targetMilitary;
            decimal siege = besiegingMilitary;
            decimal defense = defendingMilitary;
            if (strong >= weak * 10m && siege >= defense * 8m)
                return 3;
            if (strong >= weak * 6m && siege >= defense * 5m)
                return 2;
            if (strong >= weak * 4m && siege >= defense * 3m)
                return 1;
            return 0;
        }

        internal static int ChancePercent(int lordId, int band,
            DiplomacyV2SubmissionOfferOrigin origin)
        {
            DiplomacyV2SubmissionProfile profile = ProfileFor(lordId);
            if (profile == null || NeverSubmits(lordId) || band < profile.MinimumPressureBand
                || band > 3 || !ValidOrigin(origin)) return 0;
            bool demand = origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand;
            int chance;
            switch (profile.Temperament)
            {
                case DiplomacyV2SubmissionTemperament.Yielding:
                    chance = demand ? (band == 1 ? 80 : band == 2 ? 95 : 100)
                        : (band == 1 ? 50 : band == 2 ? 75 : 95); break;
                case DiplomacyV2SubmissionTemperament.Adaptable:
                    chance = demand ? (band == 1 ? 50 : band == 2 ? 75 : 95)
                        : (band == 1 ? 20 : band == 2 ? 45 : 75); break;
                case DiplomacyV2SubmissionTemperament.Steadfast:
                    chance = demand ? (band == 2 ? 45 : 75) : (band == 2 ? 20 : 45); break;
                case DiplomacyV2SubmissionTemperament.Proud:
                    chance = demand ? 45 : 20; break;
                default: return 0;
            }
            return Math.Min(100, chance + profile.ChanceBonusPercent);
        }

        private static bool ValidOrigin(DiplomacyV2SubmissionOfferOrigin origin)
        {
            return origin == DiplomacyV2SubmissionOfferOrigin.AiOffer
                || origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand;
        }

        internal static DiplomacyV2SubmissionAvailability Availability(
            RelationState relation, int day, int knownLordId,
            int coalitionMemberCount, bool canJoinAlliance)
        {
            DiplomacyV2SubmissionAvailability? blocker = EligibilityBlocker(
                relation, day, knownLordId, coalitionMemberCount, canJoinAlliance);
            if (blocker.HasValue) return blocker.Value;
            DiplomacyV2RelationState state = relation.V2;
            if (HasOffer(state))
                return state.SubmissionOfferAccepted || state.SubmissionAcceptancePending
                    ? DiplomacyV2SubmissionAvailability.OfferCommitting
                    : DiplomacyV2SubmissionAvailability.OfferPending;
            if (day < state.SubmissionNextOfferDay)
                return DiplomacyV2SubmissionAvailability.OfferCooldown;
            if (state.SubmissionLastComparedDay != day)
                return DiplomacyV2SubmissionAvailability.AwaitingDailyAssessment;
            if (state.SubmissionPressureDays <= 0)
                return DiplomacyV2SubmissionAvailability.PressureNotEstablished;
            if (state.SubmissionPressureDays < ProfileFor(knownLordId).RequiredPressureDays)
                return DiplomacyV2SubmissionAvailability.PressureDeveloping;
            return DiplomacyV2SubmissionAvailability.AwaitingOffer;
        }

        internal static DiplomacyV2SubmissionAssessment Assess(RelationState relation,
            int day, int lordId, int coalitionMemberCount, bool canJoinAlliance,
            int pressureBand, DiplomacyV2SubmissionOfferOrigin origin)
        {
            DiplomacyV2SubmissionProfile profile = ProfileFor(lordId);
            DiplomacyV2RelationState state = relation == null ? null : relation.V2;
            var result = new DiplomacyV2SubmissionAssessment
            {
                Profile = profile,
                Availability = Availability(relation, day, lordId, coalitionMemberCount, canJoinAlliance),
                PressureBand = pressureBand,
                PressureDays = state == null ? 0 : state.SubmissionPressureDays,
                RequiredPressureDays = profile == null ? 0 : profile.RequiredPressureDays,
                ChancePercent = ChancePercent(lordId, pressureBand, origin),
                NextAttemptDay = state == null ? 0
                    : origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand
                        ? state.SubmissionNextDemandDay : state.SubmissionNextOfferDay,
            };
            if (EligibilityBlocker(relation, day, lordId, coalitionMemberCount, canJoinAlliance).HasValue
                || HasOffer(state) || !ValidOrigin(origin)) return result;
            // Automatic polling has a separate short retry timer. Its failure
            // must not make the explicit player action perpetually unreachable.
            if (day < result.NextAttemptDay)
                result.Availability = DiplomacyV2SubmissionAvailability.OfferCooldown;
            else if (state.SubmissionLastComparedDay != day)
                result.Availability = DiplomacyV2SubmissionAvailability.AwaitingDailyAssessment;
            else if (pressureBand < profile.MinimumPressureBand || pressureBand > 3
                || state.SubmissionPressureDays == 0)
                result.Availability = DiplomacyV2SubmissionAvailability.PressureNotEstablished;
            else if (state.SubmissionPressureDays < profile.RequiredPressureDays)
                result.Availability = DiplomacyV2SubmissionAvailability.PressureDeveloping;
            else
            {
                result.Availability = DiplomacyV2SubmissionAvailability.AwaitingOffer;
                result.CanAttempt = result.ChancePercent > 0;
            }
            return result;
        }

        // Null only means that these structural restrictions do not block the
        // attempt. Live roster/lord and physical pressure checks remain required
        // before creation and acceptance. Quoted economic terms stay fixed.
        internal static DiplomacyV2SubmissionAvailability? EligibilityBlocker(
            RelationState relation, int day, int knownLordId,
            int coalitionMemberCount, bool canJoinAlliance)
        {
            if (relation == null || relation.V2 == null || coalitionMemberCount < 1
                || !DiplomacyLogicalClock.IsValidSavedDay(day))
                return DiplomacyV2SubmissionAvailability.Unavailable;
            DiplomacyV2RelationState state = relation.V2;
            if (DiplomacyV2Vassalage.IsActive(state))
                return DiplomacyV2SubmissionAvailability.ActiveFealty;
            if (state.PendingVassalOverlordPlayerId != 0 || relation.PendingOffer)
                return DiplomacyV2SubmissionAvailability.OtherDecisionPending;
            if (coalitionMemberCount != 1)
                return DiplomacyV2SubmissionAvailability.CoalitionHasMultipleMembers;
            if (relation.Allied)
                return DiplomacyV2SubmissionAvailability.EqualAlliance;
            if (state.Agreement != DiplomacyV2AgreementKind.None)
                return DiplomacyV2SubmissionAvailability.ActiveTreaty;
            if (relation.Demand != null)
                return DiplomacyV2SubmissionAvailability.NegotiationPending;
            if (day < relation.RelationshipBlockedUntilDay)
                return DiplomacyV2SubmissionAvailability.RelationshipBlocked;
            // The caller supplies an observed ruler identity, or0 if unknown.
            // A saved primary personality/lord fallback is not substituted here.
            if (knownLordId <= 0)
                return DiplomacyV2SubmissionAvailability.LordUnknown;
            if (NeverSubmits(knownLordId))
                return DiplomacyV2SubmissionAvailability.LordNeverSubmits;
            if (!CanAiSubmit(knownLordId))
                return DiplomacyV2SubmissionAvailability.LordNotEligible;
            if (!canJoinAlliance)
                return DiplomacyV2SubmissionAvailability.NoRemainingOpponent;
            return null;
        }

        internal static bool HasOffer(DiplomacyV2RelationState state)
        {
            return state != null && state.SubmissionOfferPlayerId != 0;
        }

        internal static bool HasCurrentPressure(DiplomacyV2RelationState state,
            int lordId, int band)
        {
            DiplomacyV2SubmissionProfile profile = ProfileFor(lordId);
            return state != null && state.SubmissionPressureRuleVersion == CurrentPressureRuleVersion
                && CanAiSubmit(lordId) && profile != null
                && band >= profile.MinimumPressureBand && band <= 3;
        }

        /// <summary>
        /// Ob der zuletzt BEWERTETE Spieltag noch Druck ausgewiesen hat.
        /// </summary>
        /// <remarks>
        /// Entscheidet am FRISTENDE, ob nachgebessert statt zurueckgezogen
        /// wird. Waehrend der laufenden Frist wird der Druck bewusst nicht
        /// mehr abgefragt: bis zum 09.09.2026 pruefte der Ablauf ihn in jedem
        /// Takt und mass das Band dabei neu, obwohl er nur einmal je Spieltag
        /// aufgebaut wird. Zwischen zwei Takten bewegen sich Einheiten, und
        /// eine einzige schwankende Messung nahm ein eben gemachtes Angebot
        /// wieder zurueck und setzte ueber LosePressure den ueber Tage
        /// aufgebauten Druck auf null. Im Spiel beobachtet: submission_offered
        /// seq=294, submission_withdrawn seq=296 - zwei Takte, derselbe Tag.
        /// </remarks>
        internal static bool OfferPressureHolds(DiplomacyV2RelationState state)
        {
            return state != null && state.SubmissionPressureDays > 0;
        }

        /// <summary>Nachgebesserter Tribut, gedeckelt auf das Maximum.</summary>
        internal static int ImprovedTribute(int amount)
        {
            if (amount <= 0) return 0;
            long besser = (long)amount * (100 + OfferImprovementPercent) / 100;
            if (besser < DiplomacyV2Vassalage.MinimumTributeAmount)
                besser = DiplomacyV2Vassalage.MinimumTributeAmount;
            if (besser > DiplomacyV2Vassalage.MaximumTributeAmount)
                besser = DiplomacyV2Vassalage.MaximumTributeAmount;
            return (int)besser;
        }

        internal static void LosePressure(DiplomacyV2RelationState state, int day)
        {
            if (state == null || !DiplomacyLogicalClock.IsValidSavedDay(day)) return;
            state.SubmissionPressureRuleVersion = CurrentPressureRuleVersion;
            state.SubmissionPressureDays = 0;
            state.SubmissionLastComparedDay = Math.Max(state.SubmissionLastComparedDay, day);
        }

        internal static bool CanCommitOffer(RelationState relation)
        {
            return CanAcceptQuote(relation) && relation.V2.SubmissionOfferAccepted
                && !relation.V2.SubmissionAcceptancePending;
        }

        private static bool CanAcceptQuote(RelationState relation)
        {
            if (relation == null || !HasOffer(relation.V2)) return false;
            DiplomacyV2RelationState s = relation.V2;
            return !relation.Allied
                && !relation.PendingOffer && relation.Demand == null
                && s.Agreement == DiplomacyV2AgreementKind.None
                && !DiplomacyV2Vassalage.IsActive(s)
                && s.PendingVassalOverlordPlayerId == 0
                && CanAiSubmit(s.SubmissionOfferLordId)
                && s.SubmissionOfferPlayerId > 0 && s.SubmissionOfferPlayerId <= 8
                && s.SubmissionOfferCreatedDay >= 0
                && s.SubmissionResponseDaysRemaining > 0
                && s.SubmissionResponseDaysRemaining <= ResponseDays
                && ValidOrigin(s.SubmissionOfferOrigin)
                && s.SubmissionOfferTributeAmount >= DiplomacyV2Vassalage.MinimumTributeAmount
                && s.SubmissionOfferTributeAmount <= DiplomacyV2Vassalage.MaximumTributeAmount;
        }

        internal static bool ObservePressure(DiplomacyV2RelationState state,
            int day, bool eligible)
        {
            // Compatibility for existing pure scenario builders: Rat's original
            // five-day rule. Production uses the identity-aware overload below.
            return ObservePressure(state, day, 1, eligible ? 1 : 0, eligible);
        }

        internal static bool ObservePressure(DiplomacyV2RelationState state,
            int day, int lordId, int band, bool structurallyEligible)
        {
            if (state == null || !DiplomacyLogicalClock.IsValidSavedDay(day)) return false;
            if (state.SubmissionPressureRuleVersion != CurrentPressureRuleVersion)
            {
                state.SubmissionPressureDays = 0;
                state.SubmissionLastComparedDay = -1;
                state.SubmissionPressureRuleVersion = CurrentPressureRuleVersion;
            }
            if (day <= state.SubmissionLastComparedDay) return false;
            DiplomacyV2SubmissionProfile profile = ProfileFor(lordId);
            bool eligible = structurallyEligible && CanAiSubmit(lordId)
                && band >= profile.MinimumPressureBand && band <= 3;
            bool consecutive = state.SubmissionLastComparedDay == day - 1;
            state.SubmissionLastComparedDay = day;
            state.SubmissionPressureDays = eligible
                ? Math.Min(MaximumPressureDays,
                    consecutive ? state.SubmissionPressureDays + 1 : 1)
                : 0;
            return eligible && !HasOffer(state)
                && state.SubmissionPressureDays >= profile.RequiredPressureDays
                && day >= state.SubmissionNextOfferDay;
        }

        internal static DiplomacyV2SubmissionAttemptResult TryAttempt(
            RelationState relation, int player, int lordId, int amount, int day,
            string mapFingerprint, DiplomacyV2SubmissionOfferOrigin origin, int pressureBand)
        {
            if (string.IsNullOrEmpty(mapFingerprint) || relation == null
                || string.IsNullOrEmpty(relation.CoalitionId) || !ValidOrigin(origin)
                || !CanStageQuote(relation, player, lordId, amount, day))
                return DiplomacyV2SubmissionAttemptResult.Blocked;
            DiplomacyV2RelationState state = relation.V2;
            DiplomacyV2SubmissionProfile profile = ProfileFor(lordId);
            int next = origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand
                ? state.SubmissionNextDemandDay : state.SubmissionNextOfferDay;
            int chance = ChancePercent(lordId, pressureBand, origin);
            if (day < next || state.SubmissionLastComparedDay != day
                || state.SubmissionPressureDays < profile.RequiredPressureDays || chance <= 0)
                return DiplomacyV2SubmissionAttemptResult.Blocked;

            // Commit the attempt's cooldown before exposing its result. The
            // stable daily roll deliberately has no click/frame/attempt seed:
            // both initiators share it, with different willingness thresholds.
            bool accepted = DiplomacyBalance.OfferRoll(mapFingerprint,
                "submission:" + relation.CoalitionId, day, 0, chance * 10);
            int delay = origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand
                ? OfferCooldownDays : AutomaticRetryDays;
            state.SubmissionNextOfferDay = Math.Max(state.SubmissionNextOfferDay, checked(day + delay));
            if (origin == DiplomacyV2SubmissionOfferOrigin.PlayerDemand)
                state.SubmissionNextDemandDay = Math.Max(state.SubmissionNextDemandDay,
                    checked(day + OfferCooldownDays));
            if (!accepted) return DiplomacyV2SubmissionAttemptResult.Refused;
            CreateQuote(state, player, lordId, amount, day, origin);
            return DiplomacyV2SubmissionAttemptResult.Offered;
        }

        internal static bool TryQueueAcceptance(RelationState relation)
        {
            if (!CanAcceptQuote(relation) || relation.V2.SubmissionOfferAccepted) return false;
            relation.V2.SubmissionAcceptancePending = true;
            return true;
        }

        internal static bool TryAcceptOffer(RelationState relation)
        {
            if (!CanAcceptQuote(relation)) return false;
            relation.V2.SubmissionOfferAccepted = true;
            relation.V2.SubmissionAcceptancePending = false;
            return true;
        }

        internal static void RestoreUncommittedOffer(RelationState relation,
            DiplomacyPendingTeamTransition transition)
        {
            // Native work did not start. Preserve the confirmed answer for a
            // later automatic retry; never turn it back into an unanswered offer.
            // A live team journal retains its accepted consent unchanged.
            if (relation != null && !relation.Allied && transition == null
                && HasOffer(relation.V2)
                && (relation.V2.SubmissionOfferAccepted || relation.V2.SubmissionAcceptancePending))
            {
                relation.V2.SubmissionOfferAccepted = false;
                relation.V2.SubmissionAcceptancePending = true;
            }
        }

        internal static bool StageOffer(RelationState relation, int player,
            int lordId, int amount, int day)
        {
            if (!CanStageQuote(relation, player, lordId, amount, day)
                || day < relation.V2.SubmissionNextOfferDay
                || relation.V2.SubmissionPressureDays < ProfileFor(lordId).RequiredPressureDays)
                return false;
            CreateQuote(relation.V2, player, lordId, amount, day,
                DiplomacyV2SubmissionOfferOrigin.AiOffer);
            return true;
        }

        private static bool CanStageQuote(RelationState relation, int player,
            int lordId, int amount, int day)
        {
            return !(relation == null || relation.V2 == null || relation.Allied
                || relation.Demand != null || relation.PendingOffer
                || relation.V2.Agreement != DiplomacyV2AgreementKind.None
                || DiplomacyV2Vassalage.IsActive(relation.V2)
                || relation.V2.PendingVassalOverlordPlayerId != 0
                || relation.V2.SubmissionPressureRuleVersion != CurrentPressureRuleVersion
                || !CanAiSubmit(lordId) || player < 1 || player > 8
                || !DiplomacyLogicalClock.IsValidSavedDay(day)
                || day < relation.RelationshipBlockedUntilDay
                || HasOffer(relation.V2)
                || amount < DiplomacyV2Vassalage.MinimumTributeAmount
                || amount > DiplomacyV2Vassalage.MaximumTributeAmount);
        }

        private static void CreateQuote(DiplomacyV2RelationState state,
            int player, int lordId, int amount, int day, DiplomacyV2SubmissionOfferOrigin origin)
        {
            state.SubmissionOfferPlayerId = player;
            state.SubmissionOfferLordId = lordId;
            state.SubmissionOfferTributeAmount = amount;
            state.SubmissionOfferCreatedDay = day;
            state.SubmissionResponseDaysRemaining = ResponseDays;
            state.SubmissionOfferAccepted = false;
            state.SubmissionAcceptancePending = false;
            state.SubmissionOfferOrigin = origin;
        }

        /// <summary>Was ein abgelaufener Angebotstag ergeben hat.</summary>
        internal enum DiplomacyV2OfferDayResult
        {
            /// <summary>Die Frist laeuft weiter.</summary>
            Pending = 0,
            /// <summary>Der Druck hielt an: besserer Tribut, Frist von vorn.</summary>
            Improved = 1,
            /// <summary>Das Angebot ist vom Tisch.</summary>
            Withdrawn = 2,
        }

        /// <summary>
        /// Zaehlt einen Angebotstag herunter und entscheidet am Fristende.
        /// </summary>
        /// <remarks>
        /// 09.09.2026, Benutzervorgabe: das Angebot steht drei Spieltage. Ist
        /// der Druck danach immer noch da, faellt ein Wurf: mit halber Chance
        /// bessert der Fuerst den Tribut nach und die Frist beginnt von vorn,
        /// sonst ist das Angebot ganz vom Tisch. Ohne anhaltenden Druck laeuft
        /// es wie bisher aus. In beiden Schlussfaellen raeumt CloseOffer den
        /// Druckzaehler ab, sodass erst ein neu aufgebauter Druck wieder ein
        /// Angebot erzeugen kann.
        ///
        /// Der Wurf haengt an Karte, Koalition und Spieltag, nicht am Takt oder
        /// an einem Klick: derselbe Tag ergibt dieselbe Entscheidung.
        /// </remarks>
        internal static DiplomacyV2OfferDayResult ElapseResponseDay(
            DiplomacyV2RelationState state, int day, bool presentedThisSession,
            string mapFingerprint, string coalitionId)
        {
            if (!HasOffer(state) || state.SubmissionOfferAccepted || state.SubmissionAcceptancePending
                || !presentedThisSession || day <= state.SubmissionOfferCreatedDay)
                return DiplomacyV2OfferDayResult.Pending;
            state.SubmissionResponseDaysRemaining = Math.Max(0,
                state.SubmissionResponseDaysRemaining - 1);
            if (state.SubmissionResponseDaysRemaining != 0)
                return DiplomacyV2OfferDayResult.Pending;
            if (OfferPressureHolds(state)
                && !string.IsNullOrEmpty(mapFingerprint)
                && !string.IsNullOrEmpty(coalitionId)
                && DiplomacyBalance.OfferRoll(mapFingerprint,
                    "submission_renewal:" + coalitionId, day, 0, OfferRenewalChanceTenths))
            {
                state.SubmissionOfferTributeAmount =
                    ImprovedTribute(state.SubmissionOfferTributeAmount);
                state.SubmissionResponseDaysRemaining = ResponseDays;
                return DiplomacyV2OfferDayResult.Improved;
            }
            CloseOffer(state, day, true);
            return DiplomacyV2OfferDayResult.Withdrawn;
        }

        internal static void CloseOffer(DiplomacyV2RelationState state,
            int day, bool cooldown)
        {
            if (state == null) return;
            if (cooldown)
            {
                int next = checked(day + OfferCooldownDays);
                state.SubmissionNextOfferDay = Math.Max(state.SubmissionNextOfferDay, next);
                state.SubmissionNextDemandDay = Math.Max(state.SubmissionNextDemandDay, next);
            }
            state.SubmissionOfferPlayerId = 0;
            state.SubmissionOfferLordId = 0;
            state.SubmissionOfferTributeAmount = 0;
            state.SubmissionOfferCreatedDay = -1;
            state.SubmissionResponseDaysRemaining = 0;
            state.SubmissionOfferAccepted = false;
            state.SubmissionAcceptancePending = false;
            state.SubmissionOfferOrigin = DiplomacyV2SubmissionOfferOrigin.None;
            state.SubmissionPressureDays = 0;
        }

        internal static void CancelAcceptedTeamTransition(DiplomacyV2RelationState state, int day)
        {
            // A stopped team operation never established the quoted fealty.
            // Remove its consent together with that operation, without a
            // refusal cooldown, tribute, release counter or relationship loss.
            if (state != null && state.SubmissionOfferAccepted)
                CloseOffer(state, Math.Max(0, day), false);
        }

        internal static void Validate(RelationState relation, int day)
        {
            DiplomacyV2RelationState s = relation.V2;
            bool open = HasOffer(s);
            if (s.SubmissionPressureDays < 0
                || s.SubmissionPressureDays > MaximumPressureDays
                || s.SubmissionPressureRuleVersion < 0
                || s.SubmissionPressureRuleVersion > CurrentPressureRuleVersion
                || s.SubmissionPressureRuleVersion == 0 && s.SubmissionPressureDays != 0
                || s.SubmissionLastComparedDay < -1 || s.SubmissionLastComparedDay > day
                || s.SubmissionNextOfferDay < 0 || s.SubmissionNextOfferDay > (long)day + OfferCooldownDays
                || s.SubmissionNextDemandDay < 0 || s.SubmissionNextDemandDay > (long)day + OfferCooldownDays)
                throw new InvalidOperationException("submission history has invalid dates or pressure");
            if (!open)
            {
                if (s.SubmissionOfferLordId != 0 || s.SubmissionOfferTributeAmount != 0
                    || s.SubmissionOfferCreatedDay != -1 || s.SubmissionResponseDaysRemaining != 0
                    || s.SubmissionOfferAccepted || s.SubmissionAcceptancePending
                    || s.SubmissionOfferOrigin != DiplomacyV2SubmissionOfferOrigin.None)
                    throw new InvalidOperationException("closed submission retains a decision");
                return;
            }
            if (s.SubmissionOfferAccepted && s.SubmissionAcceptancePending
                || relation.Allied || relation.PendingOffer || relation.Demand != null
                || s.Agreement != DiplomacyV2AgreementKind.None || DiplomacyV2Vassalage.IsActive(s)
                || s.PendingVassalOverlordPlayerId != 0
                || s.SubmissionOfferPlayerId < 1 || s.SubmissionOfferPlayerId > 8
                || !CanAiSubmit(s.SubmissionOfferLordId)
                || !ValidOrigin(s.SubmissionOfferOrigin)
                || s.SubmissionOfferCreatedDay < 0 || s.SubmissionOfferCreatedDay > day
                || s.SubmissionResponseDaysRemaining < 1 || s.SubmissionResponseDaysRemaining > ResponseDays
                || s.SubmissionOfferTributeAmount < DiplomacyV2Vassalage.MinimumTributeAmount
                || s.SubmissionOfferTributeAmount > DiplomacyV2Vassalage.MaximumTributeAmount)
                throw new InvalidOperationException("pending submission is invalid");
        }
    }

    /// <summary>
    /// Die wiederkehrende Tributpflicht - reine Regeln, kein Spielzugriff.
    /// </summary>
    /// <remarks>
    /// Warum eigenstaendig (07.09.2026): eine Forderung ist einmalig und
    /// quittiert sich selbst. Tribut ist eine Pflicht ueber die Zeit und
    /// braucht Zeitraum, Faelligkeit und eine Folge bei Ausbleiben.
    /// </remarks>
    internal static class DiplomacyV2Tribute
    {
        internal const int GraceDays = 5;
        internal const int WarningLeadDays = 3;

        internal static int GraceDeadlineDay(DiplomacyV2RelationState state)
        {
            return !IsActive(state) || state.TributeNextDueDay < 0
                ? -1 : checked(state.TributeNextDueDay + GraceDays);
        }

        internal static int DaysUntilGraceDeadline(DiplomacyV2RelationState state, int day)
        {
            int deadline = GraceDeadlineDay(state);
            return deadline < 0 ? -1 : Math.Max(0, deadline - day);
        }

        internal static bool CanRegisterMiss(DiplomacyV2RelationState state, int day)
        {
            return IsDue(state, day) && day >= GraceDeadlineDay(state)
                && state.TributeMissedCycles == 0;
        }

        internal static bool IsWarningDay(DiplomacyV2RelationState state, int day)
        {
            return IsActive(state) && state.TributeNextDueDay >= 0
                && day == state.TributeNextDueDay - WarningLeadDays;
        }

        // A settled invoice starts a fresh full period. A poor vassal must not
        // face the next payment only a few days after clearing an old debt.
        private static int NextScheduledDay(DiplomacyV2RelationState state, int day)
        {
            return checked(day + state.TributeIntervalDays);
        }
        /// <summary>Vorgabe des Zahlungszeitraums in Spieltagen.</summary>
        internal const int DefaultIntervalDays = 20;

        /// <summary>Kuerzester zulaessiger Zeitraum.</summary>
        internal const int MinimumIntervalDays = 5;

        /// <summary>Laengster zulaessiger Zeitraum.</summary>
        internal const int MaximumIntervalDays = 120;

        /// <summary>
        /// Historic threshold retained for loading an already pending legacy
        /// treaty transition; new arrears never reach a second default.
        /// </summary>
        /// <remarks>
        /// Eines kann ein schlechter Monat sein, zwei sind eine Entscheidung.
        /// </remarks>
        internal const int MissedCyclesUntilBreak = 2;

        /// <summary>Gold - die Vorgabe, weil es keine Lagerfrage kennt.</summary>
        internal const int GoldGoodId = 15;

        internal static bool IsActive(DiplomacyV2RelationState state)
        {
            return state != null
                && state.TributeGoodId > 0
                && state.TributeAmount > 0
                && state.TributeIntervalDays > 0;
        }

        /// <summary>Ist die Zahlung an diesem Tag faellig?</summary>
        internal static bool IsDue(DiplomacyV2RelationState state, int day)
        {
            return IsActive(state)
                && state.TributeNextDueDay >= 0
                && day >= state.TributeNextDueDay;
        }

        // A gold invoice may be settled with one complete goods transfer.
        // Frozen map prices make the amount reproducible after save/load;
        // rounding is bounded so a high-priced item cannot grossly overpay.
        internal static bool TryEquivalentGoodsAmount(
            DiplomacyV2RelationState state, int goodId, int unitValue,
            out int amount)
        {
            amount = 0;
            if (!IsActive(state) || state.TributeGoodId != GoldGoodId
                || goodId < 2 || goodId > 24 || goodId == 5 || goodId == 8
                || goodId == GoldGoodId || unitValue <= 0)
                return false;
            long needed = ((long)state.TributeAmount + unitValue - 1) / unitValue;
            long value = needed * unitValue;
            if (needed < 1 || needed > 1000000
                || value > (long)state.TributeAmount
                    + Math.Max(10, state.TributeAmount / 4))
                return false;
            amount = (int)needed;
            return true;
        }

        internal static bool AcceptsSettlement(
            DiplomacyV2RelationState state, int goodId, int amount,
            IReadOnlyDictionary<int, int> frozenPrices)
        {
            if (!IsActive(state) || amount <= 0) return false;
            if (goodId == state.TributeGoodId)
                return amount == state.TributeAmount;
            int price;
            int equivalent;
            return frozenPrices != null
                && frozenPrices.TryGetValue(goodId, out price)
                && TryEquivalentGoodsAmount(state, goodId, price, out equivalent)
                && amount == equivalent;
        }

        /// <summary>Wie viele Tage bis zur naechsten Faelligkeit.</summary>
        internal static int DaysUntilDue(
            DiplomacyV2RelationState state,
            int day)
        {
            if (!IsActive(state) || state.TributeNextDueDay < 0)
            {
                return -1;
            }
            return Math.Max(0, state.TributeNextDueDay - day);
        }

        /// <summary>
        /// Vereinbart eine Tributpflicht. Ungueltige Angaben werden nicht
        /// stillschweigend zurechtgebogen, sondern abgewiesen.
        /// </summary>
        internal static bool Arrange(
            DiplomacyV2RelationState state,
            int goodId,
            int amount,
            int intervalDays,
            int day)
        {
            if (state == null
                || goodId < 2 || goodId > 24 || goodId == 5 || goodId == 8
                || amount <= 0
                || amount > 1000000
                || !DiplomacyLogicalClock.IsValidSavedDay(day)
                || intervalDays < MinimumIntervalDays
                || intervalDays > MaximumIntervalDays)
            {
                return false;
            }
            state.TributeGoodId = goodId;
            state.TributeAmount = amount;
            state.TributeIntervalDays = intervalDays;
            // Die erste Zahlung ist erst am Ende des ersten Zeitraums faellig,
            // nicht sofort - sonst waere die Pflicht im Augenblick der
            // Vereinbarung schon versaeumt.
            state.TributeNextDueDay = day + intervalDays;
            state.TributeMissedCycles = 0;
            state.TributeReassessmentPending = false;
            return true;
        }

        /// <summary>Eine Zahlung ist eingegangen.</summary>
        internal static void RegisterPayment(
            DiplomacyV2RelationState state,
            int day)
        {
            if (!IsDue(state, day))
            {
                return;
            }
            state.TributePaidCycles++;
            state.TributeMissedCycles = 0;
            state.TributeNextDueDay = NextScheduledDay(state, day);
            state.TributeReassessmentPending = state.TributeGoodId == GoldGoodId;
        }

        /// <summary>
        /// Ein Zeitraum ist ohne Zahlung verstrichen. Die Rechnung bleibt
        /// offen; eine wiederholte taegliche Pruefung zaehlt nicht erneut.
        /// </summary>
        internal static bool RegisterMiss(
            DiplomacyV2RelationState state,
            int day)
        {
            if (!CanRegisterMiss(state, day))
            {
                return false;
            }
            // One unpaid invoice remains due and is retried on later days.
            // A continuing lack of gold must not manufacture a second default.
            state.TributeMissedCycles = 1;
            // Lebenslaufzaehler: er ueberlebt `Clear` und gehoert damit zur
            // Geschichte der Beziehung, nicht zur laufenden Pflicht.
            state.TributeDefaults++;
            return false;
        }

        // Only a future period is repriced after payment. An overdue invoice
        // keeps its accepted quote until it has actually been settled.
        // The workflow additionally excludes every in-flight transfer journal.
        internal static bool TryReassessNextPeriod(DiplomacyV2RelationState state,
            int day, long economicStrength)
        {
            if (!IsActive(state) || !state.TributeReassessmentPending
                || state.TributeGoodId != GoldGoodId
                || !DiplomacyLogicalClock.IsValidSavedDay(day)
                || state.TributeNextDueDay <= day) return false;
            state.TributeAmount = DiplomacyV2Vassalage.TributeAmountForEconomy(economicStrength);
            state.TributeReassessmentPending = false;
            return true;
        }

        /// <summary>Hebt die Pflicht auf.</summary>
        internal static void Clear(DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            state.TributeGoodId = 0;
            state.TributeAmount = 0;
            state.TributeIntervalDays = 0;
            state.TributeNextDueDay = -1;
            state.TributeMissedCycles = 0;
            state.TributeReassessmentPending = false;
        }

        /// <summary>
        /// Raeumt einen widerspruechlichen Zustand aus einem Spielstand auf.
        /// </summary>
        /// <remarks>
        /// Ein halb beschriebener Tribut - Gut ohne Menge, Faelligkeit ohne
        /// Zeitraum - ist keine Pflicht, sondern ein Datenfehler. Er wird
        /// geloescht statt geraten.
        /// </remarks>
        internal static void Normalize(DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            bool vollstaendig = state.TributeGoodId > 0
                && state.TributeAmount > 0
                && state.TributeIntervalDays >= MinimumIntervalDays
                && state.TributeIntervalDays <= MaximumIntervalDays;
            state.TributeDefaults = Math.Max(0, state.TributeDefaults);
            if (!vollstaendig)
            {
                Clear(state);
                state.TributePaidCycles = Math.Max(0, state.TributePaidCycles);
                return;
            }
            if (state.TributeNextDueDay < 0)
            {
                state.TributeNextDueDay = 0;
            }
            state.TributeMissedCycles = Math.Max(
                0,
                Math.Min(MissedCyclesUntilBreak, state.TributeMissedCycles));
            state.TributePaidCycles = Math.Max(0, state.TributePaidCycles);
        }
    }

    /// <summary>
    /// Das Lehnsverhaeltnis - reine Regeln, kein Spielzugriff.
    /// </summary>
    internal static class DiplomacyV2Vassalage
    {
        /// <summary>
        /// Ab welchem Staerkeverhaeltnis eine Unterwerfung ueberhaupt
        /// angeboten wird, in Prozent.
        /// </summary>
        /// <remarks>
        /// 400 heisst: der Staerkere muss viermal so stark sein. Darunter ist
        /// es kein erdrueckendes Uebergewicht, sondern ein Krieg.
        /// </remarks>
        internal const int SubjugationRatioPercent = 400;
        internal const int SubjugationMinimumMilitaryValue =
            DiplomacyV2CombatRules.SubstantialForceMinimumValue;

        /// <summary>
        /// So viele aufeinanderfolgende Tage muss das Verhaeltnis bestehen.
        /// </summary>
        /// <remarks>
        /// Ein einzelner verlorener Trupp darf nichts ausloesen.
        /// </remarks>
        internal const int SubjugationEdgeDays = 5;

        /// <summary>
        /// So viele aufeinanderfolgende Tage militaerischer Ueberlegenheit,
        /// bevor sich ein Vasall auflehnt.
        /// </summary>
        internal const int RebellionEdgeDays = 5;

        /// <summary>Vor Ablauf ist das Verhaeltnis nicht aufloesbar.</summary>
        /// <remarks>
        /// Sonst waere Vasallentum eine Ausrede statt einer Bindung.
        /// </remarks>
        internal const int MinimumTermDays = 40;

        /// <summary>
        /// So lange bleibt ein Antrag auf Gleichberechtigung offen.
        /// </summary>
        /// <remarks>
        /// Danach gilt er als abgelehnt - Schweigen ist auch eine Antwort,
        /// und ein Antrag, der ewig offen steht, blockiert das Verhaeltnis.
        /// </remarks>
        internal const int EqualityRequestGraceDays = 10;
        internal const int EqualityRequestCooldownDays = DiplomacyV2Tribute.DefaultIntervalDays;

        internal static bool IsActive(DiplomacyV2RelationState state)
        {
            return state != null
                && state.VassalRole != DiplomacyV2VassalRole.None;
        }

        internal static bool StageVassalOffer(RelationState relation,
            int overlordPlayer, int amount, int day)
        {
            if (relation == null || relation.V2 == null || !relation.Allied
                || IsActive(relation.V2)
                || DiplomacyV2StateMachine.HasOutstandingUltimatum(relation)
                || relation.V2.PendingVassalOverlordPlayerId != 0
                || overlordPlayer < 1 || overlordPlayer > 8
                || amount < MinimumTributeAmount || amount > MaximumTributeAmount
                || !DiplomacyLogicalClock.IsValidSavedDay(day)) return false;
            relation.V2.PendingVassalOverlordPlayerId = overlordPlayer;
            relation.V2.PendingVassalTributeAmount = amount;
            relation.V2.PendingVassalOfferDay = day;
            return true;
        }

        /// <summary>
        /// Nimmt der Vasall Befehle seines Lehnsherrn vorrangig an?
        /// </summary>
        /// <remarks>
        /// Vorgabe des Benutzers (07.09.2026): "Befehle (Angriff,
        /// Verteidigung) an den Vasallen werden von diesem nach MOEGLICHKEIT
        /// vorrangig akzeptiert."
        ///
        /// Zwei Lagen heben die Bereitschaft auf, und beide sind dieselbe
        /// Sache aus zwei Richtungen:
        ///
        ///   * Ein offener Antrag auf Gleichstellung. In dem Augenblick stellt
        ///     der Vasall seinen Lehnsherrn auf die Probe; wer gleichzeitig
        ///     fordert und gehorcht, fordert nicht ernsthaft.
        ///   * Ein versaeumter Tribut. Wer die eine Pflicht nicht erfuellt,
        ///     erfuellt die andere auch nicht - sonst haette der Spieler einen
        ///     Vasallen, der nichts zahlt und trotzdem marschiert.
        ///
        /// Damit haengen Tribut, Gleichstellung und Befehlsgewalt an
        /// derselben Rechnung, statt drei unabhaengige Mechaniken zu sein, die
        /// sich widersprechen koennen.
        /// </remarks>
        internal static bool ObeysOrders(DiplomacyV2RelationState state)
        {
            return IsActive(state)
                && !EqualityRequestOpen(state)
                && state.TributeMissedCycles == 0;
        }

        /// <summary>Der Spieler, der Tribut schuldet - oder -1.</summary>
        internal static int VassalOf(DiplomacyV2RelationState state)
        {
            return IsActive(state) ? state.VassalPlayerId : -1;
        }

        /// <summary>Der Spieler, dem Tribut zusteht - oder -1.</summary>
        internal static int OverlordOf(DiplomacyV2RelationState state)
        {
            return IsActive(state) ? state.VassalOverlordPlayerId : -1;
        }

        internal static bool CoalitionIsVassal(DiplomacyV2RelationState state)
        {
            return state != null
                && state.VassalRole == DiplomacyV2VassalRole.CoalitionIsVassal;
        }

        internal static bool LocalIsVassal(DiplomacyV2RelationState state)
        {
            return state != null
                && state.VassalRole == DiplomacyV2VassalRole.LocalIsVassal;
        }

        /// <summary>
        /// Reicht das Staerkeverhaeltnis fuer eine Unterwerfung?
        /// </summary>
        internal static bool SubjugationRatioReached(
            long strongMilitary,
            long weakMilitary)
        {
            if (strongMilitary <= 0)
            {
                return false;
            }
            // Ohne jede Streitmacht ist jeder Vergleich erdrueckend; das ist
            // gewollt, aber erst nach den Bestandstagen wirksam.
            long schwelle = Math.Max(0, weakMilitary)
                * SubjugationRatioPercent / 100L;
            return strongMilitary >= Math.Max(1L, schwelle);
        }

        /// <summary>Begruendet das Verhaeltnis.</summary>
        /// <summary>
        /// Begruendet ein Lehnsverhaeltnis INNERHALB eines bestehenden
        /// Buendnisses.
        /// </summary>
        /// <remarks>
        /// Bis zum 07.09.2026 setzte diese Methode
        /// <c>Agreement = Vassalage</c> und verdraengte damit
        /// <c>Alliance</c>. Die Zustandspruefung verlangt aber
        /// <c>relation.Allied == (Agreement == Alliance)</c> und haette bei
        /// jedem verbuendeten Vasallen geworfen; ausserdem laesst
        /// <c>ProcessEnemyDay</c> jedes Abkommen ausser <c>None</c> und
        /// <c>Alliance</c> ablaufen, sobald der Tag die Frist erreicht - bei
        /// Frist 0 also sofort. Aufgefallen ist beides nie, weil die Methode
        /// im Spiel gar nicht gerufen wurde.
        ///
        /// Ein Vasall ist ein Buendnispartner mit besonderen Pflichten, kein
        /// eigener Vertragstyp. Die Rolle steht in <c>VassalRole</c>,
        /// <c>Agreement</c> bleibt <c>Alliance</c>.
        /// </remarks>
        /// <summary>
        /// Doppelte Ueberlegenheit genuegt, wenn der Schwaechere am Boden
        /// liegt.
        /// </summary>
        internal const int PressureRatioPercent = 200;

        /// <summary>
        /// "Am Boden": hoechstens dieser Anteil dessen, was der staerkste
        /// Spieler der Karte im Feld hat.
        /// </summary>
        internal const int NearDefeatPercentOfStrongest = 20;

        /// <summary>Kleinste und groesste Tributmenge je Zeitraum.</summary>
        internal const int MinimumTributeAmount = 25;
        internal const int MaximumTributeAmount = 1000;

        /// <summary>Der Tribut ist dieser Bruchteil des Koalitionsmasses.</summary>
        internal const int TributeTargetDivisor = 8;

        /// <summary>
        /// Rechtfertigt die Lage ein Lehnsverhaeltnis beim Buendnisschluss?
        /// </summary>
        /// <param name="strongMilitary">Feldstaerke der staerkeren Seite.</param>
        /// <param name="weakMilitary">Feldstaerke der schwaecheren Seite.</param>
        /// <param name="strongestOnMap">
        /// Groesste Feldstaerke auf der Karte - der Massstab fuer "am Boden".
        /// </param>
        /// <remarks>
        /// Zwei Ausloeser nach Vorgabe des Benutzers (07.09.2026): extreme
        /// Ungleichheit, ODER militaerischer Druck kurz vor der Niederlage.
        /// Beide rein rechnerisch, kein Zufall - dieselbe Lage ergibt immer
        /// dieselbe Entscheidung.
        ///
        /// Haben beide Seiten nichts im Feld, gibt es keine Unterwerfung:
        /// ein Verhaeltnis, das auf "null gegen null" beruht, waere beim
        /// ersten Rekruten hinfaellig.
        /// </remarks>
        internal static bool SubjugationWarranted(
            long strongMilitary,
            long weakMilitary,
            long strongestOnMap)
        {
            if (strongMilitary < SubjugationMinimumMilitaryValue || weakMilitary < 0L)
            {
                return false;
            }
            // Ueber decimal, damit kein Ueberlauf entsteht: Feldstaerken
            // koennen bis an die long-Grenze reichen.
            bool extrem = (decimal)strongMilitary
                    >= (decimal)weakMilitary * SubjugationRatioPercent / 100m;
            if (extrem)
            {
                return true;
            }
            bool ueberlegen = (decimal)strongMilitary
                >= (decimal)weakMilitary * PressureRatioPercent / 100m;
            bool amBoden = strongestOnMap > 0L
                && (decimal)weakMilitary
                    <= (decimal)strongestOnMap
                        * NearDefeatPercentOfStrongest / 100m;
            return ueberlegen && amBoden;
        }

        /// <summary>
        /// Die Tributmenge je Zeitraum, abgeleitet aus dem Koalitionsmass.
        /// </summary>
        /// <remarks>
        /// Das Mass (`coalition.Target`) ist die im Mod schon eingefuehrte
        /// Groesse fuer "was ist ein Warenpaket hier wert" und passt sich
        /// damit von selbst an Kartengroesse und Spielstand an. Gedeckelt,
        /// damit ein Ausreisser keine unbezahlbare Pflicht erzeugt - eine
        /// Pflicht, die niemand erfuellen kann, ist keine Pflicht, sondern
        /// ein Ablaufdatum.
        /// </remarks>
        internal static int TributeAmountFor(int coalitionTarget)
        {
            if (coalitionTarget <= 0)
            {
                return MinimumTributeAmount;
            }
            int roh = coalitionTarget / TributeTargetDivisor;
            if (roh < MinimumTributeAmount)
            {
                return MinimumTributeAmount;
            }
            return roh > MaximumTributeAmount
                ? MaximumTributeAmount
                : roh;
        }

        // New contracts quote two percent of this vassal's own economic value
        // for the existing20-day period. Historical accepted quotes stay fixed.
        internal static int TributeAmountForEconomy(long economicStrength)
        {
            decimal amount = decimal.Round(Math.Max(0L, economicStrength) * .02m,
                0, MidpointRounding.AwayFromZero);
            return (int)Math.Max(MinimumTributeAmount, Math.Min(MaximumTributeAmount, amount));
        }

        /// <summary>
        /// Leitet die Rolle aus Sicht des oertlichen Spielers ab.
        /// </summary>
        internal static DiplomacyV2VassalRole RoleFor(
            int vassalPlayerId,
            int overlordPlayerId,
            int localPlayerId)
        {
            if (vassalPlayerId == localPlayerId)
            {
                return DiplomacyV2VassalRole.LocalIsVassal;
            }
            if (overlordPlayerId == localPlayerId)
            {
                return DiplomacyV2VassalRole.CoalitionIsVassal;
            }
            return DiplomacyV2VassalRole.WithinCoalition;
        }

        internal static bool Establish(
            RelationState relation,
            int vassalPlayerId,
            int overlordPlayerId,
            int localPlayerId,
            int day)
        {
            if (relation == null || !relation.Allied)
            {
                // Ohne Buendnis kein Lehnsverhaeltnis. Ein Vasall ausserhalb
                // eines Buendnisses waere ein Vertrag ohne Grundlage.
                return false;
            }
            DiplomacyV2RelationState state = relation.V2;
            if (state == null
                || day < 0
                || IsActive(state)
                || DiplomacyV2StateMachine.HasOutstandingUltimatum(relation)
                || state.Agreement != DiplomacyV2AgreementKind.Alliance)
            {
                return false;
            }
            // Spieler 0 ist die bekannte Falle: `GetAlivePlayerIds` liefert
            // ihn mit, und native Abfragen darauf koennen das Spiel wortlos
            // beenden. Er kommt hier gar nicht erst herein.
            if (vassalPlayerId <= 0
                || overlordPlayerId <= 0
                || vassalPlayerId == overlordPlayerId)
            {
                return false;
            }
            state.VassalPlayerId = vassalPlayerId;
            state.VassalOverlordPlayerId = overlordPlayerId;
            state.VassalRole = RoleFor(
                vassalPlayerId, overlordPlayerId, localPlayerId);
            state.VassalSinceDay = day;
            ClearEqualityResponse(state);
            state.VassalEqualityNextAllowedDay = 0;
            state.VassalStrengthEdgeDays = 0;
            ClearPendingOffer(state);
            DiplomacyV2Submission.CloseOffer(state, day, false);
            DiplomacyV2StateMachine.SuspendVassalMaintenance(relation);
            return true;
        }

        internal static void ClearPendingOffer(DiplomacyV2RelationState state)
        {
            if (state == null) return;
            if (DiplomacyV2VassalActions.IsSubjugation(state.PendingVassalAction))
                DiplomacyV2VassalActions.Clear(state);
            state.PendingVassalOverlordPlayerId = 0;
            state.PendingVassalTributeAmount = 0;
            state.PendingVassalOfferDay = -1;
        }

        /// <summary>Loest das Verhaeltnis auf, ohne Groll.</summary>
        internal static void Release(DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            if (IsActive(state))
            {
                state.VassalReleases++;
            }
            DiplomacyV2VassalActions.Clear(state);
            state.VassalRole = DiplomacyV2VassalRole.None;
            state.VassalPlayerId = -1;
            state.VassalOverlordPlayerId = -1;
            state.VassalSinceDay = -1;
            ClearEqualityResponse(state);
            state.VassalEqualityNextAllowedDay = 0;
            state.VassalStrengthEdgeDays = 0;
            DiplomacyV2Tribute.Clear(state);
            // `Agreement` bleibt unangetastet: eine Freilassung beendet die
            // Pflichten, nicht das Buendnis (07.09.2026).
        }

        /// <summary>Ist die Mindestlaufzeit vorbei?</summary>
        internal static bool TermElapsed(
            DiplomacyV2RelationState state,
            int day)
        {
            return IsActive(state)
                && state.VassalSinceDay >= 0
                && day - state.VassalSinceDay >= MinimumTermDays;
        }

        /// <summary>
        /// Traegt den taeglichen Staerkevergleich nach und meldet, ob sich der
        /// Vasall jetzt auflehnt.
        /// </summary>
        /// <remarks>
        /// Aufgelehnt wird nur, wenn das Uebergewicht ANHAELT und die
        /// Mindestlaufzeit vorbei ist. Faellt es weg, faellt der Zaehler auf
        /// null - ein guter Tag zaehlt nicht weiter.
        /// </remarks>
        internal static bool NoteStrengthComparison(
            DiplomacyV2RelationState state,
            long vassalMilitary,
            long overlordMilitary,
            int day)
        {
            if (!IsActive(state))
            {
                return false;
            }
            if (vassalMilitary <= overlordMilitary)
            {
                state.VassalStrengthEdgeDays = 0;
                return false;
            }
            if (state.VassalStrengthEdgeDays < int.MaxValue)
            {
                state.VassalStrengthEdgeDays++;
            }
            return CanRequestEquality(state, day);
        }

        internal static bool CanRequestEquality(DiplomacyV2RelationState state, int day)
        {
            return EqualityStrengthAndTermSatisfied(state, day)
                && !EqualityRequestOpen(state)
                && day >= state.VassalEqualityNextAllowedDay;
        }

        private static bool EqualityStrengthAndTermSatisfied(DiplomacyV2RelationState state, int day)
        {
            return IsActive(state)
                && DiplomacyLogicalClock.IsValidSavedDay(day)
                && TermElapsed(state, day)
                && state.VassalStrengthEdgeDays >= RebellionEdgeDays;
        }

        /// <summary>Ein offener Antrag braucht weiterhin einen anhaltenden Staerkevorsprung.</summary>
        internal static bool EqualityRequestStillJustified(DiplomacyV2RelationState state, int day)
        {
            return EqualityRequestOpen(state)
                && EqualityStrengthAndTermSatisfied(state, day);
        }

        /// <summary>Ein gegenstandsloser Antrag ist keine Ablehnung und erzeugt keine neue Sperrfrist.</summary>
        internal static bool CancelUnjustifiedEqualityRequest(DiplomacyV2RelationState state, int day)
        {
            if (!EqualityRequestOpen(state) || EqualityRequestStillJustified(state, day))
            {
                return false;
            }
            ClearEqualityResponse(state);
            return true;
        }

        /// <summary>Der Vasall bittet um Gleichberechtigung.</summary>
        internal static bool RequestEquality(
            DiplomacyV2RelationState state,
            int day)
        {
            if (!CanRequestEquality(state, day))
            {
                return false;
            }
            state.VassalEqualityRequestedDay = day;
            state.VassalEqualityResponseDaysRemaining = EqualityRequestGraceDays;
            state.VassalEqualityLastResponseDay = day;
            return true;
        }

        internal static void ClearEqualityResponse(DiplomacyV2RelationState state)
        {
            if (state == null) return;
            if (DiplomacyV2VassalActions.IsEquality(state.PendingVassalAction))
                DiplomacyV2VassalActions.Clear(state);
            state.VassalEqualityRequestedDay = -1;
            state.VassalEqualityResponseDaysRemaining = 0;
            state.VassalEqualityLastResponseDay = -1;
        }

        internal static void RestoreLegacyEqualityResponse(DiplomacyV2RelationState state, int day)
        {
            if (state == null) return;
            // Schemas 2..8 contain no evidence of visible response time.
            // Preserve the historical request date; never infer a refusal.
            state.VassalEqualityResponseDaysRemaining = EqualityRequestOpen(state)
                ? EqualityRequestGraceDays : 0;
            state.VassalEqualityLastResponseDay = EqualityRequestOpen(state) ? day : -1;
        }

        internal static bool ElapseEqualityResponseDay(DiplomacyV2RelationState state,
            int day, bool presented)
        {
            if (!EqualityRequestOpen(state) || !presented
                || DiplomacyV2VassalActions.IsEquality(state.PendingVassalAction)
                || !DiplomacyLogicalClock.IsValidSavedDay(day)
                || day <= state.VassalEqualityRequestedDay
                || day <= state.VassalEqualityLastResponseDay) return false;
            state.VassalEqualityLastResponseDay = day;
            state.VassalEqualityResponseDaysRemaining = Math.Max(0,
                state.VassalEqualityResponseDaysRemaining - 1);
            return EqualityRequestExpired(state, day);
        }

        internal static void ValidateEqualityResponse(DiplomacyV2RelationState state, int day)
        {
            bool open = EqualityRequestOpen(state);
            if (state.VassalEqualityResponseDaysRemaining < 0
                || state.VassalEqualityResponseDaysRemaining > EqualityRequestGraceDays
                || (open ? state.VassalEqualityLastResponseDay < state.VassalEqualityRequestedDay
                        || state.VassalEqualityLastResponseDay > day
                    : state.VassalEqualityResponseDaysRemaining != 0
                        || state.VassalEqualityLastResponseDay != -1))
                throw new InvalidOperationException("equality response clock is invalid");
        }

        /// <summary>Schliesst einen offenen Antrag - beantwortet oder nicht.</summary>
        internal static void CloseEqualityRequest(
            DiplomacyV2RelationState state,
            int day)
        {
            if (state == null)
            {
                return;
            }
            ClearEqualityResponse(state);
            state.VassalEqualityNextAllowedDay = checked(
                Math.Max(0, day) + EqualityRequestCooldownDays);
        }

        // Existing callers/tests can migrate without losing the refusal cooldown.
        internal static void CloseEqualityRequest(DiplomacyV2RelationState state)
        {
            CloseEqualityRequest(state, state == null ? 0 : Math.Max(0, state.VassalEqualityRequestedDay));
        }

        /// <summary>
        /// Ein Vasall hat sich tatsaechlich losgesagt.
        /// </summary>
        /// <remarks>
        /// Bis zum 07.09.2026 zaehlte schon der ANTRAG auf Gleichstellung als
        /// Auflehnung. Ein Vasall, dem der Lehnsherr die Gleichstellung
        /// gewaehrte, stand danach im Spielstand als Aufstaendischer - und der
        /// Zaehler wandert in die Speicherdatei, also blieb der falsche
        /// Eintrag ueber die Partie hinaus stehen. Gezaehlt wird jetzt nur der
        /// vollzogene Bruch.
        /// </remarks>
        internal static void NoteRebellion(DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            state.VassalRebellions++;
        }

        /// <summary>
        /// Loest das Verhaeltnis auf, OHNE es als einvernehmliche Entlassung
        /// zu zaehlen - fuer die Bruchwege.
        /// </summary>
        internal static void ClearWithoutRelease(
            DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            DiplomacyV2VassalActions.Clear(state);
            state.VassalRole = DiplomacyV2VassalRole.None;
            state.VassalPlayerId = -1;
            state.VassalOverlordPlayerId = -1;
            state.VassalSinceDay = -1;
            ClearEqualityResponse(state);
            state.VassalEqualityNextAllowedDay = 0;
            state.VassalStrengthEdgeDays = 0;
            ClearPendingOffer(state);
            DiplomacyV2Tribute.Clear(state);
            DiplomacyV2Submission.CloseOffer(state, 0, false);
            // `Agreement` gehoert dem Bruchweg, der uns gerufen hat - der
            // setzt es selbst auf `None` (07.09.2026).
        }

        internal static bool EqualityRequestOpen(
            DiplomacyV2RelationState state)
        {
            return IsActive(state) && state.VassalEqualityRequestedDay >= 0;
        }

        /// <summary>Ist die Bedenkzeit abgelaufen?</summary>
        /// <remarks>
        /// Schweigen ist auch eine Antwort. Ein Antrag, der ewig offen steht,
        /// blockiert das Verhaeltnis fuer beide Seiten.
        /// </remarks>
        internal static bool EqualityRequestExpired(
            DiplomacyV2RelationState state,
            int day)
        {
            return EqualityRequestOpen(state)
                && state.VassalEqualityResponseDaysRemaining == 0;
        }

        /// <summary>
        /// Wie entschlossen bricht dieser Vasall weg, wenn man ihn abweist?
        /// </summary>
        /// <remarks>
        /// KEIN Zufall - der ganze Diplomatiecode kommt ohne `Random` aus, und
        /// das bleibt so. Entscheidend sind die Wesensart des Fuersten
        /// (Bruchempfindlichkeit) und wie lange sein Uebergewicht schon
        /// anhaelt. Damit ist die Folge erklaerbar und wiederholbar; ein
        /// Wuerfel waere fuer den Spieler nicht lesbar.
        /// </remarks>
        internal static int RebellionResolve(
            DiplomacyV2RelationState state,
            int breachSensitivityPercent)
        {
            if (state == null)
            {
                return 0;
            }
            int tage = Math.Max(0, Math.Min(60, state.VassalStrengthEdgeDays));
            int empfindlich = Math.Max(0, Math.Min(300, breachSensitivityPercent));
            // Anhaltendes Uebergewicht und eine reizbare Wesensart addieren
            // sich; Dankbarkeit fuer frueheres Entgegenkommen daempft.
            int dankbar = (int)Math.Max(0m, Math.Min(100m, state.Gratitude));
            return (tage * 2) + (empfindlich / 5) - (dankbar / 4);
        }

        /// <summary>
        /// Ab diesem Entschluss bricht der abgewiesene Vasall weg.
        /// </summary>
        internal const int RebellionBreakThreshold = 40;

        internal static bool RejectionBreaksRelation(
            DiplomacyV2RelationState state,
            int breachSensitivityPercent)
        {
            return RebellionResolve(state, breachSensitivityPercent)
                >= RebellionBreakThreshold;
        }

        /// <summary>
        /// Raeumt einen widerspruechlichen Zustand aus einem Spielstand auf.
        /// </summary>
        internal static void Normalize(DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            state.VassalStrengthEdgeDays =
                Math.Max(0, state.VassalStrengthEdgeDays);
            state.VassalReleases = Math.Max(0, state.VassalReleases);
            state.VassalRebellions = Math.Max(0, state.VassalRebellions);
            if (!Enum.IsDefined(typeof(DiplomacyV2VassalRole), state.VassalRole))
            {
                state.VassalRole = DiplomacyV2VassalRole.None;
            }
            if (state.VassalPlayerId <= 0
                || state.VassalOverlordPlayerId <= 0
                || state.VassalPlayerId == state.VassalOverlordPlayerId)
            {
                // Eine Rolle ohne benannte Gegenseite ist ein Datenfehler -
                // entweder ein Spielstand aus der Fassung vor dem 07.09.2026
                // oder ein beschaedigter. Beides wird geloescht statt geraten:
                // an wen der Tribut ginge, laesst sich nicht erraten.
                state.VassalRole = DiplomacyV2VassalRole.None;
            }
            if (state.VassalRole == DiplomacyV2VassalRole.None)
            {
                // Kein Verhaeltnis, also auch keine Begleitwerte.
                state.VassalPlayerId = -1;
                state.VassalOverlordPlayerId = -1;
                state.VassalSinceDay = -1;
                ClearEqualityResponse(state);
                state.VassalEqualityNextAllowedDay = 0;
                state.VassalStrengthEdgeDays = 0;
                if (state.Agreement == DiplomacyV2AgreementKind.Vassalage)
                {
                    // Zwischenfassung vom 07.09.2026: ohne Rolle war das ein
                    // Abkommen ohne Inhalt.
                    state.Agreement = DiplomacyV2AgreementKind.None;
                }
                return;
            }
            if (state.VassalSinceDay < 0)
            {
                // Ein Verhaeltnis ohne Anfang ist ein Datenfehler. Statt es zu
                // loeschen wird der Anfang auf Tag 0 gesetzt - das ist die
                // vorsichtigere Deutung: die Mindestlaufzeit gilt dann als
                // laengst abgelaufen, der Spieler ist nicht gefangen.
                state.VassalSinceDay = 0;
            }
            if (state.Agreement == DiplomacyV2AgreementKind.Vassalage)
            {
                // Rueckbildung aus der Zwischenfassung vom 07.09.2026, in der
                // das Lehnsverhaeltnis ein eigener Abkommenstyp war. Ein
                // Vasall ist immer ein Verbuendeter, also ist `Alliance` die
                // einzige Deutung, die die Zustandspruefung besteht.
                state.Agreement = DiplomacyV2AgreementKind.Alliance;
            }
        }
    }

    internal sealed class DiplomacyV2GiftResult
    {
        internal decimal CreditedValue;
        internal bool OfferAlliance;
        internal bool StageChanged;
        internal bool AgreementChanged;
    }

    internal static class DiplomacyV2StateMachine
    {
        private const int MaximumGiftMemories = 21;
        private const int GiftMemoryDecayDays = 14;
        private const int MaximumHistoricalCount = 1000000;
        // A fixed persistence ceiling is deliberately independent of the
        // coalition's current strength. Economy and military can collapse
        // after a breach; a lawful old restitution debt must remain loadable.
        private const decimal MaximumHistoricalValue = 1000000000m;

        internal static void Initialize(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyV2PersonalityKind personality,
            int primaryLordId,
            bool startingAlliance)
        {
            RequireBase(relation, gameDay, target);
            DiplomacyV2Personality profile =
                DiplomacyV2PersonalityCatalog.Get(personality);
            relation.V2 = new DiplomacyV2RelationState
            {
                Personality = profile.Kind,
                PrimaryLordId = primaryLordId,
                Trust = startingAlliance ? 82m : profile.InitialTrust,
                Gratitude = startingAlliance ? 62m : 0m,
                Respect = startingAlliance ? 64m : profile.InitialRespect,
                Grudge = startingAlliance ? 0m : profile.InitialGrudge,
                Stage = startingAlliance
                    ? DiplomacyV2NegotiationStage.Allied
                    : DiplomacyV2NegotiationStage.Hostile,
                Agreement = startingAlliance
                    ? DiplomacyV2AgreementKind.Alliance
                    : DiplomacyV2AgreementKind.None,
                // Let the complete coalition catalogue perform one initial
                // strategic assessment after every relation has been added.
                LastStrategicDay = Math.Max(-1, gameDay - 1),
                LastInteractionDay = gameDay,
                MaintenanceDueDay = startingAlliance
                    ? checked(gameDay + profile.MaintenanceIntervalDays)
                    : 0,
                LastEvent = startingAlliance
                    ? DiplomacyV2EventKind.AllianceFormed
                    : DiplomacyV2EventKind.None,
                LastEventDay = startingAlliance ? gameDay : -1,
                Reliability = startingAlliance ? 78m : 50m,
                TrustCeiling = 100m,
                AllianceTermsFulfilled = startingAlliance,
                LastPositiveEventDay = startingAlliance ? gameDay : -1,
            };
            SyncGoodwill(relation, target);
        }

        internal static void InitializeFromLegacy(
            RelationState relation,
            CoalitionState coalition,
            int gameDay)
        {
            if (coalition == null)
            {
                throw new ArgumentNullException("coalition");
            }
            int fallbackLord = coalition.MemberPlayerIds == null
                || coalition.MemberPlayerIds.Length == 0
                    ? 0
                    : coalition.MemberPlayerIds[0];
            DiplomacyV2Personality profile =
                DiplomacyV2PersonalityCatalog.SelectForLord(
                    fallbackLord,
                    coalition.SendGoodsMargin);
            decimal legacyGoodwill = relation.Goodwill;
            Initialize(
                relation,
                gameDay,
                coalition.Target,
                profile.Kind,
                fallbackLord,
                relation.Allied);
            DiplomacyV2RelationState state = relation.V2;
            state.ImportedFromV1 = true;
            state.MigrationSourceVersion = 1;
            decimal progress = coalition.Target <= 0
                ? 0m
                : Clamp100(legacyGoodwill * 100m / coalition.Target);
            if (!relation.Allied)
            {
                state.Trust = Clamp100(
                    profile.InitialTrust + progress * 0.42m);
                state.Gratitude = Clamp100(progress * 0.88m);
                state.Respect = Clamp100(
                    profile.InitialRespect + progress * 0.18m);
                state.Grudge = Clamp100(
                    profile.InitialGrudge - progress * 0.08m);
                state.Reliability = Clamp100(45m + progress * 0.35m);
                if (relation.PendingOffer || progress >= 100m)
                {
                    state.Agreement = DiplomacyV2AgreementKind.TradePact;
                    state.AgreementUntilDay = checked(
                        gameDay + profile.TradePactDays);
                    state.FulfilledDemands = Math.Max(
                        state.FulfilledDemands,
                        3);
                    state.AllianceTermsFulfilled = true;
                    PrepareAllianceReadiness(state);
                }
                else if (relation.Demand != null)
                {
                    // A V1 demand was the final goods condition before an
                    // alliance. Represent it as V2 alliance terms so partial
                    // deliveries and the expected outcome survive migration.
                    state.Agreement = DiplomacyV2AgreementKind.TradePact;
                    state.AgreementUntilDay = Math.Max(
                        checked(gameDay + 1),
                        relation.Demand.ExpiresDay);
                    state.FulfilledDemands = Math.Max(
                        state.FulfilledDemands,
                        2);
                    if (relation.Demand.Complete)
                    {
                        state.AllianceTermsFulfilled = true;
                        PrepareAllianceReadiness(state);
                    }
                    state.Stage = relation.Demand.Complete
                        ? DiplomacyV2NegotiationStage.AllianceReady
                        : DiplomacyV2NegotiationStage.Trusted;
                }
                else if (progress >= 60m)
                {
                    state.Agreement = DiplomacyV2AgreementKind.Truce;
                    state.AgreementUntilDay = checked(
                        gameDay + profile.TruceDays);
                    state.FulfilledDemands = Math.Max(
                        state.FulfilledDemands,
                        1);
                }
                AdvanceStage(relation, coalition.Target, gameDay);
            }
            SyncGoodwill(relation, coalition.Target);
        }

        internal static void RebindPersonality(
            RelationState relation,
            DiplomacyV2PersonalityKind personality,
            int primaryLordId,
            int target)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2PersonalityCatalog.Get(personality);
            state.Personality = personality;
            state.PrimaryLordId = primaryLordId;
            SyncGoodwill(relation, target);
        }

        internal static void UpdateStrategicContext(
            RelationState relation,
            int gameDay,
            int target,
            long localEconomy,
            long localMilitary,
            long foreignEconomy,
            long foreignMilitary,
            int commonEnemyCoalitions,
            bool foreignUnderPressure)
        {
            UpdateStrategicContext(
                relation,
                gameDay,
                target,
                localEconomy,
                localMilitary,
                foreignEconomy,
                foreignMilitary,
                commonEnemyCoalitions,
                Math.Max(1, commonEnemyCoalitions),
                0,
                localEconomy,
                localMilitary,
                foreignUnderPressure);
        }

        internal static void UpdateStrategicContext(
            RelationState relation,
            int gameDay,
            int target,
            long localEconomy,
            long localMilitary,
            long foreignEconomy,
            long foreignMilitary,
            int commonEnemyCoalitions,
            int hostileCoalitions,
            int playerAllianceCount,
            long hostileEconomy,
            long hostileMilitary,
            bool foreignUnderPressure)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (gameDay <= state.LastStrategicDay)
            {
                return;
            }
            decimal localPower = Math.Max(1m,
                Math.Max(0L, localEconomy) * 0.8m
                + Math.Max(0L, localMilitary) * 1.4m);
            decimal foreignPower = Math.Max(1m,
                Math.Max(0L, foreignEconomy) * 0.8m
                + Math.Max(0L, foreignMilitary) * 1.4m);
            decimal hostilePower = Math.Max(1m,
                Math.Max(0L, hostileEconomy) * 0.8m
                + Math.Max(0L, hostileMilitary) * 1.4m);
            decimal ratio = localPower / foreignPower;
            decimal desiredRespect;
            if (ratio >= 2m)
            {
                desiredRespect = 86m;
            }
            else if (ratio >= 1.4m)
            {
                desiredRespect = 74m;
            }
            else if (ratio >= 0.85m)
            {
                desiredRespect = 58m;
            }
            else if (ratio >= 0.55m)
            {
                desiredRespect = 43m;
            }
            else
            {
                desiredRespect = 27m;
            }
            DiplomacyV2Personality profile = Profile(state);
            int shared = Math.Max(0, commonEnemyCoalitions);
            int hostiles = Math.Max(0, hostileCoalitions);
            int allies = Math.Max(0, playerAllianceCount);
            desiredRespect += Math.Min(5, shared) * 2m;
            decimal leverage = Clamp(
                (localPower - foreignPower) * 100m
                    / (localPower + foreignPower),
                -100m,
                100m);
            decimal rawThreat = Clamp100(
                45m + leverage * 0.42m
                + state.BreachPoints * 0.30m
                + (state.LastHostileActDay >= 0
                    && gameDay - state.LastHostileActDay <= 14 ? 12m : 0m));
            decimal sharedFactor = hostiles <= 0
                ? 0m
                : Math.Min(1m, (decimal)shared / hostiles);
            decimal powerHelp = Clamp100(
                localPower * 100m / Math.Max(1m, hostilePower));
            decimal rawDependency = Clamp100(
                sharedFactor * 45m
                + powerHelp * 0.30m
                + (foreignUnderPressure ? 25m : 0m));
            decimal rawCoalitionValue = Clamp100(
                foreignPower * 100m / Math.Max(1m, hostilePower)
                + sharedFactor * 20m);
            state.StrategicThreat = Clamp100(
                state.StrategicThreat * 0.65m + rawThreat * 0.35m);
            state.StrategicDependency = Clamp100(
                state.StrategicDependency * 0.65m + rawDependency * 0.35m);
            state.CoalitionValue = Clamp100(
                state.CoalitionValue * 0.65m + rawCoalitionValue * 0.35m);
            state.CommonEnemyCoalitions = shared;
            state.HostileCoalitions = hostiles;
            state.PlayerAllianceCount = allies;
            desiredRespect += state.StrategicDependency
                * profile.DependencyWeightPercent / 1000m;
            desiredRespect += Math.Max(0m, leverage)
                * profile.ThreatWeightPercent / 1400m;
            if (profile.Kind == DiplomacyV2PersonalityKind.Wary)
            {
                desiredRespect -= Math.Max(0, allies - 1) * 2m;
            }
            else if (profile.Kind
                == DiplomacyV2PersonalityKind.Opportunistic)
            {
                desiredRespect += state.StrategicDependency / 12m;
            }
            decimal previousRespect = state.Respect;
            state.Respect = Clamp100(
                state.Respect * 0.70m + Clamp100(desiredRespect) * 0.30m);
            state.StrategicLeverage = leverage;
            state.LastStrategicDay = gameDay;
            if (Math.Abs(state.Respect - previousRespect) >= 8m
                && state.LastEventDay < gameDay)
            {
                state.LastEvent = DiplomacyV2EventKind.StrategicReassessment;
                state.LastEventDay = gameDay;
            }
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);
        }

        internal static DiplomacyV2GiftResult RecordGiftDetailed(
            RelationState relation,
            int gameDay,
            int goodId,
            decimal giftValue,
            int target,
            int margin,
            string mapFingerprint,
            IEnumerable<GoodNeed> needs,
            bool allianceAvailable,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            RequireBase(relation, gameDay, target);
            if (!IsSendableGiftGood(goodId) || giftValue <= 0m)
            {
                throw new ArgumentOutOfRangeException("giftValue");
            }
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            GoodNeed[] usableNeeds = (needs ?? Enumerable.Empty<GoodNeed>())
                .Where(need => need != null
                    && need.GoodId > 0
                    && need.RelativeNeed > 0m)
                .ToArray();
            DiplomacyV2GiftMemory memory = GiftMemory(state, goodId);
            int elapsed = memory.LastGiftDay < 0
                ? GiftMemoryDecayDays + 1
                : Math.Max(0, gameDay - memory.LastGiftDay);
            int rememberedRepeats = elapsed > GiftMemoryDecayDays
                ? 0
                : Math.Max(0, memory.ConsecutiveCount - elapsed / 3);
            memory.ConsecutiveCount = checked(rememberedRepeats + 1);
            state.RepeatedGiftCount = memory.ConsecutiveCount;
            bool sameGood = state.LastGiftGoodId == goodId
                && relation.LastGiftDay >= 0
                && gameDay - relation.LastGiftDay <= GiftMemoryDecayDays;
            int repetitionPercent = Math.Max(
                profile.RepeatedGiftFloorPercent,
                100 - Math.Max(0, memory.ConsecutiveCount - 1) * 13);
            DiplomacyV2GoodCategory category = GoodCategory(goodId);
            bool varied = state.LastGiftGoodId > 0
                && category != state.LastGiftCategory
                && relation.LastGiftDay >= 0
                && gameDay - relation.LastGiftDay <= GiftMemoryDecayDays;
            state.VariedGiftStreak = varied
                ? Math.Min(5, state.VariedGiftStreak + 1)
                : sameGood ? 0 : Math.Max(0, state.VariedGiftStreak - 1);
            int varietyPercent = 100 + (varied
                ? Math.Min(12, 5 + state.VariedGiftStreak * 2)
                : 0);
            decimal maximumNeed = usableNeeds.Length == 0
                ? 0m
                : usableNeeds.Max(need => need.RelativeNeed);
            GoodNeed matching = usableNeeds.FirstOrDefault(
                need => need.GoodId == goodId);
            decimal categoryNeed = usableNeeds
                .Where(need => GoodCategory(need.GoodId) == category)
                .Sum(need => need.RelativeNeed);
            int needPercent;
            if (matching != null && maximumNeed > 0m)
            {
                needPercent = 105 + decimal.ToInt32(decimal.Round(
                    Math.Min(55m, matching.RelativeNeed * 55m / maximumNeed),
                    0,
                    MidpointRounding.AwayFromZero));
            }
            else
            {
                needPercent = categoryNeed > 0m ? 88 : 70;
            }
            bool requestedGood = relation.Demand != null
                && relation.Demand.Items != null
                && relation.Demand.Items.Any(item => item != null
                    && item.GoodId == goodId);
            int requestedPercent = requestedGood ? 125 : 100;
            int agreementPercent = state.Agreement
                    == DiplomacyV2AgreementKind.TradePact
                && state.AgreementUntilDay > gameDay
                    ? 112
                    : 100;
            decimal decayedRecent = elapsed > GiftMemoryDecayDays
                ? 0m
                : memory.RecentRawValue
                    * (GiftMemoryDecayDays - elapsed)
                    / GiftMemoryDecayDays;
            int saturationPercent = decimal.ToInt32(decimal.Round(
                Clamp(100m - decayedRecent * 30m / target, 58m, 100m),
                0,
                MidpointRounding.AwayFromZero));
            decimal fullValueThreshold = target * 0.25m;
            decimal effectiveGiftValue = giftValue <= fullValueThreshold
                ? giftValue
                : fullValueThreshold
                    + (giftValue - fullValueThreshold) * 0.55m;
            decimal credited = effectiveGiftValue
                * profile.GiftBasisPoints / 10000m
                * repetitionPercent / 100m
                * needPercent / 100m
                * CategoryGiftPercent(profile, category) / 100m
                * requestedPercent / 100m
                * agreementPercent / 100m;
            credited = credited * saturationPercent / 100m
                * varietyPercent / 100m;
            credited = Math.Max(0.01m, Math.Min(target * 1.50m, credited));
            decimal progress = credited * 100m / target;
            state.Gratitude = Clamp100(state.Gratitude + Math.Min(
                36m,
                progress * profile.GratitudeResponsePercent / 100m));
            state.Trust = ClampToTrustCeiling(state, state.Trust
                + Math.Min(
                    10m,
                    progress * 0.20m
                        * profile.TrustResponsePercent / 100m)
                // Variety rewards the value actually received, not the
                // number of clicks. Five-unit alternation used to mint a
                // full trust point even after saturation/repetition cuts.
                + (varied ? Math.Min(1m, progress * 0.05m) : 0m));
            state.Respect = Clamp100(state.Respect
                + Math.Min(
                    5m,
                    progress * 0.10m
                        * profile.RespectResponsePercent / 100m));
            state.Grudge = RelieveGrudge(
                state,
                Math.Min(
                    10m,
                    progress * 0.16m
                        * profile.GrudgeReliefPercent / 100m));
            state.Reliability = Clamp100(state.Reliability
                + Math.Min(4m, progress * (requestedGood ? 0.12m : 0.06m)));
            state.LastGiftGoodId = goodId;
            state.LastGiftCategory = category;
            state.LastInteractionDay = gameDay;
            state.LastCreditedGiftValue = credited;
            state.LifetimeCreditedGiftValue = AddHistoricalValue(
                state.LifetimeCreditedGiftValue,
                credited);
            state.PositiveMomentum = Clamp100(
                state.PositiveMomentum + Math.Min(18m, progress * 0.35m));
            state.NegativeMomentum = Clamp100(
                state.NegativeMomentum - Math.Min(8m, progress * 0.18m));
            MarkPositive(state, DiplomacyV2EventKind.GiftReceived, gameDay);
            relation.LastGiftDay = gameDay;
            relation.GiftValueSinceOfferAttempt = AddHistoricalValue(
                relation.GiftValueSinceOfferAttempt,
                credited);
            state.NegotiationRequestsWithoutGift = 0;
            memory.LastGiftDay = gameDay;
            memory.RecentRawValue = AddHistoricalValue(
                decayedRecent,
                giftValue);
            memory.LifetimeCreditedValue = AddHistoricalValue(
                memory.LifetimeCreditedValue,
                credited);
            if (relation.Allied)
            {
                state.SupportValueSinceMaintenance = AddHistoricalValue(
                    state.SupportValueSinceMaintenance,
                    credited);
                state.LastSupportDay = gameDay;
                bool demandedSupport = relation.Demand != null
                    && (relation.Demand.V2Purpose
                            == DiplomacyV2DemandPurpose.Support
                        || relation.Demand.V2Purpose
                            == DiplomacyV2DemandPurpose.Ultimatum);
                if (!demandedSupport)
                {
                    state.MaintenanceCredit = AddHistoricalValue(
                        state.MaintenanceCredit,
                        credited);
                }
            }

            DiplomacyV2NegotiationStage beforeStage = state.Stage;
            DiplomacyV2AgreementKind beforeAgreement = state.Agreement;
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);

            bool offered = false;
            if (allianceAvailable
                && relation.Demand == null
                && !relation.Allied
                && !relation.PendingOffer
                && !DiplomacyV2Submission.HasOffer(state)
                && CanFormAlliance(relation, target)
                && gameDay >= relation.SpontaneousOfferBlockedUntilDay
                && relation.LastOfferAttemptDay != gameDay)
            {
                decimal minimumAdditional = target
                    * rules.OfferAdditionalGiftPercent / 100m;
                if (relation.OfferAttemptCounter == 0
                    || relation.GiftValueSinceOfferAttempt >= minimumAdditional)
                {
                    relation.LastOfferAttemptDay = gameDay;
                    int attempt = relation.OfferAttemptCounter++;
                    relation.GiftValueSinceOfferAttempt = 0m;
                    int chance = DiplomacyBalance.OfferChanceTenthsPercent(
                        margin,
                        rules);
                    chance = Math.Max(50, Math.Min(
                        950,
                        chance + profile.OfferChanceAdjustmentTenthsPercent));
                    offered = DiplomacyBalance.OfferRoll(
                        mapFingerprint,
                        relation.CoalitionId,
                        gameDay,
                        attempt,
                        chance);
                }
            }
            return new DiplomacyV2GiftResult
            {
                CreditedValue = credited,
                OfferAlliance = offered,
                StageChanged = beforeStage != state.Stage,
                AgreementChanged = beforeAgreement != state.Agreement,
            };
        }

        internal static bool RecordGift(
            RelationState relation,
            int gameDay,
            decimal giftValue,
            int target,
            int margin,
            string mapFingerprint,
            DiplomacyRules rules)
        {
            return RecordGiftDetailed(
                relation,
                gameDay,
                15,
                giftValue,
                target,
                margin,
                mapFingerprint,
                null,
                true,
                rules).OfferAlliance;
        }

        internal static void RecordGiftWithoutOffer(
            RelationState relation,
            int gameDay,
            decimal giftValue)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (giftValue <= 0m)
            {
                throw new ArgumentOutOfRangeException("giftValue");
            }
            relation.Goodwill = AddHistoricalValue(
                relation.Goodwill,
                giftValue);
            relation.LastGiftDay = gameDay;
            relation.GiftValueSinceOfferAttempt = AddHistoricalValue(
                relation.GiftValueSinceOfferAttempt,
                giftValue);
            state.Gratitude = Clamp100(state.Gratitude + 1m);
            state.LastInteractionDay = gameDay;
            state.LastEvent = DiplomacyV2EventKind.GiftReceived;
            state.LastEventDay = gameDay;
        }

        internal static DiplomacyRequestResult RequestAlliance(
            RelationState relation,
            int gameDay,
            int target,
            bool hostileCoalitionWouldRemain,
            IEnumerable<GoodNeed> needs,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (relation.Allied)
            {
                throw new InvalidOperationException(
                    "an allied relation cannot request another alliance");
            }
            if (gameDay < relation.RelationshipBlockedUntilDay
                || relation.PendingOffer || DiplomacyV2Submission.HasOffer(state))
            {
                return Result(DiplomacyRequestOutcome.Locked);
            }
            DiplomacyV2Personality profile = Profile(state);
            if (relation.Demand != null)
            {
                if (gameDay < relation.Demand.ExpiresDay)
                {
                    return new DiplomacyRequestResult
                    {
                        Outcome = DiplomacyRequestOutcome.DemandIssued,
                        Demand = relation.Demand,
                    };
                }
                MissDemand(relation, gameDay, target);
                relation.Demand = null;
                BlockNegotiationAfterMiss(relation, state, gameDay);
                AdvanceStage(relation, target, gameDay);
                SyncGoodwill(relation, target);
                return Result(DiplomacyRequestOutcome.Locked);
            }
            bool requestTooSoon = state.LastNegotiationRequestDay >= 0
                && gameDay - state.LastNegotiationRequestDay
                    < profile.RequestPatienceDays;
            if (requestTooSoon)
            {
                state.NegotiationRequestsWithoutGift = checked(
                    state.NegotiationRequestsWithoutGift + 1);
                if (state.NegotiationRequestsWithoutGift >= 2)
                {
                    state.FailedNegotiations = checked(
                        state.FailedNegotiations + 1);
                    state.Trust = ClampToTrustCeiling(
                        state,
                        state.Trust - 2m);
                    state.Grudge = Clamp100(state.Grudge + 3m);
                    state.Reliability = Clamp100(state.Reliability - 2m);
                    relation.RelationshipBlockedUntilDay = Math.Max(
                        relation.RelationshipBlockedUntilDay,
                        checked(gameDay + profile.RequestPatienceDays));
                    MarkNegative(
                        state,
                        DiplomacyV2EventKind.NegotiationPressed,
                        gameDay,
                        5m);
                    SyncGoodwill(relation, target);
                }
                return Result(DiplomacyRequestOutcome.Locked);
            }
            state.NegotiationRequestsWithoutGift = 0;
            state.LastNegotiationRequestDay = gameDay;
            state.LastInteractionDay = gameDay;
            AdvanceStage(relation, target, gameDay);
            if (CanFormAlliance(relation, target))
            {
                return Result(hostileCoalitionWouldRemain
                    ? DiplomacyRequestOutcome.AllianceReady
                    : DiplomacyRequestOutcome.AllianceBlocked);
            }
            decimal score = RelationshipScore(state);
            bool restitutionPending = state.RestitutionOutstandingValue > 0m;
            if (!restitutionPending
                && (state.Stage == DiplomacyV2NegotiationStage.Hostile
                    || score < 22m))
            {
                state.Grudge = Clamp100(state.Grudge + 1m);
                state.FailedNegotiations = checked(
                    state.FailedNegotiations + 1);
                state.Reliability = Clamp100(state.Reliability - 1m);
                MarkNegative(
                    state,
                    DiplomacyV2EventKind.NegotiationPressed,
                    gameDay,
                    2m);
                SyncGoodwill(relation, target);
                return Result(DiplomacyRequestOutcome.Rejected);
            }

            DiplomacyV2DemandPurpose purpose;
            int stagePercent;
            if (state.RestitutionOutstandingValue > 0m)
            {
                purpose = DiplomacyV2DemandPurpose.Restitution;
                stagePercent = 0;
            }
            else if (state.Agreement == DiplomacyV2AgreementKind.None)
            {
                purpose = DiplomacyV2DemandPurpose.Courtship;
                stagePercent = profile.CourtshipDemandPercent;
            }
            else if (state.Agreement == DiplomacyV2AgreementKind.Truce)
            {
                purpose = DiplomacyV2DemandPurpose.TradeProof;
                stagePercent = profile.TradeDemandPercent;
            }
            else
            {
                // Final terms are a one-time condition while the trade pact
                // remains in force. If that pact later expires, the ruler may
                // rebuild truce and trade without receiving a duplicate final
                // package. Gifts and time can still repair all non-permanent
                // dimensions before readiness is checked again.
                if (state.AllianceTermsFulfilled)
                {
                    return Result(hostileCoalitionWouldRemain
                        ? DiplomacyRequestOutcome.Rejected
                        : DiplomacyRequestOutcome.AllianceBlocked);
                }
                purpose = DiplomacyV2DemandPurpose.AllianceTerms;
                stagePercent = profile.AllianceDemandPercent;
            }
            decimal strategicFactor = 1m
                - state.StrategicLeverage / 600m
                - state.StrategicDependency
                    * profile.DependencyWeightPercent / 120000m
                + state.StrategicThreat
                    * profile.ThreatWeightPercent / 160000m;
            strategicFactor = Clamp(strategicFactor, 0.72m, 1.35m);
            decimal reliabilityFactor = Clamp(
                1m + (55m - state.Reliability) / 240m,
                0.84m,
                1.28m);
            decimal valueGap = purpose
                    == DiplomacyV2DemandPurpose.Restitution
                ? Math.Max(
                    target * 0.12m,
                    Math.Min(
                        target * 0.75m,
                        state.RestitutionOutstandingValue))
                : Math.Max(
                    1m,
                    target * stagePercent / 100m
                        * profile.DemandBasisPoints / 10000m
                        * strategicFactor
                        * reliabilityFactor
                        * HistoryDemandFactor(state));
            GoodsDemand demand = DiplomacyDemandPlanner.Create(
                valueGap,
                needs,
                gameDay,
                false,
                rules);
            demand.ExpiresDay = checked(
                gameDay + profile.NegotiationDeadlineDays);
            demand.V2Purpose = purpose;
            demand.V2Urgency = purpose
                    == DiplomacyV2DemandPurpose.AllianceTerms
                || purpose == DiplomacyV2DemandPurpose.Restitution
                    ? 2
                    : 1;
            relation.Demand = demand;
            state.LastEvent = purpose
                    == DiplomacyV2DemandPurpose.Restitution
                ? DiplomacyV2EventKind.RestitutionDemanded
                : DiplomacyV2EventKind.DemandIssued;
            state.LastEventDay = gameDay;
            return new DiplomacyRequestResult
            {
                Outcome = DiplomacyRequestOutcome.DemandIssued,
                Demand = demand,
            };
        }

        internal static DiplomacyV2DemandResolution ResolveCompletedDemand(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            GoodsDemand demand = relation.Demand;
            if (demand == null || !demand.Complete)
            {
                throw new InvalidOperationException(
                    "only a complete diplomacy demand can be resolved");
            }
            DiplomacyV2DemandPurpose purpose = demand.V2Purpose;
            if (purpose == DiplomacyV2DemandPurpose.None)
            {
                purpose = relation.Allied
                    ? DiplomacyV2DemandPurpose.Ultimatum
                    : DiplomacyV2DemandPurpose.AllianceTerms;
            }
            relation.Demand = null;
            state.FulfilledDemands = checked(state.FulfilledDemands + 1);
            state.ConsecutiveMissedDemands = 0;
            state.LastInteractionDay = gameDay;
            state.Reliability = Clamp100(state.Reliability + 9m);
            state.Trust = ClampToTrustCeiling(state, state.Trust + 11m);
            state.Gratitude = Clamp100(state.Gratitude + 7m);
            state.Grudge = RelieveGrudge(state, 8m);
            MarkPositive(
                state,
                DiplomacyV2EventKind.DemandFulfilled,
                gameDay);

            if (relation.Allied)
            {
                bool finalWarning = purpose
                    == DiplomacyV2DemandPurpose.Ultimatum;
                state.MaintenanceWarningLevel = 0;
                state.MaintenanceDueDay = DiplomacyV2Vassalage.IsActive(state)
                    ? 0 : checked(gameDay + MaintenanceInterval(state));
                state.Trust = ClampToTrustCeiling(
                    state,
                    state.Trust + (finalWarning ? 3m : 6m));
                state.Grudge = RelieveGrudge(
                    state,
                    finalWarning ? 8m : 4m);
                state.FulfilledSupportStreak = finalWarning
                    ? Math.Max(0, state.FulfilledSupportStreak - 1)
                    : Math.Min(20, state.FulfilledSupportStreak + 1);
                state.SupportValueSinceMaintenance = 0m;
                state.MaintenanceCredit = 0m;
                state.Stage = DiplomacyV2NegotiationStage.Allied;
                state.Agreement = DiplomacyV2AgreementKind.Alliance;
                SyncGoodwill(relation, target);
                return finalWarning
                    ? DiplomacyV2DemandResolution.UltimatumFulfilled
                    : DiplomacyV2DemandResolution.SupportFulfilled;
            }

            if (purpose == DiplomacyV2DemandPurpose.Restitution)
            {
                state.RestitutionOutstandingValue = 0m;
                // A breach invalidates the old political consent even though
                // fulfilled packages remain part of the historical counters.
                // This also repairs V2.0 saves created before that invariant
                // was enforced.
                state.AllianceTermsFulfilled = false;
                state.BreachPoints = Math.Max(
                    PermanentBreachFloor(state),
                    state.BreachPoints / 2);
                RefreshTrustCeiling(state);
                state.Trust = ClampToTrustCeiling(state, state.Trust + 8m);
                state.Gratitude = Clamp100(state.Gratitude + 5m);
                state.Grudge = Clamp100(
                    Math.Max(
                        PermanentGrudgeFloor(state),
                        state.Grudge - 18m));
                state.Stage = DiplomacyV2NegotiationStage.Contact;
                MarkPositive(
                    state,
                    DiplomacyV2EventKind.RestitutionAccepted,
                    gameDay);
                SyncGoodwill(relation, target);
                return DiplomacyV2DemandResolution.RestitutionAccepted;
            }

            if (purpose == DiplomacyV2DemandPurpose.Courtship)
            {
                state.Agreement = DiplomacyV2AgreementKind.Truce;
                state.AgreementUntilDay = checked(
                    gameDay + Profile(state).TruceDays);
                state.Stage = DiplomacyV2NegotiationStage.Negotiating;
                state.LastEvent = DiplomacyV2EventKind.TruceFormed;
                SyncGoodwill(relation, target);
                return DiplomacyV2DemandResolution.TruceFormed;
            }
            if (purpose == DiplomacyV2DemandPurpose.TradeProof)
            {
                state.Agreement = DiplomacyV2AgreementKind.TradePact;
                state.AgreementUntilDay = checked(
                    gameDay + Profile(state).TradePactDays);
                state.Stage = DiplomacyV2NegotiationStage.Trusted;
                state.LastEvent = DiplomacyV2EventKind.TradePactFormed;
                SyncGoodwill(relation, target);
                return DiplomacyV2DemandResolution.TradePactFormed;
            }

            // Final terms remain valid if a short pact expired while they
            // were being fulfilled or if they came from an imported V1 save.
            // The immediate team transition therefore has a complete and
            // self-consistent alliance precondition.
            state.Agreement = DiplomacyV2AgreementKind.TradePact;
            state.AgreementUntilDay = Math.Max(
                state.AgreementUntilDay,
                checked(gameDay + 1));
            state.AllianceTermsFulfilled = true;
            PrepareAllianceReadiness(state);
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);
            return CanFormAlliance(relation, target)
                ? DiplomacyV2DemandResolution.AllianceReady
                : DiplomacyV2DemandResolution.AllianceTermsAccepted;
        }

        internal static bool CompleteDemand(
            RelationState relation,
            int target,
            DiplomacyRules rules)
        {
            DiplomacyV2DemandPurpose purpose = relation.Demand == null
                ? DiplomacyV2DemandPurpose.None
                : relation.Demand.V2Purpose;
            DiplomacyV2DemandResolution result = ResolveCompletedDemand(
                relation,
                Math.Max(0, relation.LastProcessedDay),
                target,
                rules);
            return purpose == DiplomacyV2DemandPurpose.Ultimatum
                || result == DiplomacyV2DemandResolution.UltimatumFulfilled;
        }

        internal static void BeginAlliance(
            RelationState relation,
            int gameDay,
            bool startingAlliance,
            DiplomacyRules rules)
        {
            DiplomacyStateMachine.BeginAlliance(
                relation,
                gameDay,
                startingAlliance,
                rules);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            state.Trust = ClampToTrustCeiling(
                state,
                Math.Max(state.Trust, startingAlliance ? 82m : 68m));
            state.Gratitude = Math.Max(state.Gratitude, startingAlliance ? 62m : 50m);
            state.Respect = Math.Max(state.Respect, 50m);
            state.Grudge = Math.Max(
                PermanentGrudgeFloor(state),
                Math.Min(state.Grudge, 12m));
            state.Reliability = Math.Max(
                state.Reliability,
                startingAlliance ? 78m : 68m);
            state.AllianceTermsFulfilled = true;
            state.Stage = DiplomacyV2NegotiationStage.Allied;
            state.Agreement = DiplomacyV2AgreementKind.Alliance;
            state.AgreementUntilDay = 0;
            state.MaintenanceWarningLevel = 0;
            state.MaintenanceDueDay = checked(
                gameDay + MaintenanceInterval(state));
            state.MaintenanceCredit = 0m;
            state.SupportValueSinceMaintenance = 0m;
            state.LastInteractionDay = gameDay;
            MarkPositive(
                state,
                DiplomacyV2EventKind.AllianceFormed,
                gameDay);
        }

        /// <summary>
        /// Beendet alles, was AN einem Abkommen haengt: Lehnsverhaeltnis und
        /// Tributpflicht.
        /// </summary>
        /// <remarks>
        /// Beide Bruchwege riefen bis zum 07.09.2026 jeweils eigene
        /// Teilmengen auf: `BreakAlliance` raeumte keines von beiden,
        /// `BreakAgreementByPlayer` nur die Vasallenrolle. Beides fiel erst
        /// hinterher auf - `ProcessV2Vassalage` prueft nur `IsActive` und
        /// `ProcessV2Tribute` nur `IsDue`, keines von beiden das Abkommen.
        /// Also lief die Lehnsspur nach dem Bruch weiter und der Tribut wurde
        /// weiter eingezogen. Damit das kein drittes Mal passiert, steht die
        /// Aufraeumarbeit jetzt an EINER Stelle, und jeder neue Bruchweg erbt
        /// sie.
        ///
        /// Nicht ueber `Release()`: das ist die einvernehmliche Entlassung und
        /// wuerde als solche gezaehlt.
        /// </remarks>
        private static void EndBoundObligations(
            DiplomacyV2RelationState state)
        {
            DiplomacyV2Vassalage.ClearWithoutRelease(state);
            DiplomacyV2Tribute.Clear(state);
        }

        internal static void BreakAlliance(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyV2BreachKind breachKind,
            DiplomacyRules rules)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyStateMachine.BreakAlliance(relation, gameDay, rules);
            bool abandoned = breachKind
                == DiplomacyV2BreachKind.PlayerAllianceAbandonment;
            // Ein Vasall, dem die Gleichstellung verweigert wurde, sagt sich
            // aus einer Position der Staerke los. Das ist schwerer als ein
            // gescheitertes Beistandsultimatum und leichter als ein
            // Buendnisbruch aus reiner Bequemlichkeit: er hat gefragt, bevor
            // er ging (07.09.2026).
            bool rebellion = breachKind
                == DiplomacyV2BreachKind.VassalRebellion;
            if (rebellion && state.VassalRole != DiplomacyV2VassalRole.None)
            {
                // Erst zaehlen, dann raeumen: danach ist die Rolle weg.
                DiplomacyV2Vassalage.NoteRebellion(state);
            }
            int sensitivity = Profile(state).BreachSensitivityPercent;
            decimal severity = (abandoned ? 45m : rebellion ? 38m : 24m)
                * sensitivity / 100m;
            state.Trust = Clamp100(
                state.Trust - (abandoned ? 34m : rebellion ? 30m : 24m));
            state.Gratitude = Clamp100(
                state.Gratitude
                * (abandoned ? 0.42m : rebellion ? 0.50m : 0.58m));
            state.Grudge = Clamp100(state.Grudge + severity * 0.72m);
            state.Reliability = Clamp100(
                state.Reliability - (abandoned ? 35m : rebellion ? 28m : 22m));
            state.Agreement = DiplomacyV2AgreementKind.None;
            state.AgreementUntilDay = 0;
            state.AllianceTermsFulfilled = false;
            relation.Demand = null;
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            state.Stage = DiplomacyV2NegotiationStage.Blocked;
            state.MaintenanceDueDay = 0;
            state.MaintenanceWarningLevel = 0;
            state.MaintenanceCredit = 0m;
            state.SupportValueSinceMaintenance = 0m;
            state.FulfilledSupportStreak = 0;
            EndBoundObligations(state);
            state.BrokenAgreements = checked(state.BrokenAgreements + 1);
            state.BreachPoints = checked(state.BreachPoints
                + decimal.ToInt32(decimal.Ceiling(severity)));
            if (abandoned)
            {
                state.AllianceAbandonments = checked(
                    state.AllianceAbandonments + 1);
            }
            state.RestitutionOutstandingValue = Math.Max(
                state.RestitutionOutstandingValue,
                target * (abandoned ? 0.55m : 0.32m)
                    * sensitivity / 100m);
            RefreshTrustCeiling(state);
            state.LastInteractionDay = gameDay;
            relation.RelationshipBlockedUntilDay = Math.Max(
                relation.RelationshipBlockedUntilDay,
                checked(gameDay + (abandoned ? 90 : 45)));
            relation.SpontaneousOfferBlockedUntilDay =
                relation.RelationshipBlockedUntilDay;
            MarkNegative(
                state,
                DiplomacyV2EventKind.AllianceBroken,
                gameDay,
                abandoned ? 45m : 28m);
            SyncGoodwill(relation, target);
        }

        /// <summary>
        /// Eine Tributzahlung ist eingegangen - das zaehlt als gehaltenes
        /// Versprechen.
        /// </summary>
        /// <summary>
        /// Die Bruchempfindlichkeit der Wesensart - fuer Regeln, die sie
        /// brauchen, ohne das Profil selbst offenzulegen.
        /// </summary>
        internal static int BreachSensitivityOf(
            DiplomacyV2RelationState state)
        {
            return state == null ? 100 : Profile(state).BreachSensitivityPercent;
        }

        /// <summary>
        /// Der Lehnsherr hat seinen Vasallen freiwillig freigelassen.
        /// </summary>
        /// <remarks>
        /// Wer loslaesst, gewinnt einen verlaesslichen Partner. Das wiegt
        /// mehr als eine einzelne Gabe, aber es ist kein Freibrief.
        /// </remarks>
        internal static void RecordVassalReleased(
            DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            state.Gratitude = Clamp100(state.Gratitude + 22m);
            state.Trust = ClampToTrustCeiling(state, state.Trust + 12m);
            state.PositiveMomentum = Clamp100(state.PositiveMomentum + 8m);
            state.Grudge = RelieveGrudge(state, 10m);
        }

        internal static void RecordTributePaid(
            DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                return;
            }
            // Verlaesslichkeit waechst langsam und gedeckelt: eine Zahlung
            // ist die Erfuellung einer Pflicht, kein Geschenk.
            state.Reliability = Clamp100(state.Reliability + 1.5m);
            state.PositiveMomentum = Clamp100(state.PositiveMomentum + 1m);
        }

        internal static void BreakAgreementByPlayer(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyRules rules)
        {
            BreakAgreementByPlayer(
                relation,
                gameDay,
                target,
                DiplomacyV2BreachKind.ManualTreatyEnd,
                rules);
        }

        internal static void BreakAgreementByPlayer(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyV2BreachKind breachKind,
            DiplomacyRules rules)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (state.Agreement == DiplomacyV2AgreementKind.None
                || state.Agreement == DiplomacyV2AgreementKind.Alliance)
            {
                return;
            }
            // Tribute and fealty end through the alliance/team transaction.
            // An unrelated reason must not mutate a truce or trade pact.
            if (breachKind != DiplomacyV2BreachKind.ManualTreatyEnd
                && breachKind != DiplomacyV2BreachKind.TreacherousAttack
                && breachKind != DiplomacyV2BreachKind.MilitaryIncursion)
            {
                return;
            }
            state.Agreement = DiplomacyV2AgreementKind.None;
            state.AgreementUntilDay = 0;
            state.AllianceTermsFulfilled = false;
            relation.Demand = null;
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            relation.GiftValueSinceOfferAttempt = 0m;
            bool attack = breachKind
                == DiplomacyV2BreachKind.TreacherousAttack;
            bool incursion = breachKind
                == DiplomacyV2BreachKind.MilitaryIncursion;
            int sensitivity = Profile(state).BreachSensitivityPercent;
            decimal severity =
                (attack ? 34m : incursion ? 28m : 18m)
                * sensitivity / 100m;
            state.Trust = Clamp100(
                state.Trust
                - (attack ? 28m : incursion ? 22m : 16m));
            state.Gratitude = Clamp100(
                state.Gratitude
                * (attack ? 0.55m : incursion ? 0.64m : 0.75m));
            EndBoundObligations(state);
            state.Grudge = Clamp100(state.Grudge + severity * 0.78m);
            state.Reliability = Clamp100(
                state.Reliability - (attack ? 27m : incursion ? 22m : 15m));
            state.BrokenAgreements = checked(state.BrokenAgreements + 1);
            state.BreachPoints = checked(state.BreachPoints
                + decimal.ToInt32(decimal.Ceiling(severity)));
            if (attack)
            {
                state.TreacherousAttacks = checked(
                    state.TreacherousAttacks + 1);
                state.HostileActs = checked(state.HostileActs + 1);
                state.LastHostileActDay = gameDay;
            }
            else if (incursion)
            {
                state.MilitaryIncursions = checked(
                    state.MilitaryIncursions + 1);
                state.HostileActs = checked(state.HostileActs + 1);
                state.LastHostileActDay = gameDay;
                state.LastMilitaryIncursionDay = gameDay;
            }
            else
            {
                state.ManualTreatyEnds = checked(
                    state.ManualTreatyEnds + 1);
            }
            state.RestitutionOutstandingValue = Math.Max(
                state.RestitutionOutstandingValue,
                target * (attack ? 0.42m : incursion ? 0.34m : 0.24m)
                    * sensitivity / 100m);
            RefreshTrustCeiling(state);
            state.LastInteractionDay = gameDay;
            relation.RelationshipBlockedUntilDay = checked(
                gameDay + Math.Max(
                    attack ? 60 : incursion ? 45 : 30,
                    rules.BreakLockDays * (attack ? 4 : incursion ? 3 : 2)));
            relation.SpontaneousOfferBlockedUntilDay =
                relation.RelationshipBlockedUntilDay;
            state.Stage = DiplomacyV2NegotiationStage.Blocked;
            MarkNegative(
                state,
                incursion
                    ? DiplomacyV2EventKind.MilitaryIncursion
                    : DiplomacyV2EventKind.AgreementBrokenByPlayer,
                gameDay,
                attack ? 38m : incursion ? 31m : 20m);
            SyncGoodwill(relation, target);
        }

        internal static bool RecordMilitaryIncursion(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (!DiplomacyV2CombatRules.TreatyProtects(
                    relation.Allied,
                    state.Agreement,
                    state.AgreementUntilDay,
                    gameDay))
            {
                return false;
            }
            BreakAgreementByPlayer(
                relation,
                gameDay,
                target,
                DiplomacyV2BreachKind.MilitaryIncursion,
                rules);
            return true;
        }

        internal static void RecordObservedAllianceAbandonment(
            RelationState relation,
            int gameDay,
            int target,
            int abandonedAllianceCount)
        {
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (relation.Allied || abandonedAllianceCount <= 0)
            {
                return;
            }
            int count = Math.Min(7, abandonedAllianceCount);
            decimal sensitivity = Profile(state).BreachSensitivityPercent / 100m;
            decimal distrust = Math.Min(28m, count * 5m * sensitivity);
            decimal resentment = Math.Min(22m, count * 3.5m * sensitivity);
            state.ObservedAllianceAbandonments = checked(
                state.ObservedAllianceAbandonments + count);
            state.Trust = Clamp100(state.Trust - distrust);
            state.Gratitude = Clamp100(state.Gratitude - count * 2m);
            state.Grudge = Clamp100(state.Grudge + resentment);
            state.Reliability = Clamp100(
                state.Reliability - Math.Min(30m, count * 7m * sensitivity));
            state.BreachPoints = checked(
                state.BreachPoints
                    + decimal.ToInt32(decimal.Ceiling(
                        count * 5m * sensitivity)));
            state.FailedNegotiations = checked(
                state.FailedNegotiations + count);
            RefreshTrustCeiling(state);
            state.LastInteractionDay = gameDay;
            relation.RelationshipBlockedUntilDay = Math.Max(
                relation.RelationshipBlockedUntilDay,
                checked(gameDay + Math.Min(42, count * 14)));
            relation.SpontaneousOfferBlockedUntilDay = Math.Max(
                relation.SpontaneousOfferBlockedUntilDay,
                relation.RelationshipBlockedUntilDay);
            MarkNegative(
                state,
                DiplomacyV2EventKind.AllianceBetrayalObserved,
                gameDay,
                distrust + resentment);
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);
        }

        internal static void RecordHostileAct(
            RelationState relation,
            int gameDay,
            int target)
        {
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (relation.Allied || state.LastHostileActDay == gameDay)
            {
                return;
            }
            DiplomacyV2Personality profile = Profile(state);
            // These notifications include automatic arrows, melee and fire from
            // combat already in progress. They are history, not a new player's
            // decision to revoke the quoted negotiation. No treaty is implied:
            // combat remains possible until the actual terms are fulfilled.
            state.HostileActs = checked(state.HostileActs + 1);
            state.LastHostileActDay = gameDay;
            state.LastInteractionDay = gameDay;
            state.Trust = ClampToTrustCeiling(
                state,
                state.Trust - 1.5m);
            state.Grudge = Clamp100(state.Grudge
                + 2m
                    * profile.BreachSensitivityPercent / 100m);
            state.Reliability = Clamp100(
                state.Reliability - 1m);
            if (profile.Kind == DiplomacyV2PersonalityKind.Warlike)
            {
                state.Respect = Clamp100(state.Respect + 1m);
            }
            else if (profile.Kind
                == DiplomacyV2PersonalityKind.Honorable)
            {
                state.Respect = Clamp100(state.Respect - 1m);
            }
            MarkNegative(
                state,
                DiplomacyV2EventKind.HostileAct,
                gameDay,
                3m);
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);
        }

        internal static bool HasOutstandingUltimatum(RelationState relation)
        {
            return relation != null && relation.V2 != null
                && (relation.V2.MaintenanceWarningLevel >= 2
                    || relation.Demand != null
                        && relation.Demand.V2Purpose == DiplomacyV2DemandPurpose.Ultimatum);
        }

        internal static void SuspendVassalMaintenance(RelationState relation)
        {
            if (relation == null || relation.V2 == null) return;
            if (relation.Demand != null
                && (relation.Demand.V2Purpose == DiplomacyV2DemandPurpose.Support
                    || relation.Demand.V2Purpose == DiplomacyV2DemandPurpose.Ultimatum))
                relation.Demand = null;
            if (relation.Allied) relation.V2.Stage = DiplomacyV2NegotiationStage.Allied;
            relation.V2.MaintenanceDueDay = 0;
            relation.V2.MaintenanceWarningLevel = 0;
            relation.V2.MaintenanceCredit = 0m;
            relation.V2.SupportValueSinceMaintenance = 0m;
        }

        internal static void ResumeAllianceMaintenance(DiplomacyV2RelationState state, int day)
        {
            if (state == null || state.Agreement != DiplomacyV2AgreementKind.Alliance
                || DiplomacyV2Vassalage.IsActive(state)
                || state.MaintenanceWarningLevel >= 2) return;
            if (!DiplomacyLogicalClock.IsValidSavedDay(day))
                throw new ArgumentOutOfRangeException("day");
            state.MaintenanceDueDay = checked(day + MaintenanceInterval(state));
            state.MaintenanceWarningLevel = 0;
            state.MaintenanceCredit = 0m;
            state.SupportValueSinceMaintenance = 0m;
        }

        internal static bool ProcessDay(
            RelationState relation,
            int gameDay,
            int target,
            int margin,
            IEnumerable<GoodNeed> ultimatumNeeds,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (gameDay <= relation.LastProcessedDay)
            {
                return false;
            }
            GoodNeed[] needs = (ultimatumNeeds ?? Enumerable.Empty<GoodNeed>())
                .Where(need => need != null)
                .ToArray();
            int first = Math.Max(0, relation.LastProcessedDay + 1);
            bool allianceExpired = false;
            for (int day = first; day <= gameDay; day++)
            {
                ProcessMemoryDay(state, day);
                if (!relation.Allied)
                {
                    ProcessEnemyDay(relation, day, target);
                    continue;
                }
                state.Stage = state.MaintenanceWarningLevel >= 2
                    ? DiplomacyV2NegotiationStage.Ultimatum
                    : DiplomacyV2NegotiationStage.Allied;
                state.Agreement = DiplomacyV2AgreementKind.Alliance;
                if (day > relation.AllianceGraceUntilDay)
                {
                    if (day - state.LastSupportDay > 21)
                    {
                        state.Gratitude = Clamp100(state.Gratitude
                            - Profile(state).GratitudeDecayBasisPoints / 100m);
                    }
                    if (day - state.LastInteractionDay > 45)
                    {
                        state.Trust = ClampToTrustCeiling(
                            state,
                            state.Trust
                                - Profile(state).TrustDecayBasisPoints / 100m);
                    }
                }
                bool vassalageActive = DiplomacyV2Vassalage.IsActive(state);
                if (vassalageActive)
                {
                    // Tribute replaces ordinary alliance support in both
                    // directions. The current rule also forgives a legacy
                    // support ultimatum, without another breach or penalty.
                    SuspendVassalMaintenance(relation);
                    SyncGoodwill(relation, target);
                    continue;
                }
                if (!vassalageActive && relation.Demand == null
                    && state.MaintenanceDueDay == 0)
                    ResumeAllianceMaintenance(state, day);
                if (relation.Demand != null
                    && day >= relation.Demand.ExpiresDay
                    && !relation.Demand.Complete)
                {
                    if (state.MaintenanceWarningLevel < 2)
                    {
                        MissDemand(relation, day, target);
                        state.MaintenanceWarningLevel = 2;
                        DiplomacyV2Vassalage.ClearPendingOffer(state);
                        relation.Demand = CreateMaintenanceDemand(
                            relation,
                            day,
                            target,
                            needs,
                            true,
                            rules);
                        state.Stage = DiplomacyV2NegotiationStage.Ultimatum;
                        state.UltimatumsIssued = checked(
                            state.UltimatumsIssued + 1);
                        state.LastEvent = DiplomacyV2EventKind.AllianceWarned;
                        state.LastEventDay = day;
                    }
                    else
                    {
                        state.LastEvent = DiplomacyV2EventKind.AllianceBroken;
                        state.LastEventDay = day;
                        allianceExpired = true;
                        break;
                    }
                }
                if (relation.Demand == null
                    && !vassalageActive
                    && day > relation.AllianceGraceUntilDay
                    && day >= state.MaintenanceDueDay)
                {
                    decimal proactiveThreshold =
                        ProactiveSupportThreshold(state, target);
                    if (state.MaintenanceCredit >= proactiveThreshold)
                    {
                        state.MaintenanceCredit -= proactiveThreshold;
                        state.SupportValueSinceMaintenance = 0m;
                        state.MaintenanceWarningLevel = 0;
                        state.MaintenanceDueDay = checked(
                            day + MaintenanceInterval(state));
                        state.FulfilledSupportStreak = Math.Min(
                            20,
                            state.FulfilledSupportStreak + 1);
                        state.Reliability = Clamp100(
                            state.Reliability + 3m);
                        state.Trust = ClampToTrustCeiling(
                            state,
                            state.Trust + 2m);
                        MarkPositive(
                            state,
                            DiplomacyV2EventKind.ProactiveSupportRecognized,
                            day);
                    }
                    else
                    {
                        state.MaintenanceWarningLevel = 1;
                        relation.Demand = CreateMaintenanceDemand(
                            relation,
                            day,
                            target,
                            needs,
                            false,
                            rules);
                        state.MaintenanceCredit = 0m;
                        state.LastEvent =
                            DiplomacyV2EventKind.SupportRequested;
                        state.LastEventDay = day;
                    }
                }
                SyncGoodwill(relation, target);
            }
            relation.LastProcessedDay = gameDay;
            return allianceExpired;
        }

        // An eliminated coalition retains its history, not active obligations.
        // Run this at the same day boundary as living relations (audit 2026-09-07).
        internal static void ProcessInactiveDay(RelationState relation, int gameDay, int target)
        {
            RequireBase(relation, gameDay, target);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            relation.Demand = null;
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            state.MaintenanceWarningLevel = 0;
            EndBoundObligations(state);
            if (state.Agreement != DiplomacyV2AgreementKind.Alliance
                && state.Agreement != DiplomacyV2AgreementKind.None
                && gameDay >= state.AgreementUntilDay)
            {
                state.Agreement = DiplomacyV2AgreementKind.None;
                state.AgreementUntilDay = 0;
                state.LastEvent = DiplomacyV2EventKind.AgreementExpired;
                state.LastEventDay = gameDay;
            }
            relation.LastProcessedDay = gameDay;
            AdvanceStage(relation, target, gameDay);
            SyncGoodwill(relation, target);
        }

        internal static bool CanCommitAllianceBreak(
            RelationState relation, int day, DiplomacyV2BreachKind kind)
        {
            if (relation == null || !relation.Allied || relation.V2 == null
                || !DiplomacyLogicalClock.IsValidSavedDay(day)) return false;
            DiplomacyV2RelationState state = relation.V2;
            if (kind == DiplomacyV2BreachKind.TributeDefault)
                return DiplomacyV2Vassalage.IsActive(state)
                    && DiplomacyV2Tribute.IsActive(state)
                    && state.TributeMissedCycles >= DiplomacyV2Tribute.MissedCyclesUntilBreak;
            if (kind == DiplomacyV2BreachKind.VassalRebellion)
                return DiplomacyV2Vassalage.IsActive(state)
                    && DiplomacyV2Vassalage.TermElapsed(state, day)
                    && state.VassalStrengthEdgeDays >= DiplomacyV2Vassalage.RebellionEdgeDays
                    && DiplomacyV2Vassalage.RejectionBreaksRelation(state, BreachSensitivityOf(state));
            return kind == DiplomacyV2BreachKind.FailedSupportUltimatum
                && relation.Demand != null && relation.Demand.IsUltimatum
                && !relation.Demand.Complete && day >= relation.Demand.ExpiresDay;
        }

        internal static void BeginPendingOffer(
            RelationState relation,
            int gameDay)
        {
            DiplomacyStateMachine.BeginPendingOffer(relation, gameDay);
        }

        internal static void RejectPendingOffer(
            RelationState relation,
            int gameDay,
            DiplomacyRules rules)
        {
            DiplomacyStateMachine.RejectPendingOffer(relation, gameDay, rules);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            state.Trust = ClampToTrustCeiling(state, state.Trust - 4m);
            state.Grudge = Clamp100(state.Grudge + 4m);
            state.Reliability = Clamp100(state.Reliability - 2m);
            MarkNegative(
                state,
                DiplomacyV2EventKind.OfferRejected,
                gameDay,
                4m);
        }

        internal static void RejectSpontaneousOffer(
            RelationState relation,
            int gameDay,
            DiplomacyRules rules)
        {
            DiplomacyStateMachine.RejectSpontaneousOffer(
                relation,
                gameDay,
                rules);
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            state.Trust = ClampToTrustCeiling(state, state.Trust - 2m);
            state.Grudge = Clamp100(state.Grudge + 2m);
            MarkNegative(
                state,
                DiplomacyV2EventKind.OfferRejected,
                gameDay,
                2m);
        }

        internal static bool CanFormAlliance(
            RelationState relation,
            int target)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            return !relation.Allied
                && state.Agreement == DiplomacyV2AgreementKind.TradePact
                && state.AllianceTermsFulfilled
                && state.FulfilledDemands >= 3
                && state.RestitutionOutstandingValue == 0m
                && RelationshipScore(state) >= profile.AllianceThreshold
                && state.Trust >= profile.MinimumAllianceTrust
                && state.Grudge <= profile.MaximumAllianceGrudge;
        }

        internal static int NegotiationWaitDays(
            RelationState relation,
            int gameDay)
        {
            if (relation == null || relation.V2 == null
                || relation.Allied || relation.Demand != null)
            {
                return 0;
            }
            DiplomacyV2RelationState state = relation.V2;
            int earliest = relation.RelationshipBlockedUntilDay;
            if (state.LastNegotiationRequestDay >= 0)
            {
                earliest = Math.Max(
                    earliest,
                    checked(state.LastNegotiationRequestDay
                        + Profile(state).RequestPatienceDays));
            }
            return Math.Max(0, earliest - Math.Max(0, gameDay));
        }

        internal static bool PermanentHistoryPreventsAlliance(
            RelationState relation)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            return state.TrustCeiling < profile.MinimumAllianceTrust
                || PermanentGrudgeFloor(state)
                    > profile.MaximumAllianceGrudge;
        }

        internal static decimal RelationshipScore(
            DiplomacyV2RelationState state)
        {
            if (state == null)
            {
                throw new ArgumentNullException("state");
            }
            DiplomacyV2Personality profile = Profile(state);
            decimal score = (
                Clamp100(state.Trust) * profile.TrustWeight
                + Clamp100(state.Gratitude) * profile.GratitudeWeight
                + Clamp100(state.Respect) * profile.RespectWeight
                + (100m - Clamp100(state.Grudge)) * profile.GrudgeWeight)
                / 100m;
            return Clamp100(score);
        }

        internal static void ValidateAdvanced(
            RelationState relation,
            CoalitionState coalition,
            int lastProcessedDay)
        {
            if (relation == null || coalition == null || relation.V2 == null)
            {
                throw new InvalidOperationException(
                    "diplomacy V2 relation state is incomplete");
            }
            DiplomacyV2RelationState state = relation.V2;
            DiplomacyV2PersonalityCatalog.Get(state.Personality);
            DiplomacyV2Submission.Validate(relation, lastProcessedDay);
            DiplomacyV2Vassalage.ValidateEqualityResponse(state, lastProcessedDay);
            bool hasPendingVassalOffer = state.PendingVassalOverlordPlayerId != 0
                || state.PendingVassalTributeAmount != 0 || state.PendingVassalOfferDay != -1;
            if (hasPendingVassalOffer
                && (state.PendingVassalOverlordPlayerId < 1
                    || state.PendingVassalOverlordPlayerId > 8
                    || state.PendingVassalTributeAmount < DiplomacyV2Vassalage.MinimumTributeAmount
                    || state.PendingVassalTributeAmount > DiplomacyV2Vassalage.MaximumTributeAmount
                    || state.PendingVassalOfferDay < 0
                    || state.PendingVassalOfferDay > lastProcessedDay
                    || !relation.Allied || DiplomacyV2Vassalage.IsActive(state)
                    || HasOutstandingUltimatum(relation)))
                throw new InvalidOperationException("diplomacy V2 pending fealty offer is invalid");
            if (state.PrimaryLordId < -1
                || !InRange(state.Trust)
                || !InRange(state.Gratitude)
                || !InRange(state.Respect)
                || !InRange(state.Grudge)
                || !Enum.IsDefined(typeof(DiplomacyV2NegotiationStage), state.Stage)
                || !Enum.IsDefined(typeof(DiplomacyV2AgreementKind), state.Agreement)
                || state.AgreementUntilDay < 0
                || state.AgreementUntilDay
                    > (long)lastProcessedDay + 365L
                || state.LastStrategicDay < -1
                || state.LastStrategicDay > lastProcessedDay
                || state.LastInteractionDay < -1
                || state.LastInteractionDay > lastProcessedDay
                || state.LastHostileActDay < -1
                || state.LastHostileActDay > lastProcessedDay
                || state.LastMilitaryIncursionDay < -1
                || state.LastMilitaryIncursionDay > lastProcessedDay
                || state.LastGiftGoodId != 0
                    && !IsSendableGiftGood(state.LastGiftGoodId)
                || state.RepeatedGiftCount < 0
                || state.FulfilledDemands < 0
                || state.MissedDemands < 0
                || state.BrokenAgreements < 0
                || state.MaintenanceDueDay < 0
                || state.MaintenanceDueDay
                    > (long)lastProcessedDay + 365L
                || state.MaintenanceWarningLevel < 0
                || state.MaintenanceWarningLevel > 2
                || state.StrategicLeverage < -100m
                || state.StrategicLeverage > 100m
                || state.LastCreditedGiftValue < 0m
                || !Enum.IsDefined(typeof(DiplomacyV2EventKind), state.LastEvent)
                || state.LastEventDay < -1
                || state.LastEventDay > lastProcessedDay
                || !InRange(state.Reliability)
                || state.TrustCeiling < 65m
                || state.TrustCeiling > 100m
                || state.Trust > state.TrustCeiling
                || !InRange(state.PositiveMomentum)
                || !InRange(state.NegativeMomentum)
                || state.LastPositiveEventDay < -1
                || state.LastPositiveEventDay > lastProcessedDay
                || state.LastNegativeEventDay < -1
                || state.LastNegativeEventDay > lastProcessedDay
                || state.LastNegotiationRequestDay < -1
                || state.LastNegotiationRequestDay > lastProcessedDay
                || state.NegotiationRequestsWithoutGift < 0
                || state.FailedNegotiations < 0
                || state.ConsecutiveMissedDemands < 0
                || state.HostileActs < 0
                || state.ManualTreatyEnds < 0
                || state.TreacherousAttacks < 0
                || state.MilitaryIncursions < 0
                || state.AllianceAbandonments < 0
                || state.ObservedAllianceAbandonments < 0
                || state.BreachPoints < 0
                || state.RestitutionOutstandingValue < 0m
                || state.RestitutionOutstandingValue > MaximumHistoricalValue
                || !InRange(state.StrategicThreat)
                || !InRange(state.StrategicDependency)
                || !InRange(state.CoalitionValue)
                || state.CommonEnemyCoalitions < 0
                || state.HostileCoalitions < 0
                || state.PlayerAllianceCount < 0
                || state.MaintenanceCredit < 0m
                || state.MaintenanceCredit > MaximumHistoricalValue
                || state.SupportValueSinceMaintenance < 0m
                || state.SupportValueSinceMaintenance
                    > MaximumHistoricalValue
                || state.LastSupportDay < -1
                || state.LastSupportDay > lastProcessedDay
                || state.FulfilledSupportStreak < 0
                || state.UltimatumsIssued < 0
                || state.VariedGiftStreak < 0
                || !Enum.IsDefined(
                    typeof(DiplomacyV2GoodCategory),
                    state.LastGiftCategory)
                || state.LifetimeCreditedGiftValue < 0m
                || state.LifetimeCreditedGiftValue > MaximumHistoricalValue
                || state.MigrationSourceVersion < 0
                || state.MigrationSourceVersion > 3
                || state.ImportedFromV1
                    && state.MigrationSourceVersion != 1
                || !state.ImportedFromV1
                    && state.MigrationSourceVersion != 0
                || (long)state.TreacherousAttacks
                        + state.MilitaryIncursions
                    > state.HostileActs
                || state.HostileActs == 0
                    && state.LastHostileActDay != -1
                || state.HostileActs > 0
                    && state.LastHostileActDay < 0
                || state.MilitaryIncursions == 0
                    && state.LastMilitaryIncursionDay != -1
                || state.MilitaryIncursions > 0
                    && state.LastMilitaryIncursionDay < 0
                || relation.Allied && !state.AllianceTermsFulfilled
                || new[]
                    {
                        state.RepeatedGiftCount,
                        state.FulfilledDemands,
                        state.MissedDemands,
                        state.BrokenAgreements,
                        state.NegotiationRequestsWithoutGift,
                        state.FailedNegotiations,
                        state.ConsecutiveMissedDemands,
                        state.HostileActs,
                        state.ManualTreatyEnds,
                        state.TreacherousAttacks,
                        state.MilitaryIncursions,
                        state.AllianceAbandonments,
                        state.ObservedAllianceAbandonments,
                        state.BreachPoints,
                        state.CommonEnemyCoalitions,
                        state.HostileCoalitions,
                        state.PlayerAllianceCount,
                        state.FulfilledSupportStreak,
                        state.UltimatumsIssued,
                        state.VariedGiftStreak,
                    }.Any(value => value > MaximumHistoricalCount)
                || state.Agreement == DiplomacyV2AgreementKind.None
                    && state.AgreementUntilDay != 0
                || state.Agreement == DiplomacyV2AgreementKind.Alliance
                    && state.AgreementUntilDay != 0
                || (state.Agreement == DiplomacyV2AgreementKind.Truce
                        || state.Agreement
                            == DiplomacyV2AgreementKind.TradePact)
                    && state.AgreementUntilDay <= lastProcessedDay
                || relation.Allied
                    != (state.Agreement == DiplomacyV2AgreementKind.Alliance)
                || relation.Allied
                    != (state.Stage == DiplomacyV2NegotiationStage.Allied
                        || state.Stage
                            == DiplomacyV2NegotiationStage.Ultimatum))
            {
                throw new InvalidOperationException(
                    "diplomacy V2 relation state is invalid");
            }
            if (relation.Demand != null
                && (!Enum.IsDefined(
                        typeof(DiplomacyV2DemandPurpose),
                        relation.Demand.V2Purpose)
                    || relation.Demand.V2Purpose
                        == DiplomacyV2DemandPurpose.None
                    || relation.Demand.V2Urgency < 0
                    || relation.Demand.V2Urgency > 3
                    || relation.Allied
                        != (relation.Demand.V2Purpose
                                == DiplomacyV2DemandPurpose.Support
                            || relation.Demand.V2Purpose
                                == DiplomacyV2DemandPurpose.Ultimatum)
                    || relation.Demand.IsUltimatum != relation.Allied))
            {
                throw new InvalidOperationException(
                    "diplomacy V2 demand state is invalid");
            }
            if (state.GiftMemory == null
                || state.GiftMemory.Count > MaximumGiftMemories
                || state.GiftMemory.Any(memory => memory == null
                    || !IsSendableGiftGood(memory.GoodId)
                    || memory.LastGiftDay < -1
                    || memory.LastGiftDay > lastProcessedDay
                    || memory.ConsecutiveCount < 0
                    || memory.RecentRawValue < 0m
                    || memory.RecentRawValue > MaximumHistoricalValue
                    || memory.LifetimeCreditedValue < 0m
                    || memory.LifetimeCreditedValue
                        > MaximumHistoricalValue)
                || state.GiftMemory.Select(memory => memory.GoodId)
                    .Distinct().Count() != state.GiftMemory.Count)
            {
                throw new InvalidOperationException(
                    "diplomacy V2 gift memory is invalid");
            }
        }

        private static void ProcessEnemyDay(
            RelationState relation,
            int day,
            int target)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (state.Agreement != DiplomacyV2AgreementKind.None
                && state.Agreement != DiplomacyV2AgreementKind.Alliance
                && day >= state.AgreementUntilDay)
            {
                state.Agreement = DiplomacyV2AgreementKind.None;
                state.AgreementUntilDay = 0;
                state.LastEvent = DiplomacyV2EventKind.AgreementExpired;
                state.LastEventDay = day;
            }
            int daysSinceGift = relation.LastGiftDay < 0
                ? int.MaxValue
                : day - relation.LastGiftDay;
            if (daysSinceGift > 21)
            {
                decimal gratitudeLoss =
                    Profile(state).GratitudeDecayBasisPoints / 100m;
                state.Gratitude = Clamp100(state.Gratitude - gratitudeLoss);
            }
            if (day - state.LastInteractionDay > 45)
            {
                state.Trust = ClampToTrustCeiling(
                    state,
                    state.Trust
                        - Profile(state).TrustDecayBasisPoints / 100m);
            }
            if ((state.LastHostileActDay < 0
                    || day - state.LastHostileActDay > 21)
                && state.Grudge > PermanentGrudgeFloor(state))
            {
                state.Grudge = Clamp100(Math.Max(
                    PermanentGrudgeFloor(state),
                    state.Grudge
                        - Profile(state).GrudgeRecoveryBasisPoints / 100m));
            }
            if (relation.Demand != null
                && day >= relation.Demand.ExpiresDay)
            {
                MissDemand(relation, day, target);
                relation.Demand = null;
                BlockNegotiationAfterMiss(relation, state, day);
            }
            AdvanceStage(relation, target, day);
            SyncGoodwill(relation, target);
        }

        private static GoodsDemand CreateMaintenanceDemand(
            RelationState relation,
            int gameDay,
            int target,
            IEnumerable<GoodNeed> needs,
            bool finalWarning,
            DiplomacyRules rules)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            int percent = finalWarning
                ? profile.UltimatumDemandPercent
                : profile.SupportDemandPercent;
            decimal urgencyFactor = 1m
                + state.StrategicDependency / 400m
                + state.NegativeMomentum / 500m;
            decimal reliabilityFactor = Clamp(
                1m + (55m - state.Reliability) / 250m,
                0.85m,
                1.30m);
            decimal valueGap = Math.Max(
                1m,
                target * percent / 100m
                    * profile.DemandBasisPoints / 10000m
                    * HistoryDemandFactor(state)
                    * urgencyFactor
                    * reliabilityFactor
                    - (finalWarning ? 0m : state.MaintenanceCredit));
            GoodsDemand demand = DiplomacyDemandPlanner.Create(
                valueGap,
                needs,
                gameDay,
                true,
                rules);
            demand.ExpiresDay = checked(gameDay + (finalWarning
                ? profile.UltimatumDeadlineDays
                : profile.SupportDeadlineDays));
            demand.V2Purpose = finalWarning
                ? DiplomacyV2DemandPurpose.Ultimatum
                : DiplomacyV2DemandPurpose.Support;
            demand.V2Urgency = finalWarning ? 3 : 2;
            return demand;
        }

        /// <summary>
        /// Der Spieler weist eine offene Forderung ausdruecklich zurueck.
        /// </summary>
        /// <remarks>
        /// Benutzervorgabe 09.09.2026: eine Forderung muss ablehnbar sein.
        /// Praezisiert am 10.09.2026: eine abgelehnte Bitte kostet Ansehen,
        /// beendet aber NIE das Buendnis - auch die zweite Mahnung nicht.
        ///
        /// Ablehnen ist damit bewusst milder als Schweigen: wer die Frist
        /// verstreichen laesst, klettert die Eskalationsleiter hoch (Mahnung,
        /// letzte Mahnung, Bruch); wer absagt, zahlt den Ansehensverlust aus
        /// MissDemand und ist fertig. Eine ehrliche Absage soll nicht teurer
        /// sein als Wortbruch.
        ///
        /// Die Warnstufe bleibt absichtlich unberuehrt. Der naechste Tageslauf
        /// stellt die gewoehnliche Beistandsforderung neu, sobald sie faellig
        /// ist - kein Aufstieg zum Ultimatum allein durch eine Absage.
        /// </remarks>
        internal static bool DeclineDemand(
            RelationState relation,
            int gameDay,
            int target)
        {
            if (relation == null || relation.Demand == null
                || relation.V2 == null
                || !DiplomacyLogicalClock.IsValidSavedDay(gameDay))
                return false;
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            // Bewusst NICHT MissDemand: das ist die Strafe fuer Wortbruch
            // (Trust -11, Groll +11, Zuverlaessigkeit -8,8, dazu die Zaehler
            // fuer versaeumte Forderungen). Eine Absage ist kein Wortbruch -
            // sie sagt nur, dass der Fuerst nicht mit der Lieferung rechnen
            // braucht. Sie kostet deshalb Zuverlaessigkeit und etwas Vertrauen,
            // aber keinen Groll und keinen Eintrag in der Versaeumnis-Kette.
            state.Reliability = Clamp100(state.Reliability - 6m);
            state.Trust = ClampToTrustCeiling(state, state.Trust - 3m);
            MarkNegative(
                state,
                DiplomacyV2EventKind.DemandMissed,
                gameDay,
                3m);
            SyncGoodwill(relation, target);
            relation.Demand = null;
            BlockNegotiationAfterMiss(relation, state, gameDay);
            return true;
        }

        /// <summary>Ob die offene Forderung ein Ultimatum ist.</summary>
        internal static bool DemandIsUltimatum(RelationState relation)
        {
            return relation != null && relation.Demand != null
                && relation.Demand.V2Purpose == DiplomacyV2DemandPurpose.Ultimatum;
        }

        private static void MissDemand(
            RelationState relation,
            int gameDay,
            int target)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2DemandPurpose purpose = relation.Demand == null
                ? DiplomacyV2DemandPurpose.None
                : relation.Demand.V2Purpose;
            state.MissedDemands = checked(state.MissedDemands + 1);
            state.ConsecutiveMissedDemands = checked(
                state.ConsecutiveMissedDemands + 1);
            bool allianceDemand = purpose == DiplomacyV2DemandPurpose.Support
                || purpose == DiplomacyV2DemandPurpose.Ultimatum;
            decimal severity = allianceDemand ? 11m : 7m;
            severity += Math.Min(8, state.ConsecutiveMissedDemands) * 0.75m;
            state.Trust = ClampToTrustCeiling(
                state,
                state.Trust - severity);
            state.Gratitude = Clamp100(
                state.Gratitude - (allianceDemand ? 7m : 4m));
            state.Grudge = Clamp100(state.Grudge + severity);
            state.Reliability = Clamp100(state.Reliability - severity * 0.8m);
            state.FulfilledSupportStreak = allianceDemand
                ? 0
                : state.FulfilledSupportStreak;
            MarkNegative(
                state,
                DiplomacyV2EventKind.DemandMissed,
                gameDay,
                severity);
            SyncGoodwill(relation, target);
        }

        private static void BlockNegotiationAfterMiss(
            RelationState relation,
            DiplomacyV2RelationState state,
            int gameDay)
        {
            int retryDay = checked(
                gameDay + Profile(state).RequestPatienceDays);
            relation.RelationshipBlockedUntilDay = Math.Max(
                relation.RelationshipBlockedUntilDay,
                retryDay);
            relation.SpontaneousOfferBlockedUntilDay = Math.Max(
                relation.SpontaneousOfferBlockedUntilDay,
                retryDay);
            state.LastNegotiationRequestDay = gameDay;
            state.LastInteractionDay = gameDay;
        }

        // Social progress is not evidence that either side has actually
        // started a negotiation. Keep the stored progression (and therefore
        // request eligibility/prices) separate from the player's live status.
        internal static bool HasActiveNegotiation(
            RelationState relation,
            int gameDay)
        {
            if (relation == null || relation.V2 == null
                || relation.Allied || gameDay < 0)
            {
                return false;
            }
            return relation.Demand != null
                    && (relation.Demand.Complete
                        || gameDay < relation.Demand.ExpiresDay)
                || relation.PendingOffer
                || DiplomacyV2Submission.HasOffer(relation.V2);
        }

        internal static DiplomacyV2NegotiationStage DisplayStage(
            RelationState relation,
            int gameDay)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (relation.Allied)
            {
                return state.MaintenanceWarningLevel >= 2
                    ? DiplomacyV2NegotiationStage.Ultimatum
                    : DiplomacyV2NegotiationStage.Allied;
            }
            if (gameDay < relation.RelationshipBlockedUntilDay)
            {
                return DiplomacyV2NegotiationStage.Blocked;
            }
            if (HasActiveNegotiation(relation, gameDay))
            {
                return DiplomacyV2NegotiationStage.Negotiating;
            }
            return state.Stage == DiplomacyV2NegotiationStage.Negotiating
                ? DiplomacyV2NegotiationStage.Contact
                : state.Stage;
        }

        private static void AdvanceStage(
            RelationState relation,
            int target,
            int gameDay)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            if (relation.Allied)
            {
                state.Stage = state.MaintenanceWarningLevel >= 2
                    ? DiplomacyV2NegotiationStage.Ultimatum
                    : DiplomacyV2NegotiationStage.Allied;
                return;
            }
            if (gameDay < relation.RelationshipBlockedUntilDay)
            {
                state.Stage = DiplomacyV2NegotiationStage.Blocked;
                return;
            }
            if (state.RestitutionOutstandingValue > 0m)
            {
                state.Stage = DiplomacyV2NegotiationStage.Contact;
                return;
            }
            if (CanFormAllianceWithoutStage(relation))
            {
                state.Stage = DiplomacyV2NegotiationStage.AllianceReady;
                return;
            }
            if (state.Agreement == DiplomacyV2AgreementKind.TradePact)
            {
                state.Stage = DiplomacyV2NegotiationStage.Trusted;
                return;
            }
            if (state.Agreement == DiplomacyV2AgreementKind.Truce)
            {
                state.Stage = DiplomacyV2NegotiationStage.Negotiating;
                return;
            }
            decimal score = RelationshipScore(state);
            state.Stage = score < 22m
                ? DiplomacyV2NegotiationStage.Hostile
                : score < 45m
                    ? DiplomacyV2NegotiationStage.Contact
                    : score < 68m
                        ? DiplomacyV2NegotiationStage.Negotiating
                        : DiplomacyV2NegotiationStage.Trusted;
        }

        private static bool CanFormAllianceWithoutStage(RelationState relation)
        {
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            DiplomacyV2Personality profile = Profile(state);
            return !relation.Allied
                && state.Agreement == DiplomacyV2AgreementKind.TradePact
                && state.AllianceTermsFulfilled
                && state.FulfilledDemands >= 3
                && state.RestitutionOutstandingValue == 0m
                && RelationshipScore(state) >= profile.AllianceThreshold
                && state.Trust >= profile.MinimumAllianceTrust
                && state.Grudge <= profile.MaximumAllianceGrudge;
        }

        private static void PrepareAllianceReadiness(
            DiplomacyV2RelationState state)
        {
            DiplomacyV2Personality profile = Profile(state);
            decimal acceptanceFloor = Math.Min(
                96m,
                profile.AllianceThreshold + 10m);
            state.Trust = ClampToTrustCeiling(
                state,
                Math.Max(
                    state.Trust,
                    Math.Max(
                        profile.MinimumAllianceTrust,
                        profile.AllianceThreshold)));
            state.Gratitude = Math.Max(state.Gratitude, acceptanceFloor);
            state.Respect = Math.Max(state.Respect, acceptanceFloor);
            state.Grudge = Math.Max(
                PermanentGrudgeFloor(state),
                Math.Min(
                    state.Grudge,
                    profile.MaximumAllianceGrudge));
        }

        private static decimal HistoryDemandFactor(
            DiplomacyV2RelationState state)
        {
            // Broken promises are remembered even after the visible grudge
            // has slowly cooled. Repeatedly missed terms also make the next
            // demand firmer, but the cap keeps reconciliation attainable.
            decimal surcharge = state.BrokenAgreements * 0.10m
                + state.MissedDemands * 0.03m
                + state.BreachPoints * 0.003m
                + state.FailedNegotiations * 0.015m
                + state.ObservedAllianceAbandonments * 0.05m;
            return 1m + Math.Min(0.90m, Math.Max(0m, surcharge));
        }

        private static DiplomacyV2GiftMemory GiftMemory(
            DiplomacyV2RelationState state,
            int goodId)
        {
            if (state.GiftMemory == null)
            {
                state.GiftMemory = new List<DiplomacyV2GiftMemory>();
            }
            DiplomacyV2GiftMemory memory = state.GiftMemory.FirstOrDefault(
                value => value.GoodId == goodId);
            if (memory != null)
            {
                return memory;
            }
            if (state.GiftMemory.Count >= MaximumGiftMemories)
            {
                DiplomacyV2GiftMemory oldest = state.GiftMemory
                    .OrderBy(value => value.LastGiftDay)
                    .ThenBy(value => value.GoodId)
                    .First();
                state.GiftMemory.Remove(oldest);
            }
            memory = new DiplomacyV2GiftMemory { GoodId = goodId };
            state.GiftMemory.Add(memory);
            return memory;
        }

        internal static DiplomacyV2GoodCategory GoodCategory(int goodId)
        {
            if (goodId == 15)
            {
                return DiplomacyV2GoodCategory.Gold;
            }
            if (goodId >= 17 && goodId <= 24)
            {
                return DiplomacyV2GoodCategory.Weapons;
            }
            if (goodId == 3 || goodId == 14)
            {
                return DiplomacyV2GoodCategory.Luxury;
            }
            if (goodId == 9 || goodId == 10 || goodId == 11
                || goodId == 12 || goodId == 13 || goodId == 16)
            {
                return DiplomacyV2GoodCategory.Food;
            }
            return DiplomacyV2GoodCategory.Materials;
        }

        private static int CategoryGiftPercent(
            DiplomacyV2Personality profile,
            DiplomacyV2GoodCategory category)
        {
            switch (category)
            {
                case DiplomacyV2GoodCategory.Food:
                    return profile.FoodGiftPercent;
                case DiplomacyV2GoodCategory.Luxury:
                    return profile.LuxuryGiftPercent;
                case DiplomacyV2GoodCategory.Weapons:
                    return profile.WeaponsGiftPercent;
                case DiplomacyV2GoodCategory.Gold:
                    return profile.GoldGiftPercent;
                default:
                    return profile.MaterialsGiftPercent;
            }
        }

        private static void ProcessMemoryDay(
            DiplomacyV2RelationState state,
            int day)
        {
            state.PositiveMomentum = Clamp100(state.PositiveMomentum * 0.94m);
            state.NegativeMomentum = Clamp100(state.NegativeMomentum * 0.96m);
            if (state.GiftMemory == null)
            {
                state.GiftMemory = new List<DiplomacyV2GiftMemory>();
                return;
            }
            foreach (DiplomacyV2GiftMemory memory in state.GiftMemory)
            {
                if (memory.LastGiftDay < day)
                {
                    memory.RecentRawValue *= 0.93m;
                    if (memory.RecentRawValue < 0.01m)
                    {
                        memory.RecentRawValue = 0m;
                    }
                }
            }
        }

        private static int MaintenanceInterval(
            DiplomacyV2RelationState state)
        {
            DiplomacyV2Personality profile = Profile(state);
            int reliabilityBonus = state.Reliability >= 80m ? 14 : 0;
            int supportBonus = Math.Min(30, state.FulfilledSupportStreak * 4);
            int pressurePenalty = Math.Min(
                14,
                decimal.ToInt32(decimal.Floor(
                    state.StrategicDependency / 8m)));
            return Math.Max(
                60,
                profile.MaintenanceIntervalDays
                    + reliabilityBonus + supportBonus - pressurePenalty);
        }

        private static decimal ProactiveSupportThreshold(
            DiplomacyV2RelationState state,
            int target)
        {
            DiplomacyV2Personality profile = Profile(state);
            return Math.Max(
                1m,
                target * profile.ProactiveSupportPercent / 100m
                    * (1m + state.StrategicDependency / 500m));
        }

        private static int PermanentBreachFloor(
            DiplomacyV2RelationState state)
        {
            return Math.Min(
                250,
                state.ManualTreatyEnds * 5
                    + state.TreacherousAttacks * 14
                    + state.MilitaryIncursions * 10
                    + state.AllianceAbandonments * 20
                    + state.ObservedAllianceAbandonments * 4);
        }

        private static decimal PermanentGrudgeFloor(
            DiplomacyV2RelationState state)
        {
            return Math.Min(60m, PermanentBreachFloor(state) * 0.35m);
        }

        private static void RefreshTrustCeiling(
            DiplomacyV2RelationState state)
        {
            state.TrustCeiling = Clamp(
                100m - state.BreachPoints * 0.52m,
                65m,
                100m);
            state.Trust = ClampToTrustCeiling(state, state.Trust);
        }

        private static decimal ClampToTrustCeiling(
            DiplomacyV2RelationState state,
            decimal value)
        {
            return Clamp(value, 0m, Clamp(state.TrustCeiling, 0m, 100m));
        }

        private static decimal RelieveGrudge(
            DiplomacyV2RelationState state,
            decimal relief)
        {
            return Clamp100(Math.Max(
                PermanentGrudgeFloor(state),
                state.Grudge - Math.Max(0m, relief)));
        }

        private static decimal AddHistoricalValue(
            decimal current,
            decimal addition)
        {
            if (current < 0m || addition < 0m)
            {
                throw new ArgumentOutOfRangeException("addition");
            }
            return Math.Min(
                MaximumHistoricalValue,
                current > MaximumHistoricalValue - addition
                    ? MaximumHistoricalValue
                    : current + addition);
        }

        private static void MarkPositive(
            DiplomacyV2RelationState state,
            DiplomacyV2EventKind kind,
            int day)
        {
            state.LastEvent = kind;
            state.LastEventDay = day;
            state.LastPositiveEventDay = day;
            state.PositiveMomentum = Clamp100(state.PositiveMomentum + 2m);
        }

        private static void MarkNegative(
            DiplomacyV2RelationState state,
            DiplomacyV2EventKind kind,
            int day,
            decimal weight)
        {
            state.LastEvent = kind;
            state.LastEventDay = day;
            state.LastNegativeEventDay = day;
            state.NegativeMomentum = Clamp100(
                state.NegativeMomentum + Math.Max(0m, weight));
        }

        private static void SyncGoodwill(RelationState relation, int target)
        {
            if (target < 1)
            {
                throw new ArgumentOutOfRangeException("target");
            }
            DiplomacyV2RelationState state = RequireAdvanced(relation);
            relation.Goodwill = CanFormAllianceWithoutStage(relation)
                ? target
                : target * RelationshipScore(state) / 100m;
        }

        private static DiplomacyRequestResult Result(
            DiplomacyRequestOutcome outcome)
        {
            return new DiplomacyRequestResult { Outcome = outcome };
        }

        private static DiplomacyV2RelationState RequireAdvanced(
            RelationState relation)
        {
            if (relation == null || relation.V2 == null)
            {
                throw new InvalidOperationException(
                    "diplomacy V2 relation is not initialized");
            }
            return relation.V2;
        }

        private static DiplomacyV2Personality Profile(
            DiplomacyV2RelationState state)
        {
            return DiplomacyV2PersonalityCatalog.Get(state.Personality);
        }

        private static void RequireBase(
            RelationState relation,
            int gameDay,
            int target)
        {
            if (relation == null || string.IsNullOrEmpty(relation.CoalitionId))
            {
                throw new ArgumentNullException("relation");
            }
            if (!DiplomacyLogicalClock.IsValidSavedDay(gameDay)
                || target < 1)
            {
                throw new ArgumentOutOfRangeException("gameDay");
            }
        }

        private static void RequireRules(DiplomacyRules rules)
        {
            if (rules == null || rules.Validate() != null)
            {
                throw new InvalidOperationException("diplomacy rules are invalid");
            }
        }

        private static bool InRange(decimal value)
        {
            return value >= 0m && value <= 100m;
        }

        private static bool IsSendableGiftGood(int goodId)
        {
            return goodId == 2 || goodId == 3 || goodId == 4
                || goodId == 6 || goodId == 7
                || goodId >= 9 && goodId <= 24;
        }

        private static decimal Clamp100(decimal value)
        {
            return Clamp(value, 0m, 100m);
        }

        private static decimal Clamp(decimal value, decimal minimum, decimal maximum)
        {
            return Math.Max(minimum, Math.Min(maximum, value));
        }
    }

    /// <summary>
    /// Worauf ein Spielerbefehl zielt - in der Sprache der Diplomatie statt
    /// der nativen Befehlsnummern. Die Zuordnung TribeAICommand -> Art steht
    /// im Feature (<c>V2AttackTargetKind</c>); die Entscheidung liegt hier,
    /// damit sie ohne Spiel pruefbar ist (06.09.2026).
    /// </summary>
    internal enum DiplomacyV2AttackTargetKind
    {
        None = 0,
        Unit = 1,
        Building = 2,
        WallTile = 3,
        GroundTile = 4,
    }

    /// <summary>
    /// Abzug des Mausklicks: was beim Klick unter dem Zeiger lag. Die
    /// Loeschform (<see cref="Cleared"/>) passt auf keinen Befehl - ein Klick
    /// gibt genau einen Angriff frei, nie den naechsten mit.
    /// </summary>
    internal struct DiplomacyV2ExplicitAttackInput
    {
        internal int HoverUnitId;
        internal int HoverBuildingId;
        internal int HoverBuildingTileId;
        internal int HoverTileId;
        internal int TileX;
        internal int TileY;

        internal static DiplomacyV2ExplicitAttackInput Cleared
        {
            get
            {
                return new DiplomacyV2ExplicitAttackInput
                {
                    HoverUnitId = 0,
                    HoverBuildingId = 0,
                    HoverBuildingTileId = -1,
                    HoverTileId = -1,
                    TileX = -1,
                    TileY = -1,
                };
            }
        }
    }

    /// <summary>
    /// Reine Kampfregeln der V2-Diplomatie: bewusster Angriff,
    /// Eingabefenster, Kernzone, Paktschutz. Keine Spielzugriffe - jede Regel
    /// ist im Pruefstand gegen Zahlen pruefbar. Das Feature liefert nur die
    /// Messwerte (Mausabzug, Einheitenpositionen, Burgtor) und protokolliert.
    /// </summary>
    internal static class DiplomacyV2CombatRules
    {
        /// <summary>SHCDESE: eine lokale Kachel sind acht Weltpositionen.</summary>
        internal const int WorldPositionsPerLocalTile = 8;
        internal const int IntimateZoneRadiusLocalTiles = 18;
        internal const int SubstantialForceMinimumUnits = 8;
        internal const int SubstantialForceMinimumValue = 250;
        internal const int MassedForceMinimumUnits = 12;
        internal const int HeavyForceMinimumUnits = 4;
        internal const int HeavyForceMinimumValue = 600;
        /// <summary>Feindakt-Zuordnung fuer Weltziele: hoechstens ein
        /// Vollscan je 32 Takte (RecordHostileAct ist je Tag idempotent).</summary>
        internal const int HostileAttributionIntervalTicks = 32;
        /// <summary>Abstandsgebot: ein Stamm wird hoechstens alle 128 Takte
        /// (rund vier Sekunden) nach Hause geschickt.</summary>
        internal const int TreatyRecallIntervalTicks = 128;
        /// <summary>Sentinel "noch nie gescannt". Takte sind nie negativ.</summary>
        internal const long NeverScannedTick = -1L;

        /// <summary>
        /// Ob ein Scan faellig ist. Pruefbefund P1-A (06.09.2026): der alte
        /// Sentinel int.MinValue lief bei "now - last" ueber und drosselte
        /// ab Takt 0 fuer immer. Hier: Sentinel ohne Arithmetik, Differenz
        /// in long, ein zurueckgelaufener Zaehler (neue Karte) ist faellig.
        /// </summary>
        internal static bool ScanDue(
            long lastScanTick,
            long nowTick,
            int intervalTicks)
        {
            if (lastScanTick == NeverScannedTick || nowTick < lastScanTick)
            {
                return true;
            }
            return nowTick - lastScanTick >= intervalTicks;
        }

        internal static long IntimateZoneSquaredRadiusWorld
        {
            get
            {
                long radius = (long)IntimateZoneRadiusLocalTiles
                    * WorldPositionsPerLocalTile;
                return radius * radius;
            }
        }

        internal static bool IsTreaty(DiplomacyV2AgreementKind agreement)
        {
            return agreement == DiplomacyV2AgreementKind.Truce
                || agreement == DiplomacyV2AgreementKind.TradePact;
        }

        /// <summary>
        /// Ein Pakt schuetzt, solange er laeuft. Ein Buendnis schuetzt das
        /// Spiel selbst ueber das Team - darum zaehlt es hier nicht.
        /// </summary>
        internal static bool TreatyProtects(
            bool allied,
            DiplomacyV2AgreementKind agreement,
            int agreementUntilDay,
            int day)
        {
            return !allied
                && IsTreaty(agreement)
                && agreementUntilDay > day;
        }

        /// <summary>
        /// Wie viele Simulationstakte nach dem Klick ein Zielbefehl noch als
        /// derselbe Vorgang gilt.
        /// </summary>
        /// <remarks>
        /// GEMESSEN am 07.09.2026, 14:26 (15 Faelle, Spieler 1 auf Spieler 8):
        /// der native Zielbefehl trifft **2 bis 5 Takte** nach der Mauseingabe
        /// ein, im Mittel gut 4. Das alte Fenster deckte genau einen Takt ab -
        /// deshalb kam kein einziger gezielter Vertragsbruch zustande, und im
        /// Protokoll stand fuenfzehnmal
        /// `breach_denied|reason=input_window_closed|tick=26818|until=26814`.
        ///
        /// Der Grund ist die Fadentrennung: die Mauseingabe kommt im
        /// Unity-Faden, der Stammbefehl im Simulationsfaden - beide am selben
        /// Lauf gemessen (`lane_identity ... same_thread=false`).
        ///
        /// Acht Takte decken das Gemessene mit Reserve und sind bei der
        /// nativen Taktrate etwa eine Viertelsekunde - kurz genug, dass es
        /// derselbe Klick bleibt. Die Zahl ist eine Messung, keine Schaetzung;
        /// wer sie aendert, misst neu.
        /// </remarks>
        internal const int InputWindowTicks = 8;

        internal static long InputWindowUntil(long simulationTick)
        {
            return simulationTick > long.MaxValue - InputWindowTicks
                ? long.MaxValue
                : simulationTick + InputWindowTicks;
        }

        internal static bool InputWindowOpen(
            long simulationTick,
            long inputUntilTick)
        {
            return simulationTick <= inputUntilTick;
        }

        /// <summary>
        /// Nur der Befehl auf genau das Ziel, das beim Klick unter dem Zeiger
        /// lag, ist ein bewusster Angriff. Kennung 0 (nichts unter dem Zeiger)
        /// und negative Kacheln passen nie.
        /// </summary>
        internal static bool ExplicitAttackMatches(
            DiplomacyV2AttackTargetKind kind,
            int targetValue1,
            int targetValue2,
            DiplomacyV2ExplicitAttackInput input)
        {
            switch (kind)
            {
                case DiplomacyV2AttackTargetKind.Unit:
                    return targetValue1 > 0
                        && targetValue1 == input.HoverUnitId;
                case DiplomacyV2AttackTargetKind.Building:
                    return targetValue1 > 0
                        && targetValue1 == input.HoverBuildingId;
                case DiplomacyV2AttackTargetKind.WallTile:
                    return targetValue1 >= 0
                        && (targetValue1 == input.HoverBuildingTileId
                            || targetValue1 == input.HoverTileId);
                case DiplomacyV2AttackTargetKind.GroundTile:
                    return targetValue1 >= 0
                        && targetValue2 >= 0
                        && targetValue1 == input.TileX
                        && targetValue2 == input.TileY;
                default:
                    return false;
            }
        }

        /// <summary>
        /// Eine Streitmacht, die einen Pakt bricht: acht Einheiten mit etwas
        /// Wert, oder zwoelf beliebige, oder vier schwere. Weniger als vier
        /// ist nie ein Einmarsch.
        /// </summary>
        internal static bool IsSubstantialForce(int units, long militaryValue)
        {
            return units >= SubstantialForceMinimumUnits
                    && militaryValue >= SubstantialForceMinimumValue
                || units >= MassedForceMinimumUnits
                || units >= HeavyForceMinimumUnits
                    && militaryValue >= HeavyForceMinimumValue;
        }

        internal static int TileCenterWorld(int localTile)
        {
            return checked(
                localTile * WorldPositionsPerLocalTile
                    + WorldPositionsPerLocalTile / 2);
        }

        /// <summary>
        /// Die Kernzone haengt am festen Burgtor (Kachelkoordinaten), nie am
        /// Fuersten. SHCDESE liefert (0, 0), wenn keine Spielerressourcen
        /// existieren - dann gibt es keine Zone, statt einer wandernden.
        /// </summary>
        internal static bool TryKeepCenter(
            int keepDoorX,
            int keepDoorY,
            int mapSize,
            out int worldX,
            out int worldY)
        {
            worldX = 0;
            worldY = 0;
            if (mapSize <= 0
                || keepDoorX < 0 || keepDoorX >= mapSize
                || keepDoorY < 0 || keepDoorY >= mapSize
                || keepDoorX == 0 && keepDoorY == 0)
            {
                return false;
            }
            worldX = TileCenterWorld(keepDoorX);
            worldY = TileCenterWorld(keepDoorY);
            return true;
        }

        /// <summary>
        /// Steht der Punkt innerhalb von <paramref name="bandTiles"/> lokalen
        /// Kacheln um die Mitte?
        /// </summary>
        /// <remarks>
        /// Fuer die Entfernungsmessung vom 07.09.2026: der Benutzer marschierte
        /// mit ueber 200 Einheiten ein, gezaehlt wurden 7, weil die Kernzone
        /// nur 18 Kacheln um das Burgtor reicht. Bevor diese Zahl geaendert
        /// wird, soll gemessen werden, wie weit eine Streitmacht wirklich
        /// steht. Dieselbe Kreisprobe wie <see cref="InsideZone"/> - zwei
        /// Stellen mit eigener Geometrie liefen sonst auseinander.
        /// </remarks>
        internal static bool WithinBandTiles(
            int x,
            int y,
            int centerX,
            int centerY,
            int bandTiles)
        {
            long radius = (long)Math.Max(0, bandTiles) * WorldPositionsPerLocalTile;
            return InsideZone(x, y, centerX, centerY, radius * radius);
        }

        internal static bool InsideZone(
            int unitX,
            int unitY,
            int centerX,
            int centerY,
            long squaredRadius)
        {
            long dx = (long)unitX - centerX;
            long dy = (long)unitY - centerY;
            return dx * dx + dy * dy <= squaredRadius;
        }
    }

    internal static class DiplomacyV2Contract
    {
        internal const string LegacySaveDataIdentifier =
            "StrongholdEuropeDE.Diplomacy.v1";
    }
    internal enum DiplomacyV2RelationshipDecisionKind
    {
        None = 0, EndAlliance = 1, EndAgreement = 2,
        AcceptAllianceOffer = 3, RejectAllianceOffer = 4,
    }

    internal static class DiplomacyV2RelationshipDecisions
    {
        internal const int MaximumContractBytes = 512;
        internal static bool HasPending(DiplomacyV2RelationState s)
        { return s != null && s.PendingRelationshipDecision != DiplomacyV2RelationshipDecisionKind.None; }

        // Carry a confirmed decision into an older inventory recovery base.
        // Only this contract's four fields belong to the copy: economic and
        // diplomatic state in that base must continue to describe its snapshot.
        internal static void CopyPendingDecision(DiplomacyV2RelationState source,
            DiplomacyV2RelationState destination)
        {
            if (source == null) throw new ArgumentNullException(nameof(source));
            if (destination == null) throw new ArgumentNullException(nameof(destination));
            destination.PendingRelationshipDecision = source.PendingRelationshipDecision;
            destination.PendingRelationshipDecisionPlayerId = source.PendingRelationshipDecisionPlayerId;
            destination.PendingRelationshipDecisionDay = source.PendingRelationshipDecisionDay;
            destination.PendingRelationshipDecisionContract = source.PendingRelationshipDecisionContract;
        }

        internal static void Clear(DiplomacyV2RelationState s)
        {
            s.PendingRelationshipDecision = DiplomacyV2RelationshipDecisionKind.None;
            s.PendingRelationshipDecisionPlayerId = 0;
            s.PendingRelationshipDecisionDay = -1;
            s.PendingRelationshipDecisionContract = null;
        }

        internal static bool Eligible(RelationState r, DiplomacyV2RelationshipDecisionKind kind, int day)
        {
            if (r == null || r.V2 == null) return false;
            switch (kind)
            {
                case DiplomacyV2RelationshipDecisionKind.EndAlliance: return r.Allied;
                case DiplomacyV2RelationshipDecisionKind.EndAgreement:
                    return !r.Allied && (r.V2.Agreement == DiplomacyV2AgreementKind.Truce
                        || r.V2.Agreement == DiplomacyV2AgreementKind.TradePact) && r.V2.AgreementUntilDay > day;
                case DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer:
                case DiplomacyV2RelationshipDecisionKind.RejectAllianceOffer: return !r.Allied && r.PendingOffer;
                default: return false;
            }
        }

        private static string Roster(CoalitionState c)
        {
            return string.Join(",", c.MemberPlayerIds.Select((p, i) => new { Player = p, Team = c.OriginalTeams[i] })
                .OrderBy(x => x.Player).Select(x => x.Player.ToString(System.Globalization.CultureInfo.InvariantCulture)
                    + ":" + x.Team.ToString(System.Globalization.CultureInfo.InvariantCulture)));
        }

        internal static string Contract(RelationState r, CoalitionState c, int local, int player,
            DiplomacyV2RelationshipDecisionKind kind = DiplomacyV2RelationshipDecisionKind.None)
        {
            if (r == null || r.V2 == null || c == null || r.CoalitionId != c.CoalitionId
                || c.MemberPlayerIds == null || c.OriginalTeams == null
                || c.MemberPlayerIds.Length != c.OriginalTeams.Length
                || !c.MemberPlayerIds.Contains(player) || player == local) return null;
            var s = r.V2;
            // No goodwill, gift/day counters or mutable object identity. Grace
            // identifies alliance birth; breach counters distinguish a same-day
            // break/reform. A pact's kind and fixed expiry identify its period.
            bool offer = kind == DiplomacyV2RelationshipDecisionKind.AcceptAllianceOffer
                || kind == DiplomacyV2RelationshipDecisionKind.RejectAllianceOffer;
            int[] values = { 1, local, player, r.Allied ? 1 : 0, c.Allied ? 1 : 0,
                r.StartingAlliance ? 1 : 0, c.StartingAlly ? 1 : 0, r.AllianceGraceUntilDay,
                offer ? r.PendingOfferIssuedDay : -1, offer ? r.OfferAttemptCounter : 0,
                offer ? r.SpontaneousOfferBlockedUntilDay : 0,
                (int)s.Agreement, s.AgreementUntilDay, s.BrokenAgreements, s.ManualTreatyEnds,
                (int)s.VassalRole, s.VassalPlayerId, s.VassalOverlordPlayerId, s.VassalSinceDay, s.VassalReleases };
            return string.Join("|", values.Select(x => x.ToString(System.Globalization.CultureInfo.InvariantCulture)))
                + "|" + Roster(c);
        }

        internal static bool Stage(RelationState r, CoalitionState c, int local, int player,
            int day, DiplomacyV2RelationshipDecisionKind kind, string contract)
        {
            if (!Eligible(r, kind, day) || HasPending(r.V2) || string.IsNullOrEmpty(contract)
                || !string.Equals(contract, Contract(r, c, local, player, kind), StringComparison.Ordinal)) return false;
            r.V2.PendingRelationshipDecision = kind;
            r.V2.PendingRelationshipDecisionPlayerId = player;
            r.V2.PendingRelationshipDecisionDay = day;
            r.V2.PendingRelationshipDecisionContract = contract;
            return true;
        }

        internal static bool Matches(RelationState r, CoalitionState c, int local, int day)
        {
            return r != null && HasPending(r.V2) && Eligible(r, r.V2.PendingRelationshipDecision, day)
                && string.Equals(r.V2.PendingRelationshipDecisionContract,
                    Contract(r, c, local, r.V2.PendingRelationshipDecisionPlayerId, r.V2.PendingRelationshipDecision), StringComparison.Ordinal);
        }

        internal static void Validate(RelationState r, CoalitionState c, int local, int day)
        {
            var s = r.V2;
            if (!HasPending(s))
            {
                if (s.PendingRelationshipDecisionPlayerId != 0 || s.PendingRelationshipDecisionDay != -1
                    || s.PendingRelationshipDecisionContract != null)
                    throw new InvalidOperationException("Inactive relationship decision has data");
                return;
            }
            if (!Enum.IsDefined(typeof(DiplomacyV2RelationshipDecisionKind), s.PendingRelationshipDecision)
                || s.PendingRelationshipDecisionPlayerId == local
                || !c.MemberPlayerIds.Contains(s.PendingRelationshipDecisionPlayerId)
                || s.PendingRelationshipDecisionDay < 0 || s.PendingRelationshipDecisionDay > day)
                throw new InvalidOperationException("Relationship decision identity is invalid");
            string stamp = s.PendingRelationshipDecisionContract;
            if (string.IsNullOrEmpty(stamp) || stamp.Length > MaximumContractBytes)
                throw new InvalidOperationException("Relationship contract stamp length is invalid");
            string[] parts = stamp.Split('|');
            if (parts.Length != 21 || parts[20] != Roster(c))
                throw new InvalidOperationException("Relationship contract roster is invalid");
            int[] n = new int[20];
            for (int i = 0; i < n.Length; i++)
                if (!int.TryParse(parts[i], System.Globalization.NumberStyles.AllowLeadingSign,
                        System.Globalization.CultureInfo.InvariantCulture, out n[i])
                    || n[i].ToString(System.Globalization.CultureInfo.InvariantCulture) != parts[i]
                    || n[i] < ((i == 8 || i == 16 || i == 17 || i == 18) ? -1 : 0))
                    throw new InvalidOperationException("Relationship contract number is invalid");
            if (n[0] != 1 || n[1] != local || n[2] != s.PendingRelationshipDecisionPlayerId
                || n.Skip(3).Take(4).Any(x => x > 1)
                || !Enum.IsDefined(typeof(DiplomacyV2AgreementKind), n[11])
                || !Enum.IsDefined(typeof(DiplomacyV2VassalRole), n[15])
                || n[16] > 8 || n[17] > 8)
                throw new InvalidOperationException("Relationship contract identity is invalid");
            bool endingAlliance = s.PendingRelationshipDecision == DiplomacyV2RelationshipDecisionKind.EndAlliance;
            bool endingPact = s.PendingRelationshipDecision == DiplomacyV2RelationshipDecisionKind.EndAgreement;
            if (endingAlliance ? n[3] != 1 || n[4] != 1 || n[11] != (int)DiplomacyV2AgreementKind.Alliance
                : endingPact ? n[3] != 0 || n[4] != 0
                    || (n[11] != (int)DiplomacyV2AgreementKind.Truce && n[11] != (int)DiplomacyV2AgreementKind.TradePact)
                    || n[12] <= s.PendingRelationshipDecisionDay
                : n[3] != 0 || n[4] != 0 || n[8] < 0 || n[8] > s.PendingRelationshipDecisionDay)
                throw new InvalidOperationException("Relationship decision does not match its quoted contract");
            if (endingAlliance || endingPact)
            {
                if (n[8] != -1 || n[9] != 0 || n[10] != 0)
                    throw new InvalidOperationException("Contract end contains unrelated offer identity");
            }
            else if (n[9] < 1)
                throw new InvalidOperationException("Alliance answer has no quoted offer attempt");
            // A contract may expire or be broken while an inventory journal is
            // settling. Preserve a well-formed stale decision in the save; the
            // pump discards it via Matches, never authorizes a replacement.
        }
    }

}
#endif
