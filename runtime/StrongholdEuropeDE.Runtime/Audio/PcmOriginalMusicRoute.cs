using System;
using System.Threading;

namespace StrongholdEuropeDE.Runtime.Audio
{
    /// <summary>
    /// Exact Crusader request captured before the eu_ rewrite. Prepared route
    /// and live lease share this same instance so a later audio-thread reader
    /// fault can restart the original route on Unity's main thread.
    /// </summary>
    internal sealed class PcmOriginalMusicRoute
    {
        private const string RawMusicPrefix = "fx\\music\\";

        private readonly Action<string, float, bool, bool, bool, bool> _restart;
        private int _restartState;

        internal PcmOriginalMusicRoute(
            string fullPath,
            float gameVolume,
            bool loop,
            bool followon,
            bool fadePrevious,
            bool restartOnSamePiece,
            Action<string, float, bool, bool, bool, bool> restart)
        {
            if (!IsCanonicalRawMusicPath(fullPath))
            {
                throw new ArgumentException(
                    "Original PCM fallback route is not canonical",
                    "fullPath");
            }
            FullPath = fullPath;
            GameVolume = gameVolume;
            Loop = loop;
            Followon = followon;
            FadePrevious = fadePrevious;
            RestartOnSamePiece = restartOnSamePiece;
            _restart = restart ?? throw new ArgumentNullException("restart");
        }

        internal string FullPath { get; private set; }
        internal float GameVolume { get; private set; }
        internal bool Loop { get; private set; }
        internal bool Followon { get; private set; }
        internal bool FadePrevious { get; private set; }
        internal bool RestartOnSamePiece { get; private set; }

        internal bool Restarted
        {
            get { return Volatile.Read(ref _restartState) == 2; }
        }

        /// <summary>
        /// Re-entrancy safe because replay traverses the patched SFXManager
        /// method again. A synchronous failure resets the attempt. The caller
        /// may also reject a normally returned but unconfirmed manager restart
        /// without ever reattaching the faulted procedural clip.
        /// </summary>
        internal bool TryRestart()
        {
            if (Interlocked.CompareExchange(ref _restartState, 1, 0) != 0)
            {
                return Restarted;
            }
            try
            {
                _restart(
                    FullPath,
                    GameVolume,
                    Loop,
                    Followon,
                    FadePrevious,
                    RestartOnSamePiece);
                Volatile.Write(ref _restartState, 2);
                return true;
            }
            catch
            {
                Volatile.Write(ref _restartState, 0);
                return false;
            }
        }

        /// <summary>
        /// MyAudioManager has no success return. A replay delegate can return
        /// normally while leaving the manager stopped. The exact ownership
        /// surface calls this only after proving that outcome, so a later
        /// vanilla retry remains possible from an owned-free manager state.
        /// </summary>
        internal void MarkRestartUnconfirmed()
        {
            Interlocked.CompareExchange(ref _restartState, 0, 2);
        }

        private static bool IsCanonicalRawMusicPath(string value)
        {
            if (string.IsNullOrEmpty(value)
                || value.Length > 260
                || !value.StartsWith(RawMusicPrefix, StringComparison.OrdinalIgnoreCase)
                || !value.EndsWith(".raw", StringComparison.OrdinalIgnoreCase)
                || value.IndexOf('/') >= 0
                || value.IndexOf("..", StringComparison.Ordinal) >= 0)
            {
                return false;
            }
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (character == '\r'
                    || character == '\n'
                    || character == '\0'
                    || character == '|')
                {
                    return false;
                }
            }
            return true;
        }
    }
}
