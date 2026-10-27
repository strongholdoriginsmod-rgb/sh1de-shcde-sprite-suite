using System;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class RosterTextEntry
    {
        internal string Kind;
        internal string LogicalId;
        internal string Section;
        internal int RawIndex;
        internal string InternalKey;
        internal string German;
        internal string English;

        internal string RawRouteKey
        {
            get
            {
                return Section + "_" + RawIndex.ToString("D3");
            }
        }

        internal string OwnedValue(bool german)
        {
            return german ? German : English;
        }
    }

    internal sealed class RosterHudBinding
    {
        internal string LogicalId;
        internal string Control;
        internal string InternalKey;
    }

    internal sealed class RosterMutationState
    {
        private readonly IDictionary<string, string> _dictionary;
        private readonly RosterTextEntry[] _entries;
        private readonly Dictionary<string, string> _originals;
        private readonly Dictionary<string, string> _owned;
        private bool _rolledBack;

        private RosterMutationState(
            IDictionary<string, string> dictionary,
            RosterTextEntry[] entries,
            Dictionary<string, string> originals,
            Dictionary<string, string> owned)
        {
            _dictionary = dictionary;
            _entries = entries;
            _originals = originals;
            _owned = owned;
        }

        internal IDictionary<string, string> Dictionary
        {
            get { return _dictionary; }
        }

        internal IReadOnlyDictionary<string, string> Originals
        {
            get { return _originals; }
        }

        internal IReadOnlyDictionary<string, string> Owned
        {
            get { return _owned; }
        }

        internal static RosterMutationState Apply(
            IDictionary<string, string> dictionary,
            RosterTextEntry[] entries,
            bool german)
        {
            if (dictionary == null)
            {
                throw new ArgumentNullException(nameof(dictionary));
            }
            if (entries == null || entries.Length == 0)
            {
                throw new ArgumentException("Roster entries are empty", nameof(entries));
            }

            Dictionary<string, string> originals =
                new Dictionary<string, string>(StringComparer.Ordinal);
            Dictionary<string, string> owned =
                new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (RosterTextEntry entry in entries)
            {
                if (entry == null
                    || string.IsNullOrEmpty(entry.InternalKey)
                    || !dictionary.ContainsKey(entry.InternalKey))
                {
                    throw new InvalidOperationException(
                        "Roster dictionary is missing an exact internal key");
                }
                if (originals.ContainsKey(entry.InternalKey))
                {
                    throw new InvalidOperationException(
                        "Roster dictionary mutation contains a duplicate key: "
                        + entry.InternalKey);
                }
                string original = dictionary[entry.InternalKey];
                string replacement = entry.OwnedValue(german);
                if (original == null || string.IsNullOrEmpty(replacement))
                {
                    throw new InvalidOperationException(
                        "Roster dictionary contains a null original/replacement: "
                        + entry.InternalKey);
                }
                originals.Add(entry.InternalKey, original);
                owned.Add(entry.InternalKey, replacement);
            }

            List<string> attempted = new List<string>();
            try
            {
                foreach (RosterTextEntry entry in entries)
                {
                    attempted.Add(entry.InternalKey);
                    dictionary[entry.InternalKey] = owned[entry.InternalKey];
                }
                foreach (RosterTextEntry entry in entries)
                {
                    string current;
                    if (!dictionary.TryGetValue(entry.InternalKey, out current)
                        || !string.Equals(
                            current,
                            owned[entry.InternalKey],
                            StringComparison.Ordinal))
                    {
                        throw new InvalidOperationException(
                            "Roster dictionary write verification failed: "
                            + entry.InternalKey);
                    }
                }
            }
            catch
            {
                for (int index = attempted.Count - 1; index >= 0; index--)
                {
                    string key = attempted[index];
                    try
                    {
                        string current;
                        if (dictionary.TryGetValue(key, out current)
                            && string.Equals(current, owned[key], StringComparison.Ordinal))
                        {
                            dictionary[key] = originals[key];
                        }
                    }
                    catch
                    {
                        // Preserve the activation exception. Every restore remains
                        // conditional, so a foreign value is never overwritten.
                    }
                }
                throw;
            }

            return new RosterMutationState(dictionary, entries, originals, owned);
        }

        internal bool VerifyOwnership(out string reason)
        {
            if (_rolledBack)
            {
                reason = "already_rolled_back";
                return false;
            }
            foreach (RosterTextEntry entry in _entries)
            {
                string current;
                if (!_dictionary.TryGetValue(entry.InternalKey, out current)
                    || !string.Equals(
                        current,
                        _owned[entry.InternalKey],
                        StringComparison.Ordinal))
                {
                    reason = "ownership_lost:" + entry.InternalKey;
                    return false;
                }
            }
            reason = string.Empty;
            return true;
        }

        internal int RollbackOwned()
        {
            if (_rolledBack)
            {
                return 0;
            }
            int restored = 0;
            foreach (RosterTextEntry entry in _entries)
            {
                try
                {
                    string current;
                    if (_dictionary.TryGetValue(entry.InternalKey, out current)
                        && string.Equals(
                            current,
                            _owned[entry.InternalKey],
                            StringComparison.Ordinal))
                    {
                        _dictionary[entry.InternalKey] = _originals[entry.InternalKey];
                        string restoredValue;
                        if (_dictionary.TryGetValue(
                                entry.InternalKey,
                                out restoredValue)
                            && string.Equals(
                                restoredValue,
                                _originals[entry.InternalKey],
                                StringComparison.Ordinal))
                        {
                            restored++;
                        }
                    }
                }
                catch
                {
                    // Rollback is best-effort and ownership-safe. The caller logs
                    // a failed_closed terminal event when fewer than all owned
                    // entries could be restored.
                }
            }
            _rolledBack = true;
            return restored;
        }

        internal static string ComputeOriginalsDigest(
            IDictionary<string, string> dictionary,
            RosterTextEntry[] entries)
        {
            if (dictionary == null || entries == null)
            {
                throw new ArgumentNullException();
            }
            StringBuilder rows = new StringBuilder();
            HashSet<string> keys = new HashSet<string>(StringComparer.Ordinal);
            foreach (RosterTextEntry entry in entries)
            {
                string value;
                if (entry == null
                    || !keys.Add(entry.InternalKey)
                    || !dictionary.TryGetValue(entry.InternalKey, out value)
                    || value == null)
                {
                    throw new InvalidOperationException(
                        "Cannot digest an incomplete roster dictionary");
                }
                rows.Append(entry.InternalKey);
                rows.Append('\t');
                rows.Append(Sha256(Encoding.UTF8.GetBytes(value)));
                rows.Append('\n');
            }
            return Sha256(Encoding.ASCII.GetBytes(rows.ToString()));
        }

        private static string Sha256(byte[] payload)
        {
            using (SHA256 algorithm = SHA256.Create())
            {
                byte[] digest = algorithm.ComputeHash(payload);
                char[] output = new char[digest.Length * 2];
                const string alphabet = "0123456789abcdef";
                for (int index = 0; index < digest.Length; index++)
                {
                    output[index * 2] = alphabet[digest[index] >> 4];
                    output[index * 2 + 1] = alphabet[digest[index] & 15];
                }
                return new string(output);
            }
        }
    }

    internal static class RosterConflictDetector
    {
        internal static bool TryFindConflict(
            RosterTextEntry[] entries,
            IDictionary[] directDictionaries,
            IDictionary localizedDictionaries,
            out string conflict)
        {
            if (entries == null
                || directDictionaries == null
                || localizedDictionaries == null)
            {
                throw new ArgumentNullException();
            }
            foreach (RosterTextEntry entry in entries)
            {
                foreach (IDictionary dictionary in directDictionaries)
                {
                    if (dictionary == null)
                    {
                        throw new InvalidOperationException(
                            "SHCDE-SE translation dictionary is unavailable");
                    }
                    if (dictionary.Contains(entry.InternalKey))
                    {
                        conflict = "direct:" + entry.InternalKey;
                        return true;
                    }
                    if (dictionary.Contains(entry.RawRouteKey))
                    {
                        conflict = "route:" + entry.RawRouteKey;
                        return true;
                    }
                }
                foreach (DictionaryEntry locale in localizedDictionaries)
                {
                    IDictionary translations = locale.Value as IDictionary;
                    if (translations == null)
                    {
                        throw new InvalidOperationException(
                            "SHCDE-SE localized translation dictionary is malformed");
                    }
                    if (translations.Contains(entry.InternalKey)
                        || translations.Contains(entry.RawRouteKey))
                    {
                        conflict = "locale:" + Convert.ToString(locale.Key)
                            + ":" + entry.RawRouteKey;
                        return true;
                    }
                }
            }
            conflict = string.Empty;
            return false;
        }
    }

    internal sealed class RosterOwnedStringSlot
    {
        private readonly Func<string> _read;
        private readonly Action<string> _write;

        internal RosterOwnedStringSlot(
            Func<string> read,
            Action<string> write,
            string original,
            string owned)
        {
            _read = read ?? throw new ArgumentNullException(nameof(read));
            _write = write ?? throw new ArgumentNullException(nameof(write));
            Original = original ?? throw new ArgumentNullException(nameof(original));
            Owned = owned ?? throw new ArgumentNullException(nameof(owned));
        }

        internal string Original { get; }
        internal string Owned { get; }

        internal bool VerifyOwned()
        {
            try
            {
                return string.Equals(_read(), Owned, StringComparison.Ordinal);
            }
            catch
            {
                return false;
            }
        }

        internal bool RestoreIfOwned()
        {
            try
            {
                if (!string.Equals(_read(), Owned, StringComparison.Ordinal))
                {
                    return false;
                }
                _write(Original);
                return string.Equals(_read(), Original, StringComparison.Ordinal);
            }
            catch
            {
                // A superseded Noesis tree may already be disposed. Dropping
                // that generation is safe; it is no longer an active surface.
                return false;
            }
        }
    }

    internal sealed class RosterHudGenerationState
    {
        private List<RosterOwnedStringSlot> _current =
            new List<RosterOwnedStringSlot>();

        internal int Count
        {
            get { return _current.Count; }
        }

        internal int Replace(IList<RosterOwnedStringSlot> next)
        {
            if (next == null)
            {
                throw new ArgumentNullException(nameof(next));
            }
            List<RosterOwnedStringSlot> unique =
                new List<RosterOwnedStringSlot>(next.Count);
            foreach (RosterOwnedStringSlot slot in next)
            {
                if (slot == null || unique.Contains(slot))
                {
                    throw new InvalidOperationException(
                        "HUD ownership generation contains a null/duplicate slot");
                }
                unique.Add(slot);
            }
            int restored = Restore(_current);
            _current = unique;
            return restored;
        }

        internal bool VerifyOwnership(out string reason)
        {
            foreach (RosterOwnedStringSlot slot in _current)
            {
                if (!slot.VerifyOwned())
                {
                    reason = "hud_tag_changed_or_disposed";
                    return false;
                }
            }
            reason = string.Empty;
            return true;
        }

        internal int RollbackOwned()
        {
            int restored = Restore(_current);
            _current = new List<RosterOwnedStringSlot>();
            return restored;
        }

        private static int Restore(IEnumerable<RosterOwnedStringSlot> slots)
        {
            int restored = 0;
            foreach (RosterOwnedStringSlot slot in slots)
            {
                if (slot.RestoreIfOwned())
                {
                    restored++;
                }
            }
            return restored;
        }
    }
}
