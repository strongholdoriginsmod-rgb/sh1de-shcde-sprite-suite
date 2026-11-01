// Offline metadata-only inspection, does not load/execute the Unity game.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using Mono.Cecil;

public static class OriginsNativeSignatureProbe {
    static TypeDefinition GetType(string path,string full) {
        using (var assembly=AssemblyDefinition.ReadAssembly(path)) {
            return assembly.MainModule.Types.FirstOrDefault(t=>t.FullName==full);
        }
    }
    static bool MethodPresent(string path,string typeName,string name,
                              string ret,params string[] args) {
        using (var assembly=AssemblyDefinition.ReadAssembly(path)) {
            var t=assembly.MainModule.Types.FirstOrDefault(x=>x.FullName==typeName);
            if(t==null)return false;
            return t.Methods.Any(m=>m.Name==name && m.ReturnType.FullName==ret &&
                  m.Parameters.Select(p=>p.ParameterType.FullName).SequenceEqual(args));
        }
    }
    static bool HasNamedType(string path,string name) {
        using (var assembly=AssemblyDefinition.ReadAssembly(path)) {
            return assembly.MainModule.Types.Any(t=>t.FullName==name);
        }
    }
    static void Assert(bool condition,string marker) {
        Console.WriteLine(marker+"="+(condition?"1":"0"));
    }
    public static int Main(string[] args) {
        if(args.Length!=5 && args.Length!=6){
            Console.Error.WriteLine("Expected five game paths plus optional candidate DLL");
            return 2;
        }
        try {
            string game=args[0],noesis=args[1],bep=args[2],
                   harmony=args[3],cecil=args[4];
            using(var assembly=AssemblyDefinition.ReadAssembly(game)) {
                var type=assembly.MainModule.Types.FirstOrDefault(
                    x=>x.FullName=="CrusaderDE.FrontendMenus");
                Assert(type!=null,"HAS_FRONTEND_TYPE");
                Assert(type!=null && type.BaseType.FullName=="Noesis.UserControl",
                       "FRONTEND_EXTENDS_NOESIS_USERCONTROL");
                Assert(type!=null && type.Methods.Any(m=>
                       m.Name=="ButtonClicked" && !m.IsStatic &&
                       m.ReturnType.FullName=="System.Void" &&
                       m.Parameters.Count==1 &&
                       m.Parameters[0].ParameterType.FullName=="System.String"),
                       "HAS_MENU_COMMAND_STRING_CALLBACK");
            }
            Assert(MethodPresent(noesis,"Noesis.FrameworkElement","FindName",
                "System.Object","System.String"),"HAS_NOESIS_FINDNAME");
            Assert(HasNamedType(bep,"BepInEx.BaseUnityPlugin"),"HAS_BEPINEX_PLUGIN_HOST");
            Assert(HasNamedType(harmony,"HarmonyLib.Harmony"),"HAS_HARMONY_PATCH_HOST");
            Assert(File.Exists(cecil),"HAS_METADATA_READER");
            if (args.Length==6) {
                using(var candidate=AssemblyDefinition.ReadAssembly(args[5])) {
                    var plugin=candidate.MainModule.Types.FirstOrDefault(t=>
                        t.FullName=="SpriteSuite.Origins.NativeMenuCandidate." +
                                    "OriginsFrontendBepInExCandidate");
                    Assert(plugin!=null && plugin.BaseType.FullName==
                           "BepInEx.BaseUnityPlugin","CANDIDATE_HAS_PLUGIN_HOST");
                    Assert(plugin!=null && plugin.CustomAttributes.Any(a=>
                           a.AttributeType.FullName=="BepInEx.BepInPlugin"),
                           "CANDIDATE_HAS_PLUGIN_ATTRIBUTE");
                    Assert(plugin!=null && plugin.Methods.Any(m=>
                           m.Name=="MenuParameterPrefix" && m.IsStatic &&
                           m.ReturnType.FullName=="System.Boolean" &&
                           m.Parameters.Count==2 &&
                           m.Parameters[0].ParameterType.FullName=="System.Object" &&
                           m.Parameters[1].ParameterType.FullName=="System.String"),
                           "CANDIDATE_HAS_HARMONY_PREFIX");
                    Assert(plugin!=null && plugin.Methods.Any(m=>
                           m.Name=="Awake"),"CANDIDATE_HAS_AWAKE");
                    Assert(plugin!=null && plugin.Methods.Any(m=>
                           m.Name=="OnDestroy"),"CANDIDATE_HAS_UNPATCH_LIFECYCLE");
                }
                Console.WriteLine("NATIVE_MENU_CANDIDATE_EXECUTED=0");
            }
            // These markers expressly do not imply registration or activation.
            Console.WriteLine("NATIVE_GAME_HOOK_INVOKED=0");
            Console.WriteLine("NOESIS_RENDERER_INVOKED=0");
            Console.WriteLine("RUNTIME_PLUGIN_REGISTERED=0");
            return 0;
        } catch(Exception e) {
            Console.Error.WriteLine("OFFLINE_METADATA_PROBE_FAILED: "+e);
            return 1;
        }
    }
}
