// Metadata ONLY verification of the exact compiled SpriteSuite in-game plugin.
// Managed game, Noesis and BepInEx binaries are parsed as data, never executed.
using System;
using System.Linq;
using Mono.Cecil;

public static class OriginsLiveMetadataProbe
{
    static void Require(bool valid, string key) {
        if(!valid)throw new InvalidOperationException("NATIVE_PLUGIN_METADATA_FAILED="+key);
        Console.WriteLine(key+"=1");
    }
    public static int Main(string[] paths) {
        if(paths.Length!=1)return 2;
        try {
            using(var a=AssemblyDefinition.ReadAssembly(paths[0])) {
                var t=a.MainModule.GetTypes().FirstOrDefault(x=>
                     x.FullName=="SpriteSuite.Origins.Live.OriginsNativeLivePlugin");
                Require(t!=null,"LIVE_PLUGIN_CLASS_PRESENT");
                Require(t.BaseType.FullName=="BepInEx.BaseUnityPlugin","LIVE_GAME_PLUGIN_BASE");
                Require(t.CustomAttributes.Any(x=>x.AttributeType.FullName==
                        "BepInEx.BepInPlugin" &&
                        x.ConstructorArguments.Count>0 &&
                        (string)x.ConstructorArguments[0].Value=="spritesuiteoriginslive"),
                        "LIVE_BEPINEX_REGISTRATION_ATTRIBUTE");
                Require(t.CustomAttributes.Any(x=>x.AttributeType.FullName==
                        "BepInEx.BepInDependency"),"LIVE_EXTENDER_DEPENDENCY_ATTRIBUTE");
                foreach(var name in new [] {
                     "Awake","OnDestroy","MenuPrefix","TryStartOriginalMission",
                     "OnGameMapLoad","OnGameMapPostLoad","OnGameMapUnload","CaptureLoop",
                     "CaptureOneNativeFrame","WriteStatus","DisableHooks"}) {
                    Require(t.Methods.Any(m=>m.Name==name),"LIVE_METHOD_"+name);
                }
                Require(t.Methods.Any(m=>m.Name=="MenuPrefix" && m.IsStatic &&
                    m.ReturnType.FullName=="System.Boolean" &&
                    m.Parameters.Count==2 &&
                    m.Parameters[0].ParameterType.FullName=="System.Object" &&
                    m.Parameters[1].ParameterType.FullName=="System.String"),
                    "LIVE_HARMONY_MENU_PREFIX_ABI");
                bool nativeTexture=t.Methods.Where(m=>m.Name=="CaptureOneNativeFrame" &&
                    m.HasBody).SelectMany(m=>m.Body.Instructions)
                    .Any(i=>i.Operand!=null &&
                        i.Operand.ToString().Contains("NoesisView::get_Texture"));
                Require(nativeTexture,"LIVE_NOESIS_RENDER_TEXTURE_CAPTURE_CODE");
                bool nativeMap=t.Methods.Where(m=>m.Name=="TryStartOriginalMission" &&
                    m.HasBody).SelectMany(m=>m.Body.Instructions)
                    .Any(i=>i.Operand!=null &&
                        i.Operand.ToString().Contains("FRONT_StandaloneMission::StartMap"));
                Require(nativeMap,"LIVE_ORIGINAL_GAME_MAP_LOADER_CALL");
                bool safeStem=t.Methods.Where(m=>m.Name=="TryStartOriginalMission" &&
                    m.HasBody).SelectMany(m=>m.Body.Instructions)
                    .Any(i=>i.Operand!=null &&
                        i.Operand.ToString().Contains("Path::GetFileNameWithoutExtension"));
                Require(safeStem,"LIVE_MAP_MANAGER_STEM_LOOKUP");
                bool matchedMap=t.Methods.Where(m=>m.Name=="OnGameMapLoad" &&
                    m.HasBody).SelectMany(m=>m.Body.Instructions)
                    .Any(i=>i.Operand!=null &&
                        i.Operand.ToString().Contains("String::Equals"));
                Require(matchedMap,"LIVE_MISSION_MAPLOAD_MATCHING_CODE");
                bool verifiedPostload=t.Methods.Where(m=>
                    m.Name=="OnGameMapPostLoad" && m.HasBody)
                    .SelectMany(m=>m.Body.Instructions).Any(i=>i.Operand!=null &&
                    i.Operand.ToString().Contains("LoadMapReturnData::errorCode"));
                Require(verifiedPostload,"LIVE_POSTLOAD_SUCCESS_CODE_CHECK");
                Console.WriteLine("LIVE_NATIVE_GAME_PROCESS_EXECUTED=0");
                Console.WriteLine("LIVE_RUNTIME_HANDLER_INVOCATION_ATTESTED=0");
            }
            return 0;
        } catch(Exception exc) {
            Console.Error.WriteLine(exc.ToString());
            return 1;
        }
    }
}
