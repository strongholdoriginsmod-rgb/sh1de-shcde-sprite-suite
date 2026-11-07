// Lightweight self-contained JSON data reader for the game's Mono runtime.
// No Unity JsonUtility depth limits, external Framework ZIP/JSON DLLs or
// restrictions on creative SpriteSuite stage content.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace SpriteSuite.BuildingDamage
{
    internal static class DamageJsonParser
    {
        internal static DamageRuntimeSettings Settings(string json)
        {
            var value = new Reader(json).ReadRoot();
            var root = Object(value);
            var cfg = new DamageRuntimeSettings();
            cfg.damageArchive = String(root, "damageArchive", cfg.damageArchive);
            cfg.damageDirectory = String(root, "damageDirectory", cfg.damageDirectory);
            cfg.enabled = Boolean(root, "enabled", cfg.enabled);
            cfg.firePersistsUntilRepaired = Boolean(root, "firePersistsUntilRepaired", cfg.firePersistsUntilRepaired);
            cfg.pollFrames = Integer(root, "pollFrames", cfg.pollFrames);
            cfg.previewEnabled = Boolean(root, "previewEnabled", false);
            cfg.previewHpPercent = Integer(root, "previewHpPercent", 50);
            cfg.previewFire = Boolean(root, "previewFire", false);
            var all = new List<SpriteBinding>();
            foreach (object item in Array(root, "bindings"))
            {
                var o = Object(item);
                all.Add(new SpriteBinding {
                    buildingType = Integer(o, "buildingType"),
                    buildingGlobalId = Integer(o, "buildingGlobalId"),
                    buildingGroupId = String(o, "buildingGroupId"),
                    sourceSprite = String(o, "sourceSprite"),
                    matchGmImage = Boolean(o, "matchGmImage"),
                    gm = Integer(o, "gm"), image = Integer(o, "image"),
                    slot = Integer(o, "slot"),
                    ownerOffsetX = Integer(o, "ownerOffsetX"),
                    ownerOffsetY = Integer(o, "ownerOffsetY"),
                    overridePivot = Boolean(o, "overridePivot"),
                    pivotX = Number(o, "pivotX", .5f),
                    pivotY = Number(o, "pivotY"),
                    overridePpu = Boolean(o, "overridePpu"),
                    pixelsPerUnit = Number(o, "pixelsPerUnit", 100f)
                });
            }
            cfg.bindings = all.ToArray();
            return cfg;
        }

        internal static DamageArchive Library(string json)
        {
            var root = Object(new Reader(json).ReadRoot());
            var library = new DamageArchive {
                format = String(root, "format"),
                version = Integer(root, "version")
            };
            var profiles = new List<DamageBuilding>();
            foreach (object rawBuilding in Array(root, "buildings"))
            {
                var b = Object(rawBuilding);
                var profile = new DamageBuilding {
                    id = String(b, "id"), name = String(b, "name"),
                    gameBuildingType = Integer(b, "gameBuildingType")
                };
                var stages = new List<DamageStage>();
                foreach (object rawStage in Array(b, "stages"))
                {
                    var s = Object(rawStage);
                    var stage = new DamageStage {
                        id = String(s, "id"), damageKind = String(s, "damageKind"),
                        hpAtOrBelow = Integer(s, "hpAtOrBelow")
                    };
                    var tiles = new List<DamageTile>();
                    foreach (object rawTile in Array(s, "tiles"))
                    {
                        var t = Object(rawTile);
                        tiles.Add(new DamageTile {
                            slot = Integer(t, "slot"), image = String(t, "image"),
                            sha256 = String(t, "sha256"), mask = String(t, "mask")
                        });
                    }
                    stage.tiles = tiles.ToArray();
                    stages.Add(stage);
                }
                profile.stages = stages.ToArray();
                profiles.Add(profile);
            }
            library.buildings = profiles.ToArray();
            return library;
        }

        private static Dictionary<string, object> Object(object value)
        {
            var result = value as Dictionary<string, object>;
            if (result == null) throw new FormatException("Expected a JSON object");
            return result;
        }

        private static IEnumerable<object> Array(Dictionary<string, object> obj, string key)
        {
            object value;
            if (!obj.TryGetValue(key, out value) || value == null) return new object[0];
            var array = value as List<object>;
            if (array == null) throw new FormatException("Expected JSON array: " + key);
            return array;
        }

        private static string String(Dictionary<string, object> obj, string key, string fallback = "")
        {
            object value;
            if (!obj.TryGetValue(key, out value) || value == null) return fallback;
            var s = value as string;
            if (s == null) throw new FormatException("Expected JSON string: " + key);
            return s;
        }

        private static bool Boolean(Dictionary<string, object> obj, string key, bool fallback = false)
        {
            object value;
            if (!obj.TryGetValue(key, out value) || value == null) return fallback;
            if (!(value is bool)) throw new FormatException("Expected JSON bool: " + key);
            return (bool)value;
        }

        private static int Integer(Dictionary<string, object> obj, string key, int fallback = 0)
        {
            object value;
            if (!obj.TryGetValue(key, out value) || value == null) return fallback;
            if (!(value is double)) throw new FormatException("Expected JSON integer: " + key);
            double n = (double)value;
            if (n < int.MinValue || n > int.MaxValue || Math.Truncate(n) != n)
                throw new FormatException("Invalid integer: " + key);
            return checked((int)n);
        }

        private static float Number(Dictionary<string, object> obj, string key, float fallback = 0)
        {
            object value;
            if (!obj.TryGetValue(key, out value) || value == null) return fallback;
            if (!(value is double)) throw new FormatException("Expected JSON number: " + key);
            double n = (double)value;
            if (Double.IsInfinity(n) || Double.IsNaN(n) || n > float.MaxValue || n < -float.MaxValue)
                throw new FormatException("Invalid number: " + key);
            return (float)n;
        }

        // JSON lexical reader: arrays, objects, strings with escapes, numbers,
        // booleans, null. Unknown metadata is parsed and otherwise left alone.
        private sealed class Reader
        {
            private readonly string text;
            private int pos;

            internal Reader(string source)
            {
                if (source == null) throw new ArgumentNullException("source");
                text = source;
            }

            internal object ReadRoot()
            {
                object result = Value();
                Space();
                if (pos != text.Length) throw Error("Trailing JSON data");
                return result;
            }

            private object Value()
            {
                Space();
                if (pos >= text.Length) throw Error("Missing value");
                switch (text[pos])
                {
                    case '{': return ObjectValue();
                    case '[': return ArrayValue();
                    case '"': return StringValue();
                    case 't': Literal("true"); return true;
                    case 'f': Literal("false"); return false;
                    case 'n': Literal("null"); return null;
                    default: return NumberValue();
                }
            }

            private Dictionary<string, object> ObjectValue()
            {
                Expect('{');
                var items = new Dictionary<string, object>(StringComparer.Ordinal);
                Space();
                if (Take('}')) return items;
                while (true)
                {
                    Space();
                    string key = StringValue();
                    Space(); Expect(':');
                    object value = Value();
                    if (items.ContainsKey(key)) throw Error("Duplicate JSON key");
                    items.Add(key, value);
                    Space();
                    if (Take('}')) return items;
                    Expect(',');
                }
            }

            private List<object> ArrayValue()
            {
                Expect('[');
                var items = new List<object>();
                Space();
                if (Take(']')) return items;
                while (true)
                {
                    items.Add(Value());
                    Space();
                    if (Take(']')) return items;
                    Expect(',');
                }
            }

            private string StringValue()
            {
                Expect('"');
                var output = new StringBuilder();
                while (pos < text.Length)
                {
                    char c = text[pos++];
                    if (c == '"') return output.ToString();
                    if (c < 32) throw Error("Unescaped control character");
                    if (c != '\\') { output.Append(c); continue; }
                    if (pos >= text.Length) throw Error("Incomplete JSON escape");
                    char escaped = text[pos++];
                    switch (escaped)
                    {
                        case '"': output.Append('"'); break;
                        case '\\': output.Append('\\'); break;
                        case '/': output.Append('/'); break;
                        case 'b': output.Append('\b'); break;
                        case 'f': output.Append('\f'); break;
                        case 'n': output.Append('\n'); break;
                        case 'r': output.Append('\r'); break;
                        case 't': output.Append('\t'); break;
                        case 'u':
                            if (pos + 4 > text.Length) throw Error("Incomplete unicode escape");
                            int unicode;
                            if (!int.TryParse(text.Substring(pos, 4),
                                NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out unicode))
                                throw Error("Invalid unicode escape");
                            output.Append((char)unicode);
                            pos += 4;
                            break;
                        default: throw Error("Unknown string escape");
                    }
                }
                throw Error("Unterminated JSON string");
            }

            private double NumberValue()
            {
                int start = pos;
                Take('-');
                if (Take('0')) { }
                else
                {
                    if (pos >= text.Length || text[pos] < '1' || text[pos] > '9')
                        throw Error("Invalid JSON number");
                    while (pos < text.Length && text[pos] >= '0' && text[pos] <= '9') pos++;
                }
                if (Take('.'))
                {
                    int digits = pos;
                    while (pos < text.Length && text[pos] >= '0' && text[pos] <= '9') pos++;
                    if (pos == digits) throw Error("Invalid number fractional part");
                }
                if (Take('e') || Take('E'))
                {
                    if (!Take('+')) Take('-');
                    int digits = pos;
                    while (pos < text.Length && text[pos] >= '0' && text[pos] <= '9') pos++;
                    if (pos == digits) throw Error("Invalid exponent");
                }
                double result;
                if (!double.TryParse(text.Substring(start, pos - start), NumberStyles.Float,
                    CultureInfo.InvariantCulture, out result) ||
                    double.IsInfinity(result) || double.IsNaN(result))
                    throw Error("Invalid floating point value");
                return result;
            }

            private void Literal(string expected)
            {
                for (int i = 0; i < expected.Length; i++)
                    if (pos >= text.Length || text[pos++] != expected[i])
                        throw Error("Invalid JSON literal");
            }

            private void Space()
            {
                while (pos < text.Length &&
                    (text[pos] == ' ' || text[pos] == '\n' ||
                     text[pos] == '\r' || text[pos] == '\t')) pos++;
            }

            private bool Take(char c)
            {
                if (pos < text.Length && text[pos] == c) { pos++; return true; }
                return false;
            }

            private void Expect(char c)
            {
                if (!Take(c)) throw Error("Expected " + c);
            }

            private FormatException Error(string message)
            {
                return new FormatException(message + " near character " + pos);
            }
        }
    }
}
