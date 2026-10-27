using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace StrongholdEuropeDE.Runtime.Audio
{
    internal enum PcmFaultRecoveryOutcome
    {
        None = 0,
        UnownedCurrentPreserved = 1,
        VanillaNextPromoted = 2,
        OriginalRouteRestarted = 3,
        VanillaIdle = 4,
        OriginalRouteRetryPending = 5,
    }

    internal sealed class PcmMusicOwnershipSnapshot
    {
        internal PcmMusicOwnershipSnapshot(
            AudioClip current,
            AudioClip next,
            AudioClip playingSource,
            string pendingFadeRequest)
        {
            Current = AliveOrNull(current);
            Next = AliveOrNull(next);
            PlayingSource = AliveOrNull(playingSource);
            PendingFadeRequest = pendingFadeRequest;
        }

        internal AudioClip Current { get; private set; }

        internal AudioClip Next { get; private set; }

        internal AudioClip PlayingSource { get; private set; }

        internal string PendingFadeRequest { get; private set; }

        internal bool Owns(AudioClip clip)
        {
            return !ReferenceEquals(clip, null)
                && clip != null
                && (ReferenceEquals(Current, clip)
                    || ReferenceEquals(Next, clip)
                    || ReferenceEquals(PlayingSource, clip));
        }

        internal bool HasPendingFade(string request)
        {
            return !string.IsNullOrEmpty(request)
                && string.Equals(
                    PendingFadeRequest,
                    request,
                    StringComparison.Ordinal);
        }

        private static AudioClip AliveOrNull(AudioClip clip)
        {
            return ReferenceEquals(clip, null) || clip == null ? null : clip;
        }
    }

    /// <summary>
    /// Exact pinned view of the procedural music owners in MyAudioManager.
    /// A stopped AudioSource deliberately does not retain its stale clip field;
    /// current/next fields and a currently playing source are the live owners.
    /// </summary>
    internal sealed class PcmMusicOwnershipSurface
    {
        private readonly FieldInfo _instance;
        private readonly FieldInfo _musicClip;
        private readonly FieldInfo _nextMusicClip;
        private readonly FieldInfo _musicSource;
        private readonly FieldInfo _musicMode;
        private readonly FieldInfo _fadingOutMusic;
        private readonly FieldInfo _fadeOutName;
        private readonly FieldInfo _nextMusicLoop;
        private readonly FieldInfo _nextMusicSoundVolume;
        private readonly FieldInfo _musicSoundVolume;
        private readonly FieldInfo _musicAboutToLoop;
        private readonly FieldInfo _musicAboutToLoopTime;
        private readonly MethodInfo _updateMusicVolume;

        private PcmMusicOwnershipSurface(
            FieldInfo instance,
            FieldInfo musicClip,
            FieldInfo nextMusicClip,
            FieldInfo musicSource,
            FieldInfo musicMode,
            FieldInfo fadingOutMusic,
            FieldInfo fadeOutName,
            FieldInfo nextMusicLoop,
            FieldInfo nextMusicSoundVolume,
            FieldInfo musicSoundVolume,
            FieldInfo musicAboutToLoop,
            FieldInfo musicAboutToLoopTime,
            MethodInfo updateMusicVolume)
        {
            _instance = instance;
            _musicClip = musicClip;
            _nextMusicClip = nextMusicClip;
            _musicSource = musicSource;
            _musicMode = musicMode;
            _fadingOutMusic = fadingOutMusic;
            _fadeOutName = fadeOutName;
            _nextMusicLoop = nextMusicLoop;
            _nextMusicSoundVolume = nextMusicSoundVolume;
            _musicSoundVolume = musicSoundVolume;
            _musicAboutToLoop = musicAboutToLoop;
            _musicAboutToLoopTime = musicAboutToLoopTime;
            _updateMusicVolume = updateMusicVolume;
        }

        internal static PcmMusicOwnershipSurface ResolveExact()
        {
            Type type = typeof(MyAudioManager);
            if (!string.Equals(type.FullName, "MyAudioManager", StringComparison.Ordinal)
                || !string.Equals(
                    type.Assembly.GetName().Name,
                    "Assembly-CSharp",
                    StringComparison.Ordinal))
            {
                throw new TypeLoadException(
                    "Exact MyAudioManager type was not found");
            }
            return new PcmMusicOwnershipSurface(
                RequireField(type, "instance", typeof(MyAudioManager), true),
                RequireField(type, "musicClip", typeof(AudioClip), false),
                RequireField(type, "nextMusicClip", typeof(AudioClip), false),
                RequireField(type, "musicSource", typeof(AudioSource), false),
                RequireField(type, "musicMode", typeof(int), false),
                RequireField(type, "fadingOutMusic", typeof(bool), false),
                RequireField(type, "fadeOutName", typeof(string), false),
                RequireField(type, "nextMusicLoop", typeof(bool), false),
                RequireField(type, "nextMusic_SoundVolume", typeof(float), false),
                RequireField(type, "music_SoundVolume", typeof(float), false),
                RequireField(type, "musicAboutToLoop", typeof(bool), false),
                RequireField(type, "musicAboutToLoopTime", typeof(DateTime), false),
                RequireMethod(
                    type,
                    "updateMusicVolumeFromSettings",
                    BindingFlags.Instance | BindingFlags.Public,
                    Type.EmptyTypes,
                    true));
        }

        internal static MethodInfo[] ResolveLifecycleTargetsExact()
        {
            Type type = typeof(MyAudioManager);
            MethodInfo monitor = RequireMethod(
                type,
                "MonitorLoadedSounds",
                BindingFlags.Instance | BindingFlags.NonPublic,
                Type.EmptyTypes,
                false);
            MethodInfo stop = RequireMethod(
                type,
                "stopMusic",
                BindingFlags.Instance | BindingFlags.Public,
                Type.EmptyTypes,
                true);
            MethodInfo play = RequireMethod(
                type,
                "PlayMusic",
                BindingFlags.Instance | BindingFlags.Public,
                new[]
                {
                    typeof(string),
                    typeof(float),
                    typeof(float),
                    typeof(bool),
                    typeof(bool),
                    typeof(bool),
                },
                true);
            ParameterInfo[] parameters = play.GetParameters();
            string[] names =
            {
                "soundName",
                "gameVolume",
                "soundVolume",
                "loop",
                "followon",
                "fadeOut",
            };
            for (int index = 0; index < parameters.Length; index++)
            {
                if (!string.Equals(
                        parameters[index].Name,
                        names[index],
                        StringComparison.Ordinal))
                {
                    throw new MissingMethodException(
                        "MyAudioManager.PlayMusic parameter names changed");
                }
            }
            if (parameters[0].IsOptional
                || parameters[1].IsOptional
                || parameters[2].IsOptional
                || !parameters[3].IsOptional
                || !object.Equals(parameters[3].DefaultValue, true)
                || !parameters[4].IsOptional
                || !object.Equals(parameters[4].DefaultValue, false)
                || !parameters[5].IsOptional
                || !object.Equals(parameters[5].DefaultValue, false))
            {
                throw new MissingMethodException(
                    "MyAudioManager.PlayMusic defaults changed");
            }
            return new[] { monitor, stop, play };
        }

        internal bool TryCapture(out PcmMusicOwnershipSnapshot snapshot)
        {
            snapshot = null;
            try
            {
                MyAudioManager manager = _instance.GetValue(null)
                    as MyAudioManager;
                if (ReferenceEquals(manager, null) || manager == null)
                {
                    snapshot = new PcmMusicOwnershipSnapshot(
                        null,
                        null,
                        null,
                        null);
                    return true;
                }
                if (manager.GetType() != typeof(MyAudioManager))
                {
                    return false;
                }
                int mode = (int)_musicMode.GetValue(manager);
                if (mode < 0 || mode > 2)
                {
                    return false;
                }
                AudioClip current = _musicClip.GetValue(manager) as AudioClip;
                AudioClip next = _nextMusicClip.GetValue(manager) as AudioClip;
                bool fading = (bool)_fadingOutMusic.GetValue(manager);
                string fadeName = _fadeOutName.GetValue(manager) as string;
                AudioSource source = _musicSource.GetValue(manager) as AudioSource;
                AudioClip playing = null;
                if (!ReferenceEquals(source, null)
                    && source != null
                    && source.isPlaying)
                {
                    playing = source.clip;
                }
                snapshot = new PcmMusicOwnershipSnapshot(
                    current,
                    next,
                    playing,
                    mode == 2 && fading && !string.IsNullOrEmpty(fadeName)
                        ? fadeName
                        : null);
                return true;
            }
            catch
            {
                snapshot = null;
                return false;
            }
        }

        /// <summary>
        /// Stops and detaches only procedural clips owned by this lane. The
        /// exact manager fields are cleared before Unity Destroy can run, so a
        /// later MonitorLoadedSounds call cannot dereference a destroyed clip.
        /// </summary>
        internal bool TryDetachOwnedClips(
            IList<AudioClip> ownedClips,
            IList<string> ownedPendingFadeRequests,
            out bool detachedAny)
        {
            PcmFaultRecoveryOutcome ignoredOutcome;
            return TryDetachOwnedClipsCore(
                ownedClips,
                ownedPendingFadeRequests,
                null,
                false,
                out detachedAny,
                out ignoredOutcome);
        }

        /// <summary>
        /// Fault-only detach. An already playing unowned source always wins;
        /// only faulted references are removed and no restart is attempted.
        /// Otherwise a faulted current path is replaced in the same main-thread
        /// call by a healthy unowned Next or its bound original Crusader route.
        /// If the first original-route attempt fails, the manager is left
        /// stopped and owned-free while the lane schedules one later retry. A
        /// faulted reader is never restored as current/source for that retry.
        /// </summary>
        internal bool TryRecoverFaultedClips(
            IList<AudioClip> faultedClips,
            IList<string> faultedRequests,
            PcmOriginalMusicRoute originalRoute,
            out bool detachedAny,
            out PcmFaultRecoveryOutcome outcome)
        {
            return TryDetachOwnedClipsCore(
                faultedClips,
                faultedRequests,
                originalRoute,
                true,
                out detachedAny,
                out outcome);
        }

        /// <summary>
        /// Executes the single delayed retry only while the manager is still
        /// idle. A newer healthy vanilla route always wins. A failed or
        /// unconfirmed retry is scrubbed back to the same owned-free idle
        /// state before this method returns.
        /// </summary>
        internal bool TryRetryFaultedOriginalRoute(
            IList<AudioClip> faultedClips,
            IList<string> faultedRequests,
            PcmOriginalMusicRoute originalRoute,
            out PcmFaultRecoveryOutcome outcome)
        {
            outcome = PcmFaultRecoveryOutcome.None;
            if (faultedClips == null)
            {
                throw new ArgumentNullException("faultedClips");
            }
            if (faultedRequests == null)
            {
                throw new ArgumentNullException("faultedRequests");
            }
            if (originalRoute == null)
            {
                throw new ArgumentNullException("originalRoute");
            }

            MyAudioManager manager = null;
            AudioSource source = null;
            try
            {
                manager = _instance.GetValue(null) as MyAudioManager;
                if (ReferenceEquals(manager, null) || manager == null)
                {
                    originalRoute.MarkRestartUnconfirmed();
                    outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                    return true;
                }
                if (manager.GetType() != typeof(MyAudioManager))
                {
                    return false;
                }
                source = _musicSource.GetValue(manager) as AudioSource;

                AudioClip liveUnownedSource;
                if (TryGetLiveUnownedSource(
                        source,
                        faultedClips,
                        out liveUnownedSource))
                {
                    originalRoute.MarkRestartUnconfirmed();
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return TryPreserveLiveUnownedSource(
                        manager,
                        source,
                        liveUnownedSource,
                        faultedClips,
                        faultedRequests);
                }

                if (!IsOwnedFree(
                        manager,
                        source,
                        faultedClips,
                        faultedRequests))
                {
                    originalRoute.MarkRestartUnconfirmed();
                    outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                    return TryEnterVanillaIdleOwnedFree(
                        manager,
                        source,
                        faultedClips,
                        faultedRequests);
                }

                if (HasUnownedManagerRoute(manager, source))
                {
                    // A real request arrived between pumps. Never replace it
                    // with the now-stale recovery route.
                    originalRoute.MarkRestartUnconfirmed();
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return true;
                }

                if (TryRestartOriginalRouteOnce(
                        manager,
                        source,
                        faultedClips,
                        faultedRequests,
                        originalRoute))
                {
                    outcome = PcmFaultRecoveryOutcome.OriginalRouteRestarted;
                    return true;
                }

                originalRoute.MarkRestartUnconfirmed();
                if (TryGetLiveUnownedSource(
                        source,
                        faultedClips,
                        out liveUnownedSource))
                {
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return TryPreserveLiveUnownedSource(
                        manager,
                        source,
                        liveUnownedSource,
                        faultedClips,
                        faultedRequests);
                }
                outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                return TryEnterVanillaIdleOwnedFree(
                    manager,
                    source,
                    faultedClips,
                    faultedRequests);
            }
            catch
            {
                originalRoute.MarkRestartUnconfirmed();
                AudioClip liveUnownedSource;
                if (!ReferenceEquals(manager, null)
                    && manager != null
                    && TryGetLiveUnownedSource(
                        source,
                        faultedClips,
                        out liveUnownedSource))
                {
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return TryPreserveLiveUnownedSource(
                        manager,
                        source,
                        liveUnownedSource,
                        faultedClips,
                        faultedRequests);
                }
                outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                return !ReferenceEquals(manager, null)
                    && manager != null
                    && TryEnterVanillaIdleOwnedFree(
                        manager,
                        source,
                        faultedClips,
                        faultedRequests);
            }
        }

        private bool TryDetachOwnedClipsCore(
            IList<AudioClip> ownedClips,
            IList<string> ownedPendingFadeRequests,
            PcmOriginalMusicRoute originalRoute,
            bool requireHealthyCurrentReplacement,
            out bool detachedAny,
            out PcmFaultRecoveryOutcome outcome)
        {
            detachedAny = false;
            outcome = PcmFaultRecoveryOutcome.None;
            if (ownedClips == null)
            {
                throw new ArgumentNullException("ownedClips");
            }
            if (ownedPendingFadeRequests == null)
            {
                throw new ArgumentNullException("ownedPendingFadeRequests");
            }
            MyAudioManager manager = null;
            AudioSource source = null;
            try
            {
                manager = _instance.GetValue(null)
                    as MyAudioManager;
                if (ReferenceEquals(manager, null) || manager == null)
                {
                    return true;
                }
                if (manager.GetType() != typeof(MyAudioManager))
                {
                    return false;
                }

                AudioClip current = _musicClip.GetValue(manager) as AudioClip;
                AudioClip next = _nextMusicClip.GetValue(manager) as AudioClip;
                source = _musicSource.GetValue(manager) as AudioSource;
                AudioClip sourceClip = ReferenceEquals(source, null) || source == null
                    ? null
                    : source.clip;
                bool currentOwned = ContainsReference(ownedClips, current);
                bool nextOwned = ContainsReference(ownedClips, next);
                bool sourceOwned = ContainsReference(ownedClips, sourceClip);
                bool pendingFadeOwned =
                    (bool)_fadingOutMusic.GetValue(manager)
                    && ContainsOrdinal(
                        ownedPendingFadeRequests,
                        _fadeOutName.GetValue(manager) as string);
                PcmMusicDetachPlan plan = PcmMusicDetachPlan.Create(
                    currentOwned,
                    sourceOwned,
                    nextOwned,
                    !ReferenceEquals(next, null) && next != null,
                    pendingFadeOwned);
                if (!currentOwned
                    && !nextOwned
                    && !sourceOwned
                    && !pendingFadeOwned)
                {
                    return true;
                }
                detachedAny = true;

                AudioClip liveUnownedSource;
                if (requireHealthyCurrentReplacement
                    && TryGetLiveUnownedSource(
                        source,
                        ownedClips,
                        out liveUnownedSource))
                {
                    if (originalRoute != null)
                    {
                        originalRoute.MarkRestartUnconfirmed();
                    }
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return TryPreserveLiveUnownedSource(
                        manager,
                        source,
                        liveUnownedSource,
                        ownedClips,
                        ownedPendingFadeRequests);
                }

                if (plan.CurrentPathOwned)
                {
                    if (!ReferenceEquals(source, null)
                        && source != null
                        && sourceOwned
                        && source.isPlaying)
                    {
                        source.Stop();
                    }
                    if (currentOwned)
                    {
                        _musicClip.SetValue(manager, null);
                    }
                    if (plan.CancelPendingFade)
                    {
                        _fadingOutMusic.SetValue(manager, false);
                        _fadeOutName.SetValue(manager, string.Empty);
                    }

                    if (plan.PromoteUnownedNext
                        && !ReferenceEquals(source, null)
                        && source != null)
                    {
                        // Preserve an unowned (usually vanilla) follow-on by
                        // applying the exact promotion state synchronously.
                        source.loop = (bool)_nextMusicLoop.GetValue(manager);
                        source.clip = next;
                        _musicClip.SetValue(manager, next);
                        _nextMusicClip.SetValue(manager, null);
                        _musicSoundVolume.SetValue(
                            manager,
                            (float)_nextMusicSoundVolume.GetValue(manager));
                        _musicMode.SetValue(manager, 2);
                        if (plan.ResetLoopCue)
                        {
                            _musicAboutToLoop.SetValue(manager, false);
                            _musicAboutToLoopTime.SetValue(
                                manager,
                                DateTime.MinValue);
                        }
                        _updateMusicVolume.Invoke(manager, null);
                        source.Play();
                        outcome = PcmFaultRecoveryOutcome.VanillaNextPromoted;
                    }
                    else
                    {
                        if (requireHealthyCurrentReplacement
                            && plan.PromoteUnownedNext)
                        {
                            // The healthy Next could not be promoted because
                            // the exact source disappeared. Do not leave a
                            // half-pending manager that can block a later
                            // vanilla request.
                            outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                            return TryEnterVanillaIdleOwnedFree(
                                manager,
                                source,
                                ownedClips,
                                ownedPendingFadeRequests);
                        }
                        if (plan.RemoveOwnedNext)
                        {
                            _nextMusicClip.SetValue(manager, null);
                        }
                        if (!ReferenceEquals(source, null)
                            && source != null
                            && sourceOwned)
                        {
                            source.clip = null;
                        }
                        _musicMode.SetValue(manager, 0);
                        if (requireHealthyCurrentReplacement
                            && plan.RestartOriginalRoute)
                        {
                            bool restarted = originalRoute != null
                                && TryRestartOriginalRouteOnce(
                                    manager,
                                    source,
                                    ownedClips,
                                    ownedPendingFadeRequests,
                                    originalRoute);
                            if (!restarted)
                            {
                                if (originalRoute != null)
                                {
                                    originalRoute.MarkRestartUnconfirmed();
                                }
                                if (TryGetLiveUnownedSource(
                                        source,
                                        ownedClips,
                                        out liveUnownedSource))
                                {
                                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                                    return TryPreserveLiveUnownedSource(
                                        manager,
                                        source,
                                        liveUnownedSource,
                                        ownedClips,
                                        ownedPendingFadeRequests);
                                }
                                bool idleOwnedFree = TryEnterVanillaIdleOwnedFree(
                                    manager,
                                    source,
                                    ownedClips,
                                    ownedPendingFadeRequests);
                                outcome = idleOwnedFree && originalRoute != null
                                    ? PcmFaultRecoveryOutcome.OriginalRouteRetryPending
                                    : PcmFaultRecoveryOutcome.VanillaIdle;
                                return idleOwnedFree;
                            }
                            outcome = PcmFaultRecoveryOutcome.OriginalRouteRestarted;
                        }
                        else if (requireHealthyCurrentReplacement)
                        {
                            outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                        }
                    }
                }
                else
                {
                    if (plan.RemoveOwnedNext)
                    {
                        // A faulted/owned follow-on can be removed without
                        // interrupting an unrelated current clip.
                        _nextMusicClip.SetValue(manager, null);
                    }
                    if (plan.RestoreCurrentVolume)
                    {
                        // Cancel only our delayed eu_ token. The current
                        // vanilla/healthy clip keeps playing; restore the
                        // pre-fade volume through the exact public manager API.
                        _fadingOutMusic.SetValue(manager, false);
                        _fadeOutName.SetValue(manager, string.Empty);
                        _updateMusicVolume.Invoke(manager, null);
                    }
                    if (requireHealthyCurrentReplacement)
                    {
                        outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    }
                }

                bool ownedFree = IsOwnedFree(
                    manager,
                    source,
                    ownedClips,
                    ownedPendingFadeRequests);
                if (ownedFree)
                {
                    return true;
                }
                if (!requireHealthyCurrentReplacement)
                {
                    return false;
                }
                if (originalRoute != null)
                {
                    originalRoute.MarkRestartUnconfirmed();
                }
                if (TryGetLiveUnownedSource(
                        source,
                        ownedClips,
                        out liveUnownedSource))
                {
                    outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                    return TryPreserveLiveUnownedSource(
                        manager,
                        source,
                        liveUnownedSource,
                        ownedClips,
                        ownedPendingFadeRequests);
                }
                outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                return TryEnterVanillaIdleOwnedFree(
                    manager,
                    source,
                    ownedClips,
                    ownedPendingFadeRequests);
            }
            catch
            {
                if (requireHealthyCurrentReplacement
                    && !ReferenceEquals(manager, null)
                    && manager != null)
                {
                    if (originalRoute != null)
                    {
                        originalRoute.MarkRestartUnconfirmed();
                    }
                    AudioClip liveUnownedSource;
                    if (TryGetLiveUnownedSource(
                            source,
                            ownedClips,
                            out liveUnownedSource))
                    {
                        outcome = PcmFaultRecoveryOutcome.UnownedCurrentPreserved;
                        return TryPreserveLiveUnownedSource(
                            manager,
                            source,
                            liveUnownedSource,
                            ownedClips,
                            ownedPendingFadeRequests);
                    }
                    outcome = PcmFaultRecoveryOutcome.VanillaIdle;
                    return TryEnterVanillaIdleOwnedFree(
                        manager,
                        source,
                        ownedClips,
                        ownedPendingFadeRequests);
                }
                return false;
            }
        }

        private bool TryEnterVanillaIdleOwnedFree(
            MyAudioManager manager,
            AudioSource source,
            IList<AudioClip> ownedClips,
            IList<string> ownedPendingFadeRequests)
        {
            AudioClip liveUnownedSource;
            if (TryGetLiveUnownedSource(
                    source,
                    ownedClips,
                    out liveUnownedSource))
            {
                return TryPreserveLiveUnownedSource(
                    manager,
                    source,
                    liveUnownedSource,
                    ownedClips,
                    ownedPendingFadeRequests);
            }

            // Each mutation is isolated so a secondary Unity/reflection fault
            // cannot prevent the remaining owned references from being scrubbed.
            TryBestEffort(delegate
            {
                if (!ReferenceEquals(source, null) && source != null && source.isPlaying)
                {
                    source.Stop();
                }
            });
            TryBestEffort(delegate { _musicClip.SetValue(manager, null); });
            TryBestEffort(delegate { _nextMusicClip.SetValue(manager, null); });
            TryBestEffort(delegate
            {
                if (!ReferenceEquals(source, null) && source != null)
                {
                    source.clip = null;
                }
            });
            TryBestEffort(delegate { _musicMode.SetValue(manager, 0); });
            TryBestEffort(delegate { _fadingOutMusic.SetValue(manager, false); });
            TryBestEffort(delegate { _fadeOutName.SetValue(manager, string.Empty); });
            TryBestEffort(delegate { _musicAboutToLoop.SetValue(manager, false); });
            TryBestEffort(delegate
            {
                _musicAboutToLoopTime.SetValue(manager, DateTime.MinValue);
            });
            TryBestEffort(delegate { _updateMusicVolume.Invoke(manager, null); });

            try
            {
                return IsOwnedFree(
                    manager,
                    source,
                    ownedClips,
                    ownedPendingFadeRequests);
            }
            catch
            {
                return false;
            }
        }

        private bool TryPreserveLiveUnownedSource(
            MyAudioManager manager,
            AudioSource source,
            AudioClip liveUnownedSource,
            IList<AudioClip> ownedClips,
            IList<string> ownedPendingFadeRequests)
        {
            bool replaceCurrent = false;
            bool removeNext = false;
            bool cancelPendingFade = false;
            try
            {
                replaceCurrent = ContainsReference(
                    ownedClips,
                    _musicClip.GetValue(manager) as AudioClip);
                removeNext = ContainsReference(
                    ownedClips,
                    _nextMusicClip.GetValue(manager) as AudioClip);
                cancelPendingFade =
                    (bool)_fadingOutMusic.GetValue(manager)
                    && ContainsOrdinal(
                        ownedPendingFadeRequests,
                        _fadeOutName.GetValue(manager) as string);
            }
            catch
            {
                return false;
            }

            if (replaceCurrent)
            {
                TryBestEffort(delegate
                {
                    _musicClip.SetValue(manager, liveUnownedSource);
                });
            }
            if (removeNext)
            {
                TryBestEffort(delegate { _nextMusicClip.SetValue(manager, null); });
            }
            if (cancelPendingFade)
            {
                TryBestEffort(delegate { _fadingOutMusic.SetValue(manager, false); });
                TryBestEffort(delegate { _fadeOutName.SetValue(manager, string.Empty); });
                TryBestEffort(delegate { _updateMusicVolume.Invoke(manager, null); });
            }

            try
            {
                AudioClip current = _musicClip.GetValue(manager) as AudioClip;
                AudioClip stillPlaying = ReferenceEquals(source, null)
                    || source == null
                    ? null
                    : source.clip;
                return source.isPlaying
                    && ReferenceEquals(stillPlaying, liveUnownedSource)
                    && (!replaceCurrent
                        || ReferenceEquals(current, liveUnownedSource))
                    && IsOwnedFree(
                        manager,
                        source,
                        ownedClips,
                        ownedPendingFadeRequests);
            }
            catch
            {
                return false;
            }
        }

        private bool TryRestartOriginalRouteOnce(
            MyAudioManager manager,
            AudioSource source,
            IList<AudioClip> faultedClips,
            IList<string> faultedRequests,
            PcmOriginalMusicRoute originalRoute)
        {
            if (!originalRoute.TryRestart())
            {
                return false;
            }
            bool confirmed = (int)_musicMode.GetValue(manager) != 0
                && IsOwnedFree(
                    manager,
                    source,
                    faultedClips,
                    faultedRequests)
                && HasUnownedManagerRoute(manager, source);
            if (!confirmed)
            {
                originalRoute.MarkRestartUnconfirmed();
            }
            return confirmed;
        }

        private bool IsOwnedFree(
            MyAudioManager manager,
            AudioSource source,
            IList<AudioClip> ownedClips,
            IList<string> ownedPendingFadeRequests)
        {
            AudioClip current = _musicClip.GetValue(manager) as AudioClip;
            AudioClip next = _nextMusicClip.GetValue(manager) as AudioClip;
            AudioClip sourceClip = ReferenceEquals(source, null) || source == null
                ? null
                : source.clip;
            return !ContainsReference(ownedClips, current)
                && !ContainsReference(ownedClips, next)
                && !ContainsReference(ownedClips, sourceClip)
                && !((bool)_fadingOutMusic.GetValue(manager)
                    && ContainsOrdinal(
                        ownedPendingFadeRequests,
                        _fadeOutName.GetValue(manager) as string));
        }

        private bool HasUnownedManagerRoute(
            MyAudioManager manager,
            AudioSource source)
        {
            AudioClip current = _musicClip.GetValue(manager) as AudioClip;
            AudioClip next = _nextMusicClip.GetValue(manager) as AudioClip;
            AudioClip sourceClip = ReferenceEquals(source, null) || source == null
                ? null
                : source.clip;
            bool fading = (bool)_fadingOutMusic.GetValue(manager);
            string fadeName = _fadeOutName.GetValue(manager) as string;
            return IsAlive(current)
                || IsAlive(next)
                || (!ReferenceEquals(source, null)
                    && source != null
                    && source.isPlaying
                    && IsAlive(sourceClip))
                || ((int)_musicMode.GetValue(manager) != 0
                    && fading
                    && !string.IsNullOrEmpty(fadeName));
        }

        private static bool IsAlive(AudioClip clip)
        {
            return !ReferenceEquals(clip, null) && clip != null;
        }

        private static bool TryGetLiveUnownedSource(
            AudioSource source,
            IList<AudioClip> ownedClips,
            out AudioClip liveUnownedSource)
        {
            liveUnownedSource = null;
            try
            {
                if (ReferenceEquals(source, null)
                    || source == null
                    || !source.isPlaying)
                {
                    return false;
                }
                AudioClip sourceClip = source.clip;
                if (!IsAlive(sourceClip)
                    || ContainsReference(ownedClips, sourceClip))
                {
                    return false;
                }
                liveUnownedSource = sourceClip;
                return true;
            }
            catch
            {
                liveUnownedSource = null;
                return false;
            }
        }

        private static void TryBestEffort(Action action)
        {
            try
            {
                action();
            }
            catch
            {
                // The final exact readback decides whether detach succeeded.
            }
        }

        private static bool ContainsReference(
            IList<AudioClip> values,
            AudioClip candidate)
        {
            if (ReferenceEquals(candidate, null))
            {
                return false;
            }
            for (int index = 0; index < values.Count; index++)
            {
                if (ReferenceEquals(values[index], candidate))
                {
                    return true;
                }
            }
            return false;
        }

        private static bool ContainsOrdinal(
            IList<string> values,
            string candidate)
        {
            if (string.IsNullOrEmpty(candidate))
            {
                return false;
            }
            for (int index = 0; index < values.Count; index++)
            {
                if (string.Equals(
                    values[index],
                    candidate,
                    StringComparison.Ordinal))
                {
                    return true;
                }
            }
            return false;
        }

        private static FieldInfo RequireField(
            Type type,
            string name,
            Type fieldType,
            bool isStatic)
        {
            FieldInfo field = type.GetField(
                name,
                BindingFlags.NonPublic
                    | BindingFlags.DeclaredOnly
                    | (isStatic ? BindingFlags.Static : BindingFlags.Instance));
            if (field == null
                || field.FieldType != fieldType
                || field.IsStatic != isStatic
                || !field.IsPrivate)
            {
                throw new MissingFieldException(
                    "Exact MyAudioManager field was not found: " + name);
            }
            return field;
        }

        private static MethodInfo RequireMethod(
            Type type,
            string name,
            BindingFlags flags,
            Type[] parameters,
            bool shouldBePublic)
        {
            MethodInfo method = type.GetMethod(
                name,
                flags | BindingFlags.DeclaredOnly,
                null,
                parameters,
                null);
            if (method == null
                || method.IsStatic
                || method.ReturnType != typeof(void)
                || method.IsPublic != shouldBePublic
                || method.DeclaringType != type)
            {
                throw new MissingMethodException(
                    "Exact MyAudioManager lifecycle method was not found: "
                    + name);
            }
            return method;
        }
    }
}
