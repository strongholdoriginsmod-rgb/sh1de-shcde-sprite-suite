using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Rewrites a requested Crusader music path to the European stand-in the
    /// payload already ships.
    /// </summary>
    /// <remarks>
    /// The music table override only reaches SFXManager.playMusic(int).  The
    /// gameplay path is SFXManager.playMusic(string), whose argument comes from
    /// the native display-list state and never touches music_filenames, so the
    /// table can never influence it.  Rewriting the argument reaches both.
    ///
    /// The comparison follows what playMusic(string) itself does: lowercase the
    /// path, keep the segment after the last separator.  Replacements are full
    /// "fx\music\eu_*.raw" paths so the caller's volumeData lookup — which uses
    /// the whole string — lands on the volume entry registered for that track.
    /// </remarks>
    internal static class MusicRouteRewriter
    {
        private const string StopSignal = "null.raw";

        private static readonly char[] Separators = new[] { '\\', '/' };

        private static readonly Dictionary<string, string> Map = Build();
        internal static int Count
        {
            get { return Map.Count; }
        }

        internal static bool TryRewrite(string fullpath, out string replacement)
        {
            replacement = null;
            if (string.IsNullOrEmpty(fullpath))
            {
                return false;
            }
            string lowered = fullpath.ToLowerInvariant();
            int separator = lowered.LastIndexOfAny(Separators);
            string requested = separator < 0
                ? lowered
                : lowered.Substring(separator + 1);
            if (requested.Length == 0
                || string.Equals(requested, StopSignal, StringComparison.Ordinal))
            {
                return false;
            }
            return Map.TryGetValue(requested, out replacement);
        }

        internal static bool TryResolvePcmRoute(
            string fullpath,
            out string replacement,
            out string vanillaFallback)
        {
            vanillaFallback = null;
            if (TryRewrite(fullpath, out replacement))
            {
                vanillaFallback = fullpath;
                return true;
            }
            replacement = null;
            return false;
        }

        private static Dictionary<string, string> Build()
        {
            string[] requested = GeneratedMusicRouteContract.RequestedFiles;
            string[] replacements = GeneratedMusicRouteContract.ReplacementPaths;
            if (requested == null
                || replacements == null
                || requested.Length != replacements.Length
                || requested.Length != GeneratedMusicRouteContract.EntryCount
                || requested.Length == 0)
            {
                throw new InvalidOperationException(
                    "Generated music route contract is not a complete pair table");
            }
            Dictionary<string, string> map =
                new Dictionary<string, string>(
                    requested.Length,
                    StringComparer.OrdinalIgnoreCase);
            for (int index = 0; index < requested.Length; index++)
            {
                string key = requested[index];
                string value = replacements[index];
                if (string.IsNullOrEmpty(key)
                    || string.IsNullOrEmpty(value)
                    || key.IndexOfAny(Separators) >= 0
                    || string.Equals(key, StopSignal, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException(
                        "Generated music route entry is not a rewritable pair: " + key);
                }
                if (map.ContainsKey(key))
                {
                    throw new InvalidOperationException(
                        "Generated music route contains a duplicate key: " + key);
                }
                map.Add(key, value);
            }
            return map;
        }

    }
}
