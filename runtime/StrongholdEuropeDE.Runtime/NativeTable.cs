using System;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Eine Tabelle im Speicher des Spielmoduls, sicher adressiert.
    /// </summary>
    /// <remarks>
    /// Herausgezogen aus der Hafenbahn, nachdem dort dreimal dasselbe gelernt
    /// werden musste. Wer die naechste native Tabelle anfasst - die
    /// Nahkampftabelle fuer kaempfende Jaeger, die Trefferpunkte, die
    /// Wohnraumtabelle - soll nicht wieder bei null anfangen.
    ///
    /// WAS DIE HAFENBAHN GELEHRT HAT, in der Reihenfolge, in der es wehtat:
    ///
    /// 1. **Es gibt oft ZWEI Tabellen.** Eine Vorgabetabelle als Quelle und
    ///    eine zweite, aus der das Spiel tatsaechlich rechnet. Die zweite wird
    ///    genau einmal je Prozess aus der ersten gefuellt, hinter einem
    ///    "schon erledigt"-Byte. Wer die Vorgabe schreibt, sieht seine Werte
    ///    im Protokoll und im Spiel trotzdem nichts. Frueher zu schreiben
    ///    hilft nicht - die Kopie faellt beim Kartenladen und nie wieder.
    ///    Gemessen am Hafen: Vorgabe Wood=20/Gold=30, abgerechnet 0/0.
    ///
    /// 2. **Die Setzer des Extenders koennen unbrauchbar sein.** Sie treffen
    ///    die richtige Stelle, fuehren aber einen Unity-Spiegel mit, dessen
    ///    Zeiger fuer hohe Indizes hinter das Ende eines verwalteten Feldes
    ///    zeigt. Ihre eigene Schranke greift dort nicht, weil sie Elementzahl
    ///    mit Bytezahl verwechselt. Das ist Heap-Korruption.
    ///
    /// 3. **Ohne Ende-Symbol ist die Laenge nicht raten, sondern messen.**
    ///    Beim Hafen ergab sie sich aus der Fuellschleife: Deren Abbruchmarke
    ///    IST das Ende der Vorgabetabelle, also fassen beide gleich viele
    ///    Eintraege. Eine solche Bruecke ist Pflicht, bevor geschrieben wird.
    ///
    /// 4. **Zwei uebereinstimmende Nullen sind kein Nachweis.** Die
    ///    Selbstpruefung muss an einer Stelle laufen, die ab Werk von null
    ///    verschieden ist, sonst bestaetigt sie eine falsche Adresse.
    ///
    /// 5. **Zuruecknehmen muss man selbst.** Der Extender loescht bei
    ///    OnUnloadMap nur einen Teil seiner Overrides; native Tabellen
    ///    gehoeren nicht dazu.
    ///
    /// Kein <c>unsafe</c>: Marshal genuegt, und das haelt die Baukonfiguration
    /// unveraendert.
    /// </remarks>
    internal sealed class NativeTable
    {
        /// <summary>Das Spielmodul, in dem alle diese Tabellen liegen.</summary>
        internal const string GameModule = "CrusaderDE.dll";

        private readonly string _name;
        private readonly IntPtr _module;
        private readonly long _rva;
        private readonly long _stride;
        private readonly long _entries;

        private NativeTable(
            string name, IntPtr module, long rva, long stride, long entries)
        {
            _name = name;
            _module = module;
            _rva = rva;
            _stride = stride;
            _entries = entries;
        }

        /// <summary>
        /// Eine Tabelle aufschliessen, oder mit Begruendung scheitern.
        /// </summary>
        /// <param name="name">Fuer Protokoll und Fehlermeldung.</param>
        /// <param name="rva">Aus einem oeffentlichen Feld des GameGlobalsManager,
        /// nie fest verdrahtet - die Adressen wandern mit jedem Spielstand.</param>
        /// <param name="stride">Bytes je Eintrag.</param>
        /// <param name="entries">Eintragszahl. MUSS aus einer Messung stammen;
        /// wer sie nicht hat, uebergibt 0 und bekommt eine Tabelle, die nur
        /// liest.</param>
        internal static bool TryOpen(
            string name,
            ulong rva,
            long stride,
            long entries,
            out NativeTable table,
            out string failure)
        {
            table = null;
            if (stride <= 0L)
            {
                failure = name + ": Schrittweite muss positiv sein";
                return false;
            }
            if (rva == 0UL)
            {
                // Ein gescheiterter Muster-Scan des Extenders hinterlaesst 0.
                // Ein Zugriff relativ zu 0 waere das Ende der Sitzung.
                failure = name + ": Adresse wurde nicht aufgeloest";
                return false;
            }
            IntPtr module = ModuleBase();
            if (module == IntPtr.Zero)
            {
                failure = name + ": " + GameModule + " ist nicht geladen";
                return false;
            }
            table = new NativeTable(name, module, (long)rva, stride, entries);
            failure = null;
            return true;
        }

        internal string Name
        {
            get { return _name; }
        }

        /// <summary>Ob <paramref name="index"/> nachweislich in der Tabelle liegt.</summary>
        internal bool Covers(long index)
        {
            return index >= 0L && _entries > 0L && index < _entries;
        }

        /// <summary>
        /// Die eigene Adressrechnung gegen einen fremden Leser halten.
        /// </summary>
        /// <remarks>
        /// Der entscheidende Wachposten. <paramref name="reference"/> ist
        /// ueblicherweise ein Getter des Extenders; stimmen beide ueberein,
        /// sind Modul, Schrittweite und Spaltenversatz zugleich bestaetigt.
        ///
        /// Ein Wert von null wird abgewiesen, nicht angenommen: Zwei
        /// uebereinstimmende Nullen belegen nichts. Die Probe gehoert deshalb
        /// auf einen Eintrag, der ab Werk belegt ist.
        /// </remarks>
        internal bool Verify(
            long index, long columnOffset, int reference, out string failure)
        {
            if (!Covers(index))
            {
                failure = _name + ": Probeindex "
                    + index.ToString(CultureInfo.InvariantCulture)
                    + " liegt ausserhalb der gemessenen Tabelle";
                return false;
            }
            int mine = Read(index, columnOffset);
            if (mine != reference || mine == 0)
            {
                failure = _name + ": Adressprobe gescheitert (eigen "
                    + mine.ToString(CultureInfo.InvariantCulture) + ", fremd "
                    + reference.ToString(CultureInfo.InvariantCulture) + ")";
                return false;
            }
            failure = null;
            return true;
        }

        internal int Read(long index, long columnOffset)
        {
            return Marshal.ReadInt32(Address(index, columnOffset));
        }

        /// <summary>
        /// Schreiben. Nur innerhalb der gemessenen Schranke.
        /// </summary>
        internal bool TryWrite(
            long index, long columnOffset, int value, out string failure)
        {
            if (!Covers(index))
            {
                failure = _name + ": Index "
                    + index.ToString(CultureInfo.InvariantCulture)
                    + " ist nicht nachweislich in der Tabelle; nicht geschrieben";
                return false;
            }
            if (columnOffset < 0L || columnOffset + 4L > _stride)
            {
                failure = _name + ": Spaltenversatz "
                    + columnOffset.ToString(CultureInfo.InvariantCulture)
                    + " liegt ausserhalb eines Eintrags";
                return false;
            }
            Marshal.WriteInt32(Address(index, columnOffset), value);
            failure = null;
            return true;
        }

        private IntPtr Address(long index, long columnOffset)
        {
            return new IntPtr(
                _module.ToInt64() + _rva + index * _stride + columnOffset);
        }

        private static IntPtr ModuleBase()
        {
            using (Process self = Process.GetCurrentProcess())
            {
                foreach (ProcessModule module in self.Modules)
                {
                    if (string.Equals(
                            module.ModuleName,
                            GameModule,
                            StringComparison.OrdinalIgnoreCase))
                    {
                        return module.BaseAddress;
                    }
                }
            }
            return IntPtr.Zero;
        }
    }
}
