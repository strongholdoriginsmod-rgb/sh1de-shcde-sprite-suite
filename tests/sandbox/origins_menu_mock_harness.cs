// Fake Windows/.NET UI host for behavioral testing the REAL C# menu bridge.
// There is no Unity, game, Noesis native DLL or Harmony patching in this binary.
// Tests compile the unchanged adapter against these test-only replacements.
using System;
using System.Collections.Generic;
using System.Reflection;

namespace BepInEx {
    [AttributeUsage(AttributeTargets.Class)]
    public sealed class BepInPlugin : Attribute {
        public BepInPlugin(string guid, string name, string version) {}
    }
    public class BaseUnityPlugin {
        public BepInEx.Logging.ManualLogSource Logger =
            new BepInEx.Logging.ManualLogSource();
    }
}

namespace BepInEx.Logging {
    public sealed class ManualLogSource {
        public static List<string> Messages = new List<string>();
        public void LogWarning(object message) { Messages.Add("WARN "+message); }
        public void LogError(object message) { Messages.Add("ERROR "+message); }
    }
}

namespace HarmonyLib {
    public sealed class HarmonyMethod : Attribute {
        public readonly Type Owner;
        public readonly string Name;
        public HarmonyMethod(Type owner, string name) {
            Owner=owner; Name=name;
        }
    }
    public sealed class Harmony {
        public static int Patched;
        public static int Unpatched;
        public static MethodInfo LastMethod;
        private readonly string id;
        public Harmony(string name) { id=name; }
        public void Patch(MethodBase original,HarmonyMethod prefix=null) {
            if (original==null || prefix==null)
                throw new InvalidOperationException("Missing real adapter patch metadata");
            LastMethod=(MethodInfo)original;
            ++Patched;
        }
        public void UnpatchSelf() { ++Unpatched; }
    }
    public static class AccessTools {
        public static bool AllowGameType=true;
        public static Type TypeByName(string name) {
            return AllowGameType && name=="CrusaderDE.FrontendMenus" ?
                typeof(CrusaderDE.FrontendMenus) : null;
        }
        public static MethodInfo Method(Type type,string name,Type[] args) {
            if (type==null)return null;
            return type.GetMethod(name,BindingFlags.Instance |
                                  BindingFlags.Public | BindingFlags.NonPublic,
                                  null,args,null);
        }
    }
}

namespace Noesis {
    public enum Visibility { Visible=0, Hidden=1, Collapsed=2 }
    public class UIElement {
        public Visibility Visibility=Visibility.Visible;
    }
    public class UserControl : UIElement {
        private readonly Dictionary<string,object> _views =
            new Dictionary<string,object>();
        public object FindName(string name) {
            object value;
            return _views.TryGetValue(name,out value) ? value:null;
        }
        public void AddControl(string name,object value) { _views[name]=value; }
    }
    public class TextBlock : UIElement {
        public string Text;
    }
}

namespace CrusaderDE {
    public class FrontendMenus : Noesis.UserControl {
        public void ButtonClicked(string parameter) {}
    }
}

public static class FakeNativeMenuRunner {
    private static int passed;
    private static MethodInfo _prefix;

    private static void Require(bool ok,string message) {
        if (!ok)throw new Exception("MENU_ASSERT_FAILED: "+message);
        ++passed;
    }
    private static object CreateBridge() {
        var type=typeof(SpriteSuite.Origins.NativeMenuCandidate.OriginsFrontendBepInExCandidate);
        return Activator.CreateInstance(type,true);
    }
    private static void Startup(object instance) {
        var method=instance.GetType().GetMethod("Awake",
            BindingFlags.NonPublic|BindingFlags.Instance);
        Require(method!=null,"adapter Awake exists");
        method.Invoke(instance,null);
    }
    private static bool Handle(Noesis.UserControl window,string param) {
        object ret=_prefix.Invoke(null,new object[] {window,param});
        return (bool)ret;
    }
    public static int Main(string[] args) {
        try {
            var type=typeof(SpriteSuite.Origins.NativeMenuCandidate.OriginsFrontendBepInExCandidate);
            _prefix=type.GetMethod("MenuParameterPrefix",
                BindingFlags.NonPublic|BindingFlags.Static);
            Require(_prefix!=null,"actual adapter prefix exists");

            // An unavailable game type MUST leave the original game untouched.
            HarmonyLib.AccessTools.AllowGameType=false;
            object absent=CreateBridge();
            Startup(absent);
            Require(HarmonyLib.Harmony.Patched==0,"no patch if game ABI absent");
            Require(BepInEx.Logging.ManualLogSource.Messages.Exists(
                x=>x.Contains("ABI not present")),"missing ABI error logged");

            // The real branch of Awake targets a fake FrontendMenus signature.
            HarmonyLib.AccessTools.AllowGameType=true;
            object installed=CreateBridge();
            Startup(installed);
            Require(HarmonyLib.Harmony.Patched==1,"one adapter patch registered");
            Require(HarmonyLib.Harmony.LastMethod.Name=="ButtonClicked",
                    "correct original method targeted");

            // Do not intercept controls until our own XAML is really present.
            var missing=new CrusaderDE.FrontendMenus();
            Require(Handle(missing,"OriginsLegacyCampaign"),
                    "missing authored XAML falls through to original game");
            Require(Handle(missing,"LegacyStart"),
                    "missing authored launch stays original");

            var menu=new CrusaderDE.FrontendMenus();
            var screen=new Noesis.UIElement();
            screen.Visibility=Noesis.Visibility.Collapsed;
            var label=new Noesis.TextBlock();
            label.Text="Before";
            menu.AddControl("SpriteSuiteOriginsCampaignScreen",screen);
            menu.AddControl("SpriteSuiteSelectedMission",label);

            Require(Handle(menu,"Roadmap"),"original Roadmap command untouched");
            Require(Handle(menu,"Multiplayer"),"original multiplayer command untouched");
            Require(Handle(menu,"LegacyM999"),"unknown mission command untouched");
            Require(Handle(menu,null),"null command untouched");
            Require(screen.Visibility==Noesis.Visibility.Collapsed,
                    "game remains on original screen before opening");

            Require(!Handle(menu,"OriginsLegacyCampaign"),
                    "authored open request intercepted");
            Require(screen.Visibility==Noesis.Visibility.Visible,
                    "authored campaign screen really becomes visible");
            Require(!Handle(menu,"LegacyM1"),"existing mission selection intercepted");
            Require(label.Text=="Mission 1","real TextBlock value changed");
            bool secondMissionExists=SpriteSuite.Origins.Authoring.AuthoredCampaign.NewSession().MissionCount>=2;
            Require(Handle(menu,"LegacyM2")==!secondMissionExists,
                "mission 2 is locked if authored; otherwise left to original game");
            Require(label.Text=="Mission 1","invalid request preserves selection");
            Require(!Handle(menu,"LegacyStart"),"unverified game launch never runs");
            Require(BepInEx.Logging.ManualLogSource.Messages.Exists(
                x=>x.Contains("no verified native map-loading handler")),
                "launch refusal was actually logged");
            Require(!Handle(menu,"LegacyBack"),"authored Back command intercepted");
            Require(screen.Visibility==Noesis.Visibility.Collapsed,
                    "campaign screen actually hidden");
            Require(Handle(menu,"Roadmap"),"original controls still work after closing");

            // A different control tree must not be mutated via stale state.
            var another=new CrusaderDE.FrontendMenus();
            Require(Handle(another,"OriginsLegacyCampaign"),
                    "unpatched screen original game command left intact");

            var stop=installed.GetType().GetMethod("OnDestroy",
                BindingFlags.NonPublic|BindingFlags.Instance);
            Require(stop!=null,"OnDestroy exists");
            stop.Invoke(installed,null);
            Require(HarmonyLib.Harmony.Unpatched==1,
                    "Harmony patches unregistered during lifecycle shutdown");
            Require(HarmonyLib.Harmony.Patched==1,
                    "no duplicate registrations");
            Console.WriteLine("SPRITESUITE_MOCK_MENU_ASSERTIONS="+passed);
            Console.WriteLine("MOCK_HARMONY_PATCHES="+HarmonyLib.Harmony.Patched);
            Console.WriteLine("MOCK_HARMONY_UNPATCHES="+HarmonyLib.Harmony.Unpatched);
            Console.WriteLine("REAL_GAME_DLL_LOADED=0");
            Console.WriteLine("REAL_NOESIS_RENDERER_LOADED=0");
            Console.WriteLine("NATIVE_GAME_HOOK_REGISTERED=0");
            return 0;
        } catch (Exception ex) {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }
}
