#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Threading;
using CrusaderDE;
using SHCDESE.API;
using SHCDESE.API.Components.SaveData;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.AI;
using SHCDESE.EventAPI.Tribes;
using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private sealed class V2DemandPackageLine
        {
            internal int GoodId;
            internal int Amount;
            internal int SenderBefore;
            internal int RecipientBefore;
        }

        private sealed class V2WorldForceUnit
        {
            internal int X;
            internal int Y;
            internal long MilitaryValue;
        }

        /// <summary>Kernzone eines Fuersten (Burgtor, Weltkoordinaten) und
        /// die Vertragsseite, der er angehoert.</summary>
        private sealed class V2TreatyZone
        {
            internal int Owner;
            internal int X;
            internal int Y;
            internal bool LocalBloc;
            internal DiplomacyCastleBoundary Boundary;
        }

        private sealed class V2TribeRecall
        {
            internal int Owner;
            internal uint GlobalId;
            internal V2TreatyZone Home;
        }

        private readonly HashSet<string> _v2PendingAgreementSafety =
            new HashSet<string>(StringComparer.Ordinal);

        private sealed class V2CounterpartHit
        {
            internal int Owner;
            internal long Distance;
            internal bool Treaty;
        }

        // A full unit catalogue traversal is deliberately throttled. At the
        // native simulation cadence 32 ticks still reacts within roughly one
        // second, while avoiding several map-wide scans per rendered frame.
        private const int V2IncursionScanIntervalTicks = 32;
        // Zonenradius und Staerkeschwellen: DiplomacyV2CombatRules (rein,
        // im Pruefstand gegen Zahlen geprueft - 06.09.2026).

        private bool _v2LegacySaveHandlerRegistered;
        private byte[] _v2PendingLegacySavePayload;
        private long _v2PendingLegacySaveEpoch = -1;
        private long _v2PendingLegacySaveTick = -1;
        private long _v2LocalPowerTick = long.MinValue;
        private long _v2LocalEconomy;
        private long _v2LocalMilitary;
        private long _v2LastIncursionScanTick =
            DiplomacyV2CombatRules.NeverScannedTick;
        private long _v2LastHostileAttributionTick =
            DiplomacyV2CombatRules.NeverScannedTick;
        // Abstandsgebot der Waffenruhe (06.09.2026): Kernzonen beider
        // Vertragsseiten, Rueckrufzeiten je Stamm, Protokollbudget.
        private readonly List<V2TreatyZone> _v2TreatyZones =
            new List<V2TreatyZone>();
        private readonly Dictionary<int, long> _v2TribeRecallTicks =
            new Dictionary<int, long>();
        private bool _v2TreatyStandoffActive;
        private bool _v2TreatyStandoffDegraded;
        private long _v2StandoffRetryTick;
        private int _v2StandoffFaultsPending;
        private int _v2IncursionLogLines;
        private int _v2StandoffMovesBlocked;
        private int _v2StandoffLogLines;
        private bool _v2UiPanelWarningLogged;

        private void InitializeV2Relation(
            RelationState relation,
            CoalitionState coalition,
            int gameDay)
        {
            DiplomacyV2PersonalitySignal signal =
                SelectV2CoalitionPersonalitySignal(coalition);
            DiplomacyV2Personality profile =
                DiplomacyV2PersonalityCatalog.SelectForLord(signal);
            DiplomacyV2StateMachine.Initialize(
                relation,
                gameDay,
                coalition.Target,
                profile.Kind,
                signal.LordId,
                coalition.StartingAlly);
        }

        private DiplomacyV2PersonalitySignal
            SelectV2CoalitionPersonalitySignal(CoalitionState coalition)
        {
            int primaryLord = -1;
            int margin = -1;
            int selectedPlayer = int.MaxValue;
            InternalAIC selectedAic = default(InternalAIC);
            int aicCount = ScriptExtenderNativeBridge.AicCount();
            foreach (int player in coalition.MemberPlayerIds.OrderBy(
                value => value))
            {
                int lord;
                if (!_capturedLordIds.TryGetValue(player, out lord)
                    || lord < 0
                    || lord >= aicCount)
                {
                    continue;
                }
                InternalAIC aic = ScriptExtenderNativeBridge.Aic(lord);
                int candidateMargin = DiplomacyBalance.ClampMargin(
                    aic.send_goods_margin);
                if (candidateMargin > margin
                    || candidateMargin == margin && player < selectedPlayer)
                {
                    margin = candidateMargin;
                    primaryLord = lord;
                    selectedPlayer = player;
                    selectedAic = aic;
                }
            }
            if (primaryLord < 0)
            {
                throw new InvalidOperationException(
                    "diplomacy V2 coalition has no personality signal");
            }
            int commerce = PositiveAverage(
                selectedAic.buy_apples_at,
                selectedAic.buy_cheese_at,
                selectedAic.buy_bread_at,
                selectedAic.buy_wheat_at,
                selectedAic.buy_hops_at,
                selectedAic.trade_wood_at,
                selectedAic.trade_stone_at,
                selectedAic.trade_resources_at,
                selectedAic.trade_flour_at,
                selectedAic.trade_ale_at,
                selectedAic.trade_pitch_at);
            int defensiveChance = AverageIncludingZero(
                selectedAic.chance_of_defensive1,
                selectedAic.chance_of_defensive2,
                selectedAic.chance_of_defensive3);
            int harassChance = AverageIncludingZero(
                selectedAic.chance_of_harrasment1,
                selectedAic.chance_of_harrasment2,
                selectedAic.chance_of_harrasment3);
            int siegeChance = AverageIncludingZero(
                selectedAic.chance_of_seiging1,
                selectedAic.chance_of_seiging2,
                selectedAic.chance_of_seiging3);
            int offensivePeak = new[]
            {
                selectedAic.chance_of_harrasment1,
                selectedAic.chance_of_harrasment2,
                selectedAic.chance_of_harrasment3,
                selectedAic.chance_of_seiging1,
                selectedAic.chance_of_seiging2,
                selectedAic.chance_of_seiging3,
            }.Max();
            int weaponSignal = PositiveAverage(
                selectedAic.buy_weapons,
                selectedAic.trade_weapons_at);
            return new DiplomacyV2PersonalitySignal
            {
                LordId = primaryLord,
                SendGoodsMargin = margin,
                CommerceOrientation = ClampSignal(
                    28 + commerce / 2
                        + (selectedAic.base_gold_reserves > 0 ? 12 : 0)),
                MilitaryOrientation = ClampSignal(
                    25 + weaponSignal / 3
                        + Math.Max(defensiveChance,
                            Math.Max(harassChance, siegeChance)) / 2),
                Aggression = ClampSignal(
                    15 + Math.Max(0, offensivePeak) * 3 / 4
                        + harassChance / 4),
                Caution = ClampSignal(
                    20 + defensiveChance * 3 / 4 + margin / 5),
            };
        }

        private static int AverageIncludingZero(params int[] values)
        {
            return values == null || values.Length == 0
                ? 0
                : values.Select(value => Math.Max(0, Math.Min(100, value)))
                    .Sum() / values.Length;
        }

        private static int PositiveAverage(params int[] values)
        {
            int[] usable = (values ?? new int[0])
                .Where(value => value > 0)
                .Select(value => Math.Min(100, value))
                .ToArray();
            return usable.Length == 0
                ? 0
                : usable.Sum() / usable.Length;
        }

        private static int ClampSignal(int value)
        {
            return Math.Max(0, Math.Min(100, value));
        }

        private void RefreshV2StrategicContext(
            CoalitionState coalition,
            int gameDay)
        {
            RelationState relation;
            if (coalition == null
                || !_relations.TryGetValue(coalition.CoalitionId, out relation)
                || relation.V2 == null)
            {
                return;
            }
            CaptureV2LocalPower();
            int commonEnemies = 0;
            int hostileCoalitions = 0;
            // The selected coalition is excluded from the candidate loop. It
            // still belongs in the displayed and evaluated total when it is
            // already allied; otherwise a sole alliance was reported as zero
            // and wary rulers only noticed the third alliance onward.
            int playerAllianceCount = relation.Allied ? 1 : 0;
            long localBlocEconomy = Math.Max(0L, _v2LocalEconomy);
            long localBlocMilitary = Math.Max(0L, _v2LocalMilitary);
            long hostileEconomy = 0L;
            long hostileMilitary = 0L;
            foreach (CoalitionState candidate in _coalitions.Values)
            {
                RelationState candidateRelation;
                if (string.Equals(
                        candidate.CoalitionId,
                        coalition.CoalitionId,
                        StringComparison.Ordinal)
                    || !candidate.MemberPlayerIds.Any(IsAlivePlayer))
                {
                    continue;
                }
                // During initialisation the coalition catalogue is complete
                // before every relation has been inserted. A not-yet-created
                // relation is necessarily still hostile; indexing the
                // dictionary here used to abort maps with several AI groups.
                bool candidateAllied = _relations.TryGetValue(
                        candidate.CoalitionId,
                        out candidateRelation)
                    && candidateRelation.Allied;
                if (candidateAllied)
                {
                    playerAllianceCount++;
                    localBlocEconomy = SaturatingAdd(
                        localBlocEconomy,
                        Math.Max(0L, candidate.Economy));
                    localBlocMilitary = SaturatingAdd(
                        localBlocMilitary,
                        Math.Max(0L, candidate.Military));
                }
                else
                {
                    commonEnemies++;
                    hostileCoalitions++;
                    hostileEconomy = SaturatingAdd(
                        hostileEconomy,
                        Math.Max(0L, candidate.Economy));
                    hostileMilitary = SaturatingAdd(
                        hostileMilitary,
                        Math.Max(0L, candidate.Military));
                }
            }
            // A hostile ruler counts the complete player bloc among the
            // forces arrayed against them. An allied ruler instead treats that
            // bloc as support and only the remaining coalitions as enemies.
            if (!relation.Allied)
            {
                hostileEconomy = SaturatingAdd(
                    hostileEconomy,
                    localBlocEconomy);
                hostileMilitary = SaturatingAdd(
                    hostileMilitary,
                    localBlocMilitary);
            }
            bool underPressure = (decimal)Math.Max(0L, coalition.Military) * 3m
                < (decimal)Math.Max(1L, hostileMilitary) * 2m;
            DiplomacyV2StateMachine.UpdateStrategicContext(
                relation,
                gameDay,
                coalition.Target,
                localBlocEconomy,
                localBlocMilitary,
                coalition.Economy,
                coalition.Military,
                commonEnemies,
                hostileCoalitions,
                playerAllianceCount,
                hostileEconomy,
                hostileMilitary,
                underPressure);
        }

        private void RefreshV2InteractionContext()
        {
            int day = AbsoluteGameDay();
            CoalitionState[] living = _coalitions.Values
                .Where(value => value.MemberPlayerIds.Any(IsAlivePlayer))
                .OrderBy(value => value.CoalitionId, StringComparer.Ordinal)
                .ToArray();
            foreach (CoalitionState coalition in living)
            {
                RefreshCoalition(coalition);
            }
            foreach (CoalitionState coalition in living)
            {
                RefreshV2StrategicContext(coalition, day);
            }
        }

        private void CaptureV2LocalPower()
        {
            if (_v2LocalPowerTick == ReadSimulationTick())
            {
                return;
            }
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            long economy = Math.Max(0, players.GetPlayerGold(_localPlayer));
            foreach (int goodId in SendableGoods)
            {
                if (goodId == 15)
                {
                    continue;
                }
                int amount = Math.Max(
                    0,
                    players.GetGoodAmount(_localPlayer, (eGoods)goodId));
                economy = SaturatingAdd(
                    economy,
                    SaturatingMultiply(amount, _frozenPrices[goodId]));
            }
            economy = SaturatingAdd(economy,
                V2ProductionEconomy(new HashSet<int> { _localPlayer }));
            long military = 0L;
            foreach (int unitId in units.GetAllAliveUnits())
            {
                if (!units.IsValidId(unitId)
                    || units.GetOwner(unitId) != _localPlayer)
                {
                    continue;
                }
                eChimps type = units.GetType(unitId);
                if (type == eChimps.CHIMP_TYPE_LORD)
                {
                    military = SaturatingAdd(
                        military,
                        _rules.LordMilitaryValue);
                    continue;
                }
                if (!IsCombatUnit(type))
                {
                    continue;
                }
                long cost = Math.Max(0, units.GetUnitGoldCost(type));
                UnitGoodCosts goods = units.GetUnitGoodCosts(type);
                cost = SaturatingAdd(cost, EquipmentValue(goods.cost1));
                cost = SaturatingAdd(cost, EquipmentValue(goods.cost2));
                cost = SaturatingAdd(cost, EquipmentValue(goods.cost3));
                cost = SaturatingAdd(cost, EquipmentValue(goods.cost4));
                if (cost <= 0)
                {
                    cost = DiplomacyBalance.UnknownUnitValue(
                        (int)units.GetDefaultHealth(type),
                        _rules);
                }
                int maximum = Math.Max(1, units.GetMaxHealth(unitId));
                int current = Math.Max(
                    0,
                    Math.Min(maximum, units.GetCurrentHealth(unitId)));
                military = SaturatingAdd(
                    military,
                    decimal.ToInt64(decimal.Ceiling(
                        (decimal)cost * current / maximum)));
            }
            _v2LocalEconomy = economy;
            _v2LocalMilitary = military;
            _v2LocalPowerTick = ReadSimulationTick();
        }

        private unsafe void EvaluateV2MilitaryIncursions()
        {
            // Unity samples the simulation clock: exact modulo ticks can all
            // be missed at high speed or low FPS (audit F02, 2026-09-08).
            if (!DiplomacyV2CombatRules.ScanDue(
                    _v2LastIncursionScanTick,
                    ReadSimulationTick(),
                    V2IncursionScanIntervalTicks))
            {
                return;
            }
            if (!_relations.Values.Any(relation => relation.V2 != null
                    && !relation.Allied
                    && DiplomacyV2CombatRules.IsTreaty(
                        relation.V2.Agreement)))
            {
                ClearV2TreatyStandoff();
                return;
            }
            int day = AbsoluteGameDay();
            var localForce = new List<V2WorldForceUnit>();
            IDisposable scanLease;
            if (!TryEnterNativeInventorySection(out scanLease)) return;
            using (scanLease)
            {
            _v2LastIncursionScanTick = ReadSimulationTick();
            if (_v2TreatyStandoffDegraded
                && unchecked(ReadSimulationTick() - _v2StandoffRetryTick) >= 0)
            {
                _v2TreatyStandoffDegraded = false;
            }
            if (_v2StandoffFaultsPending > 0)
            {
                if (_v2StandoffLogLines < 40)
                {
                    _v2StandoffLogLines++;
                    Log("treaty_standoff", "status=retry_scheduled|faults="
                        + _v2StandoffFaultsPending.ToString(CultureInfo.InvariantCulture));
                }
                _v2StandoffFaultsPending = 0;
            }
            RefreshV2TreatyZones(day);
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
            // Abstandsgebot (06.09.2026): Truppen einer Vertragsseite, die in
            // der Kernzone der anderen Seite stehen, werden je Stamm nach
            // Hause geschickt. Gemessen im Lauf bis 19:00: die KI belagerte
            // den Waffenruhe-Partner weiter - ohne Pfeile und Schaden, aber
            // mit dem ganzen Heer vor den Mauern.
            var recall = new Dictionary<int, V2TribeRecall>();
            foreach (int unitId in units.GetAllAliveUnits().OrderBy(id => id))
            {
                if (!units.IsValidId(unitId))
                {
                    continue;
                }
                int owner = units.GetOwner(unitId);
                eChimps type = units.GetType(unitId);
                if (type == eChimps.CHIMP_TYPE_LORD
                    || !IsCombatUnit(type))
                {
                    continue;
                }
                UnmanagedVector2<ushort> position =
                    units.GetCurrentWorldTilePosition(unitId);
                if (owner == _localPlayer)
                {
                    localForce.Add(new V2WorldForceUnit
                    {
                        X = position.X,
                        Y = position.Y,
                        MilitaryValue = V2MilitaryValue(
                            units,
                            unitId,
                            type),
                    });
                    continue;
                }
                V2TreatyZone home;
                if (!V2StandoffEnforceable()
                    || !V2TryGetStandoffRecallHome(
                        owner,
                        position.X,
                        position.Y,
                        out home))
                {
                    continue;
                }
                int tribeId = units.GetTribe(unitId);
                if (tribeId > 0 && !recall.ContainsKey(tribeId))
                {
                    GameTribe* tribe;
                    if (tribes.TryGetTribeById(tribeId, out tribe)
                        && tribe != null && tribe->r_PlayerIdOwner == owner)
                        recall[tribeId] = new V2TribeRecall
                        { Owner = owner, GlobalId = tribe->r_GlobalId, Home = home };
                }
            }
            EnforceV2TreatyStandoff(recall);
            }
            if (localForce.Count < DiplomacyV2CombatRules.HeavyForceMinimumUnits)
            {
                return;
            }

            foreach (CoalitionState coalition in _coalitions.Values.OrderBy(
                value => value.CoalitionId,
                StringComparer.Ordinal))
            {
                RelationState relation = _relations[coalition.CoalitionId];
                if (relation.V2 == null
                    || !DiplomacyV2CombatRules.TreatyProtects(
                        relation.Allied,
                        relation.V2.Agreement,
                        relation.V2.AgreementUntilDay,
                        day))
                {
                    continue;
                }
                var centers = new List<V2TreatyZone>();
                foreach (V2TreatyZone zone in _v2TreatyZones)
                {
                    if (!zone.LocalBloc
                        && Array.IndexOf(coalition.MemberPlayerIds, zone.Owner) >= 0)
                    {
                        centers.Add(zone);
                    }
                }
                if (centers.Count == 0)
                {
                    continue;
                }
                int count = 0;
                long strength = 0L;
                // Entfernungsbaender um das Burgtor, in lokalen Kacheln.
                // Warum (07.09.2026): der Benutzer marschierte mit ueber 200
                // Einheiten ein, gezaehlt wurden 7 - weil die Zone ein Kreis
                // von 18 Kacheln um das Burgtor ist, also der Burghof und
                // nicht das Gebiet. Wie weit die Streitmacht wirklich stand,
                // weiss niemand. Diese vier Zahlen sagen es, ohne einen
                // einzigen zusaetzlichen nativen Zugriff.
                int[] band = new int[V2IncursionBands.Length];
                foreach (V2WorldForceUnit unit in localForce)
                {
                    for (int index = 0; index < V2IncursionBands.Length; index++)
                    {
                        if (centers.Any(center =>
                                DiplomacyV2CombatRules.WithinBandTiles(
                                    unit.X,
                                    unit.Y,
                                    center.X,
                                    center.Y,
                                    V2IncursionBands[index])))
                        {
                            band[index]++;
                        }
                    }
                    bool inside = centers.Any(center =>
                        V2InsideTreatyZone(center, unit.X, unit.Y));
                    if (!inside)
                    {
                        continue;
                    }
                    count++;
                    strength = SaturatingAdd(strength, unit.MilitaryValue);
                }
                // Melden, was gezaehlt wurde - sonst ist "es wird nicht
                // registriert" nicht von "die Schwelle wird nie erreicht" zu
                // unterscheiden (Meldung des Benutzers 07.09.2026). Nur bei
                // Aenderung und nur, solange eigene Truppen ueberhaupt in der
                // Kernzone stehen.
                if (count > 0 || band[V2IncursionBands.Length - 1] > 0)
                {
                    int vorher;
                    int schluessel = (count * 100000)
                        + band[V2IncursionBands.Length - 1];
                    if (_v2IncursionLogLines < 60
                        && (!_v2IncursionCountSeen.TryGetValue(
                            coalition.CoalitionId, out vorher)
                        || vorher != schluessel))
                    {
                        _v2IncursionLogLines++;
                        // Nach dem aeussersten Band schluesseln, sonst
                        // meldet sich nichts, solange die Kernzone leer bleibt.
                        _v2IncursionCountSeen[coalition.CoalitionId] =
                            (count * 100000) + band[V2IncursionBands.Length - 1];
                        Log(
                            "incursion",
                            "coalition=" + coalition.CoalitionId
                            + "|status=counted|units="
                            + count.ToString(CultureInfo.InvariantCulture)
                            + "|strength="
                            + strength.ToString(CultureInfo.InvariantCulture)
                            + "|zones="
                            + centers.Count.ToString(CultureInfo.InvariantCulture)
                            + "|need_units="
                            + DiplomacyV2CombatRules.SubstantialForceMinimumUnits
                                .ToString(CultureInfo.InvariantCulture)
                            + "|need_value="
                            + DiplomacyV2CombatRules.SubstantialForceMinimumValue
                                .ToString(CultureInfo.InvariantCulture)
                            + "|force=" + localForce.Count.ToString(
                                CultureInfo.InvariantCulture)
                            + "|within_18=" + band[0].ToString(
                                CultureInfo.InvariantCulture)
                            + "|within_36=" + band[1].ToString(
                                CultureInfo.InvariantCulture)
                            + "|within_72=" + band[2].ToString(
                                CultureInfo.InvariantCulture)
                            + "|within_144=" + band[3].ToString(
                                CultureInfo.InvariantCulture));
                    }
                }
                bool substantial = DiplomacyV2CombatRules.IsSubstantialForce(
                    count,
                    strength);
                if (!substantial
                    || !DiplomacyV2StateMachine.RecordMilitaryIncursion(
                        relation,
                        day,
                        coalition.Target,
                        _rules))
                {
                    continue;
                }
                ShowMessage(Text(
                    "Eure Truppen sind in die Kernzone des Gegners eingerückt. Das Abkommen und alle Gespräche sind beendet.",
                    "Your troops entered the enemy's inner territory. The agreement and all talks have ended."));
                Log("agreement", "coalition=" + coalition.CoalitionId
                    + "|status=broken|actor=player_incursion|units="
                    + count.ToString(CultureInfo.InvariantCulture)
                    + "|military="
                    + strength.ToString(CultureInfo.InvariantCulture)
                    + "|fallback_radius_local="
                    + DiplomacyV2CombatRules.IntimateZoneRadiusLocalTiles
                        .ToString(CultureInfo.InvariantCulture)
                    + "|boundary=connected_castle_envelope|center=keep_door");
            }
        }

        /// <summary>
        /// Die Kernzonen beider Vertragsseiten fuer das Abstandsgebot: der
        /// Spielerblock (Spieler und verbuendete Verbuende) und jeder Verbund
        /// mit laufendem Pakt. Ohne Burgtor (SHCDESE-Vorgabe 0,0) keine Zone.
        /// </summary>
        private void RefreshV2TreatyZones(int day)
        {
            _v2TreatyZones.Clear();
            AddV2TreatyZone(_localPlayer, true);
            foreach (CoalitionState coalition in _coalitions.Values.OrderBy(
                value => value.CoalitionId,
                StringComparer.Ordinal))
            {
                RelationState relation;
                if (!_relations.TryGetValue(coalition.CoalitionId, out relation)
                    || relation.V2 == null)
                {
                    continue;
                }
                bool localBloc = relation.Allied;
                if (!localBloc
                    && !DiplomacyV2CombatRules.TreatyProtects(
                        relation.Allied,
                        relation.V2.Agreement,
                        relation.V2.AgreementUntilDay,
                        day))
                {
                    continue;
                }
                foreach (int member in coalition.MemberPlayerIds)
                {
                    AddV2TreatyZone(member, localBloc);
                }
            }
            _v2TreatyStandoffActive = _v2TreatyZones.Any(zone => !zone.LocalBloc);
        }

        private void AddV2TreatyZone(int player, bool localBloc)
        {
            V2WorldForceUnit center;
            if (player <= 0
                || !IsAlivePlayer(player)
                || !V2TryGetFixedKeepCenter(player, out center))
            {
                return;
            }
            _v2TreatyZones.Add(new V2TreatyZone
            {
                Owner = player,
                X = center.X,
                Y = center.Y,
                LocalBloc = localBloc,
                Boundary = Volatile.Read(ref _v2CastleBoundaries)[player],
            });
        }

        private void ClearV2TreatyStandoff()
        {
            // Endet der Pakt, endet auch der Messversuch - und zwar
            // zurueckgenommen, nicht abgebrochen.
            RestoreV2ProbeSubject("standoff_cleared");
            _v2TreatyZones.Clear();
            _v2TreatyStandoffActive = false;
            _v2TribeRecallTicks.Clear();
            _v2PendingAgreementSafety.Clear();
        }

        private bool V2StandoffEnforceable()
        {
            return _v2TreatyStandoffActive && !_v2TreatyStandoffDegraded;
        }

        /// <summary>
        /// Welcher Vertragsseite eine KI angehoert. Der Mensch ist nie
        /// Gegenstand des Abstandsgebots - fuer ihn gilt die Einmarschregel.
        /// </summary>
        private bool V2TryGetTreatySide(int player, out bool localBloc)
        {
            localBloc = false;
            if (player <= 0 || player == _localPlayer || !_roster.Contains(player))
            {
                return false;
            }
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(player, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || relation.V2 == null)
            {
                return false;
            }
            if (relation.Allied)
            {
                localBloc = true;
                return true;
            }
            return DiplomacyV2CombatRules.TreatyProtects(
                relation.Allied,
                relation.V2.Agreement,
                relation.V2.AgreementUntilDay,
                Math.Max(0, _lastProcessedDay));
        }

        private bool V2IsOpposingTreatyPlayer(bool localBloc, int player)
        {
            bool playerLocalBloc;
            if (player == _localPlayer)
            {
                return !localBloc;
            }
            return V2TryGetTreatySide(player, out playerLocalBloc)
                && playerLocalBloc != localBloc;
        }

        private V2TreatyZone V2FindOpposingTreatyZone(
            bool localBloc,
            int worldX,
            int worldY)
        {
            foreach (V2TreatyZone zone in _v2TreatyZones)
            {
                if (zone.LocalBloc != localBloc
                    && V2InsideTreatyZone(zone, worldX, worldY))
                {
                    return zone;
                }
            }
            return null;
        }

        private bool V2TryGetStandoffRecallHome(
            int owner,
            int worldX,
            int worldY,
            out V2TreatyZone home)
        {
            home = null;
            bool localBloc;
            if (!V2TryGetTreatySide(owner, out localBloc)
                || V2FindOpposingTreatyZone(localBloc, worldX, worldY) == null)
            {
                return false;
            }
            foreach (V2TreatyZone zone in _v2TreatyZones)
            {
                if (zone.Owner == owner)
                {
                    home = zone;
                    break;
                }
            }
            // Ohne eigenes Burgtor, oder wenn die Heimat selbst in der fremden
            // Kernzone liegt (Burgen dichter als der Radius), gibt es keinen
            // Rueckweg, den das Gebot nicht selbst sperren wuerde.
            return home != null
                && V2FindOpposingTreatyZone(localBloc, home.X, home.Y) == null;
        }

        private unsafe int V2ClearTreatyAiSiegeTargets()
        {
            RequireNativeDiplomacySection();
            int cleared = 0;
            GamePlayerManagerAPI players = GamePlayerManagerAPI.Instance;
            foreach (int player in _roster)
            {
                bool localBloc;
                if (player == _localPlayer
                    || !V2TryGetTreatySide(player, out localBloc)
                    || !GameData.Instance.lastGameState.is_skirmish_player(
                        player))
                {
                    continue;
                }
                GamePlayerResources* resources;
                if (!players.TryGetPlayerResourcesById(player, out resources)
                    || resources == null)
                {
                    continue;
                }
                uint rawTarget = resources->r_AISiegePlayerIdTarget;
                if (rawTarget < 1 || rawTarget > 8
                    || !V2IsOpposingTreatyPlayer(localBloc, (int)rawTarget))
                {
                    continue;
                }
                resources->r_AISiegePlayerIdTarget = 0;
                cleared++;
            }
            return cleared;
        }

        /// <summary>
        /// Abstandsgebot durchsetzen: Belagerungsziele in die andere
        /// Vertragsseite loeschen, Staemme in fremder Kernzone nach Hause
        /// schicken. Komfort ueber dem Waechter - ein Fehler hier schaltet
        /// nur das Gebot ab, nie die Karte; Angriff, Geschoss, Feuer und
        /// Schaden bleiben gesperrt.
        /// </summary>
        private unsafe void EnforceV2TreatyStandoff(
            Dictionary<int, V2TribeRecall> recall)
        {
            RequireNativeDiplomacySection();
            if (!V2StandoffEnforceable())
            {
                return;
            }
            try
            {
                int targetsCleared = V2ClearTreatyAiSiegeTargets();
                int recalled = 0;
                GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
                foreach (KeyValuePair<int, V2TribeRecall> entry in recall.OrderBy(
                    pair => pair.Key))
                {
                    GameTribe* tribe;
                    if (tribes == null
                        || !tribes.TryGetTribeById(entry.Key, out tribe)
                        || tribe == null
                        || !NativeDiplomacyIdentityMatches(entry.Value.Owner,
                            entry.Value.GlobalId, tribe->r_PlayerIdOwner, tribe->r_GlobalId))
                        continue;
                    long lastRecall;
                    if (_v2TribeRecallTicks.TryGetValue(entry.Key, out lastRecall)
                        && !DiplomacyV2CombatRules.ScanDue(
                            lastRecall,
                            ReadSimulationTick(),
                            DiplomacyV2CombatRules.TreatyRecallIntervalTicks))
                    {
                        continue;
                    }
                    if (tribes.IssueMoveHereCommand(
                            entry.Key,
                            entry.Value.Home.X
                                / DiplomacyV2CombatRules.WorldPositionsPerLocalTile,
                            entry.Value.Home.Y
                                / DiplomacyV2CombatRules.WorldPositionsPerLocalTile))
                    {
                        _v2TribeRecallTicks[entry.Key] = ReadSimulationTick();
                        recalled++;
                    }
                }
                int movesBlocked = _v2StandoffMovesBlocked;
                _v2StandoffMovesBlocked = 0;
                if ((targetsCleared > 0 || recalled > 0 || movesBlocked > 0)
                    && _v2StandoffLogLines < 40)
                {
                    _v2StandoffLogLines++;
                    Log("treaty_standoff", "status=enforced|ai_targets_cleared="
                        + targetsCleared.ToString(CultureInfo.InvariantCulture)
                        + "|tribes_recalled="
                        + recalled.ToString(CultureInfo.InvariantCulture)
                        + "|moves_blocked="
                        + movesBlocked.ToString(CultureInfo.InvariantCulture)
                        + "|zones="
                        + _v2TreatyZones.Count.ToString(CultureInfo.InvariantCulture)
                        + "|tick="
                        + ReadSimulationTick().ToString(CultureInfo.InvariantCulture));
                }
            }
            catch (Exception exception)
            {
                DeferV2TreatyStandoffRetry();
            }
        }

        /// <summary>
        /// Marschbefehle einer Vertragsseite in die Kernzone der anderen
        /// werden abgewiesen (Rueckgabe 0), solange der Pakt laeuft. Nur
        /// KI-Staemme mit Kampfeinheiten; der Mensch bleibt frei - fuer ihn
        /// gilt die Einmarschregel.
        /// </summary>
        private void OnV2TribeMoveOrder(TribeIssueOrderMoveHereEventArgs e)
        {
            NoteLane(LaneNative);
            if (e == null || e.Phase != EventHookPhase.Pre)
            {
                return;
            }
            // Nicht blockierend sperren (07.09.2026, nachgezogen): dieser
            // Behandler liegt auf derselben nativen Spur wie die acht
            // Kampfwaechter, die am 12:08 wegen genau dieses `lock` das Spiel
            // aufgehaengt haben. Er wurde damals uebersehen, weil die Liste
            // der nativen Waechter von Hand gepflegt war. Bekommt er das Tor
            // nicht, faellt ein Marschbefehl durch - der Abstandsschutz laesst
            // dann einen Schritt durch, statt den Spielkern anzuhalten.
            if (!TryEnterCombatGate())
            {
                return;
            }
            try
            {
                if (!_mapActive || _mapDisabled || !V2StandoffEnforceable())
                {
                    return;
                }
                try
                {
                    if (!GameTileManagerAPI.Instance.IsTileInsideMapBounds(e.TileX, e.TileY))
                    {
                        return;
                    }
                    int owner = TribeOwner(e.TribeId);
                    bool localBloc;
                    if (owner <= 0 || !V2TryGetTreatySide(owner, out localBloc))
                    {
                        return;
                    }
                    GameTribeManagerAPI tribes = GameTribeManagerAPI.Instance;
                    GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
                    int leader = tribes.GetLeaderUnitId(e.TribeId);
                    if (leader <= 0
                        || !units.IsValidId(leader)
                        || !IsCombatUnit(units.GetType(leader)))
                    {
                        return;
                    }
                    V2TreatyZone zone = V2FindOpposingTreatyZone(
                        localBloc,
                        DiplomacyV2CombatRules.TileCenterWorld(e.TileX),
                        DiplomacyV2CombatRules.TileCenterWorld(e.TileY));
                    if (zone == null)
                    {
                        return;
                    }
                    // Phase 0: waehrend des Umlenkversuchs bekommt der Stamm
                    // ein erreichbares Ersatzziel statt einer Absage. Die
                    // Frage ist, ob die KI das annimmt - heute weisen wir ab,
                    // und sie versucht es immer wieder.
                    if (V2ProbeRedirectMoveOrder(e, zone, localBloc))
                    {
                        return;
                    }
                    e.SkipOriginalFunction = true;
                    e.ReturnValue = 0;
                    _v2StandoffMovesBlocked++;
                }
                catch (Exception exception)
                {
                    // Native callbacks only record a bounded counter. Reporting
                    // and retry scheduling are observed on the next frame scan.
                    DeferV2TreatyStandoffRetry();
                }
            }
            finally
            {
                Monitor.Exit(_gate);
            }
        }


        private static bool V2TryGetFixedKeepCenter(
            int player,
            out V2WorldForceUnit center)
        {
            center = null;
            UnmanagedVector2<int> keepDoor =
                GamePlayerManagerAPI.Instance.GetPlayerKeepDoorPosition(
                    player);
            // SHCDESE returns default(0, 0) when no player resources exist.
            // A missing fixed center is not permission to move the zone with
            // the lord and accidentally declare a breach on the battlefield.
            int worldX;
            int worldY;
            if (!GameTileManagerAPI.Instance.IsTileInsideMapBounds(keepDoor.X, keepDoor.Y)
                || !DiplomacyV2CombatRules.TryKeepCenter(
                    keepDoor.X,
                    keepDoor.Y,
                    GameTileManagerAPI.MAX_WIDTH,
                    out worldX,
                    out worldY))
            {
                return false;
            }
            center = new V2WorldForceUnit
            {
                X = worldX,
                Y = worldY,
                MilitaryValue = 0L,
            };
            return true;
        }

        private long V2MilitaryValue(
            GameUnitManagerAPI units,
            int unitId,
            eChimps type)
        {
            long cost = Math.Max(0, units.GetUnitGoldCost(type));
            UnitGoodCosts goods = units.GetUnitGoodCosts(type);
            cost = SaturatingAdd(cost, EquipmentValue(goods.cost1));
            cost = SaturatingAdd(cost, EquipmentValue(goods.cost2));
            cost = SaturatingAdd(cost, EquipmentValue(goods.cost3));
            cost = SaturatingAdd(cost, EquipmentValue(goods.cost4));
            if (cost <= 0)
            {
                cost = DiplomacyBalance.UnknownUnitValue(
                    (int)units.GetDefaultHealth(type),
                    _rules);
            }
            int maximum = Math.Max(1, units.GetMaxHealth(unitId));
            int current = Math.Max(
                0,
                Math.Min(maximum, units.GetCurrentHealth(unitId)));
            return decimal.ToInt64(decimal.Ceiling(
                (decimal)cost * current / maximum));
        }

        private void HandleV2DemandResolution(
            CoalitionState coalition,
            RelationState relation,
            DiplomacyV2DemandResolution resolution)
        {
            switch (resolution)
            {
                case DiplomacyV2DemandResolution.TruceFormed:
                    ActivateV2AgreementSafety(coalition);
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    ShowMessage(Text(
                        "Waffenruhe vereinbart. Nach der Wartezeit könnt Ihr Bedingungen für ein Handelsabkommen anfragen.",
                        "Truce agreed. Once the waiting period ends, you can request terms for a trade pact."));
                    Log("agreement", "coalition=" + coalition.CoalitionId
                        + "|kind=truce|status=formed");
                    break;
                case DiplomacyV2DemandResolution.TradePactFormed:
                    ActivateV2AgreementSafety(coalition);
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    ShowMessage(string.Format(CultureInfo.InvariantCulture, Text(
                        "Handelsabkommen geschlossen: {0} Tage Schutz, höhere diplomatische Wertung Eurer Geschenke und Zugang zu Bündnisbedingungen.",
                        "Trade pact concluded: {0} days of protection, greater diplomatic value for your gifts, and access to alliance terms."),
                        Math.Max(0, relation.V2.AgreementUntilDay - AbsoluteGameDay())));
                    Log("agreement", "coalition=" + coalition.CoalitionId
                        + "|kind=trade_pact|status=formed");
                    break;
                case DiplomacyV2DemandResolution.AllianceReady:
                    if (CanJoinAlliance(coalition.CoalitionId))
                    {
                        FormAlliance(coalition, "v2_terms_fulfilled");
                    }
                    else
                    {
                        PlayCoalitionSpeech(
                            coalition,
                            "SK_THANK_GOODS",
                            "thanks");
                        ShowMessage(Text(
                            "Die Bündnisbedingungen sind erfüllt. Ein feindlicher KI-Verbund muss jedoch verbleiben; Waffenruhe und Handel gelten weiter.",
                            "The alliance terms are fulfilled, but one hostile AI coalition must remain; truce and trade stay in force."));
                    }
                    break;
                case DiplomacyV2DemandResolution.AllianceTermsAccepted:
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    ShowMessage(DiplomacyV2StateMachine
                            .PermanentHistoryPreventsAlliance(relation)
                        ? Text(
                            "Die Bündnisbedingungen sind erfüllt. Frühere Vertragsbrüche schließen ein Bündnis mit diesem Herrscher jedoch dauerhaft aus.",
                            "The alliance terms are fulfilled, but earlier treaty breaches permanently rule out an alliance with this ruler.")
                        : Text(
                            "Die Bündnisbedingungen sind erfüllt. Vertrauen und Ansehen reichen für ein Bündnis noch nicht aus.",
                            "The alliance terms are fulfilled. Trust and standing are not yet sufficient for an alliance."));
                    Log("agreement", "coalition=" + coalition.CoalitionId
                        + "|kind=alliance_terms|status=accepted_not_ready");
                    break;
                case DiplomacyV2DemandResolution.SupportFulfilled:
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    Log("support", "coalition=" + coalition.CoalitionId
                        + "|status=fulfilled");
                    break;
                case DiplomacyV2DemandResolution.UltimatumFulfilled:
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    ShowMessage(Text(
                        "Die letzte Forderung wurde erfüllt. Das Bündnis bleibt bestehen.",
                        "The final demand was fulfilled. The alliance remains in force."));
                    Log("ultimatum", "coalition=" + coalition.CoalitionId
                        + "|status=fulfilled");
                    break;
                case DiplomacyV2DemandResolution.RestitutionAccepted:
                    PlayCoalitionSpeech(coalition, "SK_THANK_GOODS", "thanks");
                    ShowMessage(Text(
                        "Die Wiedergutmachung wurde angenommen. Gespräche sind wieder möglich, doch der Vertragsbruch bleibt in Erinnerung.",
                        "Restitution was accepted. Talks may resume, but the breach will still be remembered."));
                    Log("restitution", "coalition=" + coalition.CoalitionId
                        + "|status=accepted");
                    break;
            }
        }

        /// <summary>
        /// Rechnet einen faelligen Tributzeitraum ab.
        /// </summary>
        /// <remarks>
        /// Laeuft im Tageslauf, also im Unity-Bild - dort sind
        /// Meldungsfenster erlaubt und kein Kontexthaken liegt auf dem
        /// Stapel.
        ///
        /// Haertung, bewusst so gebaut (07.09.2026):
        /// <list type="bullet">
        /// <item>Der ganze Ablauf liegt in einem eigenen `try`. Ein Fehler
        /// schaltet **nur diese Tributpflicht** ab, nie die Karte - ein
        /// normales Ereignis darf niemals dauerhaft abschalten.</item>
        /// <item>Hoechstens ein Zeitraum je Tag. Auch wenn mehrere
        /// verstrichen sind, wird einer abgerechnet; ein Nachholstoss waere
        /// weder spielbar noch bezahlbar.</item>
        /// <item>Keine Teilzahlung - die Uebertragung bleibt atomar.</item>
        /// <item>Sparsam: ohne bestehende und faellige Pflicht kostet der
        /// Zweig einen Feldvergleich.</item>
        /// </list>
        /// </remarks>
        // Militaerwert des oertlichen Spielers, hoechstens einmal je Tag
        // berechnet. -1 heisst "fuer diesen Tag noch nicht".
        // Feldstaerke je Spieler, einmal je Spieltag. Ein Durchlauf statt
        // eines je Vergleich (07.09.2026).
        private Dictionary<int, long> _v2MilitaryByPlayer;
        private int _v2MilitaryByPlayerDay = -1;

        // Aufeinanderfolgende Fehler der Lehnsspur. Erst danach gibt sie auf -
        // ein einzelner Fehler darf keinen Vertrag kosten.
        private readonly Dictionary<string, int> _v2VassalageFaultsByCoalition =
            new Dictionary<string, int>(StringComparer.Ordinal);
        private const int V2VassalageFaultLimit = 3;

        /// <summary>
        /// Der Militaerwert des oertlichen Spielers, nach derselben Formel wie
        /// bei den Koalitionen (Kosten mal Gesundheitsanteil).
        /// </summary>
        /// <remarks>
        /// Sparsam: ein Durchlauf ueber die Einheiten je Tag, und nur, wenn
        /// ueberhaupt ein Lehnsverhaeltnis besteht. Ein geschlagenes Heer
        /// zaehlt weniger als ein frisches - das ist gewollt, denn genau
        /// darum geht es beim Uebergewicht.
        /// </remarks>
        /// <summary>
        /// Feldstaerke JE SPIELER, einmal je Spieltag gemessen.
        /// </summary>
        /// <remarks>
        /// Ersetzt seit dem 07.09.2026 den Einzeldurchlauf fuer den oertlichen
        /// Spieler. Grund ist nicht Eleganz, sondern die Sperrzeit: der
        /// Tagesschritt haelt `_gate` bereits 13,9 ms und liegt damit ueber
        /// der Wartezeit des Kampftors (5 ms); im Lauf vom 07.09.2026 sind
        /// dadurch 278 Kampfwaechter uebersprungen worden. Ein Vergleich
        /// "Vasall gegen Lehnsherr" braucht Werte je SPIELER - als eigener
        /// Durchlauf je Vasall waere das ein Vielfaches gewesen. So ist es
        /// EIN Durchlauf fuer alle, und fuer den oertlichen Spieler sogar
        /// einer weniger als vorher.
        ///
        /// Der Fuerst zaehlt bewusst nicht mit: er steht in jeder Burg genau
        /// einmal und verschoebe den Vergleich zugunsten des Schwaecheren.
        /// </remarks>
        private Dictionary<int, long> V2MilitaryByPlayer(int day, bool currentTick = false)
        {
            if (_v2MilitaryByPlayerDay == day && _v2MilitaryByPlayer != null
                && _v2MilitaryGeneration == _sessionGeneration && _v2MilitaryEpoch == _mapEpoch
                && (!currentTick || _v2MilitaryByPlayerTick == ReadSimulationTick()))
            {
                return _v2MilitaryByPlayer;
            }
            RequireNativeDiplomacySection();
            Dictionary<int, long> tabelle = new Dictionary<int, long>();
            var positions = new List<V2MilitaryPosition>();
            var teams = new Dictionary<int, int>();
            foreach (int player in _roster)
                if (player >= 1 && player <= 8) teams[player] = _teamPort.GetTeam(player);
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            foreach (int unitId in units.GetAllAliveUnits())
            {
                if (!units.IsValidId(unitId))
                {
                    continue;
                }
                int owner = units.GetOwner(unitId);
                if (owner <= 0 || owner > 8)
                {
                    // Spieler 0 ist die bekannte Falle - er steht fuer
                    // "niemand", nicht fuer einen Mitspieler.
                    continue;
                }
                eChimps type = units.GetType(unitId);
                if (type == eChimps.CHIMP_TYPE_LORD || !IsCombatUnit(type))
                {
                    continue;
                }
                long vorher;
                tabelle.TryGetValue(owner, out vorher);
                long value = V2MilitaryValue(units, unitId, type);
                tabelle[owner] = SaturatingAdd(vorher, value);
                if (value > 0)
                {
                    UnmanagedVector2<ushort> position = units.GetCurrentWorldTilePosition(unitId);
                    positions.Add(new V2MilitaryPosition
                    { Owner = owner, X = position.X, Y = position.Y, Value = value });
                }
            }
            // Publish only a complete observation under the same engine lease.
            _v2MilitaryPositions = positions.ToArray();
            _v2MilitaryTeams = teams;
            _v2MilitaryByPlayerTick = ReadSimulationTick();
            _v2MilitaryGeneration = _sessionGeneration;
            _v2MilitaryEpoch = _mapEpoch;
            _v2MilitaryByPlayerDay = day;
            _v2MilitaryByPlayer = tabelle;
            return tabelle;
        }

        /// <summary>Feldstaerke eines Spielers, 0 wenn er keine hat.</summary>
        private long V2MilitaryOf(int player, int day)
        {
            long wert;
            return player > 0 && V2MilitaryByPlayer(day).TryGetValue(
                player, out wert)
                ? wert
                : 0L;
        }


        /// <summary>Ordinary alliances remain equal; discard obsolete automatic offers.</summary>
        private void EvaluateV2VassalageOnAlliance(
            CoalitionState coalition,
            RelationState relation,
            int day)
        {
            // An ordinary alliance supplies no hostile physical pressure.
            // Preserve historical active roles; never generate a new fealty
            // candidate from the allies' global strength difference.
            WithdrawV2LegacyAllianceSubjugation(relation);
        }

        /// <summary>
        /// Begruendet das Verhaeltnis und richtet den Tribut ein.
        /// </summary>
        /// <remarks>
        /// Beides zusammen oder gar nichts: ein Lehnsverhaeltnis ohne Tribut
        /// waere eine Rolle ohne Inhalt, ein Tribut ohne Verhaeltnis eine
        /// Pflicht ohne Grund (und der Tagesschritt loeschte ihn beim
        /// naechsten Durchlauf wieder).
        /// </remarks>
        private void EstablishV2Vassalage(
            CoalitionState coalition,
            RelationState relation,
            int vassalPlayer,
            int overlordPlayer,
            int day,
            string reason,
            int quotedAmount = 0)
        {
            DiplomacyV2RelationState state = relation.V2;
            int amount = quotedAmount > 0 ? quotedAmount
                : V2TributeQuoteForPlayer(vassalPlayer);
            // Protokollzeile VOR dem Schreiben: bricht etwas dazwischen ab,
            // steht wenigstens die Absicht im Protokoll (Hausregel).
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=about_to_establish|vassal="
                + vassalPlayer.ToString(CultureInfo.InvariantCulture)
                + "|overlord=" + overlordPlayer.ToString(
                    CultureInfo.InvariantCulture)
                + "|tribute_gold=" + amount.ToString(
                    CultureInfo.InvariantCulture)
                + "|interval=" + DiplomacyV2Tribute.DefaultIntervalDays
                    .ToString(CultureInfo.InvariantCulture)
                + "|reason=" + Safe(reason));
            if (!DiplomacyV2Vassalage.Establish(
                    relation,
                    vassalPlayer,
                    overlordPlayer,
                    _localPlayer,
                    day))
            {
                Log("vassalage", "coalition=" + coalition.CoalitionId
                    + "|status=refused|reason=preconditions");
                return;
            }
            if (!DiplomacyV2Tribute.Arrange(
                    state,
                    DiplomacyV2Tribute.GoldGoodId,
                    amount,
                    DiplomacyV2Tribute.DefaultIntervalDays,
                    day))
            {
                // Ohne Tribut kein Lehnsverhaeltnis - sonst bliebe eine
                // Rolle ohne Inhalt stehen.
                DiplomacyV2Vassalage.ClearWithoutRelease(state);
                Log("vassalage", "coalition=" + coalition.CoalitionId
                    + "|status=refused|reason=tribute_rejected");
                return;
            }
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=established|role=" + state.VassalRole.ToString());
            PublishCombatProtectionSnapshot();
            if (vassalPlayer == _localPlayer)
            {
                ShowMessage(Text(
                    "Ihr habt Lehnstreue geschworen. Bis Ihr Euch befreit, entrichtet Ihr regelmäßig Tribut.",
                    "You have sworn fealty. Until you free yourself you will pay regular tribute."));
                return;
            }
            ShowMessage(Text(
                "Euer neuer Verbündeter hat Euch Lehnstreue geschworen und entrichtet Euch fortan Tribut.",
                "Your new ally has sworn fealty to you and will pay you tribute from now on."));
        }

        /// <summary>Retires an obsolete automatic allied offer restored from an old save.</summary>
        private void AskV2Subjugation(
            CoalitionState coalition,
            RelationState relation,
            int overlordPlayer,
            int day)
        {
            // Retained as the old-save restore entry point. This automatic
            // allied offer has no valid siege producer under the current rule.
            WithdrawV2LegacyAllianceSubjugation(relation);
        }

        /// <summary>Der Spieler hat auf die Lehnsfrage geantwortet.</summary>
        /// <remarks>
        /// Der Rueckruf kommt spaeter und moeglicherweise in einer anderen
        /// Partie - dieselben vier Pruefungen wie bei den uebrigen Dialogen.
        /// </remarks>
        private void V2AnswerSubjugation(string coalitionId, long generation,
            string fingerprint, int overlordPlayer, int quotedAmount,
            int offerDay, int releases, bool accepted)
        {
            StageV2VassalAction(coalitionId, generation, fingerprint,
                accepted ? DiplomacyV2VassalActionKind.AcceptSubjugation : DiplomacyV2VassalActionKind.RefuseSubjugation,
                _localPlayer, overlordPlayer, -1, offerDay, quotedAmount, releases);
        }

        // ------------------------------------------------------------------
        // Vasallen-Befehlshebel (07.09.2026)
        // ------------------------------------------------------------------

        /// <summary>
        /// Grund eines Teamuebergangs, den eine Auflehnung ausgeloest hat.
        /// </summary>
        /// <remarks>
        /// Traegt die Bruchart durch den Uebergang, weil der im
        /// V1-Spielstandformat gespeichert wird und ein eigenes Feld eine
        /// Formataenderung waere (07.09.2026).
        /// </remarks>
        internal const string VassalRebellionReason = "vassal_rebellion";

        /// <summary>
        /// Grund eines Teamuebergangs, den ein Tributverzug ausgeloest hat.
        /// </summary>
        internal const string TributeDefaultReason = "tribute_default";

        /// <summary>Hoechstens so viele Protokollzeilen je Karte.</summary>
        private const int V2VassalOrderLogBudget = 40;

        private int _v2VassalOrdersSeen;
        private int _v2VassalOrdersForced;
        private int _v2VassalOrdersMismatched;
        private int _v2VassalOrderLogLines;
        private int _v2VassalOrderFaults;
        private const int V2VassalOrderFaultLogLimit = 3;

        /// <summary>
        /// Entscheidet, ob eine KI-Bewertung zugunsten des Lehnsherrn
        /// ausfaellt.
        /// </summary>
        /// <param name="hook">"attack" oder "defend" - nur fuers Protokoll.</param>
        /// <param name="consulted">
        /// Der Fuerst, dessen Bereitschaft bewertet wird (`TargetPlayerId`).
        /// </param>
        /// <param name="requester">Der Bittsteller (`SourcePlayerId`).</param>
        /// <param name="intendedTarget">
        /// Angriffsziel (`ContextPlayerId`), nur fuer Diagnose, nie Bittsteller.
        /// </param>
        /// <param name="original">Was die native KI selbst entschieden hat.</param>
        /// <returns>Der Wert, der zurueckgegeben werden soll.</returns>
        /// <remarks>
        /// MUSS unter dem Kampftor gerufen werden - liest `_relations`.
        /// Wirft nicht: der Aufrufer laeuft in einem nativen Rahmen.
        /// </remarks>
        private bool V2VassalOrderBias(
            string hook,
            int consulted,
            int requester,
            int intendedTarget,
            bool original)
        {
            if (original)
            {
                // Schon ein Ja - nichts zu beugen. Der haeufigste Fall zuerst,
                // damit die Suche unten meistens gar nicht laeuft.
                return true;
            }
            if (!_mapActive
                || _mapDisabled
                || consulted <= 0
                || requester <= 0)
            {
                return false;
            }
            bool passtVerdreht = false;
            foreach (KeyValuePair<string, RelationState> eintrag in _relations)
            {
                DiplomacyV2RelationState state = eintrag.Value == null
                    ? null
                    : eintrag.Value.V2;
                if (!DiplomacyV2Vassalage.IsActive(state))
                {
                    continue;
                }
                int vasall = DiplomacyV2Vassalage.VassalOf(state);
                int lehnsherr = DiplomacyV2Vassalage.OverlordOf(state);
                // 2026-09-07: nativer Caller 0xD771E und SE-1.45-Detour
                // belegen Source=Bittsteller, Target=KI, Context=Angriffsziel.
                bool herrFragt = lehnsherr == requester;
                if (vasall == consulted && herrFragt)
                {
                    _v2VassalOrdersSeen++;
                    if (!DiplomacyV2Vassalage.ObeysOrders(state))
                    {
                        // Er ist Vasall, aber gerade nicht willig: offener
                        // Antrag auf Gleichstellung oder versaeumter Tribut.
                        V2LogVassalOrder(
                            hook,
                            "withheld",
                            eintrag.Key,
                            consulted,
                            requester,
                            intendedTarget);
                        return false;
                    }
                    _v2VassalOrdersForced++;
                    V2LogVassalOrder(
                        hook,
                        "obeyed",
                        eintrag.Key,
                        consulted,
                        requester,
                        intendedTarget);
                    return true;
                }
                // Ein Vasall kann seinem Lehnsherrn keinen Befehl aufzwingen.
                if (vasall == requester && lehnsherr == consulted)
                {
                    passtVerdreht = true;
                }
            }
            if (passtVerdreht)
            {
                _v2VassalOrdersMismatched++;
                V2LogVassalOrder(
                    hook,
                    "role_mismatch",
                    "-",
                    consulted,
                    requester,
                    intendedTarget);
            }
            return false;
        }

        /// <summary>
        /// Ein Fehler im Befehlshebel - gezaehlt, nicht bestraft.
        /// </summary>
        /// <remarks>
        /// Kein `CaptureCombatSafetyFault`: das vermerkte Versagen wuerde
        /// spaeter auf der Bildschleife geworfen und die Karte abschalten.
        /// Der Hebel ist eine Bequemlichkeit, kein Sicherheitswaechter - sein
        /// Ausfall heisst, dass die KI selbst entscheidet, und das ist genau
        /// das Verhalten ohne diesen Mod.
        /// </remarks>
        private void V2NoteVassalOrderFault(string hook, Exception exception)
        {
            DiplomacyRuntimeSafety.SaturatingIncrement(ref _v2VassalOrderFaults);
            if (_v2VassalOrderFaults > V2VassalOrderFaultLogLimit)
            {
                return;
            }
            try
            {
                Log("vassal_order", "hook=" + Safe(hook)
                    + "|status=fault|count=" + _v2VassalOrderFaults.ToString(
                        CultureInfo.InvariantCulture)
                    + "|reason=" + Safe(exception.GetType().Name));
            }
            catch { } // Optional order diagnostics must not escape a native callback.
        }

        /// <summary>Gedeckelte Protokollzeile des Befehlshebels.</summary>
        private void V2LogVassalOrder(
            string hook,
            string status,
            string coalitionId,
            int consulted,
            int requesterA,
            int requesterB)
        {
            if (_v2VassalOrderLogLines >= V2VassalOrderLogBudget)
            {
                return;
            }
            _v2VassalOrderLogLines++;
            Log("vassal_order", "hook=" + Safe(hook)
                + "|status=" + Safe(status)
                + "|coalition=" + Safe(coalitionId)
                + "|consulted=" + consulted.ToString(
                    CultureInfo.InvariantCulture)
                + "|source=" + requesterA.ToString(CultureInfo.InvariantCulture)
                + "|context=" + requesterB.ToString(
                    CultureInfo.InvariantCulture)
                + "|local=" + _localPlayer.ToString(
                    CultureInfo.InvariantCulture)
                + "|seen=" + _v2VassalOrdersSeen.ToString(
                    CultureInfo.InvariantCulture)
                + "|forced=" + _v2VassalOrdersForced.ToString(
                    CultureInfo.InvariantCulture)
                + "|mismatched=" + _v2VassalOrdersMismatched.ToString(
                    CultureInfo.InvariantCulture));
        }

        private void ProcessV2Vassalage(
            CoalitionState coalition,
            RelationState relation,
            int day)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (!DiplomacyV2Vassalage.IsActive(state))
            {
                return;
            }
            try
            {
                if (!coalition.MemberPlayerIds.Any(IsAlivePlayer)
                    || !IsAlivePlayer(DiplomacyV2Vassalage.VassalOf(state))
                    || !IsAlivePlayer(DiplomacyV2Vassalage.OverlordOf(state)))
                {
                    // Ein besiegter Lehnsherr oder Vasall - das Verhaeltnis
                    // endet lautlos. Weiterzurechnen hiesse, den Militaerwert
                    // einer Koalition zu vergleichen, den niemand mehr
                    // auffrischt (07.09.2026).
                    DiplomacyV2Tribute.Clear(state);
                    DiplomacyV2Vassalage.Release(state);
                    _v2EqualityPresentedDays.Remove(coalition.CoalitionId);
                    CancelDiplomacyDialog("equality:" + coalition.CoalitionId);
                    Log("vassalage", "coalition=" + coalition.CoalitionId
                        + "|status=void|reason=coalition_defeated");
                    return;
                }
                // Read the named parties every day, including while a request
                // is open. A lost strength advantage invalidates the claim
                // before silence or a stale answer can cause a rebellion.
                long vasall = V2MilitaryOf(
                    DiplomacyV2Vassalage.VassalOf(state), day);
                long lehnsherr = V2MilitaryOf(
                    DiplomacyV2Vassalage.OverlordOf(state), day);
                bool canRequest = DiplomacyV2Vassalage.NoteStrengthComparison(
                    state, vasall, lehnsherr, day);
                _v2VassalageFaultsByCoalition.Remove(coalition.CoalitionId);
                if (DiplomacyV2Vassalage.CancelUnjustifiedEqualityRequest(state, day))
                {
                    _v2EqualityPresentedDays.Remove(coalition.CoalitionId);
                    CancelDiplomacyDialog("equality:" + coalition.CoalitionId);
                    Log("vassalage", "coalition=" + coalition.CoalitionId
                        + "|status=equality_withdrawn|reason=strength_changed");
                    return;
                }
                int presentedDay;
                bool presented = _v2EqualityPresentedDays.TryGetValue(
                    coalition.CoalitionId, out presentedDay) && day > presentedDay
                    && IsDiplomacyDialogPresented("equality:" + coalition.CoalitionId);
                if (DiplomacyV2Vassalage.ElapseEqualityResponseDay(state, day, presented))
                {
                    // Schweigen ist auch eine Antwort.
                    V2ResolveEqualityRequest(coalition, relation, day, false);
                    return;
                }
                if (DiplomacyV2Vassalage.EqualityRequestOpen(state))
                {
                    V2AskEqualityRequest(coalition, relation);
                    return;
                }
                if (!canRequest)
                {
                    return;
                }
                // Human vassals use the same strength/tenure rule, but choose
                // when to ask via the primary button. They are never forced
                // into an automatic rebellion or a hidden request.
                if (!DiplomacyV2Vassalage.CoalitionIsVassal(state))
                {
                    return;
                }
                // ERST zeigen, DANN vermerken. Andersherum liefe die
                // Bedenkzeit fuer einen Antrag ab, den der Spieler nie zu
                // sehen bekam - und das Schweigen gaelte als Ablehnung
                // (07.09.2026).
                if (!V2AskEqualityRequest(coalition, relation))
                {
                    Log("vassalage", "coalition=" + coalition.CoalitionId
                        + "|status=request_deferred|reason=dialog_unavailable");
                    return;
                }
                Log("vassalage", "coalition=" + coalition.CoalitionId
                    + "|status=equality_queued|vassal_military="
                    + vasall.ToString(CultureInfo.InvariantCulture)
                    + "|overlord_military="
                    + lehnsherr.ToString(CultureInfo.InvariantCulture)
                    + "|edge_days=" + state.VassalStrengthEdgeDays.ToString(
                        CultureInfo.InvariantCulture));
            }
            catch (Exception exception)
            {
                // Zu scharf waere, das Verhaeltnis gleich aufzuloesen: ein
                // einmaliger Fehler beim Lesen eines Militaerwerts ist kein
                // Grund, einen Vertrag zu beenden. Der Tagesschritt wird
                // uebersprungen und gezaehlt; erst nach mehreren Fehlern in
                // Folge gibt die Spur auf (07.09.2026).
                int faults;
                _v2VassalageFaultsByCoalition.TryGetValue(
                    coalition.CoalitionId, out faults);
                faults = Math.Min(V2VassalageFaultLimit + 1, faults + 1);
                _v2VassalageFaultsByCoalition[coalition.CoalitionId] = faults;
                if (faults <= V2VassalageFaultLimit)
                {
                    Log("vassalage", "coalition=" + coalition.CoalitionId
                        + "|status=deferred|faults="
                        + faults.ToString(CultureInfo.InvariantCulture)
                        + "|reason=" + Safe(exception.GetType().Name));
                }
            }
        }

        /// <summary>
        /// Legt dem Spieler den Antrag vor - ueber den Bestaetigungsdialog des
        /// Spiels, damit es aussieht wie alles andere.
        /// </summary>
        /// <remarks>
        /// Die Rueckrufe pruefen, ob die Welt noch dieselbe ist: Sitzung und
        /// Kartenkennung werden mitgenommen. Sonst wirkte eine Antwort in eine
        /// Partie hinein, zu der sie nicht gehoert - derselbe Schutz wie beim
        /// vorhandenen Aufkuendigungsdialog.
        /// </remarks>
        private bool V2AskEqualityRequest(
            CoalitionState coalition,
            RelationState relation)
        {
            if (DiplomacyV2VassalActions.HasPending(relation.V2)) return false;
            int vassal = relation.V2.VassalPlayerId, overlord = relation.V2.VassalOverlordPlayerId;
            int sinceDay = relation.V2.VassalSinceDay, releases = relation.V2.VassalReleases;
            int requestDay = relation.V2.VassalEqualityRequestedDay;
            long generation = _sessionGeneration;
            string fingerprint = _mapFingerprint;
            string coalitionId = coalition.CoalitionId;
            return ShowConfirmation(
                V2PlayerName(vassal) + " · " + Text("Antrag auf Gleichberechtigung", "Request for equal standing"),
                delegate { V2AnswerEqualityRequest(
                    coalitionId, generation, fingerprint, vassal, overlord, sinceDay, releases, requestDay, true); },
                delegate { V2AnswerEqualityRequest(
                    coalitionId, generation, fingerprint, vassal, overlord, sinceDay, releases, requestDay, false); },
                Text(
                    "Euer Vasall ist stärker geworden als Ihr und verlangt, Euch gleichgestellt zu werden. Gewährt Ihr es, enden die Tributzahlungen und das Bündnis bleibt bestehen. Weist Ihr ihn ab, könnte er sich lossagen.",
                    "Your vassal has grown stronger than you and demands equal standing. Granting it ends the tribute payments and keeps the alliance. Refusing may make him break away.")
                    + " " + string.Format(CultureInfo.InvariantCulture, Text(
                        "Antwortfrist: {0} Spieltage, während diese Entscheidung sichtbar ist.",
                        "Response period: {0} game days while this decision is visible."),
                        DiplomacyV2Vassalage.EqualityRequestOpen(relation.V2)
                            ? relation.V2.VassalEqualityResponseDaysRemaining
                            : DiplomacyV2Vassalage.EqualityRequestGraceDays),
                delegate
                {
                    lock (_gate)
                    {
                        RelationState current;
                        if (!V2VassalDecisionCurrent(coalitionId, generation, fingerprint, out current)
                            || !V2VassalContractMatches(current.V2, vassal, overlord, sinceDay, releases)
                            || DiplomacyV2VassalActions.HasPending(current.V2)) return;
                        if (!DiplomacyV2Vassalage.EqualityRequestOpen(current.V2))
                            DiplomacyV2Vassalage.RequestEquality(current.V2, Math.Max(0, _lastProcessedDay));
                        if (DiplomacyV2Vassalage.EqualityRequestOpen(current.V2))
                        {
                            requestDay = current.V2.VassalEqualityRequestedDay;
                            if (!_v2EqualityPresentedDays.ContainsKey(coalitionId))
                                _v2EqualityPresentedDays[coalitionId] = Math.Max(0, _lastProcessedDay);
                        }
                    }
                },
                "equality:" + coalitionId,
                delegate
                {
                    lock (_gate)
                    {
                        RelationState current;
                        return V2VassalDecisionCurrent(coalitionId, generation,
                                fingerprint, out current)
                            && !DiplomacyV2VassalActions.HasPending(current.V2)
                            && V2VassalContractMatches(current.V2, vassal, overlord, sinceDay, releases)
                            && (requestDay < 0 || current.V2.VassalEqualityRequestedDay == requestDay)
                            && DiplomacyV2Vassalage.CoalitionIsVassal(current.V2)
                            && (DiplomacyV2Vassalage.EqualityRequestOpen(current.V2)
                                || DiplomacyV2Vassalage.CanRequestEquality(
                                    current.V2, Math.Max(0, _lastProcessedDay)));
                    }
                });
        }

        private void V2AnswerEqualityRequest(string coalitionId, long generation,
            string fingerprint, int vassal, int overlord, int sinceDay,
            int releases, int requestDay, bool granted)
        {
            StageV2VassalAction(coalitionId, generation, fingerprint,
                granted ? DiplomacyV2VassalActionKind.GrantEquality : DiplomacyV2VassalActionKind.RefuseEquality,
                vassal, overlord, sinceDay, requestDay, 0, releases);
        }

        /// <summary>Setzt die Entscheidung um.</summary>
        private void V2ResolveEqualityRequest(CoalitionState coalition,
            RelationState relation, int day, bool granted)
        {
            // A timeout is a typed refusal intent too. An inventory journal
            // must settle before any role or request is resolved.
            DiplomacyV2VassalActions.Stage(relation, _localPlayer,
                granted ? DiplomacyV2VassalActionKind.GrantEquality : DiplomacyV2VassalActionKind.RefuseEquality);
        }

        private void ExecuteV2EqualityDecision(
            CoalitionState coalition,
            RelationState relation,
            int day,
            bool granted)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (!DiplomacyV2Vassalage.EqualityRequestOpen(state))
            {
                return;
            }
            if (DiplomacyV2Vassalage.CancelUnjustifiedEqualityRequest(state, day))
            {
                _v2EqualityPresentedDays.Remove(coalition.CoalitionId);
                CancelDiplomacyDialog("equality:" + coalition.CoalitionId);
                return;
            }
            // A timeout consumes only our own visible decision. Explicit
            // answers already completed it; cancellation is then a no-op.
            _v2EqualityPresentedDays.Remove(coalition.CoalitionId);
            CancelDiplomacyDialog("equality:" + coalition.CoalitionId);
            if (granted)
            {
                // Wer freiwillig loslaesst, gewinnt einen verlaesslichen
                // Partner - und die Tributpflicht endet mit dem Verhaeltnis.
                DiplomacyV2Tribute.Clear(state);
                DiplomacyV2Vassalage.Release(state);
                DiplomacyV2StateMachine.RecordVassalReleased(state);
                DiplomacyV2StateMachine.ResumeAllianceMaintenance(state, day);
                PublishCombatProtectionSnapshot();
                Log("vassalage", "coalition=" + coalition.CoalitionId
                    + "|status=equality_granted");
                ShowMessage(Text(
                    "Ihr habt Euren Vasallen freigelassen. Die Tributzahlungen enden, das Bündnis bleibt.",
                    "You have freed your vassal. The tribute payments end and the alliance remains."));
                return;
            }
            int sensitivity = DiplomacyV2StateMachine.BreachSensitivityOf(state);
            bool bricht = DiplomacyV2Vassalage.RejectionBreaksRelation(
                state,
                sensitivity);
            DiplomacyV2Vassalage.CloseEqualityRequest(state, day);
            Log("vassalage", "coalition=" + coalition.CoalitionId
                + "|status=equality_refused|resolve="
                + DiplomacyV2Vassalage.RebellionResolve(state, sensitivity)
                    .ToString(CultureInfo.InvariantCulture)
                + "|threshold="
                + DiplomacyV2Vassalage.RebellionBreakThreshold.ToString(
                    CultureInfo.InvariantCulture)
                + "|breaks=" + BoolText(bricht));
            if (!bricht)
            {
                ShowMessage(string.Format(CultureInfo.InvariantCulture, Text(
                    "Ihr habt den Antrag abgewiesen. Die Lehnspflicht bleibt bestehen; ein neuer Gleichstellungsantrag ist frühestens in {0} Tagen möglich.",
                    "You refused the request. Fealty continues; another request for equal standing is possible in {0} days at the earliest."),
                    DiplomacyV2Vassalage.EqualityRequestCooldownDays));
                return;
            }
            // Ueber den Uebergangsweg, nicht an ihm vorbei (07.09.2026,
            // zweite Fassung). Die erste Fassung rief die Regel direkt: das
            // setzte `relation.Allied = false`, liess aber `coalition.Allied`
            // und die nativen Mannschaften stehen - und genau diese
            // Ungleichheit laesst `DiplomacySaveCodec.Validate` werfen. Ab der
            // Auflehnung haette jedes Speichern geworfen.
            //
            // `BreakCoalition` reiht ein; `CommitTransitionState` setzt dann
            // Beziehung, Koalitionsflag und Mannschaften ZUSAMMEN. Die
            // Bruchart reist im Grund mit, weil der Uebergang im
            // V1-Spielstandformat gespeichert wird und ein neues Feld eine
            // Formataenderung waere.
            //
            // Meldung und Protokollzeile stehen deshalb im Commit: bevor der
            // Uebergang durch ist, hat sich niemand losgesagt, und ein
            // abgebrochener Uebergang haette den Spieler belogen.
            BreakCoalition(coalition, day, VassalRebellionReason);
        }

        // A single resource line settles the complete gold invoice. Choosing
        // the smallest share of a stockpile avoids stripping a scarce good;
        // the journal still records only the actual transfer.
        private bool TrySelectV2InKindPayment(
            int payer, int recipient, DiplomacyV2RelationState state,
            out int goodId, out int amount, out string failure)
        {
            RequireNativeDiplomacySection();
            goodId = 0;
            amount = 0;
            failure = null;
            int selectedStock = 0;
            long selectedOverpay = long.MaxValue;
            foreach (int candidate in SendableGoods)
            {
                int price;
                int needed;
                if (!_frozenPrices.TryGetValue(candidate, out price))
                {
                    failure = "frozen_price_unavailable";
                    return false;
                }
                if (!DiplomacyV2Tribute.TryEquivalentGoodsAmount(
                    state, candidate, price, out needed)) continue;
                int payerStock;
                if (!TryReadTransferAmount(payer, candidate, out payerStock))
                {
                    failure = "resource_stock_unavailable";
                    continue;
                }
                if (payerStock < needed) continue;
                int recipientStock;
                if (!TryReadTransferAmount(recipient, candidate, out recipientStock))
                {
                    failure = "recipient_stock_unavailable";
                    continue;
                }
                if (recipientStock > int.MaxValue - needed)
                {
                    failure = "recipient_capacity_unavailable";
                    continue;
                }
                long overpay = (long)needed * price - state.TributeAmount;
                if (goodId == 0
                    || (long)needed * selectedStock < (long)amount * payerStock
                    || (long)needed * selectedStock == (long)amount * payerStock
                        && (overpay < selectedOverpay
                            || overpay == selectedOverpay && candidate < goodId))
                {
                    goodId = candidate;
                    amount = needed;
                    selectedStock = payerStock;
                    selectedOverpay = overpay;
                }
            }
            if (goodId != 0) failure = null;
            return failure == null;
        }

        private void ProcessV2Tribute(
            CoalitionState coalition,
            RelationState relation,
            int day)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (state == null || !DiplomacyV2Tribute.IsActive(state)
                || _nativeTransferProbe != null || _pendingTeamTransition != null
                || _pendingPackage != null || _inventoryRestorePending || _goodsTransfersUnavailable)
            {
                return;
            }
            // Survival and the payment/default decision belong to one native
            // snapshot. A defeated payer must not be charged after an earlier
            // unprotected alive check; nested inventory operations are reentrant.
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))
            {
                NoteV2TributeTechnicalFailure(coalition.CoalitionId,
                    "native_inventory_busy");
                return;
            }
            using (lease) ProcessV2TributeUnderLease(coalition, relation, day);
        }

        private void ProcessV2TributeUnderLease(
            CoalitionState coalition,
            RelationState relation,
            int day)
        {
            RequireNativeDiplomacySection();
            DiplomacyV2RelationState state = relation.V2;
            try
            {
                // Beide Seiten sind benannt: der Tribut geht vom
                // Vasallen an SEINEN Lehnsherrn, und beide koennen
                // Bundesgenossen sein, an denen der oertliche Spieler nicht
                // beteiligt ist (Vorgabe des Benutzers, 07.09.2026).
                int payer = DiplomacyV2Vassalage.VassalOf(state);
                int recipient = DiplomacyV2Vassalage.OverlordOf(state);
                if (payer <= 0
                    || recipient <= 0
                    || !IsAlivePlayer(payer)
                    || !IsAlivePlayer(recipient))
                {
                    // Eine Seite fehlt oder ist besiegt. Die Pflicht endet
                    // lautlos - ein besiegter Empfaenger ist kein
                    // Versaeumnis des Zahlers, und ein Tribut ohne benannte
                    // Seiten ist ein Datenfehler, keine Schuld.
                    DiplomacyV2Tribute.Clear(state);
                    DiplomacyV2Vassalage.ClearWithoutRelease(state);
                    Log("tribute", "coalition=" + coalition.CoalitionId
                        + "|status=void|reason=party_gone|payer="
                        + payer.ToString(CultureInfo.InvariantCulture)
                        + "|payee=" + recipient.ToString(
                            CultureInfo.InvariantCulture));
                    return;
                }
                int goodId = state.TributeGoodId;
                int amount = state.TributeAmount;
                if (!DiplomacyV2Tribute.IsDue(state, day)) return;
                int stock;
                if (!TryReadTransferAmount(payer, goodId, out stock))
                {
                    NoteV2TributeTechnicalFailure(coalition.CoalitionId,
                        "stock_unavailable");
                    return;
                }
                int paymentGoodId = goodId;
                int paymentAmount = amount;
                bool zahlbar = stock >= amount;
                if (!zahlbar && goodId == DiplomacyV2Tribute.GoldGoodId)
                {
                    string lookupFailure;
                    if (!TrySelectV2InKindPayment(payer, recipient, state,
                        out paymentGoodId, out paymentAmount, out lookupFailure))
                    {
                        NoteV2TributeTechnicalFailure(coalition.CoalitionId,
                            lookupFailure);
                        return;
                    }
                    zahlbar = paymentGoodId != 0;
                }
                string failure = null;
                if (zahlbar)
                {
                    zahlbar = TryAtomicTransferFrom(
                        payer,
                        recipient,
                        paymentGoodId,
                        paymentAmount,
                        out failure,
                        DiplomacyTransferPurpose.Tribute,
                        day);
                    if (!zahlbar)
                    {
                        // A transport failure is not a player's missed payment.
                        // Keep the due date and retry on a later simulation day.
                        NoteV2TributeTechnicalFailure(coalition.CoalitionId,
                            failure ?? "transfer_unavailable");
                        return;
                    }
                }
                if (zahlbar)
                {
                    // Das Journal schliessen, BEVOR irgendetwas anderes
                    // geschieht (07.09.2026): `TryAtomicTransferFrom` laesst
                    // `_nativeTransferProbe` absichtlich stehen, damit der
                    // Aufrufer eine Wiederherstellung haette. Bleibt es offen,
                    // nimmt `VerifyNativeTransferProbe` die Zahlung auf der
                    // Bildschleife wieder zurueck oder sperrt alle
                    // Guetersendungen der Partie - waehrend der
                    // Beziehungszustand "bezahlt" sagt.
                    //
                    // Hier ist nichts nachzupruefen: die Belastung des Zahlers
                    // ist in `TryAtomicTransferFrom` exakt zurueckgelesen
                    // worden, sonst waere `zahlbar` falsch. Der Empfaenger wird
                    // seit 10.09.2026 NICHT mehr abgeglichen - sein Lager
                    // gehoert einer laufenden Wirtschaft.
                    CompleteVerifiedNativeTransfer(
                        _nativeTransferProbe,
                        "tribute");
                    // Transfer purpose dispatch commits payment history and
                    // resources together, including save/load journal replay.
                    _v2TributeTechnicalFaults.Remove(coalition.CoalitionId);
                    Log("tribute", "coalition=" + coalition.CoalitionId
                        + "|status=paid|payer=" + payer.ToString(
                            CultureInfo.InvariantCulture)
                        + "|payee=" + recipient.ToString(
                            CultureInfo.InvariantCulture)
                        + "|good=" + paymentGoodId.ToString(
                            CultureInfo.InvariantCulture)
                        + "|amount=" + paymentAmount.ToString(
                            CultureInfo.InvariantCulture)
                        + "|cycles=" + state.TributePaidCycles.ToString(
                            CultureInfo.InvariantCulture)
                        + "|next_due=" + state.TributeNextDueDay.ToString(
                            CultureInfo.InvariantCulture));
                    OnDiplomacyPresentationCommitted(DiplomacyPresentationEvent.Create(
                        DiplomacyPresentationEventKind.TributePaid, _sessionGeneration, day,
                        payer == _localPlayer ? recipient : payer, null, _localPlayer,
                        coalition.CoalitionId, "tribute_cycle",
                        new DiplomacyPresentationReference("tribute_cycle",
                            sequence: state.TributePaidCycles, goodId: paymentGoodId,
                            amount: paymentAmount,
                            intervalDays: state.TributeIntervalDays, dueDay: state.TributeNextDueDay,
                            payerPlayerId: payer, recipientPlayerId: recipient)));
                    return;
                }
                // The original invoice stays due until its verified payment.
                // A continued shortage does not generate a second default.
                if (!DiplomacyV2Tribute.CanRegisterMiss(state, day))
                {
                    return;
                }
                DiplomacyV2Tribute.RegisterMiss(state, day);
                Log("tribute", "coalition=" + coalition.CoalitionId
                    + "|status=arrears|good=" + goodId.ToString(
                        CultureInfo.InvariantCulture)
                    + "|amount=" + amount.ToString(
                        CultureInfo.InvariantCulture)
                    + "|stock=" + stock.ToString(CultureInfo.InvariantCulture)
                    + "|missed=" + state.TributeMissedCycles.ToString(
                        CultureInfo.InvariantCulture)
                    + "|reason=" + Safe(failure ?? "insufficient_stock"));
            }
            catch (Exception exception)
            {
                // Technical failure never forgives a debt or breaks a treaty.
                NoteV2TributeTechnicalFailure(coalition.CoalitionId,
                    exception.GetType().Name);
            }
        }

        private void FulfillV2DemandPackage(int targetPlayer)
        {
            if (RejectUnavailableGoodsTransfer())
            {
                return;
            }
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(targetPlayer, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || relation.Demand == null
                || relation.Demand.Complete
                || !IsAlivePlayer(targetPlayer)
                || targetPlayer == _localPlayer)
            {
                ShowMessage(Text(
                    "Keine erfüllbare Forderung ausgewählt.",
                    "No payable demand is selected."));
                return;
            }
            if (_nativeTransferProbe != null || _pendingPackage != null || _pendingTeamTransition != null)
            {
                ShowMessage(Text(
                    "Eine andere Übertragung wird noch abgeschlossen.",
                    "Another transfer is still being completed."));
                return;
            }
            V2DemandPackageLine[] lines = relation.Demand.Items
                .Where(item => item != null && item.RemainingAmount > 0)
                .Select(item => new V2DemandPackageLine
                {
                    GoodId = item.GoodId,
                    Amount = item.RemainingAmount,
                })
                .ToArray();
            if (lines.Length == 0)
            {
                return;
            }
            List<string> missing;
            bool boundsValid;
            if (!TryReadV2PackageAmounts(targetPlayer, lines, out missing, out boundsValid)) return;
            if (!boundsValid)
            {
                ShowMessage(Text("Das Güterpaket kann nicht sicher geprüft werden.",
                    "The goods package cannot be verified safely."));
                Log("demand_package", "coalition=" + coalitionId
                    + "|status=rejected|reason=inventory_bounds");
                return;
            }
            if (missing.Count > 0)
            {
                ShowMessage(Text("Es fehlen: ", "Missing: ")
                    + string.Join(", ", missing));
                Log("demand_package", "coalition=" + coalitionId
                    + "|status=rejected|reason=insufficient_stock");
                return;
            }

            ExecuteV2DemandPackage(targetPlayer, relation, lines);
        }

        private void HandleV2DayOutcome(
            CoalitionState coalition,
            RelationState relation,
            int gameDay,
            bool expired)
        {
            if (expired)
            {
                BreakCoalition(coalition, gameDay, "v2_ultimatum_expired");
                return;
            }
            if (relation.V2 != null && relation.V2.LastEvent == DiplomacyV2EventKind.DemandMissed
                && relation.V2.LastEventDay == gameDay)
            {
                foreach (int player in coalition.MemberPlayerIds)
                    RecordV2GoodsOutcome(player, "demand_expired", false);
            }
            if (relation.V2 != null
                && relation.V2.LastEvent
                    == DiplomacyV2EventKind.AgreementExpired
                && relation.V2.LastEventDay == gameDay)
            {
                ShowMessage(Text(
                    "Das Abkommen ist ausgelaufen.",
                    "The agreement has expired."));
                Log("agreement", "coalition=" + coalition.CoalitionId
                    + "|status=expired");
            }
            if (relation.V2 != null
                && relation.V2.LastEvent
                    == DiplomacyV2EventKind.ProactiveSupportRecognized
                && relation.V2.LastEventDay == gameDay)
            {
                Log("support", "coalition=" + coalition.CoalitionId
                    + "|status=proactive_credit_accepted");
            }
            GoodsDemand demand = relation.Demand;
            if (demand == null || demand.IssuedDay != gameDay)
            {
                return;
            }
            foreach (int player in coalition.MemberPlayerIds) ClearV2GoodsOutcome(player);
            if (demand.V2Purpose == DiplomacyV2DemandPurpose.Support)
            {
                PlayCoalitionSpeech(coalition, "SK_REQUEST_GOODS", "req");
                ShowMessage(V2DemandText(demand));
                Log("support", "coalition=" + coalition.CoalitionId
                    + "|status=requested|expires="
                    + demand.ExpiresDay.ToString(CultureInfo.InvariantCulture));
            }
            else if (demand.V2Purpose == DiplomacyV2DemandPurpose.Ultimatum)
            {
                PlayCoalitionSpeech(coalition, "SK_REQUEST_GOODS", "req");
                ShowMessage(Text(
                    "Euer Verbündeter stellt eine letzte Forderung. ",
                    "Your ally has issued a final demand. ")
                    + V2DemandText(demand));
                Log("ultimatum", "coalition=" + coalition.CoalitionId
                    + "|status=issued|expires="
                    + demand.ExpiresDay.ToString(CultureInfo.InvariantCulture));
            }
        }

        private void ActivateV2AgreementSafety(CoalitionState coalition)
        {
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))
            {
                _v2PendingAgreementSafety.Add(coalition.CoalitionId);
                PublishCombatProtectionSnapshot();
                return;
            }
            using (lease)
            {
            // A treaty is concluded with the player's complete diplomatic
            // bloc, not only with the human player object. Use a synthetic
            // positive partition because Vanilla represents unaffiliated
            // players with team zero, which must never be mistaken for a
            // shared alliance while stale combat is being purged.
            var partition = _roster.ToDictionary(
                player => player,
                player => player);
            foreach (CoalitionState ally in _coalitions.Values)
            {
                RelationState allyRelation = _relations[ally.CoalitionId];
                if (!allyRelation.Allied)
                {
                    continue;
                }
                foreach (int member in ally.MemberPlayerIds)
                {
                    partition[member] = _localPlayer;
                }
            }
            foreach (int member in coalition.MemberPlayerIds)
            {
                partition[member] = _localPlayer;
            }
            int tribes = QuarantineAlliedTribes(partition);
            int projectiles = QuarantineAlliedProjectiles(partition);
            int fires = QuarantineAlliedBuildingFires(partition);
            int targets = QuarantineAlliedAiTargets(partition);
            Log("agreement_safety", "coalition=" + coalition.CoalitionId
                + "|tribes_stopped=" + tribes.ToString(CultureInfo.InvariantCulture)
                + "|projectiles_deleted="
                + projectiles.ToString(CultureInfo.InvariantCulture)
                + "|building_fires_cleared="
                + fires.ToString(CultureInfo.InvariantCulture)
                + "|ai_targets_cleared="
                + targets.ToString(CultureInfo.InvariantCulture));
                _v2PendingAgreementSafety.Remove(coalition.CoalitionId);
            }
        }

        private void RetryV2AgreementSafety()
        {
            foreach (string id in _v2PendingAgreementSafety.ToArray())
            {
                CoalitionState coalition;
                RelationState relation;
                if (!_coalitions.TryGetValue(id, out coalition)
                    || !_relations.TryGetValue(id, out relation)
                    || relation.V2 == null
                    || !DiplomacyV2CombatRules.TreatyProtects(relation.Allied,
                        relation.V2.Agreement, relation.V2.AgreementUntilDay, AbsoluteGameDay()))
                { _v2PendingAgreementSafety.Remove(id); continue; }
                ActivateV2AgreementSafety(coalition);
            }
        }

        private bool V2TreatyProtectsPlayers(int first, int second)
        {
            if (first == second)
            {
                return false;
            }
            bool firstInLocalBloc = V2IsLocalDiplomaticBlocPlayer(first);
            bool secondInLocalBloc = V2IsLocalDiplomaticBlocPlayer(second);
            if (firstInLocalBloc == secondInLocalBloc)
            {
                return false;
            }
            int foreign = firstInLocalBloc ? second : first;
            string coalitionId;
            RelationState relation;
            if (!_playerCoalition.TryGetValue(foreign, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || relation.Allied
                || relation.V2 == null)
            {
                return false;
            }
            int day = Math.Max(0, _lastProcessedDay);
            return DiplomacyV2CombatRules.TreatyProtects(
                relation.Allied,
                relation.V2.Agreement,
                relation.V2.AgreementUntilDay,
                day);
        }

        private bool V2IsLocalDiplomaticBlocPlayer(int player)
        {
            if (player == _localPlayer)
            {
                return true;
            }
            string coalitionId;
            RelationState relation;
            return player > 0
                && _playerCoalition.TryGetValue(player, out coalitionId)
                && _relations.TryGetValue(coalitionId, out relation)
                && relation.Allied;
        }

        // Zuletzt gemeldete Einheitenzahl in der Kernzone je Koalition. Nur
        // fuer die Meldung - eine Zeile je Aenderung, nicht je Zaehlung
        // (07.09.2026; der Auslassungszaehler hat vorgemacht, wie ein Melder
        // ein Protokoll zudeckt).
        private readonly Dictionary<string, int> _v2IncursionCountSeen =
            new Dictionary<string, int>(StringComparer.Ordinal);

        // Entfernungsbaender um das Burgtor, in lokalen Kacheln. 18 ist die
        // heutige Kernzone; die drei weiteren sagen, wie weit eine
        // Streitmacht tatsaechlich steht (07.09.2026).
        private static readonly int[] V2IncursionBands = { 18, 36, 72, 144 };

        private bool V2TryResolveProtectedGroundAttackTarget(
            int source,
            TribeAICommand command,
            int targetValue1,
            int targetValue2,
            out int target)
        {
            target = 0;
            if (!_roster.Contains(source)
                || (command != TribeAICommand.AttackTilePosition
                    && command != TribeAICommand.ThrowLava))
            {
                return false;
            }
            int worldX = DiplomacyV2CombatRules.TileCenterWorld(targetValue1);
            int worldY = DiplomacyV2CombatRules.TileCenterWorld(targetValue2);
            return V2TryFindDiplomaticCounterpartNearWorldTarget(
                source,
                worldX,
                worldY,
                GroundFireProjectileRiskRadiusWorld,
                true,
                out target);
        }

        private void V2RecordUnprotectedHostileAct(int source, int target)
        {
            // This state models the foreign ruler's opinion of the human.
            // Enemy attacks must therefore never be booked as treachery by
            // the player; on an active treaty they are blocked earlier by the
            // combat guard, and outside a treaty they remain ordinary enemy
            // warfare. Only player-originated hostility damages diplomacy.
            if (source != _localPlayer
                || target <= 0
                || source == target
                || V2TreatyProtectsPlayers(source, target))
            {
                return;
            }
            int foreign = target;
            string coalitionId;
            RelationState relation;
            CoalitionState coalition;
            if (!_playerCoalition.TryGetValue(foreign, out coalitionId)
                || !_relations.TryGetValue(coalitionId, out relation)
                || !_coalitions.TryGetValue(coalitionId, out coalition)
                || relation.Allied
                || relation.V2 == null)
            {
                return;
            }
            DiplomacyV2StateMachine.RecordHostileAct(
                relation,
                Math.Max(0, _lastProcessedDay),
                coalition.Target);
        }

        private bool V2TryFindDiplomaticCounterpartNearWorldTarget(
            int sourcePlayer,
            int worldTileX,
            int worldTileY,
            int riskRadius,
            bool requireActiveTreaty,
            out int counterpartOwner)
        {
            counterpartOwner = 0;
            // Schutzsuche: ohne aktiven Pakt kann sie nichts finden - die
            // Abkuerzung aendert das Ergebnis nicht, spart aber je
            // Feuerereignis den Vollscan.
            if (requireActiveTreaty && !V2AnyActiveTreaty())
            {
                return false;
            }
            var hits = new List<V2CounterpartHit>();
            if (!V2ScanDiplomaticCounterparts(
                    sourcePlayer,
                    worldTileX,
                    worldTileY,
                    riskRadius,
                    requireActiveTreaty,
                    hits))
            {
                return false;
            }
            V2CounterpartHit best = null;
            foreach (V2CounterpartHit hit in hits)
            {
                if (best == null
                    || hit.Treaty && !best.Treaty
                    || hit.Treaty == best.Treaty && hit.Distance < best.Distance)
                {
                    best = hit;
                }
            }
            if (best == null)
            {
                return false;
            }
            counterpartOwner = best.Owner;
            return true;
        }

        /// <summary>
        /// Feindakt-Zuordnung fuer Weltziele ohne Besitzer (Boden, Feuer).
        /// Erst pruefen, dann drosseln (Pruefbefund P1-A, 06.09.2026): der
        /// alte Sentinel int.MinValue lief bei der Differenz ueber, die
        /// Zuordnung blieb ab Takt 0 fuer immer gedrosselt. Jeder Treffer im
        /// Umkreis wird gebucht, nicht nur der naechste - RecordHostileAct
        /// ist je Verbund und Tag idempotent, darum genuegt ein Vollscan je
        /// 32 Takte.
        /// </summary>
        private void V2AttributeHostileActNearWorldTarget(
            int sourcePlayer,
            int worldTileX,
            int worldTileY,
            int riskRadius)
        {
            if (sourcePlayer != _localPlayer
                || GameUnitManagerAPI.Instance == null)
            {
                return;
            }
            int worldLimit = checked(
                GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (!_roster.Contains(sourcePlayer)
                || worldTileX < 0
                || worldTileX >= worldLimit
                || worldTileY < 0
                || worldTileY >= worldLimit)
            {
                return;
            }
            if (!DiplomacyV2CombatRules.ScanDue(
                    _v2LastHostileAttributionTick,
                    ReadSimulationTick(),
                    DiplomacyV2CombatRules.HostileAttributionIntervalTicks))
            {
                return;
            }
            _v2LastHostileAttributionTick = ReadSimulationTick();
            var hits = new List<V2CounterpartHit>();
            V2ScanDiplomaticCounterparts(
                sourcePlayer,
                worldTileX,
                worldTileY,
                riskRadius,
                false,
                hits);
            var booked = new HashSet<int>();
            foreach (V2CounterpartHit hit in hits)
            {
                if (booked.Add(hit.Owner))
                {
                    V2RecordUnprotectedHostileAct(sourcePlayer, hit.Owner);
                }
            }
        }

        /// <summary>
        /// Alle diplomatischen Gegenparteien (Einheiten und Kacheln) im
        /// Umkreis eines Weltziels, mit Abstand und Paktschutz. False nur,
        /// wenn Quelle oder Koordinaten ungueltig sind.
        /// </summary>
        private bool V2ScanDiplomaticCounterparts(
            int sourcePlayer,
            int worldTileX,
            int worldTileY,
            int riskRadius,
            bool requireActiveTreaty,
            List<V2CounterpartHit> hits)
        {
            int worldLimit = checked(
                GameTileManagerAPI.MAX_WIDTH * WorldPositionsPerLocalTile);
            if (!_roster.Contains(sourcePlayer)
                || worldTileX < 0
                || worldTileX >= worldLimit
                || worldTileY < 0
                || worldTileY >= worldLimit)
            {
                return false;
            }
            int boundedRadius = Math.Max(
                0,
                Math.Min(riskRadius, worldLimit));
            long squaredRadius = (long)boundedRadius * boundedRadius;
            var unitIds = new List<int>();
            GameUnitManagerAPI units = GameUnitManagerAPI.Instance;
            if (units == null)
            {
                return false;
            }
            units.GetAllUnits(unitIds, AliveState.IsAlive);
            unitIds.Sort();
            bool sourceInLocalBloc =
                V2IsLocalDiplomaticBlocPlayer(sourcePlayer);
            foreach (int unitId in unitIds)
            {
                int owner = UnitOwner(unitId);
                bool ownerInLocalBloc =
                    V2IsLocalDiplomaticBlocPlayer(owner);
                if (owner <= 0
                    || owner == sourcePlayer
                    || sourceInLocalBloc == ownerInLocalBloc)
                {
                    continue;
                }
                int foreign = sourceInLocalBloc
                    ? owner
                    : sourcePlayer;
                string coalitionId;
                RelationState relation;
                if (!_playerCoalition.TryGetValue(foreign, out coalitionId)
                    || !_relations.TryGetValue(coalitionId, out relation)
                    || relation.Allied
                    || relation.V2 == null)
                {
                    continue;
                }
                bool protectedByTreaty = V2TreatyProtectsPlayers(
                    sourcePlayer,
                    owner);
                if (requireActiveTreaty && !protectedByTreaty)
                {
                    continue;
                }
                UnmanagedVector2<ushort> position =
                    units.GetCurrentWorldTilePosition(unitId);
                long deltaX = (long)position.X - worldTileX;
                long deltaY = (long)position.Y - worldTileY;
                long distance = deltaX * deltaX + deltaY * deltaY;
                if (distance > squaredRadius)
                {
                    continue;
                }
                hits.Add(new V2CounterpartHit
                {
                    Owner = owner,
                    Distance = distance,
                    Treaty = protectedByTreaty,
                });
            }
            int minimumTileX = Math.Max(
                0,
                worldTileX - boundedRadius) / WorldPositionsPerLocalTile;
            int maximumTileX = Math.Min(
                worldLimit - 1,
                worldTileX + boundedRadius) / WorldPositionsPerLocalTile;
            int minimumTileY = Math.Max(
                0,
                worldTileY - boundedRadius) / WorldPositionsPerLocalTile;
            int maximumTileY = Math.Min(
                worldLimit - 1,
                worldTileY + boundedRadius) / WorldPositionsPerLocalTile;
            for (int tileY = minimumTileY; tileY <= maximumTileY; tileY++)
            {
                for (int tileX = minimumTileX; tileX <= maximumTileX; tileX++)
                {
                    int owner = TileOwner(tileX, tileY);
                    bool ownerInLocalBloc =
                        V2IsLocalDiplomaticBlocPlayer(owner);
                    if (owner <= 0
                        || owner == sourcePlayer
                        || sourceInLocalBloc == ownerInLocalBloc)
                    {
                        continue;
                    }
                    int foreign = sourceInLocalBloc
                        ? owner
                        : sourcePlayer;
                    string coalitionId;
                    RelationState relation;
                    if (!_playerCoalition.TryGetValue(
                            foreign,
                            out coalitionId)
                        || !_relations.TryGetValue(
                            coalitionId,
                            out relation)
                        || relation.Allied
                        || relation.V2 == null)
                    {
                        continue;
                    }
                    bool protectedByTreaty = V2TreatyProtectsPlayers(
                        sourcePlayer,
                        owner);
                    if (requireActiveTreaty && !protectedByTreaty)
                    {
                        continue;
                    }

                    long tileMinimumWorldX =
                        (long)tileX * WorldPositionsPerLocalTile;
                    long tileMaximumWorldX = tileMinimumWorldX
                        + WorldPositionsPerLocalTile - 1;
                    long tileMinimumWorldY =
                        (long)tileY * WorldPositionsPerLocalTile;
                    long tileMaximumWorldY = tileMinimumWorldY
                        + WorldPositionsPerLocalTile - 1;
                    long deltaX = worldTileX < tileMinimumWorldX
                        ? tileMinimumWorldX - worldTileX
                        : worldTileX > tileMaximumWorldX
                            ? worldTileX - tileMaximumWorldX
                            : 0L;
                    long deltaY = worldTileY < tileMinimumWorldY
                        ? tileMinimumWorldY - worldTileY
                        : worldTileY > tileMaximumWorldY
                            ? worldTileY - tileMaximumWorldY
                            : 0L;
                    long distance = deltaX * deltaX + deltaY * deltaY;
                    if (distance > squaredRadius)
                    {
                        continue;
                    }
                    hits.Add(new V2CounterpartHit
                    {
                        Owner = owner,
                        Distance = distance,
                        Treaty = protectedByTreaty,
                    });
                }
            }
            return true;
        }


        private bool V2AnyActiveTreaty()
        {
            foreach (RelationState relation in _relations.Values)
            {
                if (V2HasBreakableAgreement(relation))
                {
                    return true;
                }
            }
            return false;
        }

        private bool V2HasBreakableAgreement(RelationState relation)
        {
            return relation != null
                && relation.V2 != null
                && DiplomacyV2CombatRules.TreatyProtects(
                    relation.Allied,
                    relation.V2.Agreement,
                    relation.V2.AgreementUntilDay,
                    _lastProcessedDay);
        }

        private void ConfirmV2BreakAgreement(int selectedPlayer)
        {
            string id;
            if (!_playerCoalition.TryGetValue(selectedPlayer, out id)) return;
            RelationshipDecisionQuote quote = CaptureRelationshipDecision(id, selectedPlayer,
                DiplomacyV2RelationshipDecisionKind.EndAgreement);
            if (quote == null) return;
            ShowConfirmation(quote.Names + " · " + Text("Abkommen aufkündigen", "End agreement"),
                delegate { StageRelationshipDecision(quote); }, delegate { },
                quote.Names + " · " + Text(
                    "Der Gegner wird den Vertragsbruch lange in Erinnerung behalten.",
                    "The opponent will remember this breach for a long time."),
                null, quote.Key, delegate { lock (_gate) return IsCurrentRelationshipDecision(quote); });
        }

        private string V2StatusText(
            RelationState relation,
            CoalitionState coalition, int player = 0)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (state == null)
            {
                return Text("unbekannt", "unknown");
            }
            int day = AbsoluteGameDay();
            if (relation.Allied)
            {
                if (V2IsFealtyCounterpart(state, player))
                {
                    return V2VassalRoleText(state);
                }
                if (relation.Demand != null
                    && relation.Demand.V2Purpose
                        == DiplomacyV2DemandPurpose.Ultimatum)
                {
                    return Text("Bündnis unter Vorbehalt — ", "Alliance at risk — ")
                        + V2DurationText(relation.Demand.ExpiresDay - day);
                }
                if (relation.Demand != null)
                {
                    return Text("Bündnis · Unterstützung erbeten — ",
                        "Alliance · support requested — ")
                        + V2DurationText(relation.Demand.ExpiresDay - day);
                }
                // The shared relation suspends maintenance while its named
                // fealty is active, also for ordinary peers in legacy teams.
                if (DiplomacyV2Vassalage.IsActive(state))
                    return Text("verbündet", "allied");
                return Text("Bündnis — nächste Prüfung ",
                    "Alliance — next review ")
                    + V2DurationText(state.MaintenanceDueDay - day);
            }
            if (state.Agreement == DiplomacyV2AgreementKind.Truce
                && state.AgreementUntilDay > day)
            {
                return Text("Waffenruhe — ", "Truce — ")
                    + V2DurationText(state.AgreementUntilDay - day);
            }
            if (state.Agreement == DiplomacyV2AgreementKind.TradePact
                && state.AgreementUntilDay > day)
            {
                return Text("Handelsabkommen — ", "Trade pact — ")
                    + V2DurationText(state.AgreementUntilDay - day);
            }
            if (day < relation.RelationshipBlockedUntilDay)
            {
                return Text("Gespräche ausgesetzt — ", "Talks suspended — ")
                    + V2DurationText(
                        relation.RelationshipBlockedUntilDay - day);
            }
            switch (DiplomacyV2StateMachine.DisplayStage(relation, day))
            {
                case DiplomacyV2NegotiationStage.Hostile:
                    return Text("feindselig", "hostile");
                case DiplomacyV2NegotiationStage.Contact:
                    return Text("gesprächsbereit", "willing to talk");
                case DiplomacyV2NegotiationStage.Negotiating:
                    return state.Agreement == DiplomacyV2AgreementKind.Truce
                        ? Text("Waffenruhe", "truce")
                        : Text("in Verhandlung", "negotiating");
                case DiplomacyV2NegotiationStage.Trusted:
                    return state.Agreement == DiplomacyV2AgreementKind.TradePact
                        ? Text("Handelspartner", "trade partner")
                        : Text("vertrauensvoll", "trusted");
                case DiplomacyV2NegotiationStage.AllianceReady:
                    return CanJoinAlliance(coalition.CoalitionId)
                        ? Text("bündnisbereit", "ready to ally")
                        : Text("Bündnis nicht möglich", "alliance unavailable");
                case DiplomacyV2NegotiationStage.Allied:
                    return Text("verbündet", "allied");
                case DiplomacyV2NegotiationStage.Ultimatum:
                    return Text("warnt Euch", "warning you");
                default:
                    return Text("misstrauisch", "distrustful");
            }
        }

        private string V2RelationshipSummary(RelationState relation)
        {
            DiplomacyV2RelationState state = relation.V2;
            if (state == null)
            {
                return Text("Beziehung unbekannt", "Relationship unknown");
            }
            return Text("Herrscher: ", "Ruler: ")
                + V2PersonalityName(state.Personality)
                + Text(" · Vertrauen ", " · trust ") + V2Level(state.Trust)
                + Text(" · Respekt ", " · respect ")
                + V2Level(state.Respect)
                + Text(" · Groll ", " · grudge ")
                + V2Level(state.Grudge);
        }

        private string V2ActionHint(
            RelationState relation,
            CoalitionState coalition)
        {
            if (HasPendingGoodsCommand) return PendingGoodsCommandStatusText();
            if (relation.Demand != null)
            {
                return V2DemandText(relation.Demand);
            }
            if (DiplomacyV2Submission.HasOffer(relation.V2))
                return relation.V2.SubmissionAcceptancePending || relation.V2.SubmissionOfferAccepted
                    ? Text("Unterwerfung bestätigt", "Submission accepted")
                    : Text("Entscheidung offen", "Decision pending");
            if (relation.PendingOffer)
            {
                return Text("Entscheidung offen", "Decision pending");
            }
            if (relation.Allied)
            {
                return V2RelationshipSummary(relation);
            }
            int waitDays = DiplomacyV2StateMachine.NegotiationWaitDays(
                relation,
                AbsoluteGameDay());
            if (!relation.Allied && waitDays > 0)
            {
                return waitDays == 1 ? Text("Gespräche in 1 Tag", "Talks in 1 day")
                    : string.Format(CultureInfo.InvariantCulture,
                    Text("Gespräche in {0} Tagen", "Talks in {0} days"), waitDays);
            }
            if (relation.V2.RestitutionOutstandingValue > 0m)
            {
                return Text(
                    "Nächster Schritt: Bedingungen zur Wiedergutmachung anfragen.",
                    "Next step: request terms for restitution.");
            }
            switch (relation.V2.Agreement)
            {
                case DiplomacyV2AgreementKind.None:
                    return relation.V2.Stage == DiplomacyV2NegotiationStage.Hostile
                        ? Text(
                            "Nächster Schritt: Benötigte Güter senden, um Gesprächsbereitschaft zu schaffen.",
                            "Next step: send needed goods to open talks.")
                        : Text(
                        "Nächster Schritt: Bedingungen für eine Waffenruhe anfragen.",
                        "Next step: request terms for a truce.");
                case DiplomacyV2AgreementKind.Truce:
                    return Text(
                        "Nächster Schritt: Bedingungen für ein Handelsabkommen anfragen.",
                        "Next step: request terms for a trade pact.");
                case DiplomacyV2AgreementKind.TradePact:
                    if (DiplomacyV2StateMachine.CanFormAlliance(
                            relation, coalition.Target))
                    {
                        return CanJoinAlliance(coalition.CoalitionId)
                            ? Text(
                                "Der Verbund ist zu einem Bündnis bereit.",
                                "The coalition is ready for an alliance.")
                            : Text(
                                "Mindestens ein feindlicher KI-Verbund muss verbleiben.",
                                "At least one hostile AI coalition must remain.");
                    }
                    if (relation.V2.AllianceTermsFulfilled)
                    {
                        return DiplomacyV2StateMachine
                                .PermanentHistoryPreventsAlliance(relation)
                            ? Text(
                                "Die Bedingungen sind erfüllt; frühere Vertragsbrüche verhindern dieses Bündnis dauerhaft.",
                                "Terms are fulfilled; earlier treaty breaches permanently prevent this alliance.")
                            : Text(
                                "Die Bedingungen sind erfüllt. Benötigte Güter senden, um Vertrauen und Ansehen weiter zu festigen.",
                                "Terms are fulfilled. Send needed goods to strengthen trust and standing.");
                    }
                    return Text(
                        "Nächster Schritt: Bündnisbedingungen anfragen und Vertrauen festigen.",
                        "Next step: request alliance terms and strengthen trust.");
                default:
                    return V2RelationshipSummary(relation);
            }
        }

        private string V2DemandText(GoodsDemand demand)
        {
            string prefix;
            switch (demand.V2Purpose)
            {
                case DiplomacyV2DemandPurpose.Courtship:
                    prefix = Text("Bedingung zur Waffenruhe: ", "Truce terms: ");
                    break;
                case DiplomacyV2DemandPurpose.TradeProof:
                    prefix = Text("Handelsbedingung: ", "Trade terms: ");
                    break;
                case DiplomacyV2DemandPurpose.AllianceTerms:
                    prefix = Text("Bündnisbedingung: ", "Alliance terms: ");
                    break;
                case DiplomacyV2DemandPurpose.Support:
                    prefix = Text("Erbetene Unterstützung: ", "Requested support: ");
                    break;
                case DiplomacyV2DemandPurpose.Ultimatum:
                    prefix = Text("Letzte Forderung: ", "Final demand: ");
                    break;
                case DiplomacyV2DemandPurpose.Restitution:
                    prefix = Text("Wiedergutmachung: ", "Restitution: ");
                    break;
                default:
                    prefix = demand.IsUltimatum
                        ? Text("Ultimatum: ", "Ultimatum: ")
                        : Text("Forderung: ", "Demand: ");
                    break;
            }
            string goods = string.Join(" · ", demand.Items
                .Where(item => item != null && item.RemainingAmount > 0)
                .Select(item =>
                item.RemainingAmount.ToString(CultureInfo.InvariantCulture)
                + " " + GoodName(item.GoodId, item.RemainingAmount)));
            int remaining = Math.Max(0, demand.ExpiresDay - AbsoluteGameDay());
            return prefix + goods + " — " + V2DurationText(remaining);
        }

        private string V2DemandProgressText(GoodsDemand demand)
        {
            return Text("Lieferung verbucht. Offen: ", "Delivery recorded. Due: ")
                + V2DemandText(demand);
        }

        private string V2DemandPackageHint()
        {
            return Text(
                "Bezahlt die offenen Positionen dieser Forderung.",
                "Pays the outstanding items in this demand.");
        }

        private string V2GraceText(int days)
        {
            int bounded = Math.Max(0, days);
            return bounded == 1 ? Text("Schonfrist: 1 Tag", "Grace: 1 day")
                : string.Format(CultureInfo.InvariantCulture,
                    Text("Schonfrist: {0} Tage", "Grace: {0} days"), bounded);
        }

        private string V2DurationText(int days)
        {
            int bounded = Math.Max(0, days);
            // These are binding game-day deadlines, not approximate durations.
            return bounded == 1 ? Text("Noch 1 Tag", "1 day remaining")
                : string.Format(CultureInfo.InvariantCulture,
                    Text("Noch {0} Tage", "{0} days remaining"), bounded);
        }

        private string V2RequestRolloverText(RelationState relation, int player = 0)
        {
            if (relation != null && relation.Demand != null)
            {
                return Text(
                    "Forderung vollständig erfüllen",
                    "Fulfil complete demand");
            }
            if (relation == null || relation.V2 == null)
            {
                return Text("Bedingungen anfragen", "Request terms");
            }
            if (DiplomacyV2Submission.HasOffer(relation.V2))
                return relation.V2.SubmissionAcceptancePending || relation.V2.SubmissionOfferAccepted
                    ? Text("Unterwerfung bestätigt", "Submission accepted")
                    : Text("Entscheidung offen", "Decision pending");
            if (relation.PendingOffer)
            {
                return Text(
                    "Eine Bündnisentscheidung ist bereits offen.",
                    "An alliance decision is already pending.");
            }
            if (relation.Allied)
            {
                if (!V2CanRequestGoodsFrom(player))
                    return Text("Als Vasall könnt Ihr keine Güter fordern.",
                        "As a vassal, you cannot request goods.");
                return Text(
                    "Güter vom Verbündeten erbitten",
                    "Request goods from ally");
            }
            int waitDays = DiplomacyV2StateMachine.NegotiationWaitDays(
                relation,
                AbsoluteGameDay());
            if (!relation.Allied && waitDays > 0)
            {
                return Text("Wartezeit: ", "Waiting period: ")
                    + V2DurationText(waitDays);
            }
            if (relation.V2.RestitutionOutstandingValue > 0m)
            {
                return Text(
                    "Wiedergutmachung anfragen",
                    "Request restitution terms");
            }
            switch (relation.V2.Agreement)
            {
                case DiplomacyV2AgreementKind.None:
                    return Text(
                        "Waffenruhe anfragen",
                        "Request truce terms");
                case DiplomacyV2AgreementKind.Truce:
                    return Text(
                        "Handelsabkommen anfragen",
                        "Request trade terms");
                case DiplomacyV2AgreementKind.TradePact:
                    if (relation.V2.AllianceTermsFulfilled)
                    {
                        return Text(
                            "Bündnisbereitschaft prüfen",
                            "Review alliance readiness");
                    }
                    return Text(
                        "Bündnisbedingungen anfragen",
                        "Request alliance terms");
                default:
                    return Text("Unterstützung leisten", "Provide support");
            }
        }

        private void HideV2DetailPanel(object panel)
        {
            _v2OverviewVisible = false;
            if (panel == null)
            {
                return;
            }
            SetVisibilityIfPresent(
                FindElement(panel, "CrusaderDiplomacyV2Panel"),
                false);
            SetVisibilityIfPresent(
                FindElement(panel, "CrusaderDiplomacyNativeDetail"),
                true);
        }

        /// <summary>
        /// Ist die Buendnisuebersicht aufgeklappt?
        /// </summary>
        /// <remarks>
        /// Bewusst nur Anzeige: das Umschalten aendert keinen Spielzustand,
        /// darum ueberlebt es auch keinen Kartenwechsel (07.09.2026).
        /// </remarks>
        private bool _v2OverviewVisible;

        /// <summary>
        /// Zeigt alle laufenden Abkommen auf einmal.
        /// </summary>
        /// <remarks>
        /// Sparsam: ist die Uebersicht zugeklappt, wird nur die Sichtbarkeit
        /// gesetzt und sonst nichts gerechnet - dieser Weg laeuft je Bild.
        ///
        /// Fehlt ein Textfeld, bleibt die Zeile leer. Ein fehlendes Element
        /// ist kein Grund, die Oberflaeche oder gar die Karte abzuschalten.
        /// </remarks>
        private void RefreshV2OverviewPanel(object panel)
        {
            UiStep("v2_overview");
            object button = FindElement(
                panel, "CrusaderDiplomacyV2OverviewButton");
            object label = FindElement(
                panel, "CrusaderDiplomacyV2OverviewLabel");
            object details = FindElement(panel, "CrusaderDiplomacyV2DetailsButton");
            object grid = FindElement(
                panel, "CrusaderDiplomacyV2OverviewPanel");
            object detailPanel = FindElement(panel, "CrusaderDiplomacyV2DetailsPanel");
            SetVisibilityIfPresent(button, true);
            SetVisibilityIfPresent(label, true);
            if (button != null) SetProperty(button, "IsChecked", _v2OverviewVisible);
            if (details != null) SetProperty(details, "IsChecked", !_v2OverviewVisible);
            SetTextIfPresent(panel, "CrusaderDiplomacyV2DetailsLabel", Text("Details", "Details"));
            if (label != null)
            {
                SetProperty(
                    label,
                    "Text",
                    Text("Bündnis", "Alliance"));
            }
            bool showOverview = grid != null && _v2OverviewVisible;
            SetVisibilityIfPresent(detailPanel, !showOverview);
            if (grid == null)
            {
                HideV2DetailPanel(panel);
                NotifyV2UiFallback();
                return;
            }
            SetVisibility(grid, showOverview);
            if (!showOverview)
            {
                // Zugeklappt kostet die Uebersicht nichts weiter.
                return;
            }
            RefreshV2AllianceManagement(panel);
        }

        /// <summary>Sieben Zeilen - so viele Koalitionen gibt es hoechstens.</summary>
        private const int V2OverviewRowCount = 7;

        /// <summary>
        /// Setzt einen Text, wenn es das Feld gibt. Fehlt es, passiert nichts.
        /// </summary>
        private void SetTextIfPresent(object panel, string name, string text)
        {
            object element = FindElement(panel, name);
            if (element != null)
            {
                SetProperty(element, "Text", text);
            }
        }

        private void RefreshV2DetailPanel(
            object panel,
            RelationState relation,
            CoalitionState coalition,
            int selectedPlayer)
        {
            // Overview has its own selected member and stock snapshot. Do not
            // rebuild hidden detail strings or read its demand a second time.
            if (_v2OverviewVisible)
            {
                object overviewGrid = FindElement(panel, "CrusaderDiplomacyV2OverviewPanel");
                object outerPanel = FindElement(panel, "CrusaderDiplomacyV2Panel");
                object nativePanel = FindElement(panel, "CrusaderDiplomacyNativeDetail");
                if (overviewGrid != null && outerPanel != null && nativePanel != null)
                {
                    SetVisibility(nativePanel, false);
                    SetVisibility(outerPanel, true);
                    RefreshV2OverviewPanel(panel);
                    return;
                }
            }
            // One nonblocking native snapshot, consumed after releasing the
            // monitor. Text, buttons and stocks describe the same observation.
            Dictionary<int, int> demandStock = V2DemandStockSnapshot(relation == null ? null : relation.Demand);
            UiStep("v2_find");
            object advanced = FindElement(
                panel,
                "CrusaderDiplomacyV2Panel");
            object native = FindElement(
                panel,
                "CrusaderDiplomacyNativeDetail");
            object ruler = FindElement(
                panel,
                "CrusaderDiplomacyV2Ruler");
            object agreement = FindElement(
                panel,
                "CrusaderDiplomacyV2Agreement");
            object attitudeTitle = FindElement(
                panel,
                "CrusaderDiplomacyV2AttitudeTitle");
            object attitudeLine1 = FindElement(
                panel,
                "CrusaderDiplomacyV2AttitudeLine1");
            object attitudeLine2 = FindElement(
                panel,
                "CrusaderDiplomacyV2AttitudeLine2");
            object gratitude = FindElement(
                panel,
                "CrusaderDiplomacyV2Gratitude");
            object respect = FindElement(
                panel,
                "CrusaderDiplomacyV2Respect");
            object reliability = FindElement(
                panel,
                "CrusaderDiplomacyV2Reliability");
            object trustCeiling = FindElement(
                panel,
                "CrusaderDiplomacyV2TrustCeiling");
            object strategicTitle = FindElement(
                panel,
                "CrusaderDiplomacyV2StrategicTitle");
            object strategicLine1 = FindElement(
                panel,
                "CrusaderDiplomacyV2StrategicLine1");
            object strategicLine2 = FindElement(
                panel,
                "CrusaderDiplomacyV2StrategicLine2");
            object threat = FindElement(
                panel,
                "CrusaderDiplomacyV2Threat");
            object dependency = FindElement(
                panel,
                "CrusaderDiplomacyV2Dependency");
            object commonEnemies = FindElement(
                panel,
                "CrusaderDiplomacyV2CommonEnemies");
            object allianceCount = FindElement(
                panel,
                "CrusaderDiplomacyV2AllianceCount");
            object demandTitle = FindElement(
                panel,
                "CrusaderDiplomacyV2DemandTitle");
            object demandLine1 = FindElement(
                panel,
                "CrusaderDiplomacyV2DemandLine1");
            object demandLine2 = FindElement(
                panel,
                "CrusaderDiplomacyV2DemandLine2");
            object actionHint = FindElement(
                panel,
                "CrusaderDiplomacyV2ActionHint");
            object primary = FindElement(
                panel,
                "CrusaderDiplomacyV2Primary");
            object primaryLabel = FindElement(
                panel,
                "CrusaderDiplomacyV2PrimaryLabel");
            object send = FindElement(
                panel,
                "CrusaderDiplomacyV2Send");
            object sendLabel = FindElement(
                panel,
                "CrusaderDiplomacyV2SendLabel");
            object orders = FindElement(
                panel,
                "CrusaderDiplomacyV2Orders");
            object ordersLabel = FindElement(
                panel,
                "CrusaderDiplomacyV2OrdersLabel");
            object breakButton = FindElement(
                panel,
                "CrusaderDiplomacyV2Break");
            object declineDemand = FindElement(
                panel,
                "CrusaderDiplomacyV2DeclineDemand");
            object declineDemandLabel = FindElement(
                panel,
                "CrusaderDiplomacyV2DeclineDemandLabel");
            object breakLabel = FindElement(
                panel,
                "CrusaderDiplomacyV2BreakLabel");
            object[] required =
            {
                advanced,
                native,
                ruler,
                agreement,
                attitudeTitle,
                attitudeLine1,
                attitudeLine2,
                gratitude,
                respect,
                reliability,
                trustCeiling,
                strategicTitle,
                strategicLine1,
                strategicLine2,
                threat,
                dependency,
                commonEnemies,
                allianceCount,
                demandTitle,
                demandLine1,
                demandLine2,
                actionHint,
                primary,
                primaryLabel,
                send,
                sendLabel,
                orders,
                ordersLabel,
                breakButton,
                breakLabel,
            };
            if (relation == null
                || relation.V2 == null
                || coalition == null
                || selectedPlayer <= 0
                || required.Any(element => element == null))
            {
                SetVisibilityIfPresent(advanced, false);
                SetVisibilityIfPresent(native, true);
                if (required.Any(element => element == null)) NotifyV2UiFallback();
                return;
            }

            UiStep("v2_texts");
            DiplomacyV2RelationState state = relation.V2;
            SetV2DetailText(ruler, V2PlayerName(selectedPlayer));
            SetProperty(ruler, "ToolTip", V2PlayerName(selectedPlayer));
            SetV2DetailText(agreement, V2StatusText(relation, coalition, selectedPlayer));
            SetV2DetailText(attitudeTitle, Text("Haltung", "Attitude"));
            SetV2DetailText(attitudeLine1, V2Metric(Text("Vertrauen", "Trust"), state.Trust));
            SetV2DetailText(gratitude, V2Metric(
                    Text("Dankbarkeit", "Gratitude"),
                    state.Gratitude));
            SetV2DetailText(respect, V2Metric(Text("Respekt", "Respect"), state.Respect));
            SetV2DetailText(attitudeLine2, V2Metric(Text("Groll", "Grudge"), state.Grudge));
            SetV2DetailText(reliability, V2Metric(
                    Text("Verlässlichkeit", "Reliability"),
                    state.Reliability));
            SetV2DetailText(trustCeiling, Text("Vertrauensgrenze ", "Trust ceiling ")
                    + V2Number(state.TrustCeiling));
            SetV2DetailText(strategicTitle, Text("Strategische Lage", "Strategic situation"));
            SetV2DetailText(strategicLine1, Text("Machtbilanz ", "Power balance ")
                    + V2SignedNumber(state.StrategicLeverage)
                    + " ("
                    + V2LeverageLevel(state.StrategicLeverage)
                    + ")");
            // The native screenshot clipped the explanation after "Ihr seid".
            // Keep the number visible and the full explanation in its tooltip.
            SetProperty(strategicLine1, "Text", Text("Machtbilanz ", "Power balance ")
                + V2SignedNumber(state.StrategicLeverage));
            SetV2DetailText(threat, Text("Bedrohung ", "Threat ")
                    + V2Number(state.StrategicThreat));
            SetV2DetailText(dependency, Text("Abhängigkeit ", "Dependency ")
                    + V2Number(state.StrategicDependency));
            SetV2DetailText(strategicLine2, Text("Koalitionswert ", "Coalition value ")
                    + V2Number(state.CoalitionValue));
            SetV2DetailText(commonEnemies, Text("Gemeinsame Gegner ", "Common enemies ")
                    + state.CommonEnemyCoalitions.ToString(
                        CultureInfo.InvariantCulture)
                    + "/"
                    + state.HostileCoalitions.ToString(
                        CultureInfo.InvariantCulture));
            SetV2DetailText(allianceCount, Text("Eure Bündnisse ", "Your alliances ")
                    + state.PlayerAllianceCount.ToString(
                        CultureInfo.InvariantCulture));

            UiStep("v2_demand");
            string[] demand = V2PanelDemandLines(relation, coalition, selectedPlayer, demandStock);
            SetV2DetailText(demandTitle, demand[0]);
            SetV2DetailText(demandLine1, demand[1]);
            SetV2DetailText(demandLine2, demand[2]);
            string actionHintText = HasPendingGoodsCommand
                ? PendingGoodsCommandStatusText() : demand[3];
            MainViewModel visibleView = MainViewModel.Instance;
            bool detailVisible = !_v2OverviewVisible && !HasPendingGoodsCommand && visibleView != null
                && visibleView.AlliesPanelVisible && visibleView.Allies_MainViewVis;
            string goodsOutcome = HasPendingGoodsCommand ? string.Empty
                : V2ShownGoodsOutcome(selectedPlayer, detailVisible);
            if (detailVisible && string.IsNullOrEmpty(goodsOutcome)) NoteV2AllyOrderStatusShown(selectedPlayer);
            string orderStatus = V2AllyOrderStatusText(selectedPlayer);
            if (!string.IsNullOrEmpty(goodsOutcome)) actionHintText = goodsOutcome + " · " + actionHintText;
            else if (!HasPendingGoodsCommand && !string.IsNullOrEmpty(orderStatus))
                actionHintText = orderStatus + " · " + actionHintText;
            SetV2DetailText(actionHint, actionHintText);
            SetProperty(actionHint, "ToolTip", actionHintText);

            bool allied = relation.Allied;
            bool breakable = allied || V2HasBreakableAgreement(relation);
            int waitDays = DiplomacyV2StateMachine.NegotiationWaitDays(
                relation,
                AbsoluteGameDay());
            bool primaryEnabled = relation.Demand != null
                ? V2CanFulfilDemand(relation.Demand, demandStock)
                : allied ? V2CanRequestGoodsFrom(selectedPlayer) : !relation.PendingOffer && waitDays == 0;
            UiStep("v2_buttons");
            RefreshV2ExtraFealtyAction(panel, relation);
            if (DiplomacyV2Submission.HasOffer(state)) primaryEnabled = false;
            SetProperty(primary, "IsEnabled", primaryEnabled);
            // Opacity ist in Noesis ein Single. SetProperty schreibt den Wert
            // ohne Umwandlung; ein Double warf dort am 06.09.2026 auf 2.80
            // "Object of type 'System.Double' cannot be converted to type
            // 'System.Single'" und riss ueber ui_refresh die ganze Diplomatie
            // mit. SetNumericProperty wandelt in den Zieltyp um.
            SetNumericProperty(
                primaryLabel,
                "Opacity",
                primaryEnabled ? 1.0 : 0.48);
            UiStep("v2_tooltip");
            SetProperty(
                primary,
                "ToolTip",
                V2RequestRolloverText(relation, selectedPlayer));
            // 10.09.2026: der ausgegraute Erfuellen-Knopf sagte nicht, warum.
            // Er liefert immer das GANZE Paket; fehlt eine Position, ist er aus.
            // Teillieferungen laufen ueber "Gueter senden" und werden auf die
            // Forderung angerechnet (GoodsDemand.ApplyDelivery).
            if (relation.Demand != null && !primaryEnabled
                && !DiplomacyV2Submission.HasOffer(state))
            {
                SetProperty(primary, "ToolTip", demandStock == null
                    ? Text("Bestand wird aktualisiert", "Updating stores")
                    : Text("Für die vollständige Erfüllung fehlen noch Vorräte.",
                        "More stores are needed to fulfil the complete package.")
                        + " " + Text("Fehlende Güter senden oder zunächst einlagern.",
                            "Send available goods or acquire the missing stores."));
            }
            // "Forderung ablehnen" erscheint nur, solange eine Forderung offen
            // ist - und auch bei Fuersten ohne Buendnis.
            bool declinable = relation.Demand != null
                && !DiplomacyV2Submission.HasOffer(state);
            SetVisibilityIfPresent(declineDemand, declinable);
            SetVisibilityIfPresent(declineDemandLabel, declinable);
            if (declineDemand != null)
            {
                SetProperty(declineDemand, "IsEnabled", declinable && !HasPendingGoodsCommand);
                SetProperty(declineDemand, "ToolTip",
                    Text("Die Forderung zurückweisen. Das kostet Ansehen, aber nie das Bündnis.",
                        "Reject the demand. It costs standing, never the alliance."));
            }
            SetV2DetailText(declineDemandLabel,
                Text("Forderung ablehnen", "Decline demand"));
            SetV2DetailText(primaryLabel, V2PrimaryActionLabel(relation, selectedPlayer));
            SetV2DetailText(sendLabel, Text("Güter senden", "Send goods"));
            SetV2DetailText(ordersLabel, Text("Befehle", "Orders"));
            SetV2DetailText(breakLabel, allied
                    ? Text("Bündnis lösen", "End alliance")
                    : Text("Abkommen lösen", "End agreement"));
            UiStep("v2_visibility");
            SetVisibility(orders, allied);
            SetVisibility(ordersLabel, allied);
            SetVisibility(breakButton, breakable);
            SetVisibility(breakLabel, breakable);
            SetVisibilityIfPresent(
                FindElement(panel, "EuropeDiplomacyBreak"),
                false);
            SetVisibility(native, false);
            SetVisibility(advanced, true);
            RefreshV2TradePanel(panel, selectedPlayer);
            // Die Uebersicht liegt ueber der Detailtafel; ist sie offen,
            // bleibt die Detailtafel darunter unsichtbar.
            RefreshV2OverviewPanel(panel);
        }

        private static void SetV2DetailText(object element, string text)
        {
            SetProperty(element, "Text", text);
            SetProperty(element, "ToolTip", text);
        }

        private void NotifyV2UiFallback()
        {
            _v2OverviewVisible = false;
            if (_v2UiPanelWarningLogged) return;
            _v2UiPanelWarningLogged = true;
            Log("ui_integration", "status=v2_detail_degraded|reason=display_unavailable");
            ShowMessage(Text("Die Diplomatieansicht ist nicht verfügbar. Die Grundansicht bleibt geöffnet; Bündnis- und Lehnsverwaltung fehlen.",
                "The diplomacy view is unavailable. The basic view remains open; alliance and fealty management are unavailable."));
        }



        private string[] V2PanelDemandLines(
            RelationState relation,
            CoalitionState coalition, int player = 0, Dictionary<int, int> stock = null)
        {
            GoodsDemand demand = relation.Demand;
            if (DiplomacyV2Submission.HasOffer(relation.V2))
            {
                bool accepted = relation.V2.SubmissionAcceptancePending || relation.V2.SubmissionOfferAccepted;
                return new[]
                {
                    accepted ? Text("Unterwerfung bestätigt", "Submission accepted")
                        : Text("Unterwerfungsangebot", "Offer of submission"),
                    V2FealtyTerms(relation.V2.SubmissionOfferTributeAmount),
                    accepted ? string.Empty : string.Format(CultureInfo.InvariantCulture,
                        Text("Antwortfrist: {0} Spieltage.", "Response time: {0} game days."),
                        relation.V2.SubmissionResponseDaysRemaining),
                    accepted ? string.Empty : Text("Angebot prüfen", "Review offer"),
                };
            }
            if (demand == null)
            {
                if (V2IsFealtyCounterpart(relation.V2, player))
                    return new[]
                    {
                        Text("Lehnsverhältnis", "Fealty"),
                        V2AllianceObligation(relation, AbsoluteGameDay(), player),
                        V2TributeLedgerText(relation.V2),
                        string.Empty,
                    };
                return new[]
                {
                    Text("Diplomatische Möglichkeiten", "Diplomatic options"),
                    V2ActionHint(relation, coalition),
                    V2PersistentHistoryText(relation.V2),
                    V2RequestRolloverText(relation, player)
                        + Text(
                            " · Gezielte Geschenke bleiben möglich.",
                            " · Targeted gifts remain available."),
                };
            }
            var items = demand.Items
                .Where(item => item != null && item.RemainingAmount > 0)
                .Select(item => V2DemandItemPanelText(item, stock))
                .ToList();
            while (items.Count < 3)
            {
                items.Add(string.Empty);
            }
            bool ready = V2CanFulfilDemand(demand, stock);
            if (string.IsNullOrEmpty(items[1]))
            {
                items[1] = stock == null ? Text("Bestand wird aktualisiert", "Updating stores") : ready
                    ? Text(
                        "Das vollständige Paket liegt in Euren Lagern bereit.",
                        "The complete package is available in your stores.")
                    : Text(
                        "Für die vollständige Erfüllung fehlen noch Vorräte.",
                        "More stores are needed to fulfil the complete package.");
            }
            string third = string.IsNullOrEmpty(items[2])
                ? (stock == null ? Text("Bestand wird aktualisiert", "Updating stores") : ready
                    ? Text(
                        "Mit einem Klick vollständig liefern.",
                        "Deliver everything with one click.")
                    : Text(
                        "Fehlende Güter senden oder zunächst einlagern.",
                        "Send available goods or acquire the missing stores."))
                : items[2];
            return new[]
            {
                V2DemandPurposeName(demand.V2Purpose)
                    + " · "
                    + V2DurationText(
                        demand.ExpiresDay - AbsoluteGameDay()),
                items[0],
                items[1],
                third,
            };
        }

        // 08.09.2026: der Lagerstand wurde bei jeder Aktualisierung frisch
        // nativ gelesen, und ein misslungener Lesezugriff loeschte die ganze
        // Anzeige. Eine beschaeftigte Engine ist aber der Normalfall, nicht die
        // Ausnahme: die Bestaende sprangen sichtbar zwischen Zahl und "?", und
        // weil V2CanFulfilDemand ohne Momentaufnahme false liefert, verschwand
        // der Erfuellen-Knopf im selben Takt - er war nur zufaellig zu treffen.
        // Der zuletzt gelesene Stand bleibt deshalb stehen, bis ein neuer
        // Lesezugriff gelingt. Er kann wenige Takte alt sein; das ist harmlos,
        // weil die Erfuellung selbst nativ nachprueft und fehlende Ware sauber
        // meldet. Ueber eine Karten- oder Sitzungsgrenze wird nie getragen.
        private Dictionary<int, int> _v2DemandStockLastKnown;
        private long _v2DemandStockEpoch = -1;
        private long _v2DemandStockGeneration = -1;

        private Dictionary<int, int> V2DemandStockFallback()
        {
            if (_v2DemandStockLastKnown == null
                || _v2DemandStockEpoch != Volatile.Read(ref _mapEpoch)
                || _v2DemandStockGeneration != Volatile.Read(ref _sessionGeneration))
                return null;
            return _v2DemandStockLastKnown;
        }

        private Dictionary<int, int> V2DemandStockSnapshot(GoodsDemand demand)
        {
            if (demand == null || demand.Items == null) return null;
            Dictionary<int, int> known = V2DemandStockFallback();
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease)) return known;
            using (lease)
            {
                var stock = new Dictionary<int, int>();
                foreach (DemandItem item in demand.Items)
                {
                    if (item == null || item.RemainingAmount <= 0 || stock.ContainsKey(item.GoodId)) continue;
                    int available;
                    // Ein echter Lesefehler bleibt ein Fehler: er koennte auf
                    // eine kaputte Lage deuten, und eine halb gelesene Aufnahme
                    // darf nie als vollstaendig durchgehen. Nur die BESETZTE
                    // Engine oben - der haeufige, harmlose Fall - haelt den
                    // letzten Stand.
                    if (!TryReadTransferAmount(_localPlayer, item.GoodId, out available)) return null;
                    stock.Add(item.GoodId, available);
                }
                _v2DemandStockLastKnown = stock;
                _v2DemandStockEpoch = Volatile.Read(ref _mapEpoch);
                _v2DemandStockGeneration = Volatile.Read(ref _sessionGeneration);
                return stock;
            }
        }

        private string V2DemandItemPanelText(DemandItem item, Dictionary<int, int> stock)
        {
            int available = 0;
            bool known = stock != null && stock.TryGetValue(item.GoodId, out available);
            return GoodName(item.GoodId, item.RequiredAmount)
                + Text(" · geliefert ", " · delivered ")
                + item.DeliveredAmount.ToString(CultureInfo.InvariantCulture)
                + "/"
                + item.RequiredAmount.ToString(CultureInfo.InvariantCulture)
                + Text(" · offen ", " · due ")
                + item.RemainingAmount.ToString(CultureInfo.InvariantCulture)
                + Text(" · Lager ", " · stores ")
                + (known
                    ? available.ToString(CultureInfo.InvariantCulture)
                    : "?");
        }

        private bool V2CanFulfilDemand(GoodsDemand demand, Dictionary<int, int> stock)
        {
            if (stock == null || demand == null
                || demand.Items == null
                || demand.Items.Length == 0)
            {
                return false;
            }
            bool hasOutstandingItem = false;
            foreach (DemandItem item in demand.Items)
            {
                int available;
                if (item == null)
                {
                    return false;
                }
                if (item.RemainingAmount <= 0)
                {
                    continue;
                }
                hasOutstandingItem = true;
                if (!stock.TryGetValue(item.GoodId, out available)
                    || available < item.RemainingAmount)
                {
                    return false;
                }
            }
            return hasOutstandingItem;
        }

        private string V2DemandPurposeName(DiplomacyV2DemandPurpose purpose)
        {
            switch (purpose)
            {
                case DiplomacyV2DemandPurpose.Courtship:
                    return Text("Bedingungen zur Waffenruhe", "Truce terms");
                case DiplomacyV2DemandPurpose.TradeProof:
                    return Text("Bedingungen zum Handel", "Trade terms");
                case DiplomacyV2DemandPurpose.AllianceTerms:
                    return Text("Bündnisbedingungen", "Alliance terms");
                case DiplomacyV2DemandPurpose.Support:
                    return Text("Unterstützungsersuchen", "Support request");
                case DiplomacyV2DemandPurpose.Ultimatum:
                    return Text("Ultimatum", "Ultimatum");
                case DiplomacyV2DemandPurpose.Restitution:
                    return Text("Wiedergutmachung", "Restitution");
                default:
                    return Text("Forderung", "Demand");
            }
        }

        private string V2PersistentHistoryText(
            DiplomacyV2RelationState state)
        {
            if (state.BrokenAgreements == 0
                && state.TreacherousAttacks == 0
                && state.MilitaryIncursions == 0
                && state.ObservedAllianceAbandonments == 0)
            {
                return Text(
                    "Keine dauerhaften Vertragsbrüche vermerkt.",
                    "No lasting treaty breaches are recorded.");
            }
            return Text("Vertragsgedächtnis · Brüche ",
                    "Treaty memory · breaches ")
                + state.BrokenAgreements.ToString(
                    CultureInfo.InvariantCulture)
                + Text(" · Vertragsbruchangriffe ", " · treaty-breaking attacks ")
                + state.TreacherousAttacks.ToString(
                    CultureInfo.InvariantCulture)
                + Text(" · Grenzverletzungen ", " · incursions ")
                + state.MilitaryIncursions.ToString(
                    CultureInfo.InvariantCulture)
                + Text(" · beobachteter Verrat ", " · observed betrayals ")
                + state.ObservedAllianceAbandonments.ToString(
                    CultureInfo.InvariantCulture);
        }

        private string V2PrimaryActionLabel(RelationState relation, int player = 0)
        {
            if (DiplomacyV2Submission.HasOffer(relation.V2))
                return relation.V2.SubmissionAcceptancePending || relation.V2.SubmissionOfferAccepted
                    ? Text("Unterwerfung bestätigt", "Submission accepted")
                    : Text("Entscheidung offen", "Decision pending");
            if (relation.Demand != null)
            {
                return Text("Forderung erfüllen", "Fulfil demand");
            }
            if (relation.Allied)
            {
                if (V2IsFealtyCounterpart(relation.V2, player)
                    && DiplomacyV2Vassalage.OverlordOf(relation.V2) == _localPlayer)
                    return Text("Güter anfordern", "Request supplies");
                return Text("Güter erbitten", "Request goods");
            }
            if (relation.PendingOffer)
            {
                return Text("Entscheidung offen", "Decision pending");
            }
            if (DiplomacyV2StateMachine.NegotiationWaitDays(
                    relation,
                    AbsoluteGameDay()) > 0)
            {
                return Text("Gesandte warten", "Envoys waiting");
            }
            if (relation.V2.RestitutionOutstandingValue > 0m)
            {
                return Text("Wiedergutmachung", "Restitution");
            }
            switch (relation.V2.Agreement)
            {
                case DiplomacyV2AgreementKind.Truce:
                    return Text("Handel anfragen", "Request trade");
                case DiplomacyV2AgreementKind.TradePact:
                    return relation.V2.AllianceTermsFulfilled
                        ? Text("Bündnis prüfen", "Review alliance")
                        : Text("Bündnis anfragen", "Request alliance");
                default:
                    return Text("Waffenruhe erbitten", "Request truce");
            }
        }

        private string V2Metric(string label, decimal value)
        {
            return label + " " + V2Number(value)
                + " (" + V2Level(value) + ")";
        }

        private static string V2Number(decimal value)
        {
            return decimal.Round(
                    value,
                    0,
                    MidpointRounding.AwayFromZero)
                .ToString("0", CultureInfo.InvariantCulture);
        }

        private static string V2SignedNumber(decimal value)
        {
            decimal rounded = decimal.Round(
                value,
                0,
                MidpointRounding.AwayFromZero);
            return (rounded > 0m ? "+" : string.Empty)
                + rounded.ToString("0", CultureInfo.InvariantCulture);
        }

        private string V2LeverageLevel(decimal value)
        {
            if (value <= -35m)
            {
                return Text(
                    "Gegner deutlich stärker",
                    "opponent much stronger");
            }
            if (value <= -12m)
            {
                return Text("Gegner stärker", "opponent stronger");
            }
            if (value < 12m)
            {
                return Text("ausgeglichen", "balanced");
            }
            if (value < 35m)
            {
                return Text("Ihr seid stärker", "you are stronger");
            }
            return Text(
                "Ihr seid deutlich stärker",
                "you are much stronger");
        }

        private string V2PersonalityName(DiplomacyV2PersonalityKind kind)
        {
            switch (kind)
            {
                case DiplomacyV2PersonalityKind.Honorable:
                    return Text("ehrenhaft", "honorable");
                case DiplomacyV2PersonalityKind.Mercantile:
                    return Text("händlerisch", "mercantile");
                case DiplomacyV2PersonalityKind.Wary:
                    return Text("vorsichtig", "wary");
                case DiplomacyV2PersonalityKind.Warlike:
                    return Text("kriegerisch", "warlike");
                case DiplomacyV2PersonalityKind.Opportunistic:
                    return Text("opportunistisch", "opportunistic");
                case DiplomacyV2PersonalityKind.Loyal:
                    return Text("treu", "loyal");
                default:
                    return Text("fordernd", "demanding");
            }
        }

        private string V2Level(decimal value)
        {
            string level = value < 20m
                ? Text("sehr gering", "very low")
                : value < 40m
                    ? Text("gering", "low")
                    : value < 60m
                        ? Text("mittel", "moderate")
                        : value < 80m
                            ? Text("hoch", "high")
                            : Text("sehr hoch", "very high");
            return level;
        }

        private void RegisterV2LegacySaveImport()
        {
            if (!ModSaveDataAPI.Instance.RegisterModDataHandler(
                DiplomacyV2Contract.LegacySaveDataIdentifier,
                SaveV2LegacyData,
                LoadV2LegacyData))
            {
                throw new InvalidOperationException(
                    "legacy diplomacy save-data identifier is already registered");
            }
            _v2LegacySaveHandlerRegistered = true;
        }

        private void UnregisterV2LegacySaveImport()
        {
            if (!_v2LegacySaveHandlerRegistered)
            {
                return;
            }
            _v2LegacySaveHandlerRegistered = false;
            ModSaveDataAPI.Instance.UnregisterModDataHandler(
                DiplomacyV2Contract.LegacySaveDataIdentifier);
        }

        private byte[] SaveV2LegacyData(SaveContext context)
        {
            NoteLane(LaneSave);
            lock (_gate)
            {
                if (context == null || !context.IsSaveFile)
                {
                    return null;
                }
                if (_saveSuppressed)
                {
                    return DiplomacySaveCodec.SerializeInactive("primary_save_suppressed");
                }
                try
                {
                    bool recoveryOnly = _mapDisabled
                        && (_nativeTransferProbe != null
                            || _disabledTeamRecoveryPending)
                        && _coalitions.Count > 0
                        && _relations.Count == _coalitions.Count
                        && _roster.Count > 1;
                    if ((!_mapActive && !recoveryOnly)
                        || (_mapDisabled && !recoveryOnly))
                    {
                        return DiplomacySaveCodec.SerializeInactive("map_inactive");
                    }
                    DiplomacySaveV1 state;
                    if (_stableSavePayload != null)
                    {
                        state = DiplomacySaveV2Codec.Deserialize(
                            _stableSavePayload,
                            _rules);
                    }
                    else
                    {
                        PumpV2HumanWarIntents(false);
                        state = recoveryOnly
                            ? SnapshotRecoverySave()
                            : SnapshotSave();
                    }
                    // V1 cannot express a foreign payer or tribute bookkeeping.
                    // Overwrite its archive entry explicitly instead of retaining
                    // an older journal or inventing a pre-transfer native state.
                    if (state.PendingTransfer != null
                        && (state.PendingTransfer.Purpose == DiplomacyTransferPurpose.Tribute
                            || state.PendingTransfer.DirectAtomicTransfer
                            || state.PendingTransfer.SenderPlayer > 0
                                && state.PendingTransfer.SenderPlayer != state.LocalPlayerId))
                    {
                        return DiplomacySaveCodec.SerializeInactive("requires_v2_transfer_recovery");
                    }
                    // Keep the legacy slot current as a genuine rollback path.
                    // The projection strips only concepts V1 cannot represent,
                    // normalises its shorter deadlines, and retains inventories,
                    // teams, transfer journals and final/support demand progress.
                    DiplomacySaveV1 projection =
                        DiplomacySaveV2Codec.BuildV1CompatibilityProjection(
                            state,
                            _rules);
                    byte[] payload = DiplomacySaveCodec.Serialize(
                        projection,
                        _rules);
                    Log("saving", "status=v1_compat_saved|bytes="
                        + payload.Length.ToString(CultureInfo.InvariantCulture));
                    return payload;
                }
                catch (Exception exception)
                {
                    // This optional V1 projection cannot invalidate a valid V2 save.
                    Log("saving", "status=v1_compat_inactive|reason="
                        + exception.GetType().Name);
                    return DiplomacySaveCodec.SerializeInactive("legacy_serialize_failed");
                }
            }
        }

        private void LoadV2LegacyData(byte[] payload, LoadContext context)
        {
            NoteLane(LaneSave);
            lock (_gate)
            {
                if (context == null || !context.IsSaveFile)
                {
                    return;
                }
                _v2PendingLegacySavePayload = payload == null
                    ? null
                    : (byte[])payload.Clone();
                _v2PendingLegacySaveEpoch = payload == null ? -1 : _mapEpoch;
                _v2PendingLegacySaveTick = payload == null
                    ? -1
                    : _featureTicks;
                Log("saving", "status=v1_import_staged|bytes="
                    + (payload == null ? "0" : payload.Length.ToString(
                        CultureInfo.InvariantCulture)));
            }
        }

        private void ReconcileV2LegacySaveEpoch()
        {
            if (_v2PendingLegacySavePayload == null
                || _v2PendingLegacySaveEpoch == _mapEpoch)
            {
                return;
            }
            if (_v2PendingLegacySaveTick == _featureTicks)
            {
                _v2PendingLegacySaveEpoch = _mapEpoch;
                return;
            }
            DiscardV2PendingLegacySave("save_load_epoch");
        }

        private void BeginV2LegacyMapEpoch(long previousEpoch)
        {
            if (_v2PendingLegacySavePayload != null
                && _v2PendingLegacySaveEpoch == previousEpoch
                && _v2PendingLegacySaveTick < _featureTicks)
            {
                DiscardV2PendingLegacySave("native_epoch");
            }
        }

        private byte[] StageV2LegacySaveForBootstrap()
        {
            return _v2PendingLegacySaveEpoch == _mapEpoch
                ? _v2PendingLegacySavePayload
                : null;
        }

        private void ConsumeV2PendingLegacySave()
        {
            _v2PendingLegacySavePayload = null;
            _v2PendingLegacySaveEpoch = -1;
            _v2PendingLegacySaveTick = -1;
        }

        private void DiscardV2PendingLegacySave(string trigger)
        {
            _v2PendingLegacySavePayload = null;
            _v2PendingLegacySaveEpoch = -1;
            _v2PendingLegacySaveTick = -1;
            Log("saving", "status=v1_import_stale_discarded|trigger="
                + Safe(trigger));
        }

        private void RestoreV2LegacySave(byte[] legacyPayload)
        {
            byte[] migrated = DiplomacySaveV2Codec.MigrateLegacyPayload(
                legacyPayload,
                _rules);
            RestoreSave(migrated);
            RebindV2MigratedPersonalities();
            Log("saving", "status=v1_import_migrated|source_bytes="
                + legacyPayload.Length.ToString(CultureInfo.InvariantCulture)
                + "|v2_bytes="
                + migrated.Length.ToString(CultureInfo.InvariantCulture));
        }

        private void RestoreV2PrimaryOrLegacySave(
            byte[] primaryPayload,
            byte[] legacyPayload)
        {
            bool usedLegacy;
            string primaryFailureKind;
            byte[] selected =
                DiplomacySaveV2Codec.SelectPrimaryOrLegacyLoadPayload(
                    primaryPayload,
                    legacyPayload,
                    _rules,
                    out usedLegacy,
                    out primaryFailureKind);
            RestoreSave(selected);
            if (!usedLegacy)
            {
                return;
            }
            RebindV2MigratedPersonalities();
            Log(
                "saving",
                "status=v2_primary_recovered_from_v1"
                + "|primary_failure=" + Safe(primaryFailureKind)
                + "|source_bytes=" + legacyPayload.Length.ToString(
                    CultureInfo.InvariantCulture)
                + "|v2_bytes=" + selected.Length.ToString(
                    CultureInfo.InvariantCulture));
        }

        private void RebindV2MigratedPersonalities()
        {
            foreach (CoalitionState coalition in _coalitions.Values)
            {
                RelationState relation = _relations[coalition.CoalitionId];
                DiplomacyV2PersonalitySignal signal =
                    SelectV2CoalitionPersonalitySignal(coalition);
                DiplomacyV2Personality profile =
                    DiplomacyV2PersonalityCatalog.SelectForLord(signal);
                DiplomacyV2StateMachine.RebindPersonality(
                    relation,
                    profile.Kind,
                    signal.LordId,
                    coalition.Target);
            }
        }

        private void ResetV2RuntimeMapState()
        {
            ClearV2SubmissionPressure();
            ResetV2GoodsRequests();
            ResetV2GoodsOutcomes();
            _v2VassalageFaultsByCoalition.Clear();
            _v2EqualityPresentedDays.Clear();
            ResetV2SubmissionPresentation();
            _v2TributeTechnicalFaults.Clear();
            _v2IncursionLogLines = 0;
            _v2StandoffRetryTick = 0;
            _v2StandoffFaultsPending = 0;
            _v2LocalPowerTick = long.MinValue;
            _v2LocalEconomy = 0L;
            _v2LocalMilitary = 0L;
            ClearV2DeferredNotices();
            _v2LastIncursionScanTick =
                DiplomacyV2CombatRules.NeverScannedTick;
            _v2LastHostileAttributionTick =
                DiplomacyV2CombatRules.NeverScannedTick;
            ClearV2TreatyStandoff();
            _v2TreatyStandoffDegraded = false;
            _v2StandoffMovesBlocked = 0;
            _v2StandoffLogLines = 0;
            ResetV2ProbeState();
            _v2UiPanelWarningLogged = false;
        }
    }
}
#endif
