#if DIPLOMACY_V2
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using CrusaderDE;
using SHCDESE.API;
using SHCDESE.Interop;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private DiplomacyV2TradeBook _v2TradeBook;
        private bool _v2TradeEditorOpen;
        private int _v2TradeEditorTarget;
        private int _v2TradeOfferGood=2;
        private int _v2TradeRequestGood=4;
        private int _v2TradeOfferAmount=10;
        private int _v2TradeRequestAmount=10;
        private long _v2TradeAnswerOffer;
        private long _v2TradeEditorGeneration;

        private sealed class LiveTradeWorld : IDiplomacyV2NativeTradePort
        {
            private readonly DiplomacyFeature _owner;
            internal LiveTradeWorld(DiplomacyFeature owner) { _owner=owner; }

            public bool IsEngineSectionHeld
            {
                get { return IsNativeDiplomacySectionHeld; }
            }
            public bool IsAlive(int player)
            {
                return player>=1 && player<=8 && _owner.IsAlivePlayer(player);
            }
            public bool IsHuman(int player)
            {
                try
                {
                    var game = GameData.Instance.lastGameState;
                    return player>=1 && player<=8 && game!=null
                        && !game.is_skirmish_player(player);
                }
                catch { return true; } // Unknown authority requires human confirmation.
            }
            public bool CanTrade(int a,int b,int day)
            {
                if (a==b || !IsAlive(a) || !IsAlive(b))return false;
                if (a==_owner._localPlayer || b==_owner._localPlayer)
                {
                    int other = a==_owner._localPlayer ? b : a;
                    string id; RelationState relation;
                    if (!_owner._playerCoalition.TryGetValue(other,out id)
                        || !_owner._relations.TryGetValue(id,out relation))
                        return false;
                    // The original native team can remain hostile while a
                    // neutral trade pact is active; v2 treaty state governs.
                    return DiplomacyV2TradeRules.CanTrade(relation,day,
                        false,IsAlive(a)&&IsAlive(b));
                }
                // Only allied AI pairs have native mutual authority here.
                // Cross-client human trading requires the official Chore
                // protocol; never synthesize remote players' consent.
                if (IsHuman(a) || IsHuman(b)) return false;
                return _owner.NativePlayersAreAllied(a,b);
            }
            public bool TryReadStock(int player,int good,out int amount)
            {
                amount=0;
                if (!IsEngineSectionHeld || !IsAlive(player)
                    || !DiplomacyV2TradeRules.IsAllowedGood(good))return false;
                return _owner.TryReadTransferAmount(player,good,out amount);
            }
            public int SafetyReserve(int player,int good)
            {
                // No fabricated production forecasts. Use native AIC buy/
                // sell thresholds as conservative reservation requirements.
                if (IsHuman(player))return 0;
                int lord;
                if (!_owner._capturedLordIds.TryGetValue(player,out lord)
                    || lord<0 || lord>=ScriptExtenderNativeBridge.AicCount())
                    return int.MaxValue; // Unknown AI must not give its stocks.
                InternalAIC aic=ScriptExtenderNativeBridge.Aic(lord);
                switch(good)
                {
                    case 2: return Math.Max(0,aic.trade_wood_at);
                    case 4: return Math.Max(0,aic.trade_stone_at);
                    case 6: return Math.Max(0,aic.trade_resources_at);
                    case 7: return Math.Max(0,aic.trade_pitch_at);
                    case 9: return Math.Max(0,aic.buy_wheat_at);
                    case 10: return Math.Max(0,aic.trade_flour_at);
                    case 11: return Math.Max(0,aic.buy_hops_at);
                    case 12: return Math.Max(0,aic.trade_ale_at);
                    case 13: return Math.Max(0,aic.buy_apples_at);
                    case 14: return Math.Max(0,aic.buy_cheese_at);
                    case 15: return Math.Max(0,aic.base_gold_reserves);
                    default:
                        return good>=17 && good<=24
                            ? Math.Max(0,Math.Max(aic.buy_weapons,aic.trade_weapons_at))
                            : 0;
                }
            }
            public int MarketUnitValue(int good)
            {
                int value;
                return _owner._frozenPrices.TryGetValue(good,out value)
                    && value>0 ? value : 0;
            }
            public bool TryReadStorageRoom(int player,int good,out int room)
            {
                room=0;
                if (!IsEngineSectionHeld || !IsAlive(player)
                    || !DiplomacyV2TradeRules.IsAllowedGood(good))return false;
                try
                {
                    int stock;
                    if (!TryReadStock(player,good,out stock))return false;
                    if (good==DiplomacyV2TradeRules.GoldGoodId)
                    {
                        // Native player gold is signed integer, NOT a storage
                        // good. This is an arithmetic upper bound, not a
                        // fabricated ware-ID or stockpile slot.
                        room=int.MaxValue-stock;
                        return true;
                    }
                    // Conservative proven lower bound: only matching goods
                    // actually stored in real, awake storage buildings can
                    // claim free stack space. Empty or ambiguous buildings
                    // are not silently assumed to accept this commodity.
                    GameBuildingManagerAPI buildings=GameBuildingManagerAPI.Instance;
                    long free=0;
                    foreach (int id in buildings.GetAllAliveBuildings())
                    {
                        if (buildings.GetOwner(id)!=player || buildings.IsSleeping(id))
                            continue;
                        eStructs type=buildings.GetType(id);
                        if (type!=eStructs.STRUCT_GOODS_YARD
                            && type!=eStructs.STRUCT_GRANARY
                            && type!=eStructs.STRUCT_ARMOURY)
                            continue;
                        if (buildings.GetLocalStorage(id,(eGoods)good)<=0)
                            continue;
                        int maximum=buildings.GetMaxGoodStackAmount(id);
                        int occupied=buildings.GetCurrentGoodStackAmount(id);
                        if (maximum<=0 || occupied<0 || occupied>maximum)
                            return false;
                        free+=Math.Max(0,maximum-occupied);
                        if (free>int.MaxValue-stock)free=int.MaxValue-stock;
                    }
                    room=(int)free;
                    return true;
                }
                catch { return false; }
            }
            public void ChangeAmount(int player,int good,int delta)
            {
                if (!IsEngineSectionHeld || !IsAlive(player)
                    || !DiplomacyV2TradeRules.IsAllowedGood(good))
                    throw new InvalidOperationException("unauthorized trade inventory mutation");
                _owner.ChangeTransferAmount(player,good,delta);
            }
        }

        private DiplomacyV2TradeBook V2TradeBook()
        {
            if (string.IsNullOrWhiteSpace(_mapFingerprint))
                throw new InvalidOperationException("diplomacy map is not initialized");
            if (_v2TradeBook==null)
            {
                _v2TradeBook=new DiplomacyV2TradeBook();
                _v2TradeBook.StartNewMap(_mapFingerprint);
            }
            if (!string.Equals(_v2TradeBook.MapFingerprint,
                _mapFingerprint,StringComparison.Ordinal))
                throw new InvalidOperationException("trade ledger belongs to another map");
            return _v2TradeBook;
        }

        private bool V2MayChangeInventory()
        {
            return _mapActive && !_mapDisabled && !_mapBootstrapPending
                && !_inventoryRestorePending && !_goodsTransfersUnavailable
                && _pendingPackage==null && _nativeTransferProbe==null
                && _pendingTeamTransition==null;
        }

        private void RecoverV2TradeJournal()
        {
            if (_v2TradeBook==null || _v2TradeBook.NativeJournal==null)return;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))
            {
                _goodsTransfersUnavailable=true;
                return;
            }
            using(lease)
            {
                DiplomacyV2TradeNativeJournal journal=_v2TradeBook.NativeJournal;
                var world=new LiveTradeWorld(this);
                if (journal.FullyApplied(world))
                {
                    // Validated exact four-cell receipt after load. Nothing
                    // replays or grants a second payment.
                    _v2TradeBook.NativeRecoveryPending=false;
                    _v2TradeBook.RecoveryOfferId=0L;
                    DiplomacyV2TradeQuote quote=_v2TradeBook.Find(journal.OfferId);
                    if (quote.Phase==DiplomacyV2TradePhase.RecoveryRequired)
                        quote.Phase=DiplomacyV2TradePhase.Settling;
                    _v2TradeBook.MarkCompleted(journal.OfferId,
                        Math.Max(journal.StartedDay,_lastProcessedDay));
                    _goodsTransfersUnavailable=false;
                    return;
                }
                string error;
                if (journal.TryRollback(world,out error))
                {
                    if (!_v2TradeBook.NativeRecoveryPending)
                        _v2TradeBook.MarkRecovery(journal.OfferId,
                            "interrupted_trade_recovered");
                    _v2TradeBook.MarkRollbackComplete(journal.OfferId);
                    _goodsTransfersUnavailable=false;
                    return;
                }
                if (!_v2TradeBook.NativeRecoveryPending)
                    _v2TradeBook.MarkRecovery(journal.OfferId,
                        error??"unresolved_trade_inventory");
                _goodsTransfersUnavailable=true;
                Log("trade","status=recovery_required|reason="+Safe(error));
            }
        }

        private void SettleV2Trade(long offerId,LiveTradeWorld world,int day)
        {
            if (!V2MayChangeInventory())return;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))return;
            using(lease)
            {
                DiplomacyV2TradeBook book=V2TradeBook();
                // No cached or UI-only quote may reach the native stock calls.
                if (!book.MarkSettling(offerId,day,world))
                {
                    DiplomacyV2TradeQuote pending=book.Find(offerId);
                    string reason;
                    if (pending!=null && !DiplomacyV2TradeRules.CanSettle(
                        pending,world,day,out reason))
                        _v2TradeStatus=Text("Buchung ausstehend: ",
                            "Settlement pending: ")+Safe(reason);
                    return;
                }
                try
                {
                    DiplomacyV2TradeNativeJournal.Apply(book.NativeJournal,world);
                    if (!book.NativeJournal.FullyApplied(world))
                        throw new InvalidOperationException("four-cell trade receipt unverified");
                    book.MarkCompleted(offerId,day);
                    _inventoryRecoveryBaseState=null;
                    Log("trade","status=settled|id="
                        +offerId.ToString(CultureInfo.InvariantCulture));
                    // Never construct or display Noesis UI under the native
                    // engine monitor. The next safe UI refresh shows receipt.
                    _v2TradeStatus=Text(
                        "Beide Handelsleistungen wurden im Spielbestand bestätigt.",
                        "Both trade deliveries are confirmed in the game.");
                }
                catch(Exception error)
                {
                    DiplomacyV2TradeNativeJournal journal=book.NativeJournal;
                    string failed;
                    bool restored=journal.TryRollback(world,out failed);
                    book.MarkRecovery(offerId,restored
                        ? "native_trade_rolled_back" : failed);
                    if (restored) book.MarkRollbackComplete(offerId);
                    else _goodsTransfersUnavailable=true;
                    _v2TradeStatus=restored
                        ? Text("Tausch nicht abgeschlossen; alle eigenen Buchungen zurückgenommen.",
                            "Trade did not complete; its own writes were rolled back.")
                        : Text("Tausch angehalten: manuelle Wiederherstellung prüfen.",
                            "Trade paused: check unresolved native recovery.");
                    Log("trade","status="
                        +(restored?"rolled_back":"recovery_required")
                        +"|reason="+Safe(error.GetType().Name));
                }
            }
        }

        private void PumpV2TradesSafely()
        {
            try { PumpV2Trades(); }
            catch (Exception exception)
            {
                // A failing external storage hook must not disable the whole
                // diplomacy lane. If even one native cell was attempted, the
                // journal stays persisted and all transfers remain blocked.
                if (_v2TradeBook!=null && _v2TradeBook.NativeJournal!=null)
                    _goodsTransfersUnavailable=true;
                _v2TradeStatus=Text("Handel angehalten: Spielzustand nicht gesichert.",
                    "Trade paused: inventory state is not verified.");
                Log("trade","status=degraded|reason="+Safe(exception.GetType().Name));
            }
        }

        private void PumpV2Trades()
        {
            if (!_mapActive || _mapDisabled || _mapBootstrapPending
                || string.IsNullOrWhiteSpace(_mapFingerprint))return;
            DiplomacyV2TradeBook book=V2TradeBook();
            if (book.NativeJournal!=null)
            {
                RecoverV2TradeJournal();
                if (book.NativeJournal!=null)return;
            }
            if (!V2MayChangeInventory())return;
            IDisposable lease;
            if (!TryEnterNativeInventorySection(out lease))return;
            using(lease) PumpV2TradesUnderNativeLease(book);
        }

        private void PumpV2TradesUnderNativeLease(DiplomacyV2TradeBook book)
        {
            RequireNativeDiplomacySection();
            LiveTradeWorld world=new LiveTradeWorld(this);
            int day=Math.Max(0,_lastProcessedDay);
            ProcessV2TradeUiUnderLease(world,day);
            DiplomacyV2TradeQuote[] due=book.Tick(ReadSimulationTick(),day,world);
            foreach (DiplomacyV2TradeQuote offered in due)
            {
                if (!world.IsAlive(offered.FromPlayer)
                    || !world.IsAlive(offered.ToPlayer))continue;
                RelationState relation=V2TradeRelationFor(
                    offered.FromPlayer,offered.ToPlayer);
                DiplomacyV2RelationState profile=relation==null?null:relation.V2;
                bool accepted=DiplomacyV2TradeRules.AiAccepts(
                    offered,world,profile,day);
                if (accepted)
                {
                    book.Reply(offered.Id,offered.ToPlayer,true,
                        world,day,false);
                }
                else if (!V2ProposeAiCounter(offered,world,day))
                {
                    // A counter must replace a still-pending quote. Marking
                    // it declined first used to make Counter() reject it.
                    book.Reply(offered.Id,offered.ToPlayer,false,world,day,false);
                }
            }
            // A legal answer does not mean a settled inventory. Recheck each
            // accepted quote on later simulation frames until the four-cell
            // native receipt succeeds or the offer expires. Never pay twice.
            foreach (long acceptedId in book.Offers
                .Where(q=>q.Phase==DiplomacyV2TradePhase.Accepted)
                .OrderBy(q=>q.Id).Select(q=>q.Id).ToArray())
                SettleV2Trade(acceptedId,world,day);
            V2PlanAiToAiTrades(world,day);
        }

        private RelationState V2TradeRelationFor(int a,int b)
        {
            int foreign=a==_localPlayer?b:b==_localPlayer?a:0;
            string id; RelationState relation;
            return foreign>0
                && _playerCoalition.TryGetValue(foreign,out id)
                && _relations.TryGetValue(id,out relation) ? relation : null;
        }

        private bool V2ProposeAiCounter(DiplomacyV2TradeQuote rejected,
            LiveTradeWorld world,int day)
        {
            if (rejected.Revision>=DiplomacyV2TradeRules.MaximumCounterRounds
                || !world.IsAlive(rejected.FromPlayer)
                || !world.IsAlive(rejected.ToPlayer))return false;
            try
            {
                // Less demanded from the original proposer, never more
                // than this AI can pay from its real strategic surplus.
                int revised=Math.Max(1,rejected.FromAmount*85/100);
                V2TradeBook().Counter(world,rejected.Id,rejected.ToPlayer,
                    rejected.ToAmount,revised,day,2);
                return true;
            }
            catch(InvalidOperationException) { return false; }
        }

        private void V2PlanAiToAiTrades(LiveTradeWorld world,int day)
        {
            DiplomacyV2TradeBook book=V2TradeBook();
            if (day<=book.LastAutonomousDay)return;
            book.LastAutonomousDay=day;
            // Multiplayer authorization is not yet verified; never mutate
            // AI/remote clients independently. The actual singleplayer AI
            // trades below execute through the same native journal.
            if (_roster.Count(world.IsHuman)!=1)return;
            int[] ais=_roster.Where(p=>world.IsAlive(p)&&!world.IsHuman(p))
                .OrderBy(p=>p).ToArray();
            if (ais.Length<2)return;
            var pairs=new List<Tuple<int,int>>();
            for(int a=0;a<ais.Length;a++)
                for(int b=a+1;b<ais.Length;b++)
                    if (world.CanTrade(ais[a],ais[b],day))
                        pairs.Add(Tuple.Create(ais[a],ais[b]));
            if (pairs.Count==0)return;
            // Rotate starting pair by logical day; do not favor lowest IDs.
            int offset=day%pairs.Count;
            for(int i=0;i<pairs.Count;i++)
            {
                var pair=pairs[(i+offset)%pairs.Count];
                if (book.Offers.Any(q=>!q.IsFinal
                    && ((q.FromPlayer==pair.Item1 && q.ToPlayer==pair.Item2)
                     || (q.FromPlayer==pair.Item2 && q.ToPlayer==pair.Item1))))
                    continue;
                if (TryCreateAutonomousTrade(pair.Item1,pair.Item2,world,day))
                    return; // bounded to one fresh proposal per simulation day
            }
        }

        private bool TryCreateAutonomousTrade(int from,int to,
            LiveTradeWorld world,int day)
        {
            int goodFrom=0,goodTo=0,stock,need;
            foreach(int good in DiplomacyV2TradeRules.Goods)
            {
                if (good==DiplomacyV2TradeRules.GoldGoodId)continue;
                if (!world.TryReadStock(from,good,out stock)
                    || !world.TryReadStock(to,good,out need))continue;
                int ownReserve=world.SafetyReserve(from,good);
                int otherReserve=world.SafetyReserve(to,good);
                if (stock>ownReserve+20 && need<otherReserve
                    && world.MarketUnitValue(good)>0) {goodFrom=good;break;}
            }
            if (goodFrom==0)return false;
            foreach(int good in DiplomacyV2TradeRules.Goods)
            {
                if (good==goodFrom)continue;
                if (!world.TryReadStock(to,good,out stock)
                    || !world.TryReadStock(from,good,out need))continue;
                int ownReserve=world.SafetyReserve(to,good);
                int otherReserve=world.SafetyReserve(from,good);
                if (stock>ownReserve+20 && need<otherReserve
                    && world.MarketUnitValue(good)>0) {goodTo=good;break;}
            }
            if (goodTo==0)return false;
            try
            {
                int aPrice=world.MarketUnitValue(goodFrom);
                int bPrice=world.MarketUnitValue(goodTo);
                int bAmount=Math.Max(1,(int)Math.Min(500L,
                    Math.Max(1L,10L*aPrice/bPrice)));
                V2TradeBook().Submit(world,from,to,goodFrom,10,
                    goodTo,bAmount,day,3);
                Log("trade","status=ai_ai_proposal|from="+from+"|to="+to);
                return true;
            }
            catch(InvalidOperationException) { return false; }
        }
    }
}
#endif
