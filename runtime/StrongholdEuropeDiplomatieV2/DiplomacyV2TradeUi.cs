#if DIPLOMACY_V2
using System;
using System.Globalization;
using System.Linq;
using System.Reflection;
using CrusaderDE;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed partial class DiplomacyFeature
    {
        private sealed class PendingV2TradeUiAction
        {
            internal string Action;
            internal int Player,Selection,FromGood,FromAmount,ToGood,ToAmount;
            internal long Generation,OfferId,QueuedTick;
            internal string Fingerprint;
            internal object Panel;
        }

        private PendingV2TradeUiAction _v2PendingTradeUi;
        private string _v2TradeStatus;

        private bool TryHandleV2TradeCommand(object panel,string command)
        {
            if (command == null ||
                !command.StartsWith("Diplomacy:Trade:",StringComparison.Ordinal))
                return false;
            if (!_mapActive || _mapDisabled || _mapBootstrapPending)
                return true;
            string[] tokens=command.Split(':');
            if (tokens.Length!=5 && tokens.Length!=6)return true;
            int player;
            long generation,offerId=0;
            if (!int.TryParse(tokens[3],NumberStyles.None,
                    CultureInfo.InvariantCulture,out player)
                || !long.TryParse(tokens[4],NumberStyles.None,
                    CultureInfo.InvariantCulture,out generation)
                || tokens.Length==6 &&
                    !long.TryParse(tokens[5],NumberStyles.None,
                        CultureInfo.InvariantCulture,out offerId)
                || generation!=_sessionGeneration
                || !ReferenceEquals(panel,CurrentAlliesPanel())
                || !MainViewModel.Instance.AlliesPanelVisible
                || player<1 || player>8 || player==_localPlayer)
                return true;
            string operation=tokens[2];
            if (operation=="Open")
            {
                if (player!=SelectedPlayer(panel) || _v2OverviewVisible)
                    return true;
                _v2TradeEditorOpen=true;
                _v2TradeEditorTarget=player;
                _v2TradeEditorGeneration=_sessionGeneration;
                _v2TradeStatus=null;
                _v2TradeOfferGood=2;
                _v2TradeRequestGood=4;
                _v2TradeOfferAmount=10;
                _v2TradeRequestAmount=10;
                _v2TradeAnswerOffer=0L;
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeFromAmountInput"),
                    "Text","10");
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeToAmountInput"),
                    "Text","10");
                RefreshV2TradePanel(panel,player);
                return true;
            }
            if (operation=="Close")
            {
                _v2TradeEditorOpen=false;
                _v2PendingTradeUi=null;
                RefreshVanillaDiplomacyUi(panel);
                return true;
            }
            if (!_v2TradeEditorOpen
                || _v2TradeEditorTarget!=player
                || _v2TradeEditorGeneration!=_sessionGeneration
                || SelectedPlayer(panel)!=player
                || _v2OverviewVisible)return true;
            if (_v2PendingTradeUi!=null)return true;
            switch(operation)
            {
                case "FromNext":
                    _v2TradeOfferGood=NextV2TradeGood(_v2TradeOfferGood,_v2TradeRequestGood);
                    break;
                case "ToNext":
                    _v2TradeRequestGood=NextV2TradeGood(_v2TradeRequestGood,_v2TradeOfferGood);
                    break;
                case "From5": _v2TradeOfferAmount=5; break;
                case "From10": _v2TradeOfferAmount=10; break;
                case "From25": _v2TradeOfferAmount=25; break;
                case "From100": _v2TradeOfferAmount=100; break;
                case "From500": _v2TradeOfferAmount=500; break;
                case "To5": _v2TradeRequestAmount=5; break;
                case "To10": _v2TradeRequestAmount=10; break;
                case "To25": _v2TradeRequestAmount=25; break;
                case "To100": _v2TradeRequestAmount=100; break;
                case "To500": _v2TradeRequestAmount=500; break;
                case "Send":
                case "Accept":
                case "Decline":
                case "Counter":
                    if ((operation=="Accept" || operation=="Decline" || operation=="Counter")
                        && offerId<=0)return true;
                    if (operation=="Send" || operation=="Counter")
                    {
                        int left,right;
                        if (!ReadV2TradeAmount(panel,"From",out left)
                            || !ReadV2TradeAmount(panel,"To",out right))
                        {
                            _v2TradeStatus=Text("Handelsmenge: eine Zahl zwischen 1 und 50000 eingeben.",
                                "Trade quantity must be between 1 and 50000.");
                            RefreshV2TradePanel(panel,player);
                            return true;
                        }
                        _v2TradeOfferAmount=left;
                        _v2TradeRequestAmount=right;
                    }
                    _v2PendingTradeUi=new PendingV2TradeUiAction
                    {
                        Action=operation,Panel=panel,
                        Player=player,Selection=SelectedPlayer(panel),
                        Generation=_sessionGeneration,Fingerprint=_mapFingerprint,
                        FromGood=_v2TradeOfferGood,FromAmount=_v2TradeOfferAmount,
                        ToGood=_v2TradeRequestGood,ToAmount=_v2TradeRequestAmount,
                        OfferId=offerId,QueuedTick=_featureTicks,
                    };
                    _v2TradeStatus=Text(
                        "Anfrage wird verbindlich im Simulationstakt geprüft.",
                        "Request awaiting authoritative simulation validation.");
                    break;
                default:return true;
            }
            // Preset amount buttons change native Noesis text controls, but
            // normal refreshes never overwrite text the player is typing.
            if (operation.StartsWith("From",StringComparison.Ordinal)
                && operation!="FromNext")
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeFromAmountInput"),
                    "Text",_v2TradeOfferAmount.ToString(CultureInfo.InvariantCulture));
            if (operation.StartsWith("To",StringComparison.Ordinal)
                && operation!="ToNext")
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeToAmountInput"),
                    "Text",_v2TradeRequestAmount.ToString(CultureInfo.InvariantCulture));
            RefreshV2TradePanel(panel,player);
            return true;
        }

        private static void SetV2TradePropertyIfPresent(object control,
            string propertyName,object value)
        {
            if (control!=null) SetProperty(control,propertyName,value);
        }

        private bool ReadV2TradeAmount(object panel,string side,out int amount)
        {
            amount=0;
            object control=FindElement(panel,"CrusaderDiplomacyV2Trade"+side+"AmountInput");
            if (control==null)return false;
            PropertyInfo text=control.GetType().GetProperty("Text",
                BindingFlags.Instance | BindingFlags.Public);
            object value=text==null?null:text.GetValue(control,null);
            string raw=value==null?null:value.ToString();
            return int.TryParse(raw,NumberStyles.None,
                       CultureInfo.InvariantCulture,out amount)
                && amount>=1 && amount<=DiplomacyV2TradeRules.MaximumGoodAmount;
        }

        private static int NextV2TradeGood(int current,int excluded)
        {
            int[] goods=DiplomacyV2TradeRules.Goods;
            int at=Array.IndexOf(goods,current);
            for(int n=1;n<=goods.Length;n++)
            {
                int next=goods[(at+n+goods.Length)%goods.Length];
                if (next!=excluded)return next;
            }
            return current;
        }

        private void ProcessV2TradeUiUnderLease(
            LiveTradeWorld world,int day)
        {
            PendingV2TradeUiAction command=_v2PendingTradeUi;
            if (command==null)return;
            if (command.Generation!=_sessionGeneration
                || !string.Equals(command.Fingerprint,_mapFingerprint,
                    StringComparison.Ordinal)
                || command.Selection!=command.Player
                || !_v2TradeEditorOpen
                || _v2TradeEditorTarget!=command.Player
                || !ReferenceEquals(command.Panel,CurrentAlliesPanel())
                || MainViewModel.Instance==null
                || !MainViewModel.Instance.AlliesPanelVisible
                || SelectedPlayer(command.Panel)!=command.Player
                || _featureTicks-command.QueuedTick>600L)
            {
                _v2PendingTradeUi=null;
                _v2TradeStatus=Text("Veraltete Handelsauswahl verworfen.",
                                    "Stale trade selection was cancelled.");
                return;
            }
            if (!V2MayChangeInventory())return;
            _v2PendingTradeUi=null;
            try
            {
                // There is one local human in singleplayer; cross-client
                // consent needs verified APIShared Chore transport, not local
                // replay or a guessed recipient. Fail closed in multiplayer.
                if (_roster.Count(world.IsHuman)!=1)
                    throw new InvalidOperationException(
                        "multiplayer trading requires an authenticated Chore session");
                DiplomacyV2TradeBook book=V2TradeBook();
                if (command.Action=="Send")
                {
                    DiplomacyV2TradeQuote quote=book.Submit(
                        world,_localPlayer,command.Player,
                        command.FromGood,command.FromAmount,
                        command.ToGood,command.ToAmount,day,4);
                    _v2TradeStatus=Text("Angebot übermittelt; Antwort steht aus.",
                        "Offer queued; waiting for an answer.")+" #"
                        +quote.Id.ToString(CultureInfo.InvariantCulture);
                    Log("trade","status=offered|id="+quote.Id+"|target="+command.Player);
                    return;
                }
                DiplomacyV2TradeQuote incoming=book.Find(command.OfferId);
                if (incoming==null || !incoming.AwaitingReply
                    || incoming.FromPlayer!=command.Player
                    || incoming.ToPlayer!=_localPlayer)
                    throw new InvalidOperationException("offer belongs to another party or has expired");
                if (command.Action=="Counter")
                {
                    DiplomacyV2TradeQuote response=book.Counter(
                        world,incoming.Id,_localPlayer,
                        command.FromAmount,command.ToAmount,day,3);
                    _v2TradeStatus=Text("Gegenangebot eingereicht.",
                        "Counteroffer sent.")+" #"+response.Id;
                    Log("trade","status=countered|id="+response.Id);
                    return;
                }
                bool accept=command.Action=="Accept";
                if (!book.Reply(incoming.Id,_localPlayer,accept,
                    world,day,true))
                    throw new InvalidOperationException("human answer is no longer authorized");
                if (accept)
                {
                    _v2TradeStatus=Text("Angenommen; Warentransfer wird überprüft.",
                        "Accepted; checking real goods transfer.");
                    SettleV2Trade(incoming.Id,world,day);
                }
                else
                {
                    _v2TradeStatus=Text("Angebot abgelehnt.",
                        "Offer declined.");
                    Log("trade","status=declined|id="+incoming.Id);
                }
            }
            catch(Exception exception)
            {
                _v2TradeStatus=Text("Handel nicht ausgeführt: ",
                    "Trade was not executed: ")+Safe(exception.Message);
                Log("trade","status=rejected|reason="+Safe(exception.GetType().Name));
            }
        }

        private void RefreshV2TradePanel(object panel,int selectedPlayer)
        {
            object grid=FindElement(panel,"CrusaderDiplomacyV2TradeGrid");
            object open=FindElement(panel,"CrusaderDiplomacyV2TradeOpen");
            object openLabel=FindElement(panel,"CrusaderDiplomacyV2TradeOpenLabel");
            bool current=selectedPlayer>0 && selectedPlayer<=8
                && _mapActive && !_mapDisabled && !_v2OverviewVisible;
            RelationState relation=V2TradeRelationFor(_localPlayer,selectedPlayer);
            bool eligible=current && relation!=null
                && DiplomacyV2TradeRules.CanTrade(relation,
                    Math.Max(0,_lastProcessedDay),false,
                    IsAlivePlayer(_localPlayer)&&IsAlivePlayer(selectedPlayer));
            SetVisibilityIfPresent(open,current);
            SetVisibilityIfPresent(openLabel,current);
            if (open!=null)
            {
                SetProperty(open,"IsEnabled",eligible);
                SetProperty(open,"ToolTip",eligible
                    ? Text("Angebote und Gegenangebote im eigenen Handelsfenster.",
                        "Manage trade offers and counteroffers.")
                    : Text("Nur mit gültigem Handelsabkommen oder Bündnis.",
                        "Requires a valid trade pact or alliance."));
                SetProperty(open,"CommandParameter",V2TradeAction(
                    "Open",selectedPlayer,0));
            }
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeOpenLabel",
                Text("Handel","Trade"));
            if (_v2TradeEditorOpen && (_v2TradeEditorTarget!=selectedPlayer
                || _v2TradeEditorGeneration!=_sessionGeneration || !current))
            {
                _v2TradeEditorOpen=false;
                _v2PendingTradeUi=null;
            }
            bool visible=_v2TradeEditorOpen && current
                && _v2TradeEditorTarget==selectedPlayer;
            SetVisibilityIfPresent(grid,visible);
            if (!visible)return;
            // Captured partner is immutable while the pane is open.
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeTitle",
                Text("Handel mit ","Trade with ")+V2PlayerName(selectedPlayer));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeRelationship",
                eligible ? Text("Handelsrecht: gültiges Abkommen.",
                    "Trade rights: valid agreement.")
                    : Text("Handelsrecht entfallen. Keine Buchung möglich.",
                        "Trading agreement ended. No settlement permitted."));
            DiplomacyV2TradeQuote incoming=_v2TradeBook==null?null
                :_v2TradeBook.Offers.Where(q=>q.AwaitingReply
                    && q.FromPlayer==selectedPlayer && q.ToPlayer==_localPlayer)
                    .OrderBy(q=>q.Id).FirstOrDefault();
            if (incoming!=null && _v2TradeAnswerOffer!=incoming.Id)
            {
                // A counteroffer always concerns the two goods of the
                // authentic incoming quote, not stale UI-selected goods.
                _v2TradeAnswerOffer=incoming.Id;
                _v2TradeOfferGood=incoming.ToGood;
                _v2TradeRequestGood=incoming.FromGood;
                _v2TradeOfferAmount=incoming.ToAmount;
                _v2TradeRequestAmount=incoming.FromAmount;
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeFromAmountInput"),
                    "Text",incoming.ToAmount.ToString(CultureInfo.InvariantCulture));
                SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeToAmountInput"),
                    "Text",incoming.FromAmount.ToString(CultureInfo.InvariantCulture));
            }
            else if (incoming==null)_v2TradeAnswerOffer=0L;
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeOfferText",
                Text("Ihr gebt: ","You give: ")
                +_v2TradeOfferAmount+" "+GoodName(_v2TradeOfferGood,_v2TradeOfferAmount));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeRequestText",
                Text("Ihr erhaltet: ","You receive: ")
                +_v2TradeRequestAmount+" "+GoodName(_v2TradeRequestGood,_v2TradeRequestAmount));
            SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeOfferIcon"),
                "Source",GetAlliesGoodsIcon(_v2TradeOfferGood));
            SetV2TradePropertyIfPresent(FindElement(panel,"CrusaderDiplomacyV2TradeRequestIcon"),
                "Source",GetAlliesGoodsIcon(_v2TradeRequestGood));
            DiplomacyV2TradeQuote lastOwn=_v2TradeBook==null?null
                :_v2TradeBook.Offers.Where(q=>q.OriginPlayer==_localPlayer
                    && (q.FromPlayer==selectedPlayer || q.ToPlayer==selectedPlayer))
                    .OrderByDescending(q=>q.Id).FirstOrDefault();
            string preview=incoming==null
                ? lastOwn==null
                    ? Text("Kein eingegangenes Angebot.", "No incoming offer.")
                    : Text("Eigener Handel #","Your trade #")+lastOwn.Id+" · "
                        +V2TradePhaseText(lastOwn.Phase)
                : Text("Eingang #","Incoming #")+incoming.Id
                    + ": "+incoming.FromAmount+" "
                    +GoodName(incoming.FromGood,incoming.FromAmount)
                    +" / "+incoming.ToAmount+" "
                    +GoodName(incoming.ToGood,incoming.ToAmount);
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeIncoming",preview);
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeStatus",
                _v2TradeStatus??Text("Waren und Mengen wählen, dann Angebot absenden.",
                    "Choose goods and quantities, then send the offer."));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeFromLabel",
                Text("Angebotene Ware wechseln","Change offered good"));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeToLabel",
                Text("Gewünschte Ware wechseln","Change requested good"));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeFromNextLabel",
                Text("Ware wechseln","Change good"));
            SetTextIfPresent(panel,"CrusaderDiplomacyV2TradeToNextLabel",
                Text("Ware wechseln","Change good"));
            foreach(string action in new[] {
                "FromNext","ToNext","From5","From10","From25","From100","From500",
                "To5","To10","To25","To100","To500",
                "Send","Accept","Decline","Counter","Close"})
            {
                object button=FindElement(panel,"CrusaderDiplomacyV2Trade"+action);
                if (button==null)continue;
                bool answer=action=="Accept"||action=="Decline"||action=="Counter";
                bool freezesGoods=incoming!=null &&
                    (action=="FromNext" || action=="ToNext" || action=="Send");
                SetProperty(button,"IsEnabled",action=="Close"
                    || ((!answer || incoming!=null) && eligible
                        && !freezesGoods && _v2PendingTradeUi==null));
                SetProperty(button,"CommandParameter",V2TradeAction(
                    action,selectedPlayer,answer?_v2TradeAnswerOffer:0L));
            }
            string[] keys={"Send","Accept","Decline","Counter","Close"};
            string[] labels={
                Text("Angebot senden","Send offer"),
                Text("Annehmen","Accept"),Text("Ablehnen","Decline"),
                Text("Gegenangebot","Counteroffer"),Text("Schließen","Close")
            };
            for(int i=0;i<keys.Length;i++)
                SetTextIfPresent(panel,"CrusaderDiplomacyV2Trade"+keys[i]+"Label",
                    labels[i]);
        }

        private string V2TradePhaseText(DiplomacyV2TradePhase phase)
        {
            switch(phase)
            {
                case DiplomacyV2TradePhase.Pending: return Text("Antwort offen","Awaiting reply");
                case DiplomacyV2TradePhase.Countered: return Text("Gegenangebot","Countered");
                case DiplomacyV2TradePhase.Accepted: return Text("Buchung wird geprüft","Settlement pending");
                case DiplomacyV2TradePhase.Declined: return Text("Abgelehnt","Declined");
                case DiplomacyV2TradePhase.Expired: return Text("Abgelaufen","Expired");
                case DiplomacyV2TradePhase.Completed: return Text("Waren vollständig übertragen","Delivered");
                case DiplomacyV2TradePhase.RecoveryRequired: return Text("Wiederherstellung erforderlich","Recovery required");
                case DiplomacyV2TradePhase.Cancelled: return Text("Ohne Lieferung beendet","Cancelled");
                default:return Text("Noch nicht abgeschlossen","Not completed");
            }
        }

        private string V2TradeAction(string action,int player,long offer)
        {
            string value="Diplomacy:Trade:"+action+":"
                +player.ToString(CultureInfo.InvariantCulture)+":"
                +_sessionGeneration.ToString(CultureInfo.InvariantCulture);
            return offer<=0?value:value+":"+offer.ToString(CultureInfo.InvariantCulture);
        }
    }
}
#endif
