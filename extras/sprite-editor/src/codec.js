/* Binary codecs. PNG samples are decoded without browser alpha premultiplication. */
(function (root, factory) {
    'use strict';
    const api = factory(typeof module === 'object' && module.exports ? require('./core.js') : root.SpriteCore);
    if (typeof module === 'object' && module.exports)
        module.exports = api;
    else
        root.SpriteCodec = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
    'use strict';
    const te = new TextEncoder(), td = new TextDecoder('utf-8', { fatal: true });
    const crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let j = 0; j < 8; j++)
            c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        crcTable[n] = c >>> 0;
    }
    function crc32(data) {
        let c = 0xffffffff;
        for (let i = 0; i < data.length; i++)
            c = crcTable[(c ^ data[i]) & 255] ^ (c >>> 8);
        return (c ^ 0xffffffff) >>> 0;
    }
    function concat(parts, total = parts.reduce((n, p) => n + p.length, 0)) {
        const a = new Uint8Array(total);
        let p = 0;
        for (const b of parts) {
            a.set(b, p);
            p += b.length;
        }
        if (p !== total)
            C.fail('Widersprüchliche Pufferlänge.');
        return a;
    }
    function aborted(signal) {
        if (signal?.aborted)
            throw new DOMException('Vorgang abgebrochen.', 'AbortError');
    }
    /**
     * Collect a bounded native compression stream. Check actual output length,
     * not only an archive's untrusted declared size; cancel the reader on errors.
     * @param {ReadableStream<Uint8Array>} stream
     * @param {number} max Maximum decompressed/encoded byte count.
     * @param {AbortSignal|undefined} signal
     * @returns {Promise<Uint8Array>}
     */
    async function collect(stream, max, signal) {
        const reader = stream.getReader(), parts = [];
        let size = 0;
        try {
            for (;;) {
                aborted(signal);
                const { value, done } = await reader.read();
                if (done)
                    break;
                size += value.byteLength;
                if (size > max)
                    C.fail('Entpackte Daten überschreiten die Schutzgrenze.');
                parts.push(value);
            }
            return concat(parts, size);
        }
        catch (e) {
            try {
                await reader.cancel();
            }
            catch (_) {
            }
            throw e;
        }
        finally {
            reader.releaseLock();
        }
    }
    async function compress(bytes, format = 'deflate', signal) {
        aborted(signal);
        if (typeof CompressionStream !== 'function')
            C.fail('Dieser Browser unterstützt keine lokalen Kompressionsstreams.');
        return collect(new Blob([bytes]).stream().pipeThrough(new CompressionStream(format)), C.LIMITS.archiveBytes, signal);
    }
    async function decompress(bytes, format, max, signal) {
        aborted(signal);
        if (typeof DecompressionStream !== 'function')
            C.fail('Dieser Browser unterstützt keine lokalen Kompressionsstreams.');
        try {
            return await collect(new Blob([bytes]).stream().pipeThrough(new DecompressionStream(format)), max, signal);
        }
        catch (e) {
            if (e.name === 'AbortError')
                throw e;
            throw new Error(`Komprimierte Daten ungültig: ${e.message}`);
        }
    }
    const signature = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
    function pngHeader(bytes) {
        if (!(bytes instanceof Uint8Array) || bytes.length < 33 || signature.some((v, i) => bytes[i] !== v))
            C.fail('Keine gültige PNG-Datei.');
        const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        if (v.getUint32(8) !== 13 || td.decode(bytes.subarray(12, 16)) !== 'IHDR')
            C.fail('PNG-IHDR fehlt.');
        const width = v.getUint32(16), height = v.getUint32(20);
        C.dimensions(width, height);
        return { width, height, depth: bytes[24], type: bytes[25], compression: bytes[26], filter: bytes[27], interlace: bytes[28] };
    }
    const paeth = (a, b, c) => {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
    };
    async function decodePNG(bytes, options = {}) {
        if (bytes.length > C.LIMITS.fileBytes)
            C.fail('PNG-Datei überschreitet 64 MiB.');
        const h = pngHeader(bytes), allowed = { 0: [1, 2, 4, 8, 16], 2: [8, 16], 3: [1, 2, 4, 8], 4: [8, 16], 6: [8, 16] };
        if (!allowed[h.type]?.includes(h.depth) || h.compression || h.filter || h.interlace > 1)
            C.fail('Nicht unterstützte PNG-Kodierung.');
        if (h.depth === 16)
            C.fail('16-Bit-PNG: vor dem Import bewusst in 8 Bit je Kanal konvertieren. Die Anwendung reduziert die Farbtiefe nicht stillschweigend.');
        const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), idats = [], warnings = [];
        let palette = null, trans = null, p = 8, seenIEND = false, seenIDAT = false, afterIDAT = false, seenIHDR = false;
        const singles = new Set();
        while (p + 12 <= bytes.length) {
            aborted(options.signal);
            const len = v.getUint32(p), end = p + 12 + len;
            if (end > bytes.length)
                C.fail('Abgeschnittener PNG-Chunk.');
            const type = td.decode(bytes.subarray(p + 4, p + 8)), data = bytes.subarray(p + 8, p + 8 + len);
            if (!/^[A-Za-z]{4}$/.test(type))
                C.fail('Ungültiger PNG-Chunkname.');
            if (crc32(bytes.subarray(p + 4, p + 8 + len)) !== v.getUint32(p + 8 + len))
                C.fail(`PNG-Prüfsumme stimmt nicht (${type}).`);
            if (!seenIHDR && type !== 'IHDR')
                C.fail('IHDR muss der erste PNG-Chunk sein.');
            if (['IHDR', 'PLTE', 'tRNS', 'IEND'].includes(type)) {
                if (singles.has(type))
                    C.fail(`Doppelter PNG-Chunk: ${type}`);
                singles.add(type);
            }
            if (type === 'IHDR') {
                if (len !== 13)
                    C.fail('Ungültiger IHDR.');
                seenIHDR = true;
            }
            else if (type === 'PLTE') {
                if (seenIDAT || !len || len % 3 || len > 768)
                    C.fail('Ungültige PNG-Palette.');
                palette = data;
            }
            else if (type === 'tRNS') {
                if (seenIDAT)
                    C.fail('PNG-Transparenz steht hinter den Bilddaten.');
                trans = data;
            }
            else if (type === 'IDAT') {
                if (afterIDAT)
                    C.fail('PNG-IDAT-Chunks sind nicht zusammenhängend.');
                seenIDAT = true;
                idats.push(data);
            }
            else if (type === 'IEND') {
                if (len || !seenIDAT)
                    C.fail('Ungültiges PNG-Ende.');
                seenIEND = true;
                p = end;
                break;
            }
            else if (type === 'acTL')
                C.fail('Animierte PNGs zuerst in einzelne Frames exportieren.');
            else if ((type.charCodeAt(0) & 32) === 0)
                C.fail(`Nicht unterstützter kritischer PNG-Chunk: ${type}`);
            if (seenIDAT && type !== 'IDAT')
                afterIDAT = true;
            if (type === 'iCCP' || type === 'cICP' || type === 'mDCV' || type === 'cHRM' || (type === 'gAMA' && (len !== 4 || new DataView(data.buffer, data.byteOffset, data.byteLength).getUint32(0) !== 45455)))
                warnings.push('Eingebettetes Farbprofil wird nicht umgerechnet. Kanalwerte bleiben unverändert; abgeleitete PNGs enthalten kein Farbprofil.');
            p = end;
        }
        if (!seenIEND || p !== bytes.length)
            C.fail('PNG unvollständig oder mit zusätzlichen Daten nach IEND.');
        if (h.type === 3 && (!palette || palette.length / 3 > 2 ** h.depth))
            C.fail('PNG-Palette fehlt oder ist zu groß.');
        if (trans && ((h.type === 0 && trans.length !== 2) || (h.type === 2 && trans.length !== 6) || (h.type === 3 && trans.length > (palette?.length || 0) / 3) || h.type === 4 || h.type === 6))
            C.fail('Ungültige PNG-Transparenz.');
        const channels = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[h.type], bits = channels * h.depth, bpp = Math.max(1, Math.ceil(bits / 8));
        const passes = h.interlace ? [[0, 0, 8, 8], [4, 0, 8, 8], [0, 4, 4, 8], [2, 0, 4, 4], [0, 2, 2, 4], [1, 0, 2, 2], [0, 1, 1, 2]] : [[0, 0, 1, 1]];
        let expected = 0;
        const specs = passes.map(([x, y, dx, dy]) => {
            const w = Math.max(0, Math.ceil((h.width - x) / dx)), hh = Math.max(0, Math.ceil((h.height - y) / dy)), stride = Math.ceil(w * bits / 8);
            if (w && hh)
                expected += (stride + 1) * hh;
            return { x, y, dx, dy, w, h: hh, stride };
        });
        const raw = await decompress(concat(idats), 'deflate', expected, options.signal);
        if (raw.length !== expected)
            C.fail('PNG-Bilddaten haben eine falsche Länge.');
        const dst = C.image(h.width, h.height);
        let offset = 0;
        const tr = trans ? new DataView(trans.buffer, trans.byteOffset, trans.byteLength) : null, maxSample = (1 << h.depth) - 1;
        for (const ps of specs) {
            if (!ps.w || !ps.h)
                continue;
            let prev = new Uint8Array(ps.stride);
            for (let y = 0; y < ps.h; y++) {
                aborted(options.signal);
                const filter = raw[offset++];
                if (filter > 4)
                    C.fail('Unbekannter PNG-Zeilenfilter.');
                const line = new Uint8Array(ps.stride);
                for (let i = 0; i < ps.stride; i++) {
                    const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
                    const f = filter === 0 ? 0 : filter === 1 ? a : filter === 2 ? b : filter === 3 ? Math.floor((a + b) / 2) : paeth(a, b, c);
                    line[i] = (raw[offset++] + f) & 255;
                }
                for (let x = 0; x < ps.w; x++) {
                    const di = ((ps.y + y * ps.dy) * h.width + ps.x + x * ps.dx) * 4, si = x * channels;
                    const sample = k => h.depth === 8 ? line[si + k] : (line[Math.floor((si + k) * h.depth / 8)] >>> (8 - h.depth - ((si + k) * h.depth % 8))) & maxSample;
                    let r = 0, g = 0, b = 0, a = 255;
                    if (h.type === 6) {
                        r = sample(0);
                        g = sample(1);
                        b = sample(2);
                        a = sample(3);
                    }
                    else if (h.type === 2) {
                        r = sample(0);
                        g = sample(1);
                        b = sample(2);
                        if (tr && r === tr.getUint16(0) && g === tr.getUint16(2) && b === tr.getUint16(4))
                            a = 0;
                    }
                    else if (h.type === 3) {
                        const n = sample(0);
                        if (n * 3 + 2 >= palette.length)
                            C.fail('PNG-Palettenindex außerhalb der Palette.');
                        r = palette[n * 3];
                        g = palette[n * 3 + 1];
                        b = palette[n * 3 + 2];
                        a = trans && n < trans.length ? trans[n] : 255;
                    }
                    else {
                        const n = sample(0);
                        r = g = b = Math.round(n * 255 / maxSample);
                        if (h.type === 4)
                            a = sample(1);
                        else if (tr && n === tr.getUint16(0))
                            a = 0;
                    }
                    dst.data[di] = r;
                    dst.data[di + 1] = g;
                    dst.data[di + 2] = b;
                    dst.data[di + 3] = a;
                }
                prev = line;
            }
        }
        return { ...dst, bytes, warnings: [...new Set(warnings)], pngInfo: h };
    }
    function chunk(type, data) {
        const out = new Uint8Array(data.length + 12), v = new DataView(out.buffer);
        v.setUint32(0, data.length);
        out.set(te.encode(type), 4);
        out.set(data, 8);
        v.setUint32(data.length + 8, crc32(out.subarray(4, data.length + 8)));
        return out;
    }
    async function encodePNG(src, options = {}) {
        C.dimensions(src.width, src.height);
        if (src.data.length !== src.width * src.height * 4)
            C.fail('Ungültiger RGBA-Puffer.');
        const header = new Uint8Array(13), v = new DataView(header.buffer);
        v.setUint32(0, src.width);
        v.setUint32(4, src.height);
        header[8] = 8;
        header[9] = 6;
        const stride = src.width * 4, raw = new Uint8Array((stride + 1) * src.height);
        for (let y = 0; y < src.height; y++) {
            aborted(options.signal);
            const base = y * (stride + 1), s = y * stride;
            raw[base] = 1;
            for (let x = 0; x < stride; x++)
                raw[base + 1 + x] = (src.data[s + x] - (x >= 4 ? src.data[s + x - 4] : 0)) & 255;
        }
        const packed = await compress(raw, 'deflate', options.signal);
        return concat([signature, chunk('IHDR', header), chunk('IDAT', packed), chunk('IEND', new Uint8Array())]);
    }
    function bytesToBase64(bytes) {
        let s = '';
        for (let i = 0; i < bytes.length; i += 0x8000)
            s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        return btoa(s);
    }
    function base64ToBytes(s) {
        if (typeof s !== 'string' || s.length > Math.ceil(C.LIMITS.fileBytes / 3) * 4 || (s.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(s) || s.indexOf('=') !== -1 && !/^[^=]*={1,2}$/.test(s)))
            C.fail('Ungültige Base64-Bilddaten.');
        const bin = atob(s), out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++)
            out[i] = bin.charCodeAt(i);
        return out;
    }
    /** SHA-256 fallback for local/opaque browser origins. Used as a corruption checksum,
        not as authentication. The native Web Crypto implementation is preferred. */
    function sha256Fallback(bytes) {
        if (!(bytes instanceof Uint8Array))
            C.fail('SHA-256 benötigt Bytes.');
        const constants = new Uint32Array([0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);
        const hash = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]), w = new Uint32Array(64), rot = (x, n) => (x >>> n) | (x << (32 - n));
        const length = bytes.length, total = Math.ceil((length + 9) / 64) * 64, last = new Uint8Array(8), lv = new DataView(last.buffer);
        lv.setUint32(0, Math.floor(length / 0x20000000));
        lv.setUint32(4, (length * 8) >>> 0);
        const byte = i => i < length ? bytes[i] : i === length ? 128 : i >= total - 8 ? last[i - (total - 8)] : 0;
        for (let offset = 0; offset < total; offset += 64) {
            for (let i = 0; i < 16; i++) {
                const j = offset + i * 4;
                w[i] = (byte(j) << 24) | (byte(j + 1) << 16) | (byte(j + 2) << 8) | byte(j + 3);
            }
            for (let i = 16; i < 64; i++) {
                const a = w[i - 15], b = w[i - 2], s0 = rot(a, 7) ^ rot(a, 18) ^ (a >>> 3), s1 = rot(b, 17) ^ rot(b, 19) ^ (b >>> 10);
                w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
            }
            let [a, b, c, d, e, f, g, h] = hash;
            for (let i = 0; i < 64; i++) {
                const s1 = rot(e, 6) ^ rot(e, 11) ^ rot(e, 25), ch = (e & f) ^ (~e & g), t1 = (h + s1 + ch + constants[i] + w[i]) >>> 0, s0 = rot(a, 2) ^ rot(a, 13) ^ rot(a, 22), maj = (a & b) ^ (a & c) ^ (b & c), t2 = (s0 + maj) >>> 0;
                h = g;
                g = f;
                f = e;
                e = (d + t1) >>> 0;
                d = c;
                c = b;
                b = a;
                a = (t1 + t2) >>> 0;
            }
            const vals = [a, b, c, d, e, f, g, h];
            for (let i = 0; i < 8; i++)
                hash[i] = (hash[i] + vals[i]) >>> 0;
        }
        return Array.from(hash, n => n.toString(16).padStart(8, '0')).join('');
    }
    async function sha256(bytes) {
        return globalThis.crypto?.subtle ? Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), v => v.toString(16).padStart(2, '0')).join('') : sha256Fallback(bytes);
    }
    function zip(entries) {
        if (entries.length > C.LIMITS.entries)
            C.fail('Zu viele Archivdateien.');
        const names = new Set(), local = [], central = [];
        let offset = 0, uncompressed = 0;
        for (const entry of entries) {
            const name = C.safePath(entry.name);
            const key = name.normalize('NFC').toLowerCase();
            if (names.has(key))
                C.fail(`Doppelter Archivpfad: ${name}`);
            names.add(key);
            const n = te.encode(name), data = typeof entry.data === 'string' ? te.encode(entry.data) : entry.data;
            if (!(data instanceof Uint8Array))
                C.fail('Ungültiger Archiveintrag.');
            uncompressed += data.length;
            if (uncompressed > C.LIMITS.archiveBytes)
                C.fail('Archiv überschreitet 192 MiB.');
            const crc = crc32(data), l = new Uint8Array(30 + n.length), lv = new DataView(l.buffer);
            lv.setUint32(0, 0x04034b50, true);
            lv.setUint16(4, 20, true);
            lv.setUint16(6, 0x800, true);
            lv.setUint16(12, 33, true);
            lv.setUint32(14, crc, true);
            lv.setUint32(18, data.length, true);
            lv.setUint32(22, data.length, true);
            lv.setUint16(26, n.length, true);
            l.set(n, 30);
            local.push(l, data);
            const c = new Uint8Array(46 + n.length), cv = new DataView(c.buffer);
            cv.setUint32(0, 0x02014b50, true);
            cv.setUint16(4, 20, true);
            cv.setUint16(6, 20, true);
            cv.setUint16(8, 0x800, true);
            cv.setUint16(14, 33, true);
            cv.setUint32(16, crc, true);
            cv.setUint32(20, data.length, true);
            cv.setUint32(24, data.length, true);
            cv.setUint16(28, n.length, true);
            cv.setUint32(42, offset, true);
            c.set(n, 46);
            central.push(c);
            offset += l.length + data.length;
        }
        const cd = concat(central), end = new Uint8Array(22), ev = new DataView(end.buffer);
        ev.setUint32(0, 0x06054b50, true);
        ev.setUint16(8, entries.length, true);
        ev.setUint16(10, entries.length, true);
        ev.setUint32(12, cd.length, true);
        ev.setUint32(16, offset, true);
        if (offset + cd.length + 22 > C.LIMITS.archiveBytes)
            C.fail('Archiv überschreitet 192 MiB.');
        return concat([...local, cd, end]);
    }
    const cp437 = 'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ';
    function zipText(bytes, flags) {
        if (flags & 0x800)
            return td.decode(bytes);
        return Array.from(bytes, x => x < 128 ? String.fromCharCode(x) : cp437[x - 128]).join('');
    }
    async function unzip(bytes, options = {}) {
        if (!(bytes instanceof Uint8Array) || bytes.length < 22 || bytes.length > C.LIMITS.archiveBytes)
            C.fail('ZIP ungültig oder größer als 192 MiB.');
        const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        let end = -1;
        for (let p = bytes.length - 22; p >= Math.max(0, bytes.length - 65557); p--)
            if (v.getUint32(p, true) === 0x06054b50 && p + 22 + v.getUint16(p + 20, true) === bytes.length) {
                end = p;
                break;
            }
        if (end < 0)
            C.fail('ZIP-Endverzeichnis fehlt.');
        if (v.getUint16(end + 4, true) || v.getUint16(end + 6, true) || v.getUint16(end + 8, true) !== v.getUint16(end + 10, true))
            C.fail('Mehrteilige ZIP-Archive werden nicht unterstützt.');
        const count = v.getUint16(end + 10, true), size = v.getUint32(end + 12, true), start = v.getUint32(end + 16, true);
        if (count === 65535 || start === 0xffffffff || size === 0xffffffff)
            C.fail('ZIP64 wird nicht unterstützt.');
        if (count > C.LIMITS.entries || start + size !== end)
            C.fail('Ungültige ZIP-Verzeichnisgröße.');
        const entries = [], names = new Set(), ranges = [];
        let p = start, total = 0;
        for (let i = 0; i < count; i++) {
            aborted(options.signal);
            if (p + 46 > end || v.getUint32(p, true) !== 0x02014b50)
                C.fail('Beschädigtes ZIP-Verzeichnis.');
            const flags = v.getUint16(p + 8, true), method = v.getUint16(p + 10, true), crc = v.getUint32(p + 16, true), packed = v.getUint32(p + 20, true), length = v.getUint32(p + 24, true), nl = v.getUint16(p + 28, true), el = v.getUint16(p + 30, true), cl = v.getUint16(p + 32, true), offset = v.getUint32(p + 42, true), attrs = v.getUint32(p + 38, true);
            if (flags & 0x41)
                C.fail('Verschlüsselte ZIP-Dateien werden nicht unterstützt.');
            if (flags & ~0x080e)
                C.fail('Nicht unterstützte ZIP-Flags.');
            if (![0, 8].includes(method))
                C.fail(`Nicht unterstützte ZIP-Kompression (${method}).`);
            if (v.getUint16(p + 34, true))
                C.fail('Mehrteiliges ZIP wird nicht unterstützt.');
            if (((attrs >>> 16) & 0xf000) === 0xa000)
                C.fail('ZIP mit symbolischen Verknüpfungen wird abgewiesen.');
            if ([packed, length, offset].includes(0xffffffff) || p + 46 + nl + el + cl > end)
                C.fail('ZIP64 oder beschädigter ZIP-Eintrag.');
            const rawName = bytes.subarray(p + 46, p + 46 + nl);
            let name = zipText(rawName, flags);
            for (let e = p + 46 + nl; e < p + 46 + nl + el;) {
                if (e + 4 > p + 46 + nl + el)
                    C.fail('Ungültiges ZIP-Zusatzfeld.');
                const type = v.getUint16(e, true), len = v.getUint16(e + 2, true);
                if (e + 4 + len > p + 46 + nl + el)
                    C.fail('Ungültiges ZIP-Zusatzfeld.');
                if (type === 1)
                    C.fail('ZIP64 wird nicht unterstützt.');
                if (type === 0x7075 && len >= 5 && bytes[e + 4] === 1 && v.getUint32(e + 5, true) === crc32(rawName))
                    name = td.decode(bytes.subarray(e + 9, e + 4 + len));
                e += 4 + len;
            }
            C.safePath(name);
            if (names.has(name.normalize('NFC').toLowerCase()))
                C.fail(`Doppelter ZIP-Dateiname: ${name}`);
            names.add(name.normalize('NFC').toLowerCase());
            if (length > C.LIMITS.fileBytes && !name.endsWith('.json'))
                C.fail(`ZIP-Datei größer als 64 MiB: ${name}`);
            total += length;
            if (total > C.LIMITS.archiveBytes)
                C.fail('Entpacktes Archiv überschreitet 192 MiB.');
            if (offset + 30 > start || v.getUint32(offset, true) !== 0x04034b50)
                C.fail('Lokaler ZIP-Dateikopf fehlt.');
            const ln = v.getUint16(offset + 26, true), le = v.getUint16(offset + 28, true), dataStart = offset + 30 + ln + le;
            if (v.getUint16(offset + 8, true) !== method || v.getUint16(offset + 6, true) !== flags || ln !== nl || rawName.some((x, j) => x !== bytes[offset + 30 + j]))
                C.fail('ZIP-Dateiköpfe widersprechen sich.');
            if (dataStart + packed > start)
                C.fail('ZIP-Nutzdaten außerhalb des Archivs.');
            if (!(flags & 8) && (v.getUint32(offset + 14, true) !== crc || v.getUint32(offset + 18, true) !== packed || v.getUint32(offset + 22, true) !== length))
                C.fail('ZIP-Längen oder Prüfsummen widersprechen sich.');
            let dataEnd = dataStart + packed;
            if (flags & 8) {
                const matches = (at) => at + 12 <= start && v.getUint32(at, true) === crc && v.getUint32(at + 4, true) === packed && v.getUint32(at + 8, true) === length;
                if (dataEnd + 4 <= start && v.getUint32(dataEnd, true) === 0x08074b50 && matches(dataEnd + 4))
                    dataEnd += 16;
                else if (matches(dataEnd))
                    dataEnd += 12;
                else
                    C.fail('ZIP-Datenbeschreibung fehlt oder widerspricht dem Verzeichnis.');
            }
            ranges.push([offset, dataEnd]);
            entries.push({ name, method, crc, packed, length, dataStart });
            p += 46 + nl + el + cl;
        }
        if (p !== end)
            C.fail('ZIP-Verzeichnis enthält zusätzliche Einträge.');
        ranges.sort((a, b) => a[0] - b[0]);
        for (let i = 1; i < ranges.length; i++)
            if (ranges[i][0] < ranges[i - 1][1])
                C.fail('Überlappende ZIP-Dateieinträge.');
        const result = [];
        for (let i = 0; i < entries.length; i++) {
            const e = entries[i];
            aborted(options.signal);
            options.progress?.(i + 1, entries.length, e.name);
            const raw = bytes.subarray(e.dataStart, e.dataStart + e.packed), data = e.method === 0 ? new Uint8Array(raw) : await decompress(raw, 'deflate-raw', e.length, options.signal);
            if (data.length !== e.length || crc32(data) !== e.crc)
                C.fail(`ZIP-Prüfsumme stimmt nicht: ${e.name}`);
            if (!e.name.endsWith('/'))
                result.push({ name: e.name, data });
        }
        return result;
    }
    return Object.freeze({
        crc32, concat, aborted, collect, compress, decompress, pngHeader, decodePNG, encodePNG, bytesToBase64, base64ToBytes, sha256, sha256Fallback, zip, unzip, encodeText: s => te.encode(s), decodeText: b => td.decode(b), chunk
    });
});
