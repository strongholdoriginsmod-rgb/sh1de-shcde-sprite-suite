using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>Catalogue operations (column <c>op</c>).</summary>
    internal enum FortificationSpriteOp
    {
        /// <summary>Adjust the engine sprite of the tile: frame swap and/or pixel offset.</summary>
        Body,
        /// <summary>Add one more sprite for the tile through the engine fill-in API.</summary>
        Layer,
        /// <summary>Move the engine sprite out of view (the variant draws its own art).</summary>
        Hide,
    }

    /// <summary>One catalogue rule.</summary>
    internal sealed class FortificationSpriteRule
    {
        internal FortificationSpriteRule(
            FortificationSpriteOp op,
            int targetGm,
            int targetImage,
            int dx,
            int dy,
            int order)
        {
            Op = op;
            TargetGm = targetGm;
            TargetImage = targetImage;
            Dx = dx;
            Dy = dy;
            Order = order;
        }

        internal FortificationSpriteOp Op { get; }

        internal int TargetGm { get; }

        internal int TargetImage { get; }

        /// <summary>Horizontal offset in atlas pixels (32 px = one tile step).</summary>
        internal int Dx { get; }

        /// <summary>Vertical offset in atlas pixels (32 px = one height unit).</summary>
        internal int Dy { get; }

        /// <summary>Sorting offset of a layer against the tile sprite.</summary>
        internal int Order { get; }

        internal bool KeepsEngineFrame => TargetGm == 0 && TargetImage == 0;
    }

    /// <summary>All rules of one (variant, engine gm, engine image, shape) key.</summary>
    internal sealed class FortificationSpriteRecipe
    {
        private readonly List<FortificationSpriteRule> _layers =
            new List<FortificationSpriteRule>();

        internal FortificationSpriteRule Body { get; private set; }

        internal bool Hidden { get; private set; }

        internal IReadOnlyList<FortificationSpriteRule> Layers => _layers;

        /// <summary>Takes body/hide from the first recipe that has one; appends layers.</summary>
        internal void Merge(FortificationSpriteRecipe other)
        {
            if (Body == null && !Hidden)
            {
                Body = other.Body;
                Hidden = other.Hidden;
            }
            foreach (FortificationSpriteRule layer in other._layers)
            {
                if (_layers.Count < FortificationSpriteCatalog.MaximumLayersPerFrame)
                {
                    _layers.Add(layer);
                }
            }
        }

        internal void Add(FortificationSpriteRule rule)
        {
            switch (rule.Op)
            {
                case FortificationSpriteOp.Layer:
                    if (_layers.Count >= FortificationSpriteCatalog.MaximumLayersPerFrame)
                    {
                        throw new InvalidDataException("Too many layers for one frame");
                    }
                    _layers.Add(rule);
                    return;
                case FortificationSpriteOp.Hide:
                    if (Hidden || Body != null)
                    {
                        throw new InvalidDataException("Hide conflicts with another rule of the frame");
                    }
                    Hidden = true;
                    return;
                default:
                    if (Body != null || Hidden)
                    {
                        throw new InvalidDataException("Duplicate body rule for one frame");
                    }
                    Body = rule;
                    return;
            }
        }
    }

    /// <summary>
    /// Private visual recipe catalogue (fortification-sprites v3).
    ///
    /// Recipes never modify pixels. Measured 2026-09-02 (SHCDE 2.80, editor):
    /// a wall is a raised walkway tile (GM 12 image 97–104, height +2.813)
    /// whose faces are tile_walls chevrons; screen-horizontal walls add a
    /// 64×199 anim_castle strip (49–62) on the front gap tile and a cap (47)
    /// on the back gap tile, screen-vertical walls add the rim pieces 46/48.
    /// A recipe assembles existing frames per tile: swap the walkway tile for
    /// a whole SH1 wall piece and lower the tile to the ground, add deck
    /// layers, and hide the engine strips the variant no longer needs. The
    /// <c>shape</c> column selects the piece by the wall direction at the
    /// tile (se, sw, h, v) with <c>any</c> as fallback.
    ///
    /// The builder stages <c>Runtime/fortification-sprites-v1.tsv</c>; its
    /// size and SHA-256 are compiled into the fortification contract. A missing
    /// or mismatching catalogue disables visuals only.
    /// </summary>
    internal sealed class FortificationSpriteCatalog
    {
        internal const string TsvRelativePath = "Runtime/fortification-sprites-v1.tsv";
        internal const string Schema = "stronghold-europe-de.fortification-sprites.v3";
        internal const string Columns =
            "variant_id\top\tshape\tgm\timage\ttarget_gm\ttarget_image\tdx\tdy\torder\tnote";
        internal const string AnyShape = "any";
        internal const int MaximumLayersPerFrame = 4;
        internal const int MaximumOffsetPixels = 512;
        internal const int MaximumOrder = 8;
        internal const int WildcardImage = 0xFFFF;
        /// <summary>
        /// Mauerrichtung (any/se/sw/h/v) und, fuer die Holztreppe,
        /// Achse+Aufstiegsrichtung+Stufe: se = +/-x, sw = +/-y, das
        /// Vorzeichen ist die Aufstiegsrichtung, die Ziffer die Stufe
        /// 0..3 vom Boden zur Wehrgangshoehe. Reihenfolge und Namen
        /// stimmen mit tools/fortification_visual_recipes.py ueberein.
        /// </summary>
        internal static readonly string[] Shapes =
        {
            AnyShape, "se", "sw", "h", "v",
            "se+0", "se+1", "se+2", "se+3",
            "se-0", "se-1", "se-2", "se-3",
            "sw+0", "sw+1", "sw+2", "sw+3",
            "sw-0", "sw-1", "sw-2", "sw-3",
        };


        private readonly string _pluginDirectory;
        private readonly Action<string> _info;
        private readonly Action<string> _warning;
        private readonly Dictionary<string, Dictionary<long, FortificationSpriteRecipe>> _recipes =
            new Dictionary<string, Dictionary<long, FortificationSpriteRecipe>>(StringComparer.Ordinal);

        internal FortificationSpriteCatalog(
            string pluginDirectory,
            Action<string> info = null,
            Action<string> warning = null)
        {
            if (string.IsNullOrEmpty(pluginDirectory))
            {
                throw new ArgumentException(
                    "Plugin directory is required",
                    nameof(pluginDirectory));
            }
            _pluginDirectory = pluginDirectory;
            _info = info;
            _warning = warning;
        }

        internal bool Prepared { get; private set; }

        internal int RuleCount { get; private set; }

        internal string Failure { get; private set; }

        internal static int FrameKey(int gm, int image)
        {
            return (gm << 16) | (image & 0xFFFF);
        }

        private static long ShapeKey(int gm, int image, int shapeIndex)
        {
            return ((long)shapeIndex << 32) | (uint)FrameKey(gm, image);
        }

        internal static int ShapeIndex(string shape)
        {
            for (int index = 0; index < Shapes.Length; index++)
            {
                if (Shapes[index] == shape)
                {
                    return index;
                }
            }
            return -1;
        }

        internal void Prepare()
        {
            Rollback();
            if (GeneratedFortificationContract.SpriteCatalogSize <= 0
                || string.IsNullOrEmpty(GeneratedFortificationContract.SpriteCatalogSha256))
            {
                Failure = "no recipe catalogue shipped";
                return;
            }
            try
            {
                string path = Path.Combine(
                    _pluginDirectory,
                    TsvRelativePath.Replace('/', Path.DirectorySeparatorChar));
                string digest = Hashing.Sha256FileStable(
                    path,
                    GeneratedFortificationContract.SpriteCatalogSize);
                if (!string.Equals(
                    digest,
                    GeneratedFortificationContract.SpriteCatalogSha256,
                    StringComparison.Ordinal))
                {
                    throw new InvalidDataException(
                        "Fortification recipe catalogue SHA-256 mismatch");
                }
                Load(File.ReadAllLines(path));
                Prepared = true;
                Failure = null;
                Log(_info,
                    "SEDE_RUNTIME_V1|event=fortification_visuals|status=ready"
                    + "|rules=" + RuleCount.ToString(CultureInfo.InvariantCulture)
                    + "|variants=" + _recipes.Count.ToString(CultureInfo.InvariantCulture));
            }
            catch (Exception exception)
            {
                Rollback();
                Failure = exception.GetType().Name + ": " + exception.Message;
                Log(_warning,
                    "SEDE_RUNTIME_V1|event=fortification_visuals|status=unavailable"
                    + "|reason=" + AssetStreamText.Sanitize(Failure, 160));
            }
        }

        /// <summary>
        /// Exact image + shape first, then exact image + any, then the
        /// wildcard image with the shape, then wildcard + any.
        /// </summary>
        internal bool TryGetRecipe(
            string variantId,
            int gm,
            int image,
            int shapeIndex,
            out FortificationSpriteRecipe recipe)
        {
            recipe = null;
            Dictionary<long, FortificationSpriteRecipe> byFrame;
            if (!Prepared
                || string.IsNullOrEmpty(variantId)
                || !_recipes.TryGetValue(variantId, out byFrame))
            {
                return false;
            }
            if (shapeIndex < 0 || shapeIndex >= Shapes.Length)
            {
                shapeIndex = 0;
            }
            // Body/hide from the most specific row; layers of every matching
            // row (specific first) so a shape-neutral deck rides on a
            // shape-specific wall piece (2026-09-02: the deck never appeared
            // while the lookup returned only the first match).
            FortificationSpriteRecipe merged = null;
            long[] keys =
            {
                ShapeKey(gm, image, shapeIndex),
                ShapeKey(gm, image, 0),
                ShapeKey(gm, WildcardImage, shapeIndex),
                ShapeKey(gm, WildcardImage, 0),
            };
            for (int index = 0; index < keys.Length; index++)
            {
                if (index > 0 && keys[index] == keys[index - 1])
                {
                    continue;
                }
                FortificationSpriteRecipe candidate;
                if (!byFrame.TryGetValue(keys[index], out candidate))
                {
                    continue;
                }
                if (merged == null)
                {
                    merged = new FortificationSpriteRecipe();
                }
                merged.Merge(candidate);
            }
            recipe = merged;
            return merged != null;
        }

        internal bool HasRecipes(string variantId)
        {
            return Prepared
                && !string.IsNullOrEmpty(variantId)
                && _recipes.ContainsKey(variantId);
        }

        internal void Rollback()
        {
            Prepared = false;
            RuleCount = 0;
            _recipes.Clear();
        }

        private void Load(string[] lines)
        {
            if (lines.Length == 0 || lines[0] != "# " + Schema)
            {
                throw new InvalidDataException("Fortification recipe catalogue schema changed");
            }
            bool headerSeen = false;
            for (int index = 1; index < lines.Length; index++)
            {
                string line = lines[index];
                if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
                {
                    continue;
                }
                if (!headerSeen)
                {
                    if (line != Columns)
                    {
                        throw new InvalidDataException("Fortification recipe catalogue columns changed");
                    }
                    headerSeen = true;
                    continue;
                }
                string[] fields = line.Split('\t');
                if (fields.Length != 11)
                {
                    throw new InvalidDataException("Malformed catalogue row " + index);
                }
                string variantId = fields[0];
                FortificationVariantDefinition variant =
                    FortificationVariantCatalog.GetRequired(variantId);
                if (variant.Role != FortificationVariantRole.AdditionalWall)
                {
                    throw new InvalidDataException("Catalogue row names a non-wall variant " + variantId);
                }
                FortificationSpriteOp op;
                switch (fields[1])
                {
                    case "body":
                        op = FortificationSpriteOp.Body;
                        break;
                    case "layer":
                        op = FortificationSpriteOp.Layer;
                        break;
                    case "hide":
                        op = FortificationSpriteOp.Hide;
                        break;
                    default:
                        throw new InvalidDataException("Unknown catalogue op in row " + index);
                }
                int shapeIndex = ShapeIndex(fields[2]);
                if (shapeIndex < 0)
                {
                    throw new InvalidDataException("Unknown catalogue shape in row " + index);
                }
                int gm = ParseInt(fields[3]);
                int image = ParseInt(fields[4]);
                int targetGm = ParseInt(fields[5]);
                int targetImage = ParseInt(fields[6]);
                int dx = ParseInt(fields[7]);
                int dy = ParseInt(fields[8]);
                int order = ParseInt(fields[9]);
                if (gm < 1 || gm > 255 || image < 0 || image > 0xFFFF
                    || targetGm < 0 || targetGm > 255
                    || targetImage < 0 || targetImage > 0xFFFF
                    || (targetGm == 0) != (targetImage == 0)
                    || Math.Abs(dx) > MaximumOffsetPixels
                    || Math.Abs(dy) > MaximumOffsetPixels
                    || Math.Abs(order) > MaximumOrder)
                {
                    throw new InvalidDataException("Catalogue row out of range " + index);
                }
                if (op != FortificationSpriteOp.Layer && order != 0)
                {
                    throw new InvalidDataException("Only layers carry a sorting order, row " + index);
                }
                if (op == FortificationSpriteOp.Hide && (targetGm != 0 || dx != 0 || dy != 0))
                {
                    throw new InvalidDataException("Hide takes no target or offset, row " + index);
                }
                if (op == FortificationSpriteOp.Body && targetGm == 0 && dx == 0 && dy == 0)
                {
                    throw new InvalidDataException("Body rule changes nothing in row " + index);
                }
                Dictionary<long, FortificationSpriteRecipe> byFrame;
                if (!_recipes.TryGetValue(variantId, out byFrame))
                {
                    byFrame = new Dictionary<long, FortificationSpriteRecipe>();
                    _recipes.Add(variantId, byFrame);
                }
                long key = ShapeKey(gm, image, shapeIndex);
                FortificationSpriteRecipe recipe;
                if (!byFrame.TryGetValue(key, out recipe))
                {
                    recipe = new FortificationSpriteRecipe();
                    byFrame.Add(key, recipe);
                }
                recipe.Add(new FortificationSpriteRule(op, targetGm, targetImage, dx, dy, order));
                RuleCount++;
            }
            if (!headerSeen)
            {
                throw new InvalidDataException("Fortification recipe catalogue has no header");
            }
        }

        private static int ParseInt(string value)
        {
            return int.Parse(value, NumberStyles.Integer, CultureInfo.InvariantCulture);
        }

        private static void Log(Action<string> sink, string message)
        {
            if (sink == null)
            {
                return;
            }
            try
            {
                sink(message);
            }
            catch
            {
            }
        }
    }
}
