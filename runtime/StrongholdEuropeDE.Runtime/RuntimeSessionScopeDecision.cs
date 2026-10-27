namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Decides whether process-local gameplay mutations are safe for the
    /// current session shape. Crusader DE represents a locally-created
    /// skirmish as a network session too, so the network flag alone cannot
    /// distinguish it from a real multiplayer match.
    /// </summary>
    internal static class RuntimeSessionScopeDecision
    {
        internal static bool AllowsLocalMutation(
            bool networked,
            bool localHost,
            int otherHumanPlayers)
        {
            // The question that decides safety is not "host or client" but
            // "can ANOTHER human observe or desynchronise this". Loaded local
            // skirmish saves report networked=true and localHost=false even
            // though their complete network roster contains no remote human.
            // Conversely, a real client exposes at least one other human in
            // that same roster. A negative count means the roster could not be
            // read and therefore remains suppressed.
            return !networked
                || otherHumanPlayers == 0;
        }

        internal static bool AllowsDiplomacyMap(
            bool networked,
            bool localHost,
            int otherHumanPlayers,
            bool hasGameData,
            bool hasLastGameState,
            bool multiplayerMap,
            bool hasDirector,
            bool directorMultiplayerGame,
            bool hasMainViewModel,
            bool skirmishModeVisible)
        {
            if (!AllowsLocalMutation(
                    networked,
                    localHost,
                    otherHumanPlayers)
                || !hasGameData
                || !hasLastGameState
                || !hasDirector
                || !hasMainViewModel
                || !skirmishModeVisible)
            {
                return false;
            }

            // In a solo skirmish these two engine flags are true even though
            // no second human can observe or desynchronise the local
            // mutations. Offline maps keep the stricter legacy classification
            // so campaigns and non-skirmish maps remain out.
            return networked
                || (!multiplayerMap && !directorMultiplayerGame);
        }

        internal static string Status(
            bool networked,
            bool localHost,
            int otherHumanPlayers)
        {
            if (!networked)
            {
                return "offline";
            }
            if (localHost && otherHumanPlayers == 0)
            {
                return "solo_host";
            }
            if (otherHumanPlayers == 0)
            {
                return "solo_loaded";
            }
            if (!localHost)
            {
                return "network_client";
            }
            if (otherHumanPlayers > 0)
            {
                return "multiplayer";
            }
            return "indeterminate";
        }
    }
}
