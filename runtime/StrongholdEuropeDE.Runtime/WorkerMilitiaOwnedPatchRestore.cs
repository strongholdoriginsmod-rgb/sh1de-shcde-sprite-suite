using System;
using System.Collections.Generic;

namespace StrongholdEuropeDE.Runtime
{
    internal sealed class WorkerMilitiaOwnedPatchSite
    {
        internal WorkerMilitiaOwnedPatchSite(
            string label,
            int rva,
            bool executable,
            byte[] original,
            byte[] applied)
        {
            if (string.IsNullOrWhiteSpace(label))
            {
                throw new ArgumentException("Patch site label is required", "label");
            }
            if (rva <= 0)
            {
                throw new ArgumentOutOfRangeException("rva");
            }
            if (original == null
                || applied == null
                || original.Length == 0
                || original.Length != applied.Length)
            {
                throw new ArgumentException(
                    "Patch site byte arrays must be non-empty and equally sized");
            }
            Label = label;
            Rva = rva;
            Executable = executable;
            Original = (byte[])original.Clone();
            Applied = (byte[])applied.Clone();
        }

        internal string Label { get; private set; }
        internal int Rva { get; private set; }
        internal bool Executable { get; private set; }
        internal byte[] Original { get; private set; }
        internal byte[] Applied { get; private set; }
    }

    /// <summary>
    /// Restores a native patch only while every site is still either the exact
    /// owned applied value or its exact original value. The complete preflight
    /// happens before the first write, so foreign drift is never overwritten.
    /// </summary>
    internal static class WorkerMilitiaOwnedPatchRestore
    {
        internal delegate byte[] ReadBytes(int rva, int length);
        internal delegate void WriteBytes(
            int rva,
            byte[] value,
            bool executable);

        internal static bool TryRestore(
            IList<WorkerMilitiaOwnedPatchSite> sites,
            ReadBytes read,
            WriteBytes write,
            Func<bool> nativeStateIsIndeterminate,
            out string reason)
        {
            if (sites == null)
            {
                throw new ArgumentNullException("sites");
            }
            if (read == null)
            {
                throw new ArgumentNullException("read");
            }
            if (write == null)
            {
                throw new ArgumentNullException("write");
            }

            var restore = new List<WorkerMilitiaOwnedPatchSite>();
            for (int index = 0; index < sites.Count; index++)
            {
                WorkerMilitiaOwnedPatchSite site = sites[index];
                if (site == null)
                {
                    reason = "native patch site " + index + " is absent";
                    return false;
                }
                byte[] current;
                try
                {
                    current = read(site.Rva, site.Original.Length);
                }
                catch (Exception exception)
                {
                    reason = "preflight read failed at " + site.Label + ": "
                        + exception.GetType().Name + ": " + exception.Message;
                    return false;
                }
                if (SequenceEquals(current, site.Applied))
                {
                    restore.Add(site);
                    continue;
                }
                if (SequenceEquals(current, site.Original))
                {
                    continue;
                }
                reason = "foreign native bytes at " + site.Label
                    + " (current=" + Hex(current)
                    + " owned=" + Hex(site.Applied)
                    + " original=" + Hex(site.Original) + ")";
                return false;
            }

            string failures = null;
            foreach (WorkerMilitiaOwnedPatchSite site in restore)
            {
                try
                {
                    write(
                        site.Rva,
                        (byte[])site.Original.Clone(),
                        site.Executable);
                }
                catch (Exception exception)
                {
                    AppendFailure(
                        ref failures,
                        site.Label + " write: " + exception.GetType().Name
                            + ": " + exception.Message);
                }
            }

            bool readbackMatches = true;
            foreach (WorkerMilitiaOwnedPatchSite site in sites)
            {
                try
                {
                    byte[] current = read(site.Rva, site.Original.Length);
                    if (!SequenceEquals(current, site.Original))
                    {
                        readbackMatches = false;
                        AppendFailure(
                            ref failures,
                            site.Label + " readback=" + Hex(current));
                    }
                }
                catch (Exception exception)
                {
                    readbackMatches = false;
                    AppendFailure(
                        ref failures,
                        site.Label + " readback: "
                            + exception.GetType().Name + ": "
                            + exception.Message);
                }
            }

            bool nativeIndeterminate = nativeStateIsIndeterminate != null
                && nativeStateIsIndeterminate();
            if (nativeIndeterminate)
            {
                AppendFailure(
                    ref failures,
                    "native page protection or instruction-cache state is "
                        + "indeterminate");
            }
            if (!readbackMatches || nativeIndeterminate)
            {
                AppendFailure(ref failures, "owned byte readback disagrees");
                reason = failures ?? "owned byte readback disagrees";
                return false;
            }
            reason = failures;
            return true;
        }

        private static void AppendFailure(ref string failures, string failure)
        {
            failures = string.IsNullOrEmpty(failures)
                ? failure
                : failures + "; " + failure;
        }

        private static bool SequenceEquals(byte[] left, byte[] right)
        {
            if (left == null || right == null || left.Length != right.Length)
            {
                return false;
            }
            for (int index = 0; index < left.Length; index++)
            {
                if (left[index] != right[index])
                {
                    return false;
                }
            }
            return true;
        }

        private static string Hex(byte[] value)
        {
            if (value == null)
            {
                return "none";
            }
            const string Digits = "0123456789ABCDEF";
            var text = new char[value.Length * 2];
            for (int index = 0; index < value.Length; index++)
            {
                text[index * 2] = Digits[value[index] >> 4];
                text[(index * 2) + 1] = Digits[value[index] & 0xF];
            }
            return new string(text);
        }
    }
}
