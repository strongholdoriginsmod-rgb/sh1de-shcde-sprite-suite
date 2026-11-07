// SpriteSuite native runtime compiled and bound to the selected SHCDE installation.
// This source is not installed by compiling. A separate installer verifies
// references, original XAML and rollback before activating a BepInEx plugin.
//
// Native screenshot capture uses the game's real NoesisView/Unity renderer,
// NEVER a fabricated Pillow/XAML canvas. Captures of the composed game frame
// are identified as such (not falsely labelled an isolated Noesis surface).
using System;
using System.Collections;
using System.IO;
using System.Security.Cryptography;
using System.Reflection;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using R3;
using SHCDESE.EventAPI;
using SHCDESE.EventAPI.MapLoader;
using SpriteSuite.Origins.Authoring;
using UnityEngine;

namespace SpriteSuite.Origins.Live
{
    [BepInPlugin("spritesuiteoriginslive",
                 "SpriteSuite Origins Native Noesis Bridge", "0.2.0")]
    [BepInDependency("000shcdese", BepInDependency.DependencyFlags.HardDependency)]
    public sealed class OriginsNativeLivePlugin : BaseUnityPlugin
    {
        private const int MaxFrames = 4;
        private static OriginsNativeLivePlugin Active;
        private static readonly CampaignSession Campaign=AuthoredCampaign.NewSession();
        private static readonly SeasonSession Seasons=AuthoredSeasons.NewSession();
        private Harmony _harmony;
        private IDisposable _onMapLoad, _onMapUnload, _onPostLoad;
        private bool _verified, _captureEnabled;
        private string _output, _observedAssemblyHash;
        private int _frameNumber, _viewsLastSeen, _mapLoadCount, _mapUnloadCount;
        private int _nativeMenuActions;
        private bool _nativeMissionLaunchVerified, _mapLoadMatched;
        private int _postLoadCount;
        private string _lastMenuCommand, _pendingMission;
        private int _captureRequest;
        private string _pendingCapture, _pendingSource;
        private float _pendingAt;
        private string _activeSeason, _lastMap, _lastFrame, _captureSource;
        private string _lastError;
        private float _nextCapture;

        private void Awake()
        {
            Active=this;
            _output=Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "SpriteSuite", "NoesisNativeLive");
            Directory.CreateDirectory(_output);
            _lastError="";
            Log("Plugin Awake executed against installed game process");
            try
            {
                string gameRoot=Directory.GetParent(Application.dataPath).FullName;
                for(int i=0;i<VerifiedGameInputs.PathsAndHashes.GetLength(0);i++)
                {
                    string relative=VerifiedGameInputs.PathsAndHashes[i,0];
                    string expected=VerifiedGameInputs.PathsAndHashes[i,1];
                    string actual=HashFile(Path.Combine(gameRoot,relative));
                    if(i==0)_observedAssemblyHash=actual;
                    if(!String.Equals(actual,expected,StringComparison.OrdinalIgnoreCase))
                    {
                        Fail("Game input changed since build: "+relative+"; game hooks disabled");
                        WriteStatus();
                        return;
                    }
                }
                Type menu=AccessTools.TypeByName("CrusaderDE.FrontendMenus");
                MethodInfo clicked=menu==null?null:
                    AccessTools.Method(menu,"ButtonClicked",new Type[]{typeof(string)});
                if(menu==null || menu.BaseType==null ||
                    menu.BaseType.FullName!="Noesis.UserControl" ||
                    clicked==null || clicked.ReturnType!=typeof(void) ||
                    clicked.IsStatic)
                {
                    Fail("Game menu callback ABI incompatible; hooks disabled");
                    WriteStatus();
                    return;
                }
                // The plugin may be loaded before Noesis views exist.
                _verified=true;
                _harmony=new Harmony("com.spritesuite.origins.live.menu");
                _harmony.Patch(clicked,
                    prefix:new HarmonyMethod(typeof(OriginsNativeLivePlugin),"MenuPrefix"));
                Log("Live menu Harmony prefix registered");

                // Script Extender provides the real map lifecycle notifications.
                _onMapLoad=MapLoaderR3EventHooks.OnLoadMap.Observable.Subscribe(
                    (MapLoadEventArgs args)=>OnGameMapLoad(args));
                _onMapUnload=MapLoaderR3EventHooks.OnUnloadMap.Observable.Subscribe(
                    (MapUnloadEventArgs args)=>OnGameMapUnload(args));
                _onPostLoad=MapLoaderR3EventHooks.OnPostLoad.Observable.Subscribe(
                    (MapPostLoadEventArgs args)=>OnGameMapPostLoad(args));
                Log("Native SHCDESE map load/postload/unload handlers registered");

                _captureEnabled=true;
                StartCoroutine(CaptureLoop());
                WriteStatus();
            }
            catch(Exception exc)
            {
                Fail("Awake: "+exc);
                _verified=false;
                DisableHooks();
                WriteStatus();
            }
        }

        private static string HashFile(string path)
        {
            if(!File.Exists(path))return "missing";
            using(var sha=SHA256.Create())
            using(var stream=File.OpenRead(path))
            {
                return BitConverter.ToString(sha.ComputeHash(stream))
                    .Replace("-","").ToLowerInvariant();
            }
        }

        private void Log(string message)
        {
            Logger.LogInfo("[SpriteSuiteOrigins] "+message);
            try {
                File.AppendAllText(Path.Combine(_output,"plugin-events.log"),
                    DateTime.UtcNow.ToString("o")+" "+message+Environment.NewLine);
            } catch(IOException) {} catch(UnauthorizedAccessException) {}
        }

        private void Fail(string text)
        {
            _lastError=text;
            Logger.LogError("[SpriteSuiteOrigins] "+text);
            try {
                File.AppendAllText(Path.Combine(_output,"plugin-events.log"),
                    DateTime.UtcNow.ToString("o")+" ERROR "+text+Environment.NewLine);
            } catch(IOException) {} catch(UnauthorizedAccessException) {}
        }

        private static string Json(string value)
        {
            if(value==null)return "null";
            return "\""+value.Replace("\\","\\\\").Replace("\"","\\\"")
                .Replace("\r","\\r").Replace("\n","\\n")+"\"";
        }
        private void WriteStatus()
        {
            if(String.IsNullOrEmpty(_output))return;
            try
            {
                string json="{\n"+
                    "  \"schema\":\"sprite-suite.origins-native-live.v1\",\n"+
                    "  \"timestamp_utc\":"+Json(DateTime.UtcNow.ToString("o"))+",\n"+
                    "  \"game_assembly_sha256\":"+Json(_observedAssemblyHash)+",\n"+
                    "  \"native_plugin_awake\":true,\n"+
                    "  \"game_process_pid\":"+System.Diagnostics.Process.GetCurrentProcess().Id+",\n"+
                    "  \"game_installation_root\":"+Json(
                        Directory.GetParent(Application.dataPath).FullName)+",\n"+
                    "  \"runtime_game_abi_verified\":"+(_verified?"true":"false")+",\n"+
                    "  \"native_menu_hook_registered\":"+(_harmony!=null?"true":"false")+",\n"+
                    "  \"native_map_hooks_registered\":"+(
                        _onMapLoad!=null && _onMapUnload!=null &&
                        _onPostLoad!=null?"true":"false")+",\n"+
                    "  \"native_map_postload_callback_count\":"+_postLoadCount+",\n"+
                    "  \"native_menu_actions_handled\":"+_nativeMenuActions+",\n"+
                    "  \"last_native_menu_command\":"+Json(_lastMenuCommand)+",\n"+
                    "  \"native_mission_launch_verified\":"+(
                        _nativeMissionLaunchVerified?"true":"false")+",\n"+
                    "  \"pending_mission_launch\":"+Json(_pendingMission)+",\n"+
                    "  \"native_noesis_views_observed\":"+_viewsLastSeen+",\n"+
                    "  \"native_frame_count\":"+_frameNumber+",\n"+
                    "  \"native_last_frame\":"+Json(_lastFrame)+",\n"+
                    "  \"frame_source\":"+Json(_captureSource)+",\n"+
                    "  \"pixel_exact_native_noesis_texture\":"+(
                        _captureSource=="native-noesis-rendertexture" &&
                        !String.IsNullOrEmpty(_lastFrame) && File.Exists(_lastFrame)?
                        "true":"false")+",\n"+
                    "  \"pixel_exact_composited_game_screenshot\":"+(
                        _captureSource=="unity-game-composited-screen" &&
                        !String.IsNullOrEmpty(_lastFrame) && File.Exists(_lastFrame)?
                        "true":"false")+",\n"+
                    "  \"active_map\":"+Json(_lastMap)+",\n"+
                    "  \"map_load_event_count\":"+_mapLoadCount+",\n"+
                    "  \"map_unload_event_count\":"+_mapUnloadCount+",\n"+
                    "  \"active_season_route\":"+Json(_activeSeason)+",\n"+

                    "  \"season_atlas_visual_override_verified\":false,\n"+
                    "  \"native_launch_isolation_safe\":true,\n"+
                    "  \"last_error\":"+Json(_lastError)+"\n"+
                    "}\n";
                string temp=Path.Combine(_output,".status-writing-"+Guid.NewGuid().ToString("N"));
                File.WriteAllText(temp,json);
                string final=Path.Combine(_output,"live-status.json");
                if(File.Exists(final))File.Delete(final);
                File.Move(temp,final);
            }
            catch(Exception error){Logger.LogWarning("Live status: "+error.Message);}
        }

        private static bool MenuPrefix(object __instance,string param)
        {
            var app=Active;
            if(app==null || !app._verified)return true;
            if(param!="OriginsLegacyCampaign" && param!="LegacyBack" &&
               param!="LegacyStart" &&
               (param==null || !param.StartsWith("LegacyM",StringComparison.Ordinal)))
                return true;
            var menu=__instance as Noesis.UserControl;
            if(menu==null)return true;
            var screen=menu.FindName("SpriteSuiteOriginsCampaignScreen") as Noesis.UIElement;
            if(screen==null)return true; // Original controls must not be affected.
            try
            {
                MenuResult result=Campaign.HandleCommand(param);
                if(result.Action==MenuAction.Ignored)return true;
                ++app._nativeMenuActions;
                app._lastMenuCommand=param;
                app.Log("REAL Noesis menu callback: "+param+
                        " action="+result.Action);
                if(result.Action==MenuAction.OpenCampaign)
                    screen.Visibility=Noesis.Visibility.Visible;
                else if(result.Action==MenuAction.BackToMenu)
                    screen.Visibility=Noesis.Visibility.Collapsed;
                else if(result.Action==MenuAction.SelectedMission)
                {
                    var selected=menu.FindName("SpriteSuiteSelectedMission") as Noesis.TextBlock;
                    if(selected!=null)selected.Text="Mission "+result.Mission;
                }
                else if(result.Action==MenuAction.LaunchRequested)
                {
                    // Only launch an installed, map-manager-verified map through
                    // the very same native path used by the built-in game menu.
                    bool started=app.TryStartOriginalMission(result.MapFile);
                    if(!started)app.Log("Native mission launch rejected: "+result.MapFile);
                }
                app.WriteStatus();
                return false;
            }
            catch(Exception exc)
            {
                app.Fail("Menu action: "+exc);
                app.WriteStatus();
                return false;
            }
        }

        private bool TryStartOriginalMission(string name)
        {
            try
            {
                if(String.IsNullOrEmpty(name) || name!=Path.GetFileName(name) ||
                   !name.EndsWith(".map",StringComparison.OrdinalIgnoreCase))
                    return false;
                string builtin=Path.Combine(Application.streamingAssetsPath,"Maps",name);
                if(!File.Exists(builtin)) {
                    Log("Mission map not in original installed StreamingAssets: "+name);
                    return false;
                }
                // Decompiled, SHA-pinned MapFileManager stores FileHeader.fileName
                // using Path.GetFileNameWithoutExtension, NOT the .map suffix.
                string fileKey=Path.GetFileNameWithoutExtension(name);
                MapFileManager files=MapFileManager.Instance;
                FileHeader header=files==null?null:
                    files.GetHeaderFromFileNameForRestart(fileKey,false,true,false);
                bool freebuild=false;
                if(header==null && files!=null) {
                    header=files.GetHeaderFromFileNameForRestart(fileKey,true,true,false);
                    freebuild=header!=null;
                }
                if(header==null) {
                    Log("MapFileManager has no registered built-in mission: "+name);
                    return false;
                }
                if(header.filePath==null ||
                   !String.Equals(Path.GetFullPath(header.filePath),
                    Path.GetFullPath(builtin),StringComparison.OrdinalIgnoreCase))
                {
                    Log("Game map metadata has unexpected file path; refusing launch");
                    return false;
                }
                var vm=CrusaderDE.MainViewModel.Instance;
                if(vm==null || vm.HUDIngameMenu==null)return false;
                var restart=new CrusaderDE.HUD_IngameMenu.RestartMapInfo();
                restart.selectedHeader=header;
                restart.missionType=(Enums.StartUpUIPanels)(freebuild?2:1);
                restart.difficulty=(Enums.GameDifficulty)1;
                vm.PreStartMapMission();
                vm.HUDIngameMenu.restartMapInfo=restart;
                vm.HUDIngameMenu.restartSkirmishMapInfo=null;
                vm.HUDIngameMenu.restartMPInfo=null;
                Log("Requesting native standalone map loader: "+name);
                _pendingMission=name;
                _mapLoadMatched=false;
                _nativeMissionLaunchVerified=false;
                CrusaderDE.FRONT_StandaloneMission.StartMap(restart);
                WriteStatus();
                return true; // Request submitted; actual map-load event attests entry.
            }
            catch(Exception exc){Fail("Native map loader: "+exc);return false;}
        }

        private void OnGameMapLoad(MapLoadEventArgs args)
        {
            try {
                ++_mapLoadCount;
                string name=Path.GetFileName(args.FileName??args.MapName??"");
                _lastMap=name;
                if(!String.IsNullOrEmpty(_pendingMission) &&
                   String.Equals(name,_pendingMission,StringComparison.OrdinalIgnoreCase))
                {
                    _mapLoadMatched=true;
                    Log("Native map load callback matched requested mission; waiting for postload: "+name);
                }
                _activeSeason=Seasons.OnMapLoaded(name);
                Log("REAL MAP LOAD callback: "+name+" season_route="+(_activeSeason??"none"));
                // Actual visual atlas swaps are not enabled until reversibility
                // has been established on the exact installed game build.
                WriteStatus();
            } catch(Exception exc) {Fail("MapLoad handler: "+exc);}
        }

        private void OnGameMapPostLoad(MapPostLoadEventArgs args)
        {
            try {
                ++_postLoadCount;
                if(_mapLoadMatched && !String.IsNullOrEmpty(_pendingMission) &&
                   args.LoadData.errorCode==1 && args.StartGameThread) {
                    _nativeMissionLaunchVerified=true;
                    Log("VERIFIED native game postload for requested mission: "+_pendingMission);
                    _pendingMission=null;
                    _mapLoadMatched=false;
                } else {
                    Log("Native postload callback; errorCode="+args.LoadData.errorCode+
                        " startThread="+args.StartGameThread);
                }
                WriteStatus();
            } catch(Exception exc) {Fail("MapPostLoad handler: "+exc);}
        }

        private void OnGameMapUnload(MapUnloadEventArgs args)
        {
            try {
                ++_mapUnloadCount;
                Seasons.OnMapUnloaded();
                _pendingMission=null;_mapLoadMatched=false;
                _activeSeason=null;_lastMap=null;
                Log("REAL MAP UNLOAD callback, season route reset");
                WriteStatus();
            } catch(Exception exc) {Fail("MapUnload handler: "+exc);}
        }

        private IEnumerator CaptureLoop()
        {
            yield return new WaitForSecondsRealtime(2.0f);
            while(_verified && _captureEnabled)
            {
                yield return new WaitForEndOfFrame();
                try {
                    if(!Application.isBatchMode && Time.realtimeSinceStartup>=_nextCapture) {
                        _nextCapture=Time.realtimeSinceStartup+2.0f;
                        CaptureOneNativeFrame();
                    }
                } catch(Exception error) {Fail("Native capture: "+error.Message);}
                yield return new WaitForSecondsRealtime(0.20f);
            }
        }

        private static bool CompletePng(string file)
        {
            if(!File.Exists(file) || new FileInfo(file).Length<60)return false;
            using(var stream=File.Open(file,FileMode.Open,FileAccess.Read,FileShare.Read))
            {
                byte[] marker=new byte[8];
                if(stream.Read(marker,0,8)!=8)return false;
                byte[] sig={137,80,78,71,13,10,26,10};
                for(int i=0;i<8;i++)if(marker[i]!=sig[i])return false;
                stream.Seek(-8,SeekOrigin.End);
                byte[] end=new byte[4];
                return stream.Read(end,0,4)==4 &&
                    end[0]==73 && end[1]==69 && end[2]==78 && end[3]==68;
            }
        }

        private void ConfirmFrame(string file,string kind)
        {
            if(!CompletePng(file))return;
            _lastFrame=file;_captureSource=kind;
            ++_frameNumber;
            // Only our own auto-generated PNGs are eligible for pruning.
            var entries=Directory.GetFiles(_output,"native-frame-*.png");
            Array.Sort(entries,(a,b)=>File.GetCreationTimeUtc(a)
                                     .CompareTo(File.GetCreationTimeUtc(b)));
            for(int i=0;i<entries.Length-MaxFrames;i++) {
                if(entries[i]!=file)try{File.Delete(entries[i]);}
                                   catch(IOException){}
            }
            WriteStatus();
        }

        private void CaptureOneNativeFrame()
        {
            if(!String.IsNullOrEmpty(_pendingCapture))
            {
                try {
                    if(CompletePng(_pendingCapture))
                        ConfirmFrame(_pendingCapture,_pendingSource);
                    else if(Time.realtimeSinceStartup-_pendingAt>12.0f)
                        Fail("Native screenshot was not written within 12 seconds");
                    else return;
                } catch(IOException){return;}
                _pendingCapture=null;
            }
            var views=UnityEngine.Object.FindObjectsOfType<NoesisView>();
            _viewsLastSeen=views==null?0:views.Length;
            if(_viewsLastSeen<=0){WriteStatus();return;}
            NoesisView selected=null;
            for(int index=0;index<views.Length;++index) {
                if(views[index]!=null && views[index].isActiveAndEnabled &&
                    views[index].Content!=null) { selected=views[index];break; }
            }
            if(selected==null){WriteStatus();return;}
            string file=Path.Combine(_output,
                "native-frame-"+(_captureRequest++).ToString("D8")+".png");
            if(selected.Texture!=null) {
                RenderTexture target=selected.Texture;
                if(target.width<1 || target.height<1 ||
                    target.width>4096 || target.height>4096)return;
                RenderTexture previous=RenderTexture.active;
                Texture2D image=null;
                try {
                    RenderTexture.active=target;
                    image=new Texture2D(target.width,target.height,
                                        TextureFormat.RGBA32,false);
                    image.ReadPixels(new Rect(0,0,target.width,target.height),0,0);
                    image.Apply();
                    byte[] nativePixels=image.EncodeToPNG();
                    string temp=file+".writing";
                    File.WriteAllBytes(temp,nativePixels);
                    File.Move(temp,file);
                } finally {
                    RenderTexture.active=previous;
                    if(image!=null)UnityEngine.Object.Destroy(image);
                }
                ConfirmFrame(file,"native-noesis-rendertexture");
            } else {
                // This captures the real composited Unity display with Noesis,
                // not a falsely claimed isolated Noesis surface.
                ScreenCapture.CaptureScreenshot(file);
                _pendingCapture=file;
                _pendingSource="unity-game-composited-screen";
                _pendingAt=Time.realtimeSinceStartup;
            }
        }

        private void DisableHooks()
        {
            if(_onMapLoad!=null){_onMapLoad.Dispose();_onMapLoad=null;}
            if(_onMapUnload!=null){_onMapUnload.Dispose();_onMapUnload=null;}
            if(_onPostLoad!=null){_onPostLoad.Dispose();_onPostLoad=null;}
            if(_harmony!=null){_harmony.UnpatchSelf();_harmony=null;}
        }
        private void OnDestroy()
        {
            _captureEnabled=false;
            DisableHooks();
            Log("Plugin OnDestroy; map observers and Harmony hooks removed");
            WriteStatus();
            if(ReferenceEquals(Active,this))Active=null;
        }
    }
}
