// Game-specific, independently compiled MENU-only bridge CANDIDATE.
// This is not a validated executable mod. It must not be auto-installed.
// Only the Noesis panel open/close/selection state is provided.
// Mission load, save persistence and seasons are intentionally NOT hooked.
using System;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Noesis;
using SpriteSuite.Origins.Authoring;

namespace SpriteSuite.Origins.NativeMenuCandidate
{
    [BepInPlugin("com.spritesuite.origins.authoring.menu",
                 "SpriteSuite Authored Menu Bridge (QA only)", "0.1.0")]
    public sealed class OriginsFrontendBepInExCandidate : BaseUnityPlugin
    {
        private Harmony harmony;
        private static ManualLogSource Log;
        private static readonly CampaignSession Campaign=AuthoredCampaign.NewSession();

        private void Awake()
        {
            Log=Logger;
            Type frontend=AccessTools.TypeByName("CrusaderDE.FrontendMenus");
            if (frontend==null || frontend.BaseType.FullName!="Noesis.UserControl")
            {
                Log.LogError("Origins menu bridge: FrontendMenus ABI not present.");
                return;
            }
            MethodInfo clicked=AccessTools.Method(frontend,"ButtonClicked",
                                                     new Type[]{typeof(string)});
            if (clicked==null || clicked.ReturnType!=typeof(void))
            {
                Log.LogError("Origins menu bridge: String callback ABI mismatch.");
                return;
            }
            harmony=new Harmony("com.spritesuite.origins.menu.qa");
            harmony.Patch(clicked,prefix:new HarmonyMethod(
                typeof(OriginsFrontendBepInExCandidate),
                "MenuParameterPrefix"));
            Log.LogWarning("SpriteSuite menu QA bridge HOOK REGISTERED: "
                           +"game launch and seasons NOT supported");
        }

        private void OnDestroy()
        {
            if (harmony!=null)
            {
                harmony.UnpatchSelf();
                harmony=null;
            }
        }

        private static bool MenuParameterPrefix(object __instance,string param)
        {
            if (param!="OriginsLegacyCampaign" && param!="LegacyBack" &&
                param!="LegacyStart" &&
                (param==null || !param.StartsWith("LegacyM",StringComparison.Ordinal)))
                return true; // Do not change ANY unhandled game command.

            var root=__instance as Noesis.UserControl;
            if (root==null)return true;
            var screen=root.FindName("SpriteSuiteOriginsCampaignScreen")
                          as Noesis.UIElement;
            if (screen==null)return true;  // No installed XAML patch: do nothing.
            MenuResult action=Campaign.HandleCommand(param);
            if (action.Action==MenuAction.Ignored) return true;

            if (action.Action==MenuAction.OpenCampaign)
            {
                screen.Visibility=Visibility.Visible;
                return false;
            }
            if (action.Action==MenuAction.BackToMenu)
            {
                screen.Visibility=Visibility.Collapsed;
                return false;
            }
            if (action.Action==MenuAction.SelectedMission)
            {
                var label=root.FindName("SpriteSuiteSelectedMission")
                          as Noesis.TextBlock;
                if (label!=null)
                    label.Text="Mission "+action.Mission.ToString();
                return false;
            }
            if (action.Action==MenuAction.LaunchRequested)
            {
                // DO NOT route a map name to an unverified native game loader.
                if (Log!=null)
                    Log.LogWarning("Launch requested for "+action.MapFile+
                        " but no verified native map-loading handler exists");
                return false;
            }
            if (Log!=null)
                Log.LogWarning("Origins menu state blocked "+param+
                                " action "+action.Action);
            return false;
        }
    }
}
