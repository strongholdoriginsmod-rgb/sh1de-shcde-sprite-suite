/* Stronghold Sprite Editor. Pure geometry and RGBA operations; no DOM or I/O. */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports)
        module.exports = api;
    else
        root.SpriteCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    /**
     * Raw, top-left-origin RGBA8 samples. Alpha is unassociated (straight).
     * Geometry functions allocate new buffers and never mutate an input image.
     * @typedef {{width:number, height:number, data:Uint8Array|Uint8ClampedArray}} RGBAImage
     */
    /** @typedef {{x:number, y:number}} NormalizedPivot Bottom-left origin, both in [0,1]. */
    const VERSION = '1.0.0';
    const LIMITS = Object.freeze({
        side: 16384, pixels: 16777216, totalPixels: 33554432,
        frames: 4096, entries: 12288, fileBytes: 67108864, importBytes: 134217728, archiveBytes: 201326592
    });
    const DEFAULT_SCENE = Object.freeze({ a: 5, b: 5, width: 64, height: 32, padding: 8, order: 'ascending', anchor: 'bottom', category: 'building' });
    const MATERIALS = Object.freeze(['Auto', 'Plain', 'TeamColour', 'Foliage']);
    const fail = message => {
        throw new Error(message);
    };
    function number(value, label, min = -Infinity, max = Infinity) {
        if (value === '' || value === null || typeof value === 'boolean' || typeof value === 'object')
            fail(`${label}: Zahl erforderlich.`);
        const n = Number(value);
        if (!Number.isFinite(n) || n < min || n > max)
            fail(`${label}: Zahl zwischen ${min} und ${max} erforderlich.`);
        return n;
    }
    function integer(value, label, min = -LIMITS.side, max = LIMITS.side) {
        const n = number(value, label, min, max);
        if (!Number.isSafeInteger(n))
            fail(`${label}: ganze Zahl erforderlich.`);
        return n;
    }
    function dimensions(width, height) {
        integer(width, 'Breite', 1, LIMITS.side);
        integer(height, 'Höhe', 1, LIMITS.side);
        if (width * height > LIMITS.pixels)
            fail(`Bild ${width} × ${height} überschreitet 16 Megapixel.`);
        return { width, height };
    }
    function image(width, height, data) {
        dimensions(width, height);
        if (data && (!(data instanceof Uint8Array || data instanceof Uint8ClampedArray) || data.length !== width * height * 4))
            fail('Ungültiger RGBA-Puffer.');
        return { width, height, data: data || new Uint8Array(width * height * 4) };
    }
    function scene(raw = {}) {
        const r = { ...DEFAULT_SCENE, ...raw }, s = {
            a: integer(r.a, 'Raster links', 1, 64), b: integer(r.b, 'Raster rechts', 1, 64),
            width: integer(r.width, 'Tilebreite', 2, 2048), height: integer(r.height, 'Rautenhöhe', 2, 2048),
            padding: integer(r.padding, 'Rand', 0, 1024), order: r.order, anchor: r.anchor, category: r.category
        };
        if (s.width % 2 || s.height % 2)
            fail('Tilebreite und Rautenhöhe müssen gerade sein.');
        if (!['ascending', 'descending'].includes(s.order))
            fail('Unbekannte Ebenenreihenfolge.');
        if (!['bottom', 'pivot'].includes(s.anchor))
            fail('Unbekannte Ankerbasis.');
        if (!['building', 'unit', 'vegetation', 'other'].includes(s.category))
            fail('Unbekannter Assettyp.');
        return s;
    }
    /** Front to back, left to right within each horizontal diagonal; zero-based slots. */
    function positions(raw) {
        const s = scene(raw), out = [];
        for (let d = 0; d < s.a + s.b - 1; d++)
            for (let u = Math.min(s.a - 1, d); u >= Math.max(0, d - s.b + 1); u--) {
                const v = d - u;
                out.push({ slot: out.length, u, v, diagonal: d, x: (v - u) * s.width / 2, bottom: d === 0 ? 0 : -d * s.height / 2 });
            }
        return out;
    }
    function footprint(raw) {
        const s = scene(raw);
        return { left: -s.a * s.width / 2, right: s.b * s.width / 2, top: -(s.a + s.b) * s.height / 2, bottom: 0 };
    }
    function pivot(raw = { x: .5, y: 0 }) {
        return { x: number(raw.x, 'Pivot X', 0, 1), y: number(raw.y, 'Pivot Y', 0, 1) };
    }
    function pixelAnchor(frame, img, usePivot = true) {
        const p = pivot(frame.pivot);
        return usePivot ? { x: img.width * p.x, y: img.height * (1 - p.y) } : { x: Math.floor(img.width / 2), y: img.height };
    }
    function layout(frames, raw, getImage) {
        const s = scene(raw), ps = positions(s), f = footprint(s), used = new Set();
        let left = f.left, top = f.top, right = f.right, bottom = f.bottom;
        const placed = frames.map(frame => {
            const slot = integer(frame.slot, 'Rasterplatz', 0, ps.length - 1);
            if (used.has(slot))
                fail(`Rasterplatz ${slot + 1} ist doppelt belegt.`);
            used.add(slot);
            const img = getImage(frame.imageId), a = pixelAnchor(frame, img, s.anchor === 'pivot');
            const dx = integer(frame.dx, 'X-Versatz'), dy = integer(frame.dy, 'Y-Versatz');
            const x = Math.round(ps[slot].x - a.x) + dx, y = Math.round(ps[slot].bottom - a.y) + dy;
            left = Math.min(left, x);
            right = Math.max(right, x + img.width);
            top = Math.min(top, y);
            bottom = Math.max(bottom, y + img.height);
            return { id: frame.id, frame, slot, x, y, width: img.width, height: img.height, anchorX: ps[slot].x + dx, anchorY: ps[slot].bottom + dy };
        });
        left = Math.floor(left) - s.padding;
        top = Math.floor(top) - s.padding;
        right = Math.ceil(right) + s.padding;
        bottom = Math.ceil(bottom) + s.padding;
        const dims = dimensions(right - left, bottom - top);
        for (const p of placed) {
            p.x -= left;
            p.y -= top;
            p.anchorX -= left;
            p.anchorY -= top;
        }
        const paint = [...placed].sort((a, b) => s.order === 'ascending' ? a.slot - b.slot : b.slot - a.slot);
        return { ...dims, left, top, originX: -left, originY: -top, placed, paint, positions: ps, settings: s };
    }
    /** Exact copy, optionally source-over. RGBA stays unassociated; no canvas round-trip. */
    function blit(dst, src, x, y, blend = false) {
        integer(x, 'X');
        integer(y, 'Y');
        const sx = Math.max(0, -x), sy = Math.max(0, -y), ex = Math.min(src.width, dst.width - x), ey = Math.min(src.height, dst.height - y);
        if (ex <= sx || ey <= sy)
            return dst;
        for (let yy = sy; yy < ey; yy++) {
            if (!blend) {
                dst.data.set(src.data.subarray((yy * src.width + sx) * 4, (yy * src.width + ex) * 4), ((yy + y) * dst.width + x + sx) * 4);
                continue;
            }
            for (let xx = sx; xx < ex; xx++) {
                const si = (yy * src.width + xx) * 4, di = ((yy + y) * dst.width + xx + x) * 4, sa = src.data[si + 3];
                if (sa === 0)
                    continue;
                const da = dst.data[di + 3];
                if (sa === 255 || da === 0) {
                    dst.data.set(src.data.subarray(si, si + 4), di);
                    continue;
                }
                const a = sa * 255 + da * (255 - sa);
                for (let c = 0; c < 3; c++)
                    dst.data[di + c] = Math.round((src.data[si + c] * sa * 255 + dst.data[di + c] * da * (255 - sa)) / a);
                dst.data[di + 3] = Math.round(a / 255);
            }
        }
        return dst;
    }
    function compose(l, getImage, mask = false) {
        const dst = image(l.width, l.height);
        for (const p of l.paint)
            if (p.frame.visible && (!mask || p.frame.maskId))
                blit(dst, getImage(mask ? p.frame.maskId : p.frame.imageId), p.x, p.y, true);
        return dst;
    }
    function crop(src, x, y, width, height) {
        integer(x, 'Ausschnitt X', 0, src.width - 1);
        integer(y, 'Ausschnitt Y', 0, src.height - 1);
        dimensions(width, height);
        if (x + width > src.width || y + height > src.height)
            fail('Ausschnitt liegt außerhalb des Bildes.');
        const dst = image(width, height);
        for (let row = 0; row < height; row++)
            dst.data.set(src.data.subarray(((y + row) * src.width + x) * 4, ((y + row) * src.width + x + width) * 4), row * width * 4);
        return dst;
    }
    function alphaBounds(src, threshold = 0) {
        integer(threshold, 'Alphaschwelle', 0, 254);
        let left = src.width, top = src.height, right = 0, bottom = 0, opaque = 0, partial = 0, hiddenRGB = 0;
        for (let y = 0; y < src.height; y++)
            for (let x = 0; x < src.width; x++) {
                const i = (y * src.width + x) * 4, a = src.data[i + 3];
                if (a === 255)
                    opaque++;
                else if (a)
                    partial++;
                else if (src.data[i] || src.data[i + 1] || src.data[i + 2])
                    hiddenRGB++;
                if (a > threshold) {
                    left = Math.min(left, x);
                    top = Math.min(top, y);
                    right = Math.max(right, x + 1);
                    bottom = Math.max(bottom, y + 1);
                }
            }
        return { left, top, right, bottom, width: Math.max(0, right - left), height: Math.max(0, bottom - top), empty: right === 0, opaque, partial, hiddenRGB };
    }
    function trimRect(src, p) {
        const a = alphaBounds(src), ap = pixelAnchor({ pivot: p }, src);
        if (a.empty)
            return { x: 0, y: 0, width: src.width, height: src.height, pivot: { ...p } };
        // Keep the anchor inside the rectangle. Do not turn bottom padding into an out-of-range Unity pivot.
        const x = Math.max(0, Math.min(a.left, Math.floor(ap.x))), y = Math.max(0, Math.min(a.top, Math.floor(ap.y)));
        const right = Math.min(src.width, Math.max(a.right, Math.ceil(ap.x))), bottom = Math.min(src.height, Math.max(a.bottom, Math.ceil(ap.y)));
        return { x, y, width: right - x, height: bottom - y, pivot: { x: (ap.x - x) / (right - x), y: 1 - (ap.y - y) / (bottom - y) } };
    }
    function flip(src, horizontal = true) {
        const dst = image(src.width, src.height);
        for (let y = 0; y < src.height; y++)
            for (let x = 0; x < src.width; x++) {
                const xx = horizontal ? src.width - 1 - x : x, yy = horizontal ? y : src.height - 1 - y;
                dst.data.set(src.data.subarray((y * src.width + x) * 4, (y * src.width + x) * 4 + 4), (yy * src.width + xx) * 4);
            }
        return dst;
    }
    function resize(src, width, height) {
        const dst = image(width, height);
        for (let y = 0; y < height; y++)
            for (let x = 0; x < width; x++) {
                const xx = Math.min(src.width - 1, Math.floor((x + .5) * src.width / width)), yy = Math.min(src.height - 1, Math.floor((y + .5) * src.height / height));
                dst.data.set(src.data.subarray((yy * src.width + xx) * 4, (yy * src.width + xx) * 4 + 4), (y * width + x) * 4);
            }
        return dst;
    }
    function channel(src, which) {
        if (which === 'rgba')
            return src;
        const dst = image(src.width, src.height), idx = { r: 0, g: 1, b: 2, a: 3 }[which];
        if (which !== 'rgb' && idx === undefined)
            fail('Unbekannter Bildkanal.');
        for (let i = 0; i < src.data.length; i += 4) {
            for (let c = 0; c < 3; c++)
                dst.data[i + c] = which === 'rgb' ? src.data[i + c] : src.data[i + idx];
            dst.data[i + 3] = 255;
        }
        return dst;
    }
    function adjust(src, opts = {}) {
        const brightness = number(opts.brightness ?? 0, 'Helligkeit', -100, 100) * 2.55, saturation = number(opts.saturation ?? 100, 'Sättigung', 0, 200) / 100, contrast = number(opts.contrast ?? 100, 'Kontrast', 0, 200) / 100, alphaMode = opts.alphaMode || 'keep';
        if (!['keep', 'unpremultiply', 'premultiply', 'clearHidden'].includes(alphaMode))
            fail('Unbekannte Alphabehandlung.');
        const dst = image(src.width, src.height, new Uint8Array(src.data));
        for (let i = 0; i < src.data.length; i += 4) {
            const a = src.data[i + 3];
            if (alphaMode === 'clearHidden' && a === 0) {
                dst.data[i] = dst.data[i + 1] = dst.data[i + 2] = 0;
                continue;
            }
            const lum = .2126 * src.data[i] + .7152 * src.data[i + 1] + .0722 * src.data[i + 2];
            for (let c = 0; c < 3; c++) {
                let v = ((lum + (src.data[i + c] - lum) * saturation) - 127.5) * contrast + 127.5 + brightness;
                if (alphaMode === 'premultiply')
                    v *= a / 255;
                if (alphaMode === 'unpremultiply')
                    v = a ? v * 255 / a : 0;
                dst.data[i + c] = Math.max(0, Math.min(255, Math.round(v)));
            }
        }
        return dst;
    }
    function difference(a, b) {
        if (a.width !== b.width || a.height !== b.height)
            fail('Pixelvergleich benötigt gleiche Bildabmessungen.');
        const out = image(a.width, a.height);
        let changed = 0, max = 0, sum = 0;
        for (let i = 0; i < a.data.length; i += 4) {
            let diff = false;
            for (let c = 0; c < 4; c++) {
                const d = Math.abs(a.data[i + c] - b.data[i + c]);
                if (d)
                    diff = true;
                max = Math.max(max, d);
                sum += d;
                if (c < 3)
                    out.data[i + c] = d;
            }
            if (diff) {
                changed++;
                out.data[i + 3] = 255;
            }
            else
                out.data[i + 3] = 80;
        }
        return { image: out, changed, max, mean: sum / a.data.length };
    }
    function parseName(name) {
        const stem = String(name).replace(/\.png$/i, '');
        const mask = /_m$/i.test(stem), base = mask ? stem.slice(0, -2) : stem;
        const m = /^(.*?)[\s_-]*(\d+)$/.exec(base);
        if (!m || !m[1].replace(/[\s_-]+$/, ''))
            return { stem, base, mask, group: base, index: null, canonical: base };
        const index = Number(m[2]);
        if (!Number.isSafeInteger(index))
            fail(`Zu große Bildnummer: ${name}`);
        const group = m[1].replace(/[\s_-]+$/, '');
        return { stem, base, mask, group, index, canonical: `${group}-${index}` };
    }
    function targetName(value) {
        const m = /^([A-Za-z][A-Za-z0-9_]*)-(\d+)$/.exec(String(value));
        if (!m)
            fail('Zielname: GM-Gruppe und Index, z. B. tile_ruins-549.');
        const index = integer(m[2], 'Zielindex', 0, 1000000);
        return { group: m[1], index, name: `${m[1]}-${index}` };
    }
    function safeName(name, fallback = 'datei') {
        let out = String(name).normalize('NFC').replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g, '_').replace(/[. ]+$/g, '').slice(0, 140);
        if (!out || /^\.+$/.test(out))
            out = fallback;
        if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(out))
            out = '_' + out;
        return out;
    }
    function safePath(path) {
        if (typeof path !== 'string' || !path || path.length > 512 || /[\x00-\x1f\x7f\\:]/.test(path) || path.startsWith('/'))
            fail('Unsicherer Archivpfad.');
        const parts = path.split('/');
        if (parts.some((p, i) => p === '..' || p === '.' || (!p && i !== parts.length - 1)))
            fail('Unsicherer Archivpfad.');
        if (parts.some(p => p && (/[<>"|?*]/.test(p) || /[ .]$/.test(p) || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(p))))
            fail('Nicht portabler Archivpfad.');
        return path;
    }
    function uniqueNames(names) {
        const used = new Set();
        return names.map(n => {
            const safe = safeName(n), m = /^(.*?)(\.[^.]*)?$/.exec(safe);
            let v = safe, i = 2;
            while (used.has(v.toLocaleLowerCase('en-US')))
                v = `${m[1]}_${i++}${m[2] || ''}`;
            used.add(v.toLocaleLowerCase('en-US'));
            return v;
        });
    }
    function assignSlots(frames, s, preserve = true) {
        const sorted = [...frames].sort((a, b) => (a.index ?? Infinity) - (b.index ?? Infinity) || a.name.localeCompare(b.name, 'de', { numeric: true }));
        const base = Math.min(...sorted.map(f => f.index ?? Infinity)), used = new Set();
        return sorted.map((f, i) => {
            const slot = preserve && Number.isFinite(base) && f.index !== null ? f.index - base : i;
            if (slot >= s.a * s.b)
                fail(`Nummernbereich passt nicht in ${s.a} × ${s.b} Rasterplätze.`);
            if (used.has(slot))
                fail(`Doppelte Bildnummer in ${f.group}.`);
            used.add(slot);
            return { ...f, slot };
        });
    }
    function autoScene(frames, preserve = true) {
        let span = frames.length;
        const indices = frames.filter(f => f.index !== null).map(f => f.index);
        if (preserve && indices.length === frames.length)
            span = Math.max(...indices) - Math.min(...indices) + 1;
        if (span > LIMITS.frames)
            fail(`Nummernbereich mit ${span} Plätzen ist zu groß. Serien getrennt importieren.`);
        const a = Math.max(1, Math.ceil(Math.sqrt(span))), b = Math.max(1, Math.ceil(span / a));
        const group = frames[0]?.group || '';
        return scene({
            ...DEFAULT_SCENE, a, b, category: /^body_/i.test(group) ? 'unit' : /^tree_/i.test(group) ? 'vegetation' : /^(tile|anim)_/i.test(group) ? 'building' : 'other'
        });
    }
    /** Inverse isometric projection; top extension is restricted to the back perimeter. */
    function ownerAt(x, y, s, anchorX, anchorY, extend = true) {
        let u = -(y - (anchorY - s.height / 2)) / s.height - (x - anchorX) / s.width;
        let v = -(y - (anchorY - s.height / 2)) / s.height + (x - anchorX) / s.width;
        if (extend) {
            const slide = Math.max(0, u - (s.a - .5 - 1e-8), v - (s.b - .5 - 1e-8));
            u -= slide;
            v -= slide;
        }
        const ui = Math.floor(u + .5), vi = Math.floor(v + .5);
        if (ui < 0 || ui >= s.a || vi < 0 || vi >= s.b)
            return -1;
        return ui * s.b + vi;
    }
    function partition(src, raw, anchorX, anchorY, extend = true) {
        const s = scene(raw);
        integer(anchorX, 'Schnittanker X');
        integer(anchorY, 'Schnittanker Y');
        const ps = positions(s), lookup = new Int32Array(s.a * s.b);
        for (const p of ps)
            lookup[p.u * s.b + p.v] = p.slot;
        const map = new Int32Array(src.width * src.height);
        for (let y = 0; y < src.height; y++)
            for (let x = 0; x < src.width; x++) {
                const key = ownerAt(x + .5, y + .5, s, anchorX, anchorY, extend);
                map[y * src.width + x] = key < 0 ? -1 : lookup[key];
            }
        return map;
    }
    function ownershipImage(map, width, height) {
        const dst = image(width, height);
        if (map.length !== width * height)
            fail('Schnittmaske hat eine falsche Größe.');
        for (let i = 0; i < map.length; i++) {
            const v = map[i] + 1;
            dst.data[i * 4] = v & 255;
            dst.data[i * 4 + 1] = (v >>> 8) & 255;
            dst.data[i * 4 + 2] = (v >>> 16) & 255;
            dst.data[i * 4 + 3] = 255;
        }
        return dst;
    }
    function ownershipMap(src, capacity) {
        const map = new Int32Array(src.width * src.height);
        for (let i = 0; i < map.length; i++) {
            const v = src.data[i * 4] + src.data[i * 4 + 1] * 256 + src.data[i * 4 + 2] * 65536 - 1;
            if (v >= capacity)
                fail('Schnittmaske enthält unbekannte Rasterplätze.');
            map[i] = v;
        }
        return map;
    }
    function paintMap(map, width, height, x, y, radius, slot) {
        integer(radius, 'Pinselradius', 1, 128);
        for (let yy = Math.max(0, Math.floor(y - radius)); yy < Math.min(height, Math.ceil(y + radius + 1)); yy++)
            for (let xx = Math.max(0, Math.floor(x - radius)); xx < Math.min(width, Math.ceil(x + radius + 1)); xx++)
                if ((xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2)
                    map[yy * width + xx] = slot;
    }
    function splitAnalysis(src, map, raw, anchorX, anchorY, mask = null) {
        const s = scene(raw), ps = positions(s);
        if (map.length !== src.width * src.height)
            fail('Schnittmaske passt nicht zum Bild.');
        if (mask && (mask.width !== src.width || mask.height !== src.height))
            fail('Maske und Schnittbild haben unterschiedliche Größen.');
        let unassigned = 0, visible = 0, overwide = 0;
        const bounds = ps.map(p => ({ slot: p.slot, left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity, pixels: 0 }));
        for (let y = 0; y < src.height; y++)
            for (let x = 0; x < src.width; x++) {
                const i = y * src.width + x;
                const meaningful = src.data[i * 4 + 3] || (mask && (mask.data[i * 4] || mask.data[i * 4 + 1] || mask.data[i * 4 + 2] || mask.data[i * 4 + 3]));
                if (!meaningful)
                    continue;
                visible++;
                const slot = map[i];
                if (slot < 0) {
                    unassigned++;
                    continue;
                }
                if (slot >= ps.length)
                    fail('Unbekannter Rasterplatz in Schnittmaske.');
                const b = bounds[slot];
                b.left = Math.min(b.left, x);
                b.right = Math.max(b.right, x + 1);
                b.top = Math.min(b.top, y);
                b.bottom = Math.max(b.bottom, y + 1);
                b.pixels++;
            }
        const rects = bounds.map((b, i) => {
            const p = ps[i], left = anchorX + p.x - s.width / 2, base = anchorY + p.bottom;
            if (b.pixels && (b.left < left || b.right > left + s.width))
                overwide++;
            const top = Math.min(base - s.height, b.pixels ? b.top : base - s.height), bottom = Math.max(base, b.pixels ? b.bottom : base);
            return { ...b, x: left, y: top, width: s.width, height: bottom - top, base, dy: bottom - base };
        });
        const totalPixels = rects.reduce((n, r) => n + r.width * r.height, 0);
        if (totalPixels > LIMITS.totalPixels)
            fail('Schnittergebnis überschreitet das Bildbudget.');
        rects.forEach(r => dimensions(r.width, r.height));
        return { visible, unassigned, overwide, rects, totalPixels, complete: unassigned === 0 && overwide === 0 };
    }
    function split(src, map, raw, anchorX, anchorY, mask = null) {
        const a = splitAnalysis(src, map, raw, anchorX, anchorY, mask);
        if (a.unassigned)
            fail(`${a.unassigned} Bild- oder Maskenpixel sind keinem Tile zugeordnet.`);
        if (a.overwide)
            fail(`${a.overwide} Tiles überschreiten die eingestellte Tilebreite. Schnittmaske korrigieren.`);
        if (mask && (mask.width !== src.width || mask.height !== src.height))
            fail('Maske und Schnittbild haben unterschiedliche Größen.');
        const tiles = a.rects.map(r => ({ ...r, image: image(r.width, r.height), mask: mask ? image(r.width, r.height) : null }));
        for (let y = 0; y < src.height; y++)
            for (let x = 0; x < src.width; x++) {
                const i = y * src.width + x, slot = map[i];
                if (slot < 0)
                    continue;
                const t = tiles[slot], xx = x - t.x, yy = y - t.y;
                if (xx < 0 || yy < 0 || xx >= t.width || yy >= t.height)
                    continue;
                const d = (yy * t.width + xx) * 4;
                t.image.data.set(src.data.subarray(i * 4, i * 4 + 4), d);
                if (mask)
                    t.mask.data.set(mask.data.subarray(i * 4, i * 4 + 4), d);
            }
        return { ...a, tiles };
    }
    function pack(items, options = {}) {
        if (!items.length)
            fail('Keine Bilder für den Atlas.');
        if (items.length > LIMITS.frames)
            fail('Zu viele Atlasbilder.');
        const padding = integer(options.padding ?? 2, 'Atlasabstand', 0, 32), extrude = integer(options.extrude ?? 1, 'Randwiederholung', 0, 32);
        if (extrude > padding)
            fail('Randwiederholung darf den Atlasabstand nicht überschreiten.');
        const max = integer(options.maxSide ?? 8192, 'Maximale Atlasgröße', 64, 8192), align = integer(options.align ?? 4, 'Atlasausrichtung', 1, 256);
        const sorted = items.map((t, i) => {
            dimensions(t.width, t.height);
            return { ...t, _i: i };
        }).sort((a, b) => b.height - a.height || b.width - a.width || String(a.name || a.id).localeCompare(String(b.name || b.id)));
        const minWidth = Math.max(...items.map(t => t.width + 2 * padding));
        const widths = [];
        if (options.width)
            widths.push(integer(options.width, 'Atlasbreite', minWidth, max));
        else {
            for (let w = 64; w <= max; w *= 2)
                if (w >= minWidth)
                    widths.push(w);
        }
        let best = null;
        for (const width of widths) {
            let rows = [], placed = [], usedW = 0, usedH = 0, failed = false;
            for (const t of sorted) {
                const w = t.width + 2 * padding, h = t.height + 2 * padding;
                let row = rows.filter(r => r.h >= h && r.x + w <= width).sort((a, b) => (a.h - h) - (b.h - h) || a.y - b.y)[0];
                if (!row) {
                    row = { x: 0, y: usedH, h };
                    rows.push(row);
                    usedH += h;
                }
                if (usedH > max) {
                    failed = true;
                    break;
                }
                placed.push({ ...t, x: row.x + padding, y: row.y + padding });
                row.x += w;
                usedW = Math.max(usedW, row.x);
            }
            if (failed)
                continue;
            const w = options.width ? width : Math.ceil(usedW / align) * align, h = Math.ceil(usedH / align) * align;
            if (w > max || h > max || w * h > LIMITS.pixels)
                continue;
            if (!best || w * h < best.width * best.height || (w * h === best.width * best.height && Math.max(w, h) < Math.max(best.width, best.height)))
                best = { width: w, height: h, placed: placed.sort((a, b) => a._i - b._i), padding, extrude };
        }
        if (!best)
            fail('Bilder passen nicht in einen Atlas innerhalb der Größenbegrenzung. Gruppe aufteilen oder Bilder verkleinern.');
        return best;
    }
    function atlasImage(packed, getImage, mask = false) {
        const dst = image(packed.width, packed.height);
        for (const p of packed.placed) {
            const id = mask ? p.maskId : p.imageId;
            if (!id)
                continue;
            const src = getImage(id);
            blit(dst, src, p.x, p.y);
            for (let yy = -packed.extrude; yy < src.height + packed.extrude; yy++)
                for (let xx = -packed.extrude; xx < src.width + packed.extrude; xx++) {
                    if (xx >= 0 && xx < src.width && yy >= 0 && yy < src.height)
                        continue;
                    const sx = Math.max(0, Math.min(src.width - 1, xx)), sy = Math.max(0, Math.min(src.height - 1, yy));
                    dst.data.set(src.data.subarray((sy * src.width + sx) * 4, (sy * src.width + sx) * 4 + 4), ((p.y + yy) * dst.width + p.x + xx) * 4);
                }
        }
        return dst;
    }
    function atlasDefinition(packed, ppu, material = 'Auto') {
        number(ppu, 'Pixels per Unit', .001, 65536);
        if (!MATERIALS.includes(material))
            fail('Unbekanntes Material.');
        return {
            pixelsPerUnit: ppu, material, frames: packed.placed.map(p => ({
                name: targetName(p.targetName || p.name).name,
                rect: { x: p.x, y: packed.height - p.y - p.height, w: p.width, h: p.height }, pivot: pivot(p.pivot)
            }))
        };
    }
    /** Metadata is separate from image extraction; Unity raw meshes are never treated as flat rectangles. */
    function parseMetadata(raw, options = {}) {
        const rows = [];
        function add(obj, name = null, type = 'simple', root = {}) {
            if (!obj || typeof obj !== 'object')
                fail('Ungültiger Metadateneintrag.');
            const isRaw = typeof obj.m_Name === 'string';
            const n = String(isRaw ? obj.m_Name : (obj.name || obj.filename || name || ''));
            if (!n || n.length > 240)
                fail('Sprite-Name fehlt in Metadaten.');
            const pp = obj.m_Pivot || obj.pivot || obj.anchor;
            let p = pp ? pivot({ x: pp.m_X ?? pp.x, y: pp.m_Y ?? pp.y }) : null;
            if (type === 'texturepacker' && p) {
                const origin = options.pivotOrigin || root.pivotOrigin;
                if (!['top-left', 'bottom-left'].includes(origin))
                    fail('TexturePacker-Pivot: Ursprung im Importdialog ausdrücklich wählen (oben links / unten links).');
                if (origin === 'top-left')
                    p = { x: p.x, y: 1 - p.y };
            }
            const r = obj.m_Rect || obj.rect || obj.frame;
            let rect = null;
            if (r)
                rect = {
                    x: number(r.m_X ?? r.x, 'Rechteck X', 0, LIMITS.side), y: number(r.m_Y ?? r.y, 'Rechteck Y', 0, LIMITS.side), w: number(r.m_Width ?? r.w ?? r.width, 'Rechteckbreite', .001, LIMITS.side), h: number(r.m_Height ?? r.h ?? r.height, 'Rechteckhöhe', .001, LIMITS.side)
                };
            const ppu = obj.m_PixelsToUnits ?? obj.pixelsPerUnit ?? root.pixelsPerUnit;
            rows.push({
                name: parseName(n).canonical, pivot: p, ppu: ppu === undefined ? null : number(ppu, 'Pixels per Unit', .001, 65536), rect,
                origin: type === 'texturepacker' ? 'top-left' : 'bottom-left', unsafePacking: !!(obj.rotated || obj.trimmed || obj.m_RD || obj.m_RenderDataKey), raw: isRaw, material: root.material || null
            });
        }
        if (Array.isArray(raw))
            raw.forEach(r => {
                if (r.frames)
                    rows.push(...parseMetadata(r, options));
                else
                    add(r);
            });
        else if (raw?.m_Name)
            add(raw);
        else if (raw?.frames) {
            if (Array.isArray(raw.frames))
                raw.frames.forEach(r => add(r, null, r.frame && !r.rect ? 'texturepacker' : 'simple', raw));
            else
                Object.entries(raw.frames).forEach(([n, r]) => add(r, n, 'texturepacker', raw));
        }
        else
            fail('JSON enthält keine unterstützten Sprite-Metadaten.');
        if (rows.length > LIMITS.frames)
            fail('Zu viele Metadateneinträge.');
        const seen = new Set();
        for (const r of rows) {
            const key = r.name.toLowerCase();
            if (seen.has(key))
                fail(`Doppelte Metadaten: ${r.name}`);
            seen.add(key);
        }
        return rows;
    }
    function atlasCropRect(row, atlas, override = 'auto') {
        if (!row.rect)
            fail('Atlas-Rechteck fehlt.');
        if (row.unsafePacking)
            fail('Rotierte, beschnittene oder mesh-gepackte Rohdaten: zuerst einzelne PNGs mit dem Sprite Previewer exportieren.');
        const r = row.rect;
        for (const k of ['x', 'y', 'w', 'h'])
            if (!Number.isInteger(r[k]))
                fail('Nicht ganzzahliges Atlas-Rechteck. Einzel-PNGs statt Rohatlas importieren.');
        const origin = override === 'auto' ? row.origin : override;
        if (!['top-left', 'bottom-left'].includes(origin))
            fail('Unbekannter Atlas-Ursprung.');
        const out = { x: r.x, y: origin === 'bottom-left' ? atlas.height - r.y - r.h : r.y, width: r.w, height: r.h };
        if (out.x < 0 || out.y < 0 || out.x + out.width > atlas.width || out.y + out.height > atlas.height)
            fail(`Atlas-Rechteck außerhalb der Textur: ${row.name}`);
        return out;
    }
    function csvString(rows) {
        const cell = v => {
            let s = String(v ?? '');
            if (typeof v === 'string' && /^[=+@\t\r-]/.test(s))
                s = "'" + s;
            return /[",;\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
        };
        return '\uFEFF' + rows.map(r => r.map(cell).join(',')).join('\r\n') + '\r\n';
    }
    function parseCSV(text) {
        if (typeof text !== 'string' || text.length > 8 * 1024 * 1024)
            fail('CSV zu groß.');
        if (text.includes('\0'))
            fail('Ungültiges Zeichen in CSV.');
        text = text.replace(/^\uFEFF/, '');
        const head = text.split(/\r?\n/, 1)[0], sep = (head.match(/;/g) || []).length > (head.match(/,/g) || []).length ? ';' : ',';
        let rows = [], row = [], s = '', quote = false, after = false;
        for (let i = 0; i < text.length; i++) {
            const c = text[i];
            if (quote) {
                if (c === '"') {
                    if (text[i + 1] === '"') {
                        s += '"';
                        i++;
                    }
                    else {
                        quote = false;
                        after = true;
                    }
                }
                else
                    s += c;
                continue;
            }
            if (c === '"') {
                if (s || after)
                    fail('Ungültige CSV-Anführungszeichen.');
                quote = true;
                continue;
            }
            if (c === sep) {
                row.push(s);
                s = '';
                after = false;
                continue;
            }
            if (c === '\r' || c === '\n') {
                if (c === '\r' && text[i + 1] === '\n')
                    i++;
                row.push(s);
                if (row.some(x => x !== ''))
                    rows.push(row);
                row = [];
                s = '';
                after = false;
                continue;
            }
            if (after)
                fail('Zeichen nach geschlossenem CSV-Feld.');
            if (c === '\0')
                fail('Ungültiges Zeichen in CSV.');
            s += c;
        }
        if (quote)
            fail('Nicht geschlossenes CSV-Feld.');
        if (s || row.length) {
            row.push(s);
            rows.push(row);
        }
        if (rows.length > LIMITS.frames + 1)
            fail('Zu viele CSV-Zeilen.');
        return rows;
    }
    function json(text) {
        if (typeof text !== 'string' || text.length > LIMITS.importBytes * 1.4)
            fail('JSON zu groß.');
        return JSON.parse(text, (key, value) => {
            if (['__proto__', 'prototype', 'constructor'].includes(key))
                fail('Unzulässiger JSON-Schlüssel.');
            return value;
        });
    }
    return Object.freeze({
        VERSION, LIMITS, DEFAULT_SCENE, MATERIALS, fail, number, integer, dimensions, image, scene, positions, footprint, pivot, pixelAnchor, layout, blit, compose, crop, alphaBounds, trimRect, flip, resize, channel, adjust, difference, parseName, targetName, safeName, safePath, uniqueNames, assignSlots, autoScene, ownerAt, partition, ownershipImage, ownershipMap, paintMap, splitAnalysis, split, pack, atlasImage, atlasDefinition, parseMetadata, atlasCropRect, csvString, parseCSV, json
    });
});
