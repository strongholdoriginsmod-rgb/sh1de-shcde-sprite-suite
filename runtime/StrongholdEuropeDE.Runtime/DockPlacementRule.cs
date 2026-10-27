using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Welche Mapper zum Hafen gehoeren, und was fuer ihn als Wasser gilt.
    /// </summary>
    /// <remarks>
    /// Bewusst ohne Unity und ohne Spiel-Singleton, nach dem Vorbild von
    /// <see cref="FarmPlacementRule"/>, damit die Entscheidung fuer sich
    /// pruefbar bleibt.
    ///
    /// Es sind vier Mapper, und es sind keine vier Bauwerke, sondern die vier
    /// Ausrichtungen desselben Hafens: getStructFromMapper gibt fuer 195, 196,
    /// 197 und 198 denselben Wert 109 zurueck (Assembly-CSharp, GameData.cs
    /// 1813-1817), und der Editor blendet fuer genau diese vier den Drehhinweis
    /// ein (EditorDirector.cs 1035-1040). Wer nur 195 behandelte, haette die
    /// Regel an drei von vier Ufern nicht.
    ///
    /// <see cref="DockPlacementController"/> verwendet diese Regel inzwischen
    /// auch fuer die Entscheidung: Ist der generierte Vertrag aktiviert, setzt
    /// er auf Nicht-Wasser CustomValidationRules und ForceBlockPlacementState.
    /// Wasserkacheln werden bewusst nicht von uns freigegeben; dort bleibt das
    /// native Gesamturteil bestehen. Die protokollierten Kacheln und Flags
    /// dienen weiterhin der Laufzeitabnahme von Grundflaeche und Uferverhalten.
    /// </remarks>
    internal static class DockPlacementRule
    {
        /// <summary>Die vier Ausrichtungen des Hafens, eMappers 195-198.</summary>
        internal static bool IsDock(eMappers mapper)
        {
            return mapper == eMappers.MAPPER_DOCK
                || mapper == eMappers.MAPPER_DOCK2
                || mapper == eMappers.MAPPER_DOCK3
                || mapper == eMappers.MAPPER_DOCK4;
        }

        /// <summary>Die Struktur hinter allen vier Mappern (eStructs 109).</summary>
        internal const eStructs DockStruct = eStructs.STRUCT_DOCK;

        /// <summary>
        /// Was fuer den Hafen als Wasser zaehlt.
        /// </summary>
        /// <remarks>
        /// <see cref="DockPlacementController"/> zaehlt und protokolliert diese
        /// Flags weiterhin, sperrt bei aktiviertem Vertrag aber zugleich jede
        /// vorgelegte Nicht-Wasser-Kachel. Die Regel arbeitet nur in Richtung
        /// SPERREN und ueberschreibt keine native Sperre auf Wasserkacheln.
        ///
        /// Ford fehlt mit Absicht: eine Furt ist die einzige Stelle, an der eine
        /// Karte ein Gewaesser zu Fuss queren laesst, und ein Hafen darauf
        /// zerstoert diese Querung. Das ist ein Ermessensurteil derselben Art
        /// wie der Sandausschluss der Farmregel und wird hier als solches
        /// benannt, nicht als Messung ausgegeben.
        ///
        /// GetTileType taugt fuer die Wasserfrage nicht: BeachOrWaves ist laut
        /// Enumkommentar ein und dasselbe Bit fuer Strandsand und Wellen
        /// (TileType.cs). Deshalb die Eigenschaftsflags und nicht die Textur.
        /// </remarks>
        internal const TilePropertyFlag Water =
            TilePropertyFlag.Sea | TilePropertyFlag.River;

        /// <summary>Traegt die Kachel nachweislich Wasser?</summary>
        internal static bool IsWater(TilePropertyFlag flags)
        {
            return (flags & Water) != TilePropertyFlag.None;
        }
    }
}
