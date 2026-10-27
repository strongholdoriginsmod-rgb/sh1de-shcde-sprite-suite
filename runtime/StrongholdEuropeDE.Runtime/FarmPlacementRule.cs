using SHCDESE.Interop;
using SHCDESE.Interop.Enums;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Decides whether a food farm may stand on a tile, Stronghold 1 style.
    /// </summary>
    /// <remarks>
    /// Crusader binds the four food farms to the fertile oasis ground. Stronghold 1
    /// puts them on ordinary grass, and that is the behaviour this conversion wants.
    ///
    /// Overriding the engine's verdict means we inherit its whole job, not just the
    /// part we disagree with: everything the native validator rejected for good
    /// reasons - sea, river, swamp, rock, walls, existing buildings - has to be
    /// rejected here too, or the player can put a wheat farm in the water.
    ///
    /// Kept free of Unity and of the game singletons on purpose, so the predicate
    /// can be exercised directly.
    /// </remarks>
    internal static class FarmPlacementRule
    {
        /// <summary>Wheat, hops, apple and cattle farm (eMappers 70-73).</summary>
        internal static bool IsFoodFarm(eMappers mapper)
        {
            return mapper == eMappers.MAPPER_WHEATFARM
                || mapper == eMappers.MAPPER_HOPSFARM
                || mapper == eMappers.MAPPER_APPLEFARM
                || mapper == eMappers.MAPPER_CATTLEFARM;
        }

        /// <summary>
        /// Ground a farm may never occupy, whatever the terrain texture says.
        /// </summary>
        /// <remarks>
        /// Deliberately includes HasStone and HasIron: those tiles are buildable in
        /// the base game, but a farm placed over a deposit destroys a resource the
        /// player cannot get back, and no Stronghold 1 rule asks for that.
        /// </remarks>
        internal const TilePropertyFlag Disqualifying =
            TilePropertyFlag.Sea
            | TilePropertyFlag.River
            | TilePropertyFlag.Ford
            | TilePropertyFlag.IsSwamp
            | TilePropertyFlag.IsMoat
            | TilePropertyFlag.PlannedMoat
            | TilePropertyFlag.IsPitch
            | TilePropertyFlag.PitchTrap
            | TilePropertyFlag.ImpassableEdge
            | TilePropertyFlag.IsWall
            | TilePropertyFlag.IsLowWall
            // SE 2.x name for bit 9 (SE 1.44 called it CrenelationComponent)
            | TilePropertyFlag.CrenelatedLow
            | TilePropertyFlag.IsStairs
            | TilePropertyFlag.IsBuilding
            | TilePropertyFlag.IsElevated
            | TilePropertyFlag.IsTree
            | TilePropertyFlag.TreeProximity
            | TilePropertyFlag.IsFarm
            | TilePropertyFlag.IsFarmFence
            | TilePropertyFlag.IsWheat
            | TilePropertyFlag.IsHops
            | TilePropertyFlag.IsAppleFarm
            | TilePropertyFlag.GoodsyardRelated
            | TilePropertyFlag.MapBorder
            | TilePropertyFlag.RealityEdge
            | TilePropertyFlag.HasStone
            | TilePropertyFlag.HasIron;

        /// <summary>
        /// Terrain textures a farm may not grow on: the beach and the coarse
        /// desert sand. "Any suitable terrain" is not "any terrain", and a wheat
        /// field on a dune would look worse than the restriction it replaced.
        /// </summary>
        /// <remarks>
        /// This is stated as an exclusion, and that is the whole point. The rule
        /// was originally written the other way round, as an allow-list of
        /// <c>Foliage | ThickFoliage | OasisGrass</c> tested with
        /// <c>(type &amp; Arable) != 0</c>. Reading the enum out of the extender
        /// assembly shows why that could never work:
        ///
        ///     NoneOrDirt      0   0x00   <- ordinary buildable ground
        ///     Foliage         1   0x01
        ///     DirtAndStones   2   0x02
        ///     OasisGrass     16   0x10
        ///     ThickFoliage  128   0x80
        ///
        /// Ordinary ground is zero. Zero ANDed with any mask is zero, so every
        /// plain tile failed the test - and the oasis passed, because it is the
        /// one fertile texture with a bit actually set. That is precisely the
        /// reported symptom: farms buildable only on former oases.
        ///
        /// An allow-list cannot express "the default value" in a flags enum.
        /// Naming what is unsuitable can, and it also fails safe: a texture
        /// added by a future patch is allowed rather than silently rejected,
        /// and the property flags above still reject sea, rock, swamp and walls.
        /// </remarks>
        /// <remarks>
        /// `CoarseSand` stand hier bis zum 16.08.2026 mit drin und war der
        /// Hauptgrund, warum Farmen wieder nur auf der Oase gingen: In Crusader
        /// ist grober Sand der GEWOEHNLICHE Boden, nicht Strand. Wer ihn
        /// ausschliesst, schliesst die halbe Karte aus und laesst genau das
        /// stehen, was die Bahn beseitigen soll - Crusaders Bindung der Farmen
        /// an fruchtbaren Boden.
        ///
        /// `BeachOrWaves` bleibt: Ein Acker in der Brandung sieht falsch aus,
        /// und die Kachel grenzt ans Wasser.
        /// </remarks>
        internal const TileType Unsuitable = TileType.BeachOrWaves;

        /// <summary>
        /// Die Flagbits, deren Bedeutung geprueft ist.
        /// </summary>
        /// <remarks>
        /// Alles ausserhalb fuehrt zum Schweigen. Gemessen sind bisher IsLand
        /// allein (Oasengras, Protokoll vom 16.08.2026) sowie die Bits der
        /// Ausschlussliste; wer weitere aufnimmt, soll den Messwert dazu
        /// nennen koennen.
        /// </remarks>
        internal const TilePropertyFlag Known =
            TilePropertyFlag.IsLand | Disqualifying;

        /// <summary>Was die Regel ueber eine Kachel zu sagen hat.</summary>
        internal enum Verdict
        {
            /// <summary>Kein Urteil - das native Urteil bleibt stehen.</summary>
            Silent = 0,

            /// <summary>Gewoehnlicher Boden: Crusaders Fruchtbarkeitsregel lockern.</summary>
            Loosen = 1,

            /// <summary>Wasser, Fels, Mauer: sperren, was das Spiel durchliesse.</summary>
            Block = 2,
        }

        /// <summary>
        /// Drei Ausgaenge, nicht zwei.
        /// </summary>
        /// <remarks>
        /// Am 16.08.2026 im Spiel gemeldet: Farmen wieder nur auf der Oase. Das
        /// war eine Regression, und sie hatte zwei Ursachen, die sich addierten.
        ///
        /// ERSTENS stand `CoarseSand` in `Unsuitable`. In Crusader ist grober
        /// Sand aber der GEWOEHNLICHE Boden, nicht Strand - die Regel weigerte
        /// sich also ausgerechnet dort zu lockern, wo gelockert werden soll.
        /// Uebrig blieb Oasengras, und genau das war die Meldung. Gemessen im
        /// Protokoll vom 16.08.: die eine angenommene Kachel trug type=0x10,
        /// also OasisGrass.
        ///
        /// ZWEITENS gab es nur zwei Ausgaenge. Seit der Sperrkorrektur vom
        /// 15.08. heisst `false` im Controller "sperren", nicht "schweigen" -
        /// jede Kachel, ueber die die Regel nichts weiss, wurde damit aktiv
        /// verboten. Das ist die gefaehrliche Richtung: Schweigen laesst das
        /// native Urteil stehen und kann nichts kaputtmachen, Sperren schon.
        ///
        /// Deshalb jetzt: sperren nur bei nachgewiesenem Hindernis, lockern nur
        /// bei nachgewiesenem gewoehnlichem Boden, und in JEDEM anderen Fall
        /// schweigen. Ein unbekanntes Flagbit - etwa das nirgends benannte
        /// Lake, das TilePropertyFlag im Gegensatz zum Spiel selbst nicht
        /// fuehrt - faellt damit ins Schweigen statt in die Erlaubnis, ohne
        /// gewoehnlichen Boden mitzunehmen.
        /// </remarks>
        internal static Verdict Judge(TilePropertyFlag flags, TileType type)
        {
            // Nachgewiesenes Hindernis: sperren. Das ist der Zweck der Bahn -
            // Crusader liesse Farmen sonst auf Wasser zu.
            if ((flags & Disqualifying) != TilePropertyFlag.None)
            {
                return Verdict.Block;
            }
            // Ohne IsLand ist es kein Baugrund, aber auch kein nachgewiesenes
            // Hindernis. Schweigen.
            if ((flags & TilePropertyFlag.IsLand) == TilePropertyFlag.None)
            {
                return Verdict.Silent;
            }
            // Jedes Bit, das wir nicht kennen, ist ein Grund zu schweigen und
            // keiner zu sperren.
            if ((flags & ~Known) != TilePropertyFlag.None)
            {
                return Verdict.Silent;
            }
            if ((type & Unsuitable) != 0)
            {
                return Verdict.Silent;
            }
            return Verdict.Loosen;
        }

        internal static bool TileAccepts(TilePropertyFlag flags, TileType type)
        {
            // Positivnachweis statt Ausschluss: Die Kachel muss GENAU IsLand
            // tragen, kein weiteres Bit.
            //
            // Der Nutzer meldete am 15.08.2026 Farmen auf Wasser, und die
            // naheliegende Erklaerung - "Wasser fehlt in der Texturmaske" - ist
            // widerlegt: TileType kennt ueberhaupt keinen Wasserwert, und alle
            // fuenf Wasserbits (Sea, River, Ford, IsSwamp, IsMoat) stehen
            // laengst in Disqualifying.
            //
            // Was dagegen fehlt: Das Spiel unterscheidet intern See, Fluss und
            // LAKE (Assembly-CSharp Enums.cs:78-91, eTerrainModes.paintLake),
            // aber TilePropertyFlag fuehrt kein Lake-Bit. Traegt eine
            // Seekachel also nur ein unbenanntes Bit, kam sie durch die
            // Ausschlussliste hindurch. Mit der Gleichheitspruefung faellt jedes
            // unbekannte Bit ins Schweigen statt in die Erlaubnis - und
            // Schweigen ist hier immer sicher, weil dann das native Urteil gilt.
            //
            // Dass das keine echten Kacheln aussperrt, ist gemessen: Im
            // Hafenprotokoll vom 15.08. trug reines Gras exakt 0x8000, und die
            // beobachteten Zusatzbits (0x1000 IsTree, 0x2000 TreeProximity,
            // 0x80 ImpassableEdge) stehen ohnehin alle in Disqualifying.
            if (flags != TilePropertyFlag.IsLand)
            {
                return false;
            }
            // Bleibt stehen, obwohl die Gleichheit oben schon strenger ist: Die
            // Liste erklaert je Bit das Warum und wird von den Vertragstests
            // gehalten. Sie ist die Begruendung, die Gleichheit ist der Waechter.
            if ((flags & Disqualifying) != TilePropertyFlag.None)
            {
                return false;
            }
            return (type & Unsuitable) == 0;
        }
    }
}
