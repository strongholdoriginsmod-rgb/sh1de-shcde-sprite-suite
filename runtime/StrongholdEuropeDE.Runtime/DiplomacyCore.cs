using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal enum DiplomacyStatus
    {
        Rebuffing = 0,
        WillingToTalk = 1,
        Interested = 2,
        ReadyToAlly = 3,
        Allied = 4,
        Ultimatum = 5,
        Blocked = 6,
    }

    internal enum DiplomacyRequestOutcome
    {
        Rejected = 0,
        DemandIssued = 1,
        AllianceReady = 2,
        AllianceBlocked = 3,
        Locked = 4,
    }

    internal static class DiplomacyLogicalClock
    {
        // Diplomacy deadlines are measured in observed simulation-day
        // transitions, not in the game's raw calendar fields. Those fields
        // are reconstructed asynchronously while a save is loading and can
        // temporarily move both forwards and backwards. The logical counter
        // is embedded in the mod save and therefore resumes exactly once.
        internal const int NewSessionDay = 0;
        // Every persisted deadline is validated up to 365 days beyond the
        // current logical day. Keep a larger fixed reserve so those additions
        // and validation comparisons cannot wrap at the end of the counter.
        internal const int MaximumSupportedDay = int.MaxValue - 512;

        internal static bool IsValidSavedDay(int day)
        {
            return day >= NewSessionDay && day <= MaximumSupportedDay;
        }

        internal static int NextDay(int currentDay)
        {
            if (!IsValidSavedDay(currentDay)
                || currentDay == MaximumSupportedDay)
            {
                throw new InvalidOperationException(
                    "diplomacy logical calendar exhausted");
            }
            return checked(currentDay + 1);
        }
    }

    internal static class DiplomacyTransferReceipt
    {
        // 10.09.2026, aus einem Spiellauf: hier stand zusaetzlich
        //     recipientAfter == recipientBefore + amount
        // Der Empfaengerbestand gehoert aber einer laufenden Wirtschaft. Bei
        // einer Lieferung von 10 Armbruesten an einen Verbuendeten, der genau
        // dann Armbrustschuetzen ausbildete, wurde gemessen: Sender -10
        // (richtig), Empfaenger -2 statt +10. Der Abgleich erklaerte die
        // Sendung fuer gescheitert, die anschliessende Ruecknahme scheiterte
        // ebenfalls, und daraufhin sperrte der Mod jede weitere Guetersendung
        // fuer die restliche Partie. Ein Verbuendeter, der Truppen ausruestet,
        // ist kein Fehler.
        //
        // Geprueft wird deshalb nur noch die Belastung beim Sender: das ist das
        // Lager des Menschen, es aendert sich nicht von selbst zwischen zwei
        // Messungen desselben Vorgangs. Der Empfaenger geht nur noch als
        // Plausibilitaet ein (kein negativer Bestand). Bewusst in Kauf
        // genommen: verschluckt das Spiel eine Gutschrift, faellt das dem Mod
        // nicht mehr auf. Benutzerentscheidung vom 10.09.2026.
        internal static bool IsSenderDebitConfirmed(
            int senderBefore,
            int recipientBefore,
            int amount,
            int senderAfter,
            int recipientAfter)
        {
            if (senderBefore < 0
                || recipientBefore < 0
                || senderAfter < 0
                || recipientAfter < 0
                || amount <= 0)
            {
                return false;
            }
            return (long)senderAfter == (long)senderBefore - amount;
        }
    }

    internal sealed class DiplomacyRules
    {
        internal const int SchemaVersion = 1;

        internal int EconomyBuildingMaterialPercent = 25;
        internal int LordMilitaryValue = 250;
        internal int UnknownUnitHealthDivisor = 4;
        internal int UnknownUnitValueMinimum = 25;
        internal int UnknownUnitValueMaximum = 250;
        internal int TargetBaseValue = 350;
        internal int EconomyWeightBasisPoints = 800;
        internal int MilitaryWeightBasisPoints = 1400;
        internal int PersonalityBaseBasisPoints = 8000;
        internal int PersonalityMarginBasisPoints = 80;
        internal int TargetMinimum = 500;
        internal int TargetMaximum = 7500;
        internal int TargetRoundStep = 50;
        internal int GoodwillGraceDays = 5;
        internal int GoodwillDecayPercent = 2;
        internal int OfferBasePercent = 85;
        internal int OfferMarginTenthsPercent = 6;
        internal int OfferMinimumPercent = 25;
        internal int OfferMaximumPercent = 85;
        internal int OfferAdditionalGiftPercent = 5;
        internal int OfferRejectionLockDays = 5;
        internal int DemandLifetimeDays = 10;
        internal int MaximumDemandGoods = 3;
        internal int NewAllianceGraceDays = 10;
        internal int StartingAllianceGraceDays = 20;
        internal int LoyaltyBaseDecayBasisPoints = 50;
        internal int LoyaltyMarginDecayBasisPoints = 1;
        internal int UltimatumThresholdPercent = 35;
        internal int UltimatumRestorePercent = 60;
        internal int UltimatumLifetimeDays = 10;
        internal int BreakLockDays = 10;

        internal string Validate()
        {
            if (EconomyBuildingMaterialPercent < 0
                || EconomyBuildingMaterialPercent > 100)
            {
                return "economy building-material percentage is out of range";
            }
            if (LordMilitaryValue < 0
                || UnknownUnitHealthDivisor < 1
                || UnknownUnitValueMinimum < 0
                || UnknownUnitValueMaximum < UnknownUnitValueMinimum)
            {
                return "military fallback values are inconsistent";
            }
            if (TargetBaseValue < 0
                || EconomyWeightBasisPoints < 0
                || MilitaryWeightBasisPoints < 0
                || PersonalityBaseBasisPoints < 0
                || PersonalityMarginBasisPoints < 0)
            {
                return "target coefficients must not be negative";
            }
            if (TargetMinimum < 1
                || TargetMaximum < TargetMinimum
                || TargetRoundStep < 1
                || TargetMinimum % TargetRoundStep != 0
                || TargetMaximum % TargetRoundStep != 0)
            {
                return "target range and rounding step are inconsistent";
            }
            if (GoodwillGraceDays < 0
                || GoodwillDecayPercent < 0
                || GoodwillDecayPercent > 100
                || OfferBasePercent < 0
                || OfferMarginTenthsPercent < 0
                || OfferMinimumPercent < 0
                || OfferMaximumPercent > 100
                || OfferMinimumPercent > OfferMaximumPercent
                || OfferAdditionalGiftPercent < 0
                || OfferAdditionalGiftPercent > 100
                || OfferRejectionLockDays < 0)
            {
                return "goodwill or offer rules are inconsistent";
            }
            if (DemandLifetimeDays < 1
                || MaximumDemandGoods < 1
                || MaximumDemandGoods > 3
                || NewAllianceGraceDays < 0
                || StartingAllianceGraceDays < 0
                || LoyaltyBaseDecayBasisPoints < 0
                || LoyaltyMarginDecayBasisPoints < 0
                || UltimatumThresholdPercent < 0
                || UltimatumThresholdPercent > 100
                || UltimatumRestorePercent < UltimatumThresholdPercent
                || UltimatumRestorePercent > 100
                || UltimatumLifetimeDays < 1
                || BreakLockDays < 0)
            {
                return "demand, loyalty, ultimatum, or break rules are inconsistent";
            }
            return null;
        }
    }

    internal static class DiplomacyBalance
    {
        private const int NativeTradeBatchSize = 5;

        internal static int UnitValueFromBaseSellPrice(int baseSellPrice)
        {
            // Crusader's packed market base price is the proceeds for the
            // native five-unit trade batch. The one-unit Ctrl trade path uses
            // the same signed division before multiplying by the quantity.
            int unitValue = baseSellPrice / NativeTradeBatchSize;
            if (unitValue <= 0)
            {
                throw new InvalidOperationException(
                    "default sell price has no positive one-unit value");
            }
            return unitValue;
        }

        internal static int ClampMargin(int sendGoodsMargin)
        {
            return Math.Max(0, Math.Min(100, sendGoodsMargin));
        }

        internal static int UnknownUnitValue(
            int standardHealth,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            int value = Math.Max(0, standardHealth)
                / rules.UnknownUnitHealthDivisor;
            return Math.Max(
                rules.UnknownUnitValueMinimum,
                Math.Min(rules.UnknownUnitValueMaximum, value));
        }

        internal static int CalculateTarget(
            long economy,
            long military,
            int sendGoodsMargin,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            decimal safeEconomy = Math.Max(0L, economy);
            decimal safeMilitary = Math.Max(0L, military);
            int margin = ClampMargin(sendGoodsMargin);
            decimal weighted = rules.TargetBaseValue
                + safeEconomy * rules.EconomyWeightBasisPoints / 10000m
                + safeMilitary * rules.MilitaryWeightBasisPoints / 10000m;
            decimal personality = (
                rules.PersonalityBaseBasisPoints
                + margin * rules.PersonalityMarginBasisPoints) / 10000m;
            decimal raw = weighted * personality;
            decimal clamped = Math.Max(
                rules.TargetMinimum,
                Math.Min(rules.TargetMaximum, raw));
            decimal rounded = Math.Ceiling(clamped / rules.TargetRoundStep)
                * rules.TargetRoundStep;
            return decimal.ToInt32(rounded);
        }

        internal static DiplomacyStatus EnemyStatus(
            decimal goodwill,
            int target)
        {
            if (target < 1)
            {
                throw new ArgumentOutOfRangeException("target");
            }
            decimal percent = Math.Max(0m, goodwill) * 100m / target;
            if (percent < 25m)
            {
                return DiplomacyStatus.Rebuffing;
            }
            if (percent < 60m)
            {
                return DiplomacyStatus.WillingToTalk;
            }
            if (percent < 100m)
            {
                return DiplomacyStatus.Interested;
            }
            return DiplomacyStatus.ReadyToAlly;
        }

        internal static int OfferChanceTenthsPercent(
            int sendGoodsMargin,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            int raw = checked(
                rules.OfferBasePercent * 10
                - ClampMargin(sendGoodsMargin)
                    * rules.OfferMarginTenthsPercent);
            return Math.Max(
                rules.OfferMinimumPercent * 10,
                Math.Min(rules.OfferMaximumPercent * 10, raw));
        }

        internal static bool OfferRoll(
            string mapFingerprint,
            string coalitionId,
            int gameDay,
            int attempt,
            int chanceTenthsPercent)
        {
            if (string.IsNullOrEmpty(mapFingerprint)
                || string.IsNullOrEmpty(coalitionId)
                || gameDay < 0
                || attempt < 0
                || chanceTenthsPercent < 0
                || chanceTenthsPercent > 1000)
            {
                throw new ArgumentException("offer roll input is not canonical");
            }
            string material = mapFingerprint + "\n" + coalitionId + "\n"
                + gameDay.ToString(CultureInfo.InvariantCulture) + "\n"
                + attempt.ToString(CultureInfo.InvariantCulture);
            byte[] bytes = Encoding.UTF8.GetBytes(material);
            ulong hash = 14695981039346656037UL;
            for (int index = 0; index < bytes.Length; index++)
            {
                hash ^= bytes[index];
                hash *= 1099511628211UL;
            }
            int roll = (int)(hash % 1000UL);
            return roll < chanceTenthsPercent;
        }

        internal static decimal DecayEnemyGoodwill(
            decimal goodwill,
            int daysSinceGift,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            decimal current = Math.Max(0m, goodwill);
            if (current == 0m || daysSinceGift <= rules.GoodwillGraceDays)
            {
                return current;
            }
            decimal loss = Math.Max(
                1m,
                decimal.Floor(current * rules.GoodwillDecayPercent / 100m));
            return Math.Max(0m, current - loss);
        }

        internal static decimal LoyaltyDailyLoss(
            int target,
            int sendGoodsMargin,
            DiplomacyRules rules)
        {
            RequireRules(rules);
            if (target < 0)
            {
                throw new ArgumentOutOfRangeException("target");
            }
            int basisPoints = rules.LoyaltyBaseDecayBasisPoints
                + ClampMargin(sendGoodsMargin)
                * rules.LoyaltyMarginDecayBasisPoints;
            return target * basisPoints / 10000m;
        }

        internal static decimal GiftValue(
            int goodId,
            int amount,
            IReadOnlyDictionary<int, int> frozenPrices)
        {
            if (amount <= 0 || frozenPrices == null)
            {
                throw new ArgumentOutOfRangeException("amount");
            }
            int unitValue;
            if (!frozenPrices.TryGetValue(goodId, out unitValue)
                || unitValue <= 0)
            {
                throw new InvalidOperationException(
                    "good has no positive frozen diplomacy value: " + goodId);
            }
            return checked((decimal)amount * unitValue);
        }

        private static void RequireRules(DiplomacyRules rules)
        {
            if (rules == null)
            {
                throw new ArgumentNullException("rules");
            }
            string failure = rules.Validate();
            if (failure != null)
            {
                throw new InvalidOperationException(failure);
            }
        }
    }

    internal sealed class CoalitionState
    {
        internal string CoalitionId;
        internal int[] MemberPlayerIds = new int[0];
        internal int[] OriginalTeams = new int[0];
        internal int SendGoodsMargin;
        internal long Economy;
        internal long Military;
        internal int Target;
        internal bool StartingAlly;
        internal bool Allied;
    }

    internal sealed class DemandItem
    {
        internal int GoodId;
        internal int UnitValue;
        internal int RequiredAmount;
        internal int DeliveredAmount;

        internal int RemainingAmount
        {
            get { return Math.Max(0, RequiredAmount - DeliveredAmount); }
        }
    }

    internal sealed class GoodsDemand
    {
        internal int IssuedDay;
        internal int ExpiresDay;
        internal bool IsUltimatum;
        internal DemandItem[] Items = new DemandItem[0];
#if DIPLOMACY_V2
        internal DiplomacyV2DemandPurpose V2Purpose;
        internal int V2Urgency;
#endif

        internal bool Complete
        {
            get
            {
                return Items != null
                    && Items.Length > 0
                    && Items.All(item => item != null && item.RemainingAmount == 0);
            }
        }

        internal int ApplyDelivery(int goodId, int amount)
        {
            if (amount <= 0 || Items == null)
            {
                return 0;
            }
            DemandItem item = Items.FirstOrDefault(value =>
                value != null && value.GoodId == goodId);
            if (item == null)
            {
                return 0;
            }
            int accepted = Math.Min(amount, item.RemainingAmount);
            item.DeliveredAmount = checked(item.DeliveredAmount + accepted);
            return accepted;
        }

        internal decimal RemainingValue()
        {
            if (Items == null)
            {
                return 0m;
            }
            decimal total = 0m;
            foreach (DemandItem item in Items)
            {
                if (item != null && item.UnitValue > 0)
                {
                    total += (decimal)item.RemainingAmount * item.UnitValue;
                }
            }
            return total;
        }
    }

    internal sealed class GoodNeed
    {
        internal int GoodId;
        internal decimal RelativeNeed;
        internal int UnitValue;
    }

    internal static class DiplomacyDemandPlanner
    {
        internal static GoodsDemand Create(
            decimal valueGap,
            IEnumerable<GoodNeed> needs,
            int gameDay,
            bool ultimatum,
            DiplomacyRules rules)
        {
            if (valueGap <= 0m)
            {
                throw new ArgumentOutOfRangeException("valueGap");
            }
            if (needs == null)
            {
                throw new ArgumentNullException("needs");
            }
            if (rules == null || rules.Validate() != null)
            {
                throw new InvalidOperationException("diplomacy rules are invalid");
            }
            GoodNeed[] selected = needs
                .Where(value => value != null
                    && value.GoodId > 0
                    && value.UnitValue > 0
                    && value.RelativeNeed > 0m)
                .GroupBy(value => value.GoodId)
                .Select(group => new GoodNeed
                {
                    GoodId = group.Key,
                    UnitValue = group.First().UnitValue,
                    RelativeNeed = group.Sum(value => value.RelativeNeed),
                })
                .OrderByDescending(value => value.RelativeNeed)
                .ThenBy(value => value.GoodId)
                .Take(rules.MaximumDemandGoods)
                .ToArray();
            if (selected.Length == 0)
            {
                throw new InvalidOperationException("coalition has no usable AIC need");
            }
            int[] shares = selected.Length == 1
                ? new[] { 100 }
                : selected.Length == 2
                    ? new[] { 60, 40 }
                    : new[] { 50, 30, 20 };
            var items = new DemandItem[selected.Length];
            decimal assignedValue = 0m;
            for (int index = 0; index < selected.Length; index++)
            {
                decimal shareValue = valueGap * shares[index] / 100m;
                int amount = decimal.ToInt32(decimal.Ceiling(
                    shareValue / selected[index].UnitValue));
                amount = Math.Max(1, amount);
                items[index] = new DemandItem
                {
                    GoodId = selected[index].GoodId,
                    UnitValue = selected[index].UnitValue,
                    RequiredAmount = amount,
                };
                assignedValue += (decimal)amount * selected[index].UnitValue;
            }
            if (assignedValue < valueGap)
            {
                DemandItem first = items[0];
                int extra = decimal.ToInt32(decimal.Ceiling(
                    (valueGap - assignedValue) / first.UnitValue));
                first.RequiredAmount = checked(first.RequiredAmount + extra);
            }
            return new GoodsDemand
            {
                IssuedDay = gameDay,
                ExpiresDay = checked(gameDay + (ultimatum
                    ? rules.UltimatumLifetimeDays
                    : rules.DemandLifetimeDays)),
                IsUltimatum = ultimatum,
                Items = items,
            };
        }
    }

    internal sealed class RelationState
    {
        internal string CoalitionId;
        internal decimal Goodwill;
        internal int LastGiftDay = -1;
        internal int LastProcessedDay = -1;
        internal int LastOfferAttemptDay = -1;
        internal int OfferAttemptCounter;
        internal decimal GiftValueSinceOfferAttempt;
        internal int SpontaneousOfferBlockedUntilDay;
        internal int RelationshipBlockedUntilDay;
        internal int AllianceGraceUntilDay;
        internal GoodsDemand Demand;
        internal bool PendingOffer;
        internal int PendingOfferIssuedDay = -1;
        internal bool Allied;
        internal bool StartingAlliance;
#if DIPLOMACY_V2
        internal DiplomacyV2RelationState V2;
#endif
    }

    internal sealed class DiplomacyRequestResult
    {
        internal DiplomacyRequestOutcome Outcome;
        internal GoodsDemand Demand;
    }

    internal static class DiplomacyStateMachine
    {
        internal static bool RecordGift(
            RelationState relation,
            int gameDay,
            decimal giftValue,
            int target,
            int margin,
            string mapFingerprint,
            DiplomacyRules rules)
        {
            RequireRelation(relation, gameDay, target, rules);
            if (giftValue <= 0m)
            {
                throw new ArgumentOutOfRangeException("giftValue");
            }
            RecordGiftWithoutOffer(relation, gameDay, giftValue);
            if (relation.Demand != null)
            {
                return false;
            }
            if (relation.Allied
                || relation.PendingOffer
                || relation.Goodwill < target
                || gameDay < relation.SpontaneousOfferBlockedUntilDay
                || relation.LastOfferAttemptDay == gameDay)
            {
                return false;
            }
            decimal minimumAdditional = target
                * rules.OfferAdditionalGiftPercent / 100m;
            if (relation.OfferAttemptCounter > 0
                && relation.GiftValueSinceOfferAttempt < minimumAdditional)
            {
                return false;
            }
            relation.LastOfferAttemptDay = gameDay;
            int attempt = relation.OfferAttemptCounter++;
            relation.GiftValueSinceOfferAttempt = 0m;
            return DiplomacyBalance.OfferRoll(
                mapFingerprint,
                relation.CoalitionId,
                gameDay,
                attempt,
                DiplomacyBalance.OfferChanceTenthsPercent(margin, rules));
        }

        internal static void RecordGiftWithoutOffer(
            RelationState relation,
            int gameDay,
            decimal giftValue)
        {
            if (relation == null)
            {
                throw new ArgumentNullException("relation");
            }
            if (string.IsNullOrEmpty(relation.CoalitionId) || gameDay < 0)
            {
                throw new InvalidOperationException(
                    "gift relation identity or day is invalid");
            }
            if (giftValue <= 0m)
            {
                throw new ArgumentOutOfRangeException("giftValue");
            }
            relation.Goodwill += giftValue;
            relation.LastGiftDay = gameDay;
            relation.GiftValueSinceOfferAttempt += giftValue;
        }

        internal static void RejectSpontaneousOffer(
            RelationState relation,
            int gameDay,
            DiplomacyRules rules)
        {
            if (relation == null || rules == null)
            {
                throw new ArgumentNullException("relation");
            }
            relation.SpontaneousOfferBlockedUntilDay = checked(
                gameDay + rules.OfferRejectionLockDays);
        }

        internal static DiplomacyRequestResult RequestAlliance(
            RelationState relation,
            int gameDay,
            int target,
            bool hostileCoalitionWouldRemain,
            IEnumerable<GoodNeed> needs,
            DiplomacyRules rules)
        {
            RequireRelation(relation, gameDay, target, rules);
            if (relation.Allied)
            {
                throw new InvalidOperationException(
                    "an allied relation cannot request another alliance");
            }
            if (gameDay < relation.RelationshipBlockedUntilDay)
            {
                return new DiplomacyRequestResult
                {
                    Outcome = DiplomacyRequestOutcome.Locked,
                };
            }
            if (relation.PendingOffer)
            {
                return new DiplomacyRequestResult
                {
                    Outcome = DiplomacyRequestOutcome.Locked,
                };
            }
            if (!hostileCoalitionWouldRemain)
            {
                relation.Demand = null;
                return new DiplomacyRequestResult
                {
                    Outcome = DiplomacyRequestOutcome.AllianceBlocked,
                };
            }
            if (relation.Demand != null)
            {
                if (!relation.Demand.IsUltimatum
                    && gameDay >= relation.Demand.ExpiresDay)
                {
                    relation.Demand = null;
                }
                else
                {
                    return new DiplomacyRequestResult
                    {
                        Outcome = DiplomacyRequestOutcome.DemandIssued,
                        Demand = relation.Demand,
                    };
                }
            }
            DiplomacyStatus status = DiplomacyBalance.EnemyStatus(
                relation.Goodwill,
                target);
            if (status == DiplomacyStatus.Rebuffing)
            {
                return new DiplomacyRequestResult
                {
                    Outcome = DiplomacyRequestOutcome.Rejected,
                };
            }
            if (status == DiplomacyStatus.ReadyToAlly)
            {
                return new DiplomacyRequestResult
                {
                    Outcome = DiplomacyRequestOutcome.AllianceReady,
                };
            }
            decimal gap = Math.Max(1m, target - relation.Goodwill);
            relation.Demand = DiplomacyDemandPlanner.Create(
                gap,
                needs,
                gameDay,
                false,
                rules);
            return new DiplomacyRequestResult
            {
                Outcome = DiplomacyRequestOutcome.DemandIssued,
                Demand = relation.Demand,
            };
        }

        internal static void BeginAlliance(
            RelationState relation,
            int gameDay,
            bool startingAlliance,
            DiplomacyRules rules)
        {
            if (relation == null || rules == null)
            {
                throw new ArgumentNullException("relation");
            }
            relation.Allied = true;
            relation.StartingAlliance = startingAlliance;
            relation.Demand = null;
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            relation.AllianceGraceUntilDay = checked(gameDay + (
                startingAlliance
                    ? rules.StartingAllianceGraceDays
                    : rules.NewAllianceGraceDays));
        }

        internal static bool CompleteDemand(
            RelationState relation,
            int target,
            DiplomacyRules rules)
        {
            if (relation == null || rules == null)
            {
                throw new ArgumentNullException("relation");
            }
            if (target < 1 || relation.Demand == null
                || !relation.Demand.Complete)
            {
                throw new InvalidOperationException(
                    "only a complete diplomacy demand can be completed");
            }
            bool ultimatum = relation.Demand.IsUltimatum;
            relation.Demand = null;
            if (ultimatum)
            {
                relation.Goodwill = Math.Max(
                    relation.Goodwill,
                    target * rules.UltimatumRestorePercent / 100m);
            }
            return ultimatum;
        }

        internal static void BreakAlliance(
            RelationState relation,
            int gameDay,
            DiplomacyRules rules)
        {
            if (relation == null || rules == null)
            {
                throw new ArgumentNullException("relation");
            }
            relation.Allied = false;
            relation.StartingAlliance = false;
            relation.Goodwill = 0m;
            relation.Demand = null;
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            relation.RelationshipBlockedUntilDay = checked(
                gameDay + rules.BreakLockDays);
            relation.SpontaneousOfferBlockedUntilDay =
                relation.RelationshipBlockedUntilDay;
            relation.GiftValueSinceOfferAttempt = 0m;
        }

        internal static void BeginPendingOffer(
            RelationState relation,
            int gameDay)
        {
            if (relation == null)
            {
                throw new ArgumentNullException("relation");
            }
            if (relation.Allied
                || relation.Demand != null
                || relation.PendingOffer
                || gameDay < 0)
            {
                throw new InvalidOperationException(
                    "only an idle hostile relation can open an offer");
            }
            relation.PendingOffer = true;
            relation.PendingOfferIssuedDay = gameDay;
        }

        internal static void RejectPendingOffer(
            RelationState relation,
            int gameDay,
            DiplomacyRules rules)
        {
            if (relation == null || !relation.PendingOffer)
            {
                throw new InvalidOperationException(
                    "no pending offer can be rejected");
            }
            relation.PendingOffer = false;
            relation.PendingOfferIssuedDay = -1;
            RejectSpontaneousOffer(relation, gameDay, rules);
        }

        internal static bool ProcessDay(
            RelationState relation,
            int gameDay,
            int target,
            int margin,
            IEnumerable<GoodNeed> ultimatumNeeds,
            DiplomacyRules rules)
        {
            RequireRelation(relation, gameDay, target, rules);
            if (gameDay <= relation.LastProcessedDay)
            {
                return false;
            }
            int first = Math.Max(0, relation.LastProcessedDay + 1);
            bool allianceExpired = false;
            for (int day = first; day <= gameDay; day++)
            {
                if (!relation.Allied)
                {
                    int daysSinceGift = relation.LastGiftDay < 0
                        ? int.MaxValue
                        : day - relation.LastGiftDay;
                    relation.Goodwill = DiplomacyBalance.DecayEnemyGoodwill(
                        relation.Goodwill,
                        daysSinceGift,
                        rules);
                    if (relation.Demand != null
                        && !relation.Demand.IsUltimatum
                        && day >= relation.Demand.ExpiresDay)
                    {
                        relation.Demand = null;
                    }
                    continue;
                }
                if (day > relation.AllianceGraceUntilDay)
                {
                    relation.Goodwill = Math.Max(
                        0m,
                        relation.Goodwill
                            - DiplomacyBalance.LoyaltyDailyLoss(
                                target,
                                margin,
                                rules));
                }
                if (relation.Demand != null
                    && relation.Demand.IsUltimatum
                    && day >= relation.Demand.ExpiresDay
                    && !relation.Demand.Complete)
                {
                    allianceExpired = true;
                    break;
                }
                decimal threshold = target
                    * rules.UltimatumThresholdPercent / 100m;
                if (relation.Demand == null
                    && day > relation.AllianceGraceUntilDay
                    && relation.Goodwill < threshold)
                {
                    decimal restore = target
                        * rules.UltimatumRestorePercent / 100m;
                    relation.Demand = DiplomacyDemandPlanner.Create(
                        Math.Max(1m, restore - relation.Goodwill),
                        ultimatumNeeds,
                        day,
                        true,
                        rules);
                }
            }
            relation.LastProcessedDay = gameDay;
            return allianceExpired;
        }

        private static void RequireRelation(
            RelationState relation,
            int gameDay,
            int target,
            DiplomacyRules rules)
        {
            if (relation == null)
            {
                throw new ArgumentNullException("relation");
            }
            if (string.IsNullOrEmpty(relation.CoalitionId))
            {
                throw new InvalidOperationException(
                    "relation has no coalition identifier");
            }
            if (gameDay < 0 || target < 1)
            {
                throw new ArgumentOutOfRangeException("gameDay");
            }
            if (rules == null || rules.Validate() != null)
            {
                throw new InvalidOperationException("diplomacy rules are invalid");
            }
        }
    }

    internal sealed class DiplomacySaveV1
    {
        internal int SchemaVersion = DiplomacyRules.SchemaVersion;
        internal string MapFingerprint;
        internal string RosterFingerprint;
        internal int LocalPlayerId;
        internal int LastProcessedDay;
        // V2 envelope extension; the unchanged V1 payload does not carry it.
        internal long NativeDayAnchor = -1L;
        internal Dictionary<int, int> FrozenPrices = new Dictionary<int, int>();
        internal List<CoalitionState> Coalitions = new List<CoalitionState>();
        internal List<RelationState> Relations = new List<RelationState>();
        internal Dictionary<int, int> TeamPartition = new Dictionary<int, int>();
        internal Dictionary<int, int> OriginalTeamPartition =
            new Dictionary<int, int>();
        internal DiplomacyPendingTransfer PendingTransfer;
        internal DiplomacyPendingPackage PendingPackage;
        internal DiplomacyPendingTeamTransition PendingTeamTransition;
#if DIPLOMACY_V2
        // V2 schema 14: authoritative, bounded multilateral exchange offers
        // and exact four-cell native settlement / rollback journal.
        internal DiplomacyV2TradeBook TradeBook;
#endif
    }

    internal sealed class DiplomacyPendingTransfer
    {
        // Zero is the legacy representation of the local player.
        internal int SenderPlayer;
        internal int TargetPlayer;
        internal int GoodId;
        internal int Amount;
        internal int SenderBefore;
        internal int RecipientBefore;
        internal bool AlliedNativeTransfer;
        internal DiplomacyTransferPurpose Purpose;
        internal bool DirectAtomicTransfer;
        internal int GameDay = -1;
        // Schema 8: an aborted operation may only undo its own observed writes.
        internal bool RollbackPending;
        internal DiplomacyTransferProgress Progress;
    }

    internal sealed class DiplomacyTransferProgress
    {
        internal bool SenderTouched;
        internal bool RecipientTouched;
        internal bool SenderObserved;
        internal bool RecipientObserved;
        internal int SenderAfter;
        internal int RecipientAfter;
    }

    internal sealed class DiplomacyPendingPackage
    {
        internal int SenderPlayer;
        internal int TargetPlayer;
        internal int GameDay;
        internal bool RollbackPending;
        internal List<DiplomacyPendingTransfer> Lines = new List<DiplomacyPendingTransfer>();
    }

    internal enum DiplomacyTransferPurpose
    {
        Gift = 0,
        Tribute = 1,
    }

    internal enum DiplomacyTransferJournalDisposition
    {
        Unchanged = 0,
        FullyApplied = 1,
        SenderDebitedOnly = 2,
        RecipientCreditedOnly = 3,
        Conflict = 4,
    }

    internal enum DiplomacyTeamJournalDisposition
    {
        Expected = 0,
        TargetApplied = 1,
        Conflict = 2,
    }

    /// <summary>
    /// Classifies native state captured around a mod-save callback. The game
    /// writes its own save and each mod payload in adjacent, but not formally
    /// atomic, steps. A journal therefore has to accept the exact state before
    /// an operation, the exact state after it, and (for a two-sided goods
    /// transfer) either exact half-state. Anything else is an external or
    /// corrupt mutation and remains fail-closed.
    /// </summary>
    internal static class DiplomacyJournalRecovery
    {
        internal static DiplomacyTransferJournalDisposition ClassifyTransfer(
            DiplomacyPendingTransfer transfer,
            int senderAmount,
            int recipientAmount)
        {
            if (transfer == null
                || transfer.Amount < 1
                || transfer.SenderBefore < transfer.Amount
                || transfer.RecipientBefore < 0
                || transfer.RecipientBefore > int.MaxValue - transfer.Amount)
            {
                return DiplomacyTransferJournalDisposition.Conflict;
            }

            int senderApplied = transfer.SenderBefore - transfer.Amount;
            int recipientApplied = transfer.RecipientBefore + transfer.Amount;
            bool senderUnchanged = senderAmount == transfer.SenderBefore;
            bool senderDebited = senderAmount == senderApplied;
            bool recipientUnchanged = recipientAmount == transfer.RecipientBefore;
            bool recipientCredited = recipientAmount == recipientApplied;
            if (senderUnchanged && recipientUnchanged)
            {
                return DiplomacyTransferJournalDisposition.Unchanged;
            }
            if (senderDebited && recipientCredited)
            {
                return DiplomacyTransferJournalDisposition.FullyApplied;
            }
            if (senderDebited && recipientUnchanged)
            {
                return DiplomacyTransferJournalDisposition.SenderDebitedOnly;
            }
            if (senderUnchanged && recipientCredited)
            {
                return DiplomacyTransferJournalDisposition.RecipientCreditedOnly;
            }
            return DiplomacyTransferJournalDisposition.Conflict;
        }

        internal static DiplomacyTeamJournalDisposition ClassifyTeamTransition(
            IReadOnlyDictionary<int, int> livePartition,
            DiplomacyPendingTeamTransition transition)
        {
            if (transition == null
                || livePartition == null
                || transition.ExpectedPartition == null
                || transition.TargetPartition == null)
            {
                return DiplomacyTeamJournalDisposition.Conflict;
            }
            if (PartitionEquals(
                    livePartition,
                    transition.ExpectedPartition))
            {
                return DiplomacyTeamJournalDisposition.Expected;
            }
            if (PartitionEquals(
                    livePartition,
                    transition.TargetPartition))
            {
                return DiplomacyTeamJournalDisposition.TargetApplied;
            }
            return DiplomacyTeamJournalDisposition.Conflict;
        }

        private static bool PartitionEquals(
            IReadOnlyDictionary<int, int> left,
            IReadOnlyDictionary<int, int> right)
        {
            if (left == null || right == null || left.Count != right.Count)
            {
                return false;
            }
            foreach (KeyValuePair<int, int> entry in left)
            {
                int value;
                if (!right.TryGetValue(entry.Key, out value)
                    || value != entry.Value)
                {
                    return false;
                }
            }
            return true;
        }
    }

    internal enum DiplomacyTeamTransitionKind
    {
        FormAlliance = 1,
        AiBreak = 2,
        PlayerBreakAll = 3,
#if DIPLOMACY_V2
        // V1 exposes Crusader's historical "end every alliance" action.
        // V2's relationship panel acts on the selected coalition instead.
        PlayerBreakOne = 4,
#endif
    }

    internal sealed class DiplomacyPendingTeamTransition
    {
        internal DiplomacyTeamTransitionKind Kind;
        internal string CoalitionId;
        internal int GameDay;
        internal string Reason;
        internal Dictionary<int, int> ExpectedPartition =
            new Dictionary<int, int>();
        internal Dictionary<int, int> TargetPartition =
            new Dictionary<int, int>();
    }

    internal interface IDiplomacyTeamPort
    {
        int GetTeam(int playerId);

        void SetTeam(int playerId, int team);
    }

    internal sealed class TeamTransactionResult
    {
        internal bool Applied;
        internal string Failure;
        internal IReadOnlyDictionary<int, int> OriginalTeams;
        internal IReadOnlyDictionary<int, int> ResidualAssignments;
    }

    internal static class DiplomacyTeamTransaction
    {
        internal static TeamTransactionResult Apply(
            IDiplomacyTeamPort port,
            IReadOnlyDictionary<int, int> targetPartition)
        {
            return ApplyExact(port, targetPartition, false);
        }

        internal static TeamTransactionResult RestoreExpected(
            IDiplomacyTeamPort port,
            IReadOnlyDictionary<int, int> expectedPartition)
        {
            return ApplyExact(port, expectedPartition, true);
        }

        private static TeamTransactionResult ApplyExact(
            IDiplomacyTeamPort port,
            IReadOnlyDictionary<int, int> targetPartition,
            bool allowTeamZero)
        {
            if (port == null)
            {
                throw new ArgumentNullException("port");
            }
            if (targetPartition == null || targetPartition.Count == 0)
            {
                return Failed("target team partition is empty", null);
            }
            var original = new SortedDictionary<int, int>();
            var assigned = new SortedDictionary<int, int>();
            try
            {
                foreach (KeyValuePair<int, int> entry in targetPartition
                    .OrderBy(value => value.Key))
                {
                    if (entry.Key < 1 || entry.Key > 8
                        || entry.Value < (allowTeamZero ? 0 : 1)
                        || entry.Value > 8)
                    {
                        return Failed(
                            "team partition contains an out-of-range player or team",
                            original);
                    }
                    original.Add(entry.Key, port.GetTeam(entry.Key));
                }
            }
            catch (Exception exception)
            {
                return Failed(
                    "team snapshot failed: "
                    + exception.GetType().Name + ": "
                    + Safe(exception.Message),
                    original);
            }
            try
            {
                foreach (KeyValuePair<int, int> entry in targetPartition
                    .OrderBy(value => value.Key))
                {
                    assigned.Add(entry.Key, entry.Value);
                    port.SetTeam(entry.Key, entry.Value);
                }
                foreach (KeyValuePair<int, int> entry in assigned)
                {
                    if (port.GetTeam(entry.Key) != entry.Value)
                    {
                        throw new InvalidOperationException(
                            "team readback mismatch for player " + entry.Key);
                    }
                }
                return new TeamTransactionResult
                {
                    Applied = true,
                    OriginalTeams = original,
                    ResidualAssignments =
                        new SortedDictionary<int, int>(),
                };
            }
            catch (Exception exception)
            {
                string rollbackFailure = RollbackOwned(port, assigned, original);
                string residualFailure;
                IReadOnlyDictionary<int, int> residual =
                    CaptureResidualAssignments(
                        port,
                        assigned,
                        original,
                        out residualFailure);
                string failure = exception.GetType().Name + ": "
                    + Safe(exception.Message);
                if (rollbackFailure != null)
                {
                    failure += "; rollback: " + rollbackFailure;
                }
                if (residualFailure != null)
                {
                    failure += "; residual: " + residualFailure;
                }
                return Failed(failure, original, residual);
            }
        }

        private static IReadOnlyDictionary<int, int>
            CaptureResidualAssignments(
                IDiplomacyTeamPort port,
                IReadOnlyDictionary<int, int> assigned,
                IReadOnlyDictionary<int, int> original,
                out string failure)
        {
            var residual = new SortedDictionary<int, int>();
            var failures = new List<string>();
            foreach (KeyValuePair<int, int> entry in assigned)
            {
                int current;
                try
                {
                    current = port.GetTeam(entry.Key);
                }
                catch (Exception exception)
                {
                    // The attempted value remains conservatively owned. A
                    // later ownership-checked rollback will still refuse to
                    // overwrite a foreign value.
                    residual[entry.Key] = entry.Value;
                    failures.Add(
                        "read player " + entry.Key + " "
                        + exception.GetType().Name);
                    continue;
                }
                int before;
                if (current == entry.Value
                    && (!original.TryGetValue(entry.Key, out before)
                        || current != before))
                {
                    residual[entry.Key] = entry.Value;
                }
            }
            failure = failures.Count == 0
                ? null
                : string.Join(",", failures);
            return residual;
        }

        internal static string RollbackOwned(
            IDiplomacyTeamPort port,
            IReadOnlyDictionary<int, int> assigned,
            IReadOnlyDictionary<int, int> original)
        {
            if (port == null || assigned == null || original == null)
            {
                return "rollback input is incomplete";
            }
            var failures = new List<string>();
            foreach (KeyValuePair<int, int> entry in assigned
                .OrderByDescending(value => value.Key))
            {
                int before;
                if (!original.TryGetValue(entry.Key, out before))
                {
                    failures.Add("missing original team for player " + entry.Key);
                    continue;
                }
                int current;
                try
                {
                    current = port.GetTeam(entry.Key);
                }
                catch (Exception exception)
                {
                    failures.Add(
                        "ownership read player " + entry.Key + " "
                        + exception.GetType().Name);
                    continue;
                }
                if (current != entry.Value)
                {
                    continue;
                }
                try
                {
                    port.SetTeam(entry.Key, before);
                    if (port.GetTeam(entry.Key) != before)
                    {
                        failures.Add("readback mismatch for player " + entry.Key);
                    }
                }
                catch (Exception exception)
                {
                    failures.Add(
                        "player " + entry.Key + " "
                        + exception.GetType().Name);
                }
            }
            return failures.Count == 0 ? null : string.Join(",", failures);
        }

        private static TeamTransactionResult Failed(
            string failure,
            IReadOnlyDictionary<int, int> original,
            IReadOnlyDictionary<int, int> residual = null)
        {
            return new TeamTransactionResult
            {
                Applied = false,
                Failure = Safe(failure),
                OriginalTeams = original,
                ResidualAssignments = residual
                    ?? new SortedDictionary<int, int>(),
            };
        }

        private static string Safe(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "unspecified";
            }
            return value.Replace('|', ' ').Replace('\r', ' ').Replace('\n', ' ');
        }
    }
}
