using System;
using System.IO;
using System.Threading;

namespace StrongholdEuropeDE.Runtime.Audio
{
    /// <summary>
    /// Thread-safe, seekable PCM16-to-float converter for Unity's procedural
    /// AudioClip callbacks. It owns one bounded byte buffer and never owns a
    /// whole WAV or a whole-clip float array.
    /// </summary>
    internal sealed class Pcm16StreamReader : IDisposable
    {
        private readonly object _gate = new object();
        private readonly Stream _stream;
        private readonly PcmWaveLayout _layout;
        private readonly byte[] _buffer;
        private readonly bool _ownsStream;
        private readonly Action<Exception> _faultSink;
        private long _sampleValuePosition;
        private int _disposed;
        private int _faulted;

        internal Pcm16StreamReader(
            Stream stream,
            PcmWaveLayout layout,
            int bufferBytes,
            bool ownsStream,
            Action<Exception> faultSink)
        {
            if (stream == null)
            {
                throw new ArgumentNullException("stream");
            }
            if (layout == null)
            {
                throw new ArgumentNullException("layout");
            }
            if (!stream.CanRead || !stream.CanSeek)
            {
                throw new ArgumentException("PCM stream must be readable and seekable", "stream");
            }
            if (layout.AudioFormat != 1
                || layout.BitsPerSample != 16
                || layout.BlockAlign != layout.Channels * 2)
            {
                throw new ArgumentException("Only interleaved PCM16 is supported", "layout");
            }
            if (bufferBytes < 2
                || (bufferBytes & 1) != 0
                || bufferBytes > PcmStreamingLimits.MaximumBufferBytes)
            {
                throw new ArgumentOutOfRangeException("bufferBytes");
            }
            _stream = stream;
            _layout = layout;
            _buffer = new byte[bufferBytes];
            _ownsStream = ownsStream;
            _faultSink = faultSink;
            _stream.Position = _layout.DataOffset;
        }

        internal bool Faulted
        {
            get { return Volatile.Read(ref _faulted) != 0; }
        }

        internal int BufferBytes
        {
            get { return _buffer.Length; }
        }

        internal long PositionFrames
        {
            get
            {
                lock (_gate)
                {
                    return _sampleValuePosition / _layout.Channels;
                }
            }
        }

        internal int ReadSamples(float[] destination)
        {
            if (destination == null)
            {
                return 0;
            }
            Exception failure = null;
            int converted = 0;
            lock (_gate)
            {
                if (_disposed != 0 || _faulted != 0)
                {
                    Array.Clear(destination, 0, destination.Length);
                    return 0;
                }
                try
                {
                    long totalSampleValues = _layout.DataSize / 2;
                    int outputOffset = 0;
                    while (outputOffset < destination.Length
                        && _sampleValuePosition < totalSampleValues)
                    {
                        long remainingValues = totalSampleValues - _sampleValuePosition;
                        int wantedValues = (int)Math.Min(
                            Math.Min((long)(destination.Length - outputOffset), remainingValues),
                            _buffer.Length / 2L);
                        int wantedBytes = checked(wantedValues * 2);
                        int readBytes = ReadExactlyOrEnd(_buffer, wantedBytes);
                        if (readBytes != wantedBytes)
                        {
                            throw new EndOfStreamException(
                                "PCM data ended before its declared data chunk");
                        }
                        for (int index = 0; index < wantedValues; index++)
                        {
                            int byteIndex = index * 2;
                            int unsigned = _buffer[byteIndex]
                                | (_buffer[byteIndex + 1] << 8);
                            short signed = unchecked((short)unsigned);
                            destination[outputOffset + index] = signed / 32768.0f;
                        }
                        outputOffset += wantedValues;
                        converted += wantedValues;
                        _sampleValuePosition += wantedValues;
                    }
                    if (converted < destination.Length)
                    {
                        Array.Clear(
                            destination,
                            converted,
                            destination.Length - converted);
                    }
                }
                catch (Exception exception)
                {
                    Volatile.Write(ref _faulted, 1);
                    failure = exception;
                    if (converted < destination.Length)
                    {
                        Array.Clear(
                            destination,
                            converted,
                            destination.Length - converted);
                    }
                }
            }
            NotifyFault(failure);
            return converted;
        }

        internal void SeekFrames(int framePosition)
        {
            Exception failure = null;
            lock (_gate)
            {
                if (_disposed != 0 || _faulted != 0)
                {
                    return;
                }
                try
                {
                    long clamped = framePosition;
                    if (clamped < 0)
                    {
                        clamped = 0;
                    }
                    if (clamped > _layout.SampleFrames)
                    {
                        clamped = _layout.SampleFrames;
                    }
                    long relativeBytes = checked(clamped * _layout.BlockAlign);
                    _stream.Position = checked(_layout.DataOffset + relativeBytes);
                    _sampleValuePosition = checked(clamped * _layout.Channels);
                }
                catch (Exception exception)
                {
                    Volatile.Write(ref _faulted, 1);
                    failure = exception;
                }
            }
            NotifyFault(failure);
        }

        internal void PcmReaderCallback(float[] data)
        {
            ReadSamples(data);
        }

        internal void PcmSetPositionCallback(int position)
        {
            SeekFrames(position);
        }

        public void Dispose()
        {
            lock (_gate)
            {
                if (Interlocked.Exchange(ref _disposed, 1) != 0)
                {
                    return;
                }
                if (_ownsStream)
                {
                    try
                    {
                        _stream.Dispose();
                    }
                    catch
                    {
                        // Shutdown/release must never escape into Unity Update.
                    }
                }
            }
        }

        private int ReadExactlyOrEnd(byte[] buffer, int count)
        {
            int offset = 0;
            while (offset < count)
            {
                int read = _stream.Read(buffer, offset, count - offset);
                if (read == 0)
                {
                    break;
                }
                offset += read;
            }
            return offset;
        }

        private void NotifyFault(Exception failure)
        {
            if (failure == null || _faultSink == null)
            {
                return;
            }
            try
            {
                _faultSink(failure);
            }
            catch
            {
                // Never let diagnostic code escape Unity's audio callback.
            }
        }
    }
}
