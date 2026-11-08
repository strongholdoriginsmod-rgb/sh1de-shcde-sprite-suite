// Offline syntax-only mocks. NEVER ship these as a game plugin or ABI proof.
using System;

namespace BepInEx
{
    [AttributeUsage(AttributeTargets.Class, AllowMultiple = false)]
    public sealed class BepInPlugin : Attribute
    {
        public BepInPlugin(string guid, string name, string version) { }
    }

    [AttributeUsage(AttributeTargets.Class, AllowMultiple = true)]
    public sealed class BepInDependency : Attribute
    {
        public BepInDependency(string guid, string version) { }
    }

    public class BaseUnityPlugin
    {
        protected readonly LoggerProxy Logger = new LoggerProxy();
    }

    public sealed class LoggerProxy
    {
        public void LogInfo(string message) { }
        public void LogError(string message) { }
    }
}

namespace APIShared
{
    public sealed class ModApiClient
    {
        public void WhenReady(Action<ModApiClient> callback) { }
    }

    public static class ApiShared
    {
        public static ModApiClient ForMod(string guid) { return new ModApiClient(); }
    }
}
