using System;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Reine Stufenwahl der Holztreppe (2026-09-04). Aus der Mauerachse, der
    /// Laenge des Treppenzuges zu beiden Seiten und der Frage, welches Ende an
    /// ein angehobenes Mauerfeld stoesst, folgt der Formindex im
    /// Sprite-Katalog. Bewusst ohne Spieltypen, damit die Regel offline
    /// geprueft werden kann - im Spiel ist sie nur einmal beobachtbar.
    /// </summary>
    internal static class FortificationStairShape
    {
        /// <summary>Keine Mauerrichtung an der Kachel.</summary>
        internal const int AxisNone = 0;

        /// <summary>Mauer laeuft in +/-x (Nachbarn se).</summary>
        internal const int AxisSe = 1;

        /// <summary>Mauer laeuft in +/-y (Nachbarn sw).</summary>
        internal const int AxisSw = 2;

        /// <summary>Erster Treppen-Formindex in FortificationSpriteCatalog.Shapes.</summary>
        internal const int ShapeBase = 5;

        /// <summary>Stufen je Treppensatz: Boden, zwei Zwischenstufen, Wehrgang.</summary>
        internal const int Steps = 4;

        /// <summary>
        /// Formindex fuer eine Treppenkachel. <paramref name="before"/> und
        /// <paramref name="after"/> zaehlen die anschliessenden Treppenfelder
        /// in negativer bzw. positiver Achsenrichtung. Liegt an beiden oder an
        /// keinem Ende eine angehobene Mauer, steigt die Treppe in positiver
        /// Richtung. Ein Zug von mehr als vier Feldern behaelt fuer die
        /// ueberzaehligen Felder die schlichte Mauerform, damit der Katalog
        /// dort auf das Palisadenfeld zurueckfaellt.
        /// </summary>
        internal static int Resolve(
            int axis,
            int before,
            int after,
            bool wallBefore,
            bool wallAfter)
        {
            if (before < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(before));
            }
            if (after < 0)
            {
                throw new ArgumentOutOfRangeException(nameof(after));
            }
            if (axis != AxisSe && axis != AxisSw)
            {
                return axis;
            }
            bool ascendPositive = wallAfter || !wallBefore;
            int step = ascendPositive ? before : after;
            if (step >= Steps)
            {
                return axis;
            }
            int block = (axis == AxisSe ? 0 : 2) + (ascendPositive ? 0 : 1);
            return ShapeBase + (block * Steps) + step;
        }
    }
}
