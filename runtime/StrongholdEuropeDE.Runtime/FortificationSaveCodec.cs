using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace StrongholdEuropeDE.Runtime
{
    /// <summary>
    /// Canonical V1 sidecar format. The checksum is verified before any count
    /// or record is trusted, and output order is independent of insertion order.
    /// </summary>
    internal static class FortificationSaveCodec
    {
        private static readonly byte[] Magic =
            Encoding.ASCII.GetBytes("SEDE-FORT-V1\0");
        private static readonly byte[] ChecksumMagic =
            Encoding.ASCII.GetBytes("SHA2");
        private const int ChecksumLength = 32;
        private const int CreditRecordBytes = 3;
        private const int EconomyCreditRecordCount =
            FortificationStateStore.MaximumPlayerId * 2;
        private const int TileRecordBytes = 10;
        private const int GateFixedRecordBytes = 15;

        internal const int SchemaVersion = 1;
        internal const int MaximumPayloadBytes = 16 * 1024 * 1024;

        internal static byte[] Serialize(FortificationStateStore state)
        {
            if (state == null)
            {
                throw new ArgumentNullException(nameof(state));
            }
            state.ValidateInvariants();
            IReadOnlyList<FortificationTileState> tiles =
                state.SnapshotTiles();
            IReadOnlyList<FortificationGateState> gates =
                state.SnapshotGates();
            IReadOnlyList<FortificationEconomyCreditRecord> credits =
                state.SnapshotEconomyCredits();

            using (var stream = new MemoryStream())
            using (var writer = new BinaryWriter(stream, Encoding.UTF8, true))
            {
                writer.Write(Magic);
                writer.Write(SchemaVersion);
                writer.Write(FortificationStateStore.MapWidth);
                writer.Write(FortificationStateStore.MapHeight);
                if (credits.Count != EconomyCreditRecordCount)
                {
                    throw new InvalidDataException(
                        "Fortification economy credit key set is incomplete.");
                }
                writer.Write(credits.Count);
                foreach (FortificationEconomyCreditRecord credit in credits)
                {
                    writer.Write(checked((byte)credit.PlayerId));
                    writer.Write(checked((byte)credit.Resource));
                    writer.Write(checked((byte)credit.CreditQuarters));
                }
                writer.Write(tiles.Count);
                foreach (FortificationTileState tile in tiles)
                {
                    FortificationVariantDefinition variant =
                        FortificationVariantCatalog.GetRequired(tile.VariantId);
                    if (variant.Role
                        != FortificationVariantRole.AdditionalWall)
                    {
                        throw new InvalidDataException(
                            "Only additional walls may be serialized as tiles.");
                    }
                    writer.Write(tile.TileId);
                    writer.Write(variant.SaveCode);
                    writer.Write(checked((byte)tile.OwnerPlayerId));
                    writer.Write(tile.DamageRemainder);
                }

                writer.Write(gates.Count);
                foreach (FortificationGateState gate in gates)
                {
                    FortificationVariantDefinition variant =
                        FortificationVariantCatalog.GetRequired(gate.VariantId);
                    if (variant.Role != FortificationVariantRole.Gatehouse)
                    {
                        throw new InvalidDataException(
                            "Only gatehouse variants may be serialized as gates.");
                    }
                    writer.Write(gate.AnchorTileId);
                    writer.Write(variant.SaveCode);
                    writer.Write(checked((byte)gate.OwnerPlayerId));
                    writer.Write(checked((byte)gate.RouteIndex));
                    writer.Write(gate.DamageRemainder);
                    writer.Write(gate.OccupiedTileIds.Count);
                    foreach (int tileId in gate.OccupiedTileIds)
                    {
                        writer.Write(tileId);
                    }
                }
                writer.Flush();

                if (stream.Length > MaximumPayloadBytes
                    - ChecksumMagic.Length
                    - ChecksumLength)
                {
                    throw new InvalidDataException(
                        "Fortification save payload is oversized.");
                }

                byte[] canonical = stream.ToArray();
                byte[] checksum;
                using (SHA256 sha = SHA256.Create())
                {
                    checksum = sha.ComputeHash(canonical);
                }
                writer.Write(ChecksumMagic);
                writer.Write(checksum);
                writer.Flush();
                if (stream.Length > MaximumPayloadBytes)
                {
                    throw new InvalidDataException(
                        "Fortification save payload is oversized.");
                }
                return stream.ToArray();
            }
        }

        internal static FortificationStateStore Deserialize(byte[] payload)
        {
            int minimumLength = Magic.Length
                + (6 * sizeof(int))
                + (EconomyCreditRecordCount * CreditRecordBytes)
                + ChecksumMagic.Length
                + ChecksumLength;
            if (payload == null
                || payload.Length < minimumLength
                || payload.Length > MaximumPayloadBytes)
            {
                throw new InvalidDataException(
                    "Fortification save payload size is invalid.");
            }

            int trailerLength = ChecksumMagic.Length + ChecksumLength;
            int canonicalLength = payload.Length - trailerLength;
            VerifyChecksum(payload, canonicalLength);

            try
            {
                using (var stream = new MemoryStream(
                    payload,
                    0,
                    canonicalLength,
                    writable: false,
                    publiclyVisible: true))
                using (var reader = new BinaryReader(
                    stream,
                    Encoding.UTF8,
                    leaveOpen: true))
                {
                    byte[] magic = reader.ReadBytes(Magic.Length);
                    if (!magic.SequenceEqual(Magic))
                    {
                        throw new InvalidDataException(
                            "Fortification save magic mismatch.");
                    }
                    if (reader.ReadInt32() != SchemaVersion
                        || reader.ReadInt32()
                            != FortificationStateStore.MapWidth
                        || reader.ReadInt32()
                            != FortificationStateStore.MapHeight)
                    {
                        throw new InvalidDataException(
                            "Fortification save schema or map bounds mismatch.");
                    }

                    int creditCount = ReadCount(
                        reader,
                        EconomyCreditRecordCount,
                        "economy credits");
                    if (creditCount != EconomyCreditRecordCount)
                    {
                        throw new InvalidDataException(
                            "Fortification economy credit key set is incomplete.");
                    }
                    EnsureRemaining(
                        stream,
                        ((long)creditCount * CreditRecordBytes) + sizeof(int),
                        "economy credit records");
                    var state = new FortificationStateStore();
                    ReadEconomyCredits(reader, creditCount, state);
                    int tileCount = ReadCount(
                        reader,
                        FortificationStateStore.MaximumTileCount,
                        "wall tiles");
                    EnsureRemaining(
                        stream,
                        ((long)tileCount * TileRecordBytes) + sizeof(int),
                        "wall tile records");
                    for (int index = 0; index < tileCount; index++)
                    {
                        int tileId = reader.ReadInt32();
                        byte saveCode = reader.ReadByte();
                        int owner = reader.ReadByte();
                        int remainder = reader.ReadInt32();
                        FortificationVariantDefinition variant =
                            GetPersistedVariant(saveCode);
                        if (variant.Role
                            != FortificationVariantRole.AdditionalWall)
                        {
                            throw new InvalidDataException(
                                "A wall tile uses a non-wall save code.");
                        }
                        state.AddTile(new FortificationTileState(
                            tileId,
                            variant.Id,
                            owner,
                            remainder));
                    }

                    int gateCount = ReadCount(
                        reader,
                        FortificationStateStore.MaximumTileCount,
                        "gates");
                    EnsureRemaining(
                        stream,
                        (long)gateCount * GateFixedRecordBytes,
                        "gate records");
                    for (int index = 0; index < gateCount; index++)
                    {
                        int anchorTileId = reader.ReadInt32();
                        byte saveCode = reader.ReadByte();
                        int owner = reader.ReadByte();
                        int routeIndex = reader.ReadByte();
                        int remainder = reader.ReadInt32();
                        int occupiedCount = ReadCount(
                            reader,
                            FortificationStateStore
                                .MaximumGateFootprintTiles,
                            "gate footprint");
                        if (occupiedCount < 1)
                        {
                            throw new InvalidDataException(
                                "Gate footprint must not be empty.");
                        }
                        EnsureRemaining(
                            stream,
                            (long)occupiedCount * sizeof(int),
                            "gate footprint tiles");
                        var occupied = new int[occupiedCount];
                        for (int tileIndex = 0;
                            tileIndex < occupied.Length;
                            tileIndex++)
                        {
                            occupied[tileIndex] = reader.ReadInt32();
                        }

                        FortificationVariantDefinition variant =
                            GetPersistedVariant(saveCode);
                        if (variant.Role != FortificationVariantRole.Gatehouse)
                        {
                            throw new InvalidDataException(
                                "A gate uses a non-gate save code.");
                        }
                        state.AddGate(new FortificationGateState(
                            anchorTileId,
                            variant.Id,
                            owner,
                            routeIndex,
                            occupied,
                            remainder));
                    }

                    if (stream.Position != canonicalLength)
                    {
                        throw new InvalidDataException(
                            "Fortification save contains trailing canonical data.");
                    }
                    state.ValidateInvariants();
                    return state;
                }
            }
            catch (InvalidDataException)
            {
                throw;
            }
            catch (Exception exception) when (
                exception is EndOfStreamException
                || exception is IOException
                || exception is ArgumentException
                || exception is KeyNotFoundException
                || exception is OverflowException)
            {
                throw new InvalidDataException(
                    "Fortification save payload is malformed.",
                    exception);
            }
        }

        private static FortificationVariantDefinition GetPersistedVariant(
            byte saveCode)
        {
            FortificationVariantDefinition variant;
            if (!FortificationVariantCatalog.TryGetPersisted(
                saveCode,
                out variant))
            {
                throw new InvalidDataException(
                    "Unknown fortification save code: " + saveCode);
            }
            return variant;
        }

        private static void ReadEconomyCredits(
            BinaryReader reader,
            int count,
            FortificationStateStore state)
        {
            var seenKeys = new HashSet<int>();
            for (int index = 0; index < count; index++)
            {
                int playerId = reader.ReadByte();
                var resource = (FortificationResource)reader.ReadByte();
                int creditQuarters = reader.ReadByte();
                var record = new FortificationEconomyCreditRecord(
                    playerId,
                    resource,
                    creditQuarters);
                if (!seenKeys.Add(record.StableKey))
                {
                    throw new InvalidDataException(
                        "Duplicate fortification economy player/resource key.");
                }
                state.SetEconomyCredit(record);
            }
            if (seenKeys.Count != EconomyCreditRecordCount)
            {
                throw new InvalidDataException(
                    "Fortification economy credit key set is incomplete.");
            }
        }

        private static int ReadCount(
            BinaryReader reader,
            int maximum,
            string label)
        {
            int count = reader.ReadInt32();
            if (count < 0 || count > maximum)
            {
                throw new InvalidDataException(
                    "Fortification " + label + " count is invalid.");
            }
            return count;
        }

        private static void EnsureRemaining(
            Stream stream,
            long requiredBytes,
            string label)
        {
            if (requiredBytes < 0
                || requiredBytes > stream.Length - stream.Position)
            {
                throw new InvalidDataException(
                    "Fortification " + label + " are truncated.");
            }
        }

        private static void VerifyChecksum(
            byte[] payload,
            int canonicalLength)
        {
            for (int index = 0; index < ChecksumMagic.Length; index++)
            {
                if (payload[canonicalLength + index] != ChecksumMagic[index])
                {
                    throw new InvalidDataException(
                        "Fortification save checksum trailer is missing.");
                }
            }

            byte[] expected;
            using (SHA256 sha = SHA256.Create())
            {
                expected = sha.ComputeHash(payload, 0, canonicalLength);
            }
            int difference = 0;
            int checksumOffset = canonicalLength + ChecksumMagic.Length;
            for (int index = 0; index < ChecksumLength; index++)
            {
                difference |= expected[index]
                    ^ payload[checksumOffset + index];
            }
            if (difference != 0)
            {
                throw new InvalidDataException(
                    "Fortification save checksum mismatch.");
            }
        }
    }
}
