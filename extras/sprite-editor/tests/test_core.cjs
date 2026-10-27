'use strict';
const { test } = require('node:test');
const A = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const C = require('../src/core.js'), K = require('../src/codec.js'), I = require('../src/io.js');
const P = path.join(__dirname, 'fixtures'), bytes = n => new Uint8Array(fs.readFileSync(path.join(P, n))), eq = (a, b) => A.deepEqual(Array.from(a), Array.from(b));
const fixture = async () => {
    const s = I.blank(), st = new I.AssetStore(), g = { id: 'g', name: 'body_test', source: 'custom', settings: C.scene({ a: 2, b: 2, category: 'unit' }) };
    s.scenes.push(g);
    s.project.author = 'Test';
    for (let i = 0; i < 3; i++) {
        const key = await st.decode(bytes('c6_d8_i0.png')), f = I.makeFrame(`body_test-${i}.png`, key, g.id, st);
        f.slot = i;
        f.targetName = `body_target-${i}`;
        f.targetConfirmed = true;
        s.frames.push(f);
    }
    return { s: I.validate(s, st), st };
};
function chunkReplace(png, kind, data) {
    let at = 8;
    const parts = [png.slice(0, 8)];
    while (at < png.length) {
        const n = new DataView(png.buffer, png.byteOffset + at, 4).getUint32(0), t = K.decodeText(png.slice(at + 4, at + 8));
        parts.push(t === kind ? K.chunk(t, data) : png.slice(at, at + n + 12));
        at += n + 12;
    }
    return K.concat(parts);
}
for (const f of JSON.parse(fs.readFileSync(path.join(P, 'index.json'), 'utf8'))) {
    test(`PNG independent reference: ${f.name}`, async () => {
        const d = await K.decodePNG(bytes(f.name + '.png'));
        A.equal(d.width, f.width);
        A.equal(d.height, f.height);
        eq(d.data, bytes(f.name + '.rgba'));
        const out = await K.decodePNG(await K.encodePNG(d));
        eq(out.data, d.data);
        eq(d.bytes, bytes(f.name + '.png'));
    });
}
test('PNG preserves low alpha and hidden RGB byte-for-byte', async () => {
    const a = C.image(256, 1);
    for (let i = 0; i < 256; i++)
        a.data.set([i, (i + 113) % 256, 199, i], 4 * i);
    const b = await K.decodePNG(await K.encodePNG(a));
    eq(a.data, b.data);
});
test('PNG accepts correctly split consecutive IDAT', async () => {
    const p = bytes('c6_d8_i0.png');
    let at = 33;
    const length = new DataView(p.buffer).getUint32(at);
    const data = p.slice(at + 8, at + 8 + length);
    const split = K.concat([p.slice(0, at), K.chunk('IDAT', data.slice(0, 3)), K.chunk('IDAT', data.slice(3)), p.slice(at + 12 + length)]);
    eq((await K.decodePNG(split)).data, bytes('c6_d8_i0.rgba'));
});
test('PNG rejects CRC damage, truncation, trailing bytes, 16-bit and APNG', async () => {
    for (const b of [bytes('broken/broken-0.png'), bytes('c6_d8_i0.png').slice(0, -5), K.concat([bytes('c6_d8_i0.png'), new Uint8Array([1])]), bytes('unsupported16.png'), bytes('apng.png')])
        await A.rejects(K.decodePNG(b));
});
test('PNG rejects huge dimensions before allocating', async () => {
    const p = bytes('c6_d8_i0.png'), h = p.slice(16, 29);
    new DataView(h.buffer).setUint32(0, 0xffffffff);
    await A.rejects(K.decodePNG(chunkReplace(p, 'IHDR', h)));
});
test('PNG rejects unknown critical chunk and broken zlib', async () => {
    const p = bytes('c6_d8_i0.png');
    await A.rejects(K.decodePNG(K.concat([p.slice(0, 33), K.chunk('ABCD', new Uint8Array()), p.slice(33)])));
    await A.rejects(K.decodePNG(chunkReplace(p, 'IDAT', new Uint8Array([1, 2, 3]))));
});
test('PNG warns about profiles without changing channels', async () => {
    const p = bytes('c6_d8_i0.png');
    const withProfile = K.concat([p.slice(0, 33), K.chunk('gAMA', new Uint8Array([0, 1, 0, 0])), p.slice(33)]);
    const d = await K.decodePNG(withProfile);
    A.equal(d.warnings.length, 1);
    eq(d.data, bytes('c6_d8_i0.rgba'));
});
test('Cancellation is propagated by codecs', async () => {
    const c = new AbortController();
    c.abort();
    for (const f of [() => K.decodePNG(bytes('c6_d8_i0.png'), { signal: c.signal }), () => K.encodePNG(C.image(1, 1), { signal: c.signal }), () => K.unzip(bytes('store.zip'), { signal: c.signal })])
        await A.rejects(f, { name: 'AbortError' });
});
test('SHA256 native and fallback match independent crypto, including block boundaries', async () => {
    for (const n of [0, 1, 3, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 255, 256, 1024, 100000]) {
        const b = new Uint8Array(n);
        for (let i = 0; i < n; i++)
            b[i] = (i * 19 + 13) % 256;
        const expected = crypto.createHash('sha256').update(b).digest('hex');
        A.equal(await K.sha256(b), expected);
        A.equal(K.sha256Fallback(b), expected);
    }
});
test('CRC32 standard vector', () => A.equal(K.crc32(K.encodeText('123456789')), 0xcbf43926));
test('Base64 round trip and malformed data', () => {
    for (const n of [0, 1, 2, 3, 40000]) {
        const b = new Uint8Array(n).fill(137);
        eq(K.base64ToBytes(K.bytesToBase64(b)), b);
    }
    for (const b of ['#', 'AAA', 'a===', 'AAAA\n'])
        A.throws(() => K.base64ToBytes(b));
});
for (const file of ['store.zip', 'deflate.zip'])
    test(`ZIP reads independent ${file}`, async () => {
        const e = await K.unzip(bytes(file));
        A.equal(e.length, 2);
        A.equal(e[1].name, 'Größe/é.txt');
        A.equal(K.decodeText(e[1].data), 'Straße\n');
        await K.decodePNG(e[0].data);
    });
test('ZIP supports standard data descriptor and rejects tampering', async () => {
    const b = bytes('descriptor.zip');
    A.equal(K.decodeText((await K.unzip(b))[0].data), 'with descriptor');
    const bad = new Uint8Array(b);
    const dv = new DataView(b.buffer);
    let i = 0;
    while (i < b.length - 4 && dv.getUint32(i, true) !== 0x08074b50)
        i++;
    A.ok(i < b.length - 4);
    bad[i + 4] ^= 1;
    await A.rejects(K.unzip(bad), /Datenbeschreibung/);
});
test('ZIP self-roundtrip UTF8 names, zero-length entries and deterministic output', async () => {
    const e = [{ name: 'a/', data: '' }, { name: 'a/é.png', data: bytes('c6_d8_i0.png') }, { name: 'zero.txt', data: '' }];
    const b = K.zip(e);
    eq(b, K.zip(e));
    const read = await K.unzip(b);
    A.equal(read.length, 2);
    eq(read[0].data, e[1].data);
});
for (const file of ['traversal.zip', 'symlink.zip', 'case_collision.zip', 'unicode_collision.zip'])
    test(`ZIP rejects ${file}`, async () => A.rejects(K.unzip(bytes(file))));
test('ZIP rejects corruption, encryption, missing directory and excess output', async () => {
    const b = K.zip([{ name: 'a.txt', data: 'hello' }]), bad = new Uint8Array(b);
    bad[35] ^= 1;
    await A.rejects(K.unzip(bad));
    await A.rejects(K.unzip(b.slice(0, -1)));
    const enc = new Uint8Array(b);
    new DataView(enc.buffer).setUint16(6, 0x801, true);
    let cd = b.length - 22 - 51;
    new DataView(enc.buffer).setUint16(cd + 8, 0x801, true);
    await A.rejects(K.unzip(enc));
    await A.rejects(K.decompress(await K.compress(new Uint8Array(100)), 'deflate', 10));
});
test('Archive path validation covers Windows, traversal, separators, names', () => {
    for (const p of ['../a', 'x/../a', '/a', 'C:a', 'a\\b', 'a//b', './b', 'a\0b', 'con.txt', 'a/nul', 'a./b', 'a /b', 'a?.png'])
        A.throws(() => C.safePath(p), p);
    for (const p of ['assets/a.png', 'a/', 'Größe/é.png'])
        A.equal(C.safePath(p), p);
    A.throws(() => K.zip([{ name: 'a', data: '' }, { name: 'A', data: '' }]));
});
test('Numerical and scene constraints reject ambiguous or excessive inputs', () => {
    for (const n of ['', null, true, {}, NaN, Infinity, '2e999'])
        A.throws(() => C.number(n, 'N'));
    A.throws(() => C.integer(1.5, 'N'));
    A.throws(() => C.scene({ width: 63 }));
    A.throws(() => C.scene({ height: 31 }));
    A.throws(() => C.scene({ a: 0 }));
    A.throws(() => C.dimensions(8192, 8192));
    A.equal(C.integer('64', 'N'), 64);
});
test('Exact 5x5 ODT numbering and geometry', () => {
    const p = C.positions({ a: 5, b: 5 }), rows = [];
    for (const v of p)
        (rows[v.diagonal] ??= []).push(v.slot + 1);
    A.deepEqual(rows, [[1], [2, 3], [4, 5, 6], [7, 8, 9, 10], [11, 12, 13, 14, 15], [16, 17, 18, 19], [20, 21, 22], [23, 24], [25]]);
    A.deepEqual(p[0], { slot: 0, u: 0, v: 0, diagonal: 0, x: 0, bottom: 0 });
    A.deepEqual(p[24], { slot: 24, u: 4, v: 4, diagonal: 8, x: 0, bottom: -128 });
    for (const row of rows) {
        const ps = row.map(i => p[i - 1]);
        for (let i = 1; i < ps.length; i++)
            A.ok(ps[i].x > ps[i - 1].x);
    }
});
test('Rectangular grids enumerate each cell exactly once', () => {
    for (let a = 1; a <= 9; a++)
        for (let b = 1; b <= 9; b++) {
            const p = C.positions({ a, b });
            A.equal(p.length, a * b);
            A.equal(new Set(p.map(p => p.u + ',' + p.v)).size, a * b);
        }
});
test('Names sort numerically and preserve gaps or compact explicitly', () => {
    const ff = ['tile_ruins 551.png', 'tile_ruins 549.png'].map(name => ({ name, ...C.parseName(name) }));
    A.deepEqual(C.assignSlots(ff, C.scene(), true).map(f => f.slot), [0, 2]);
    A.deepEqual(C.assignSlots(ff, C.scene(), false).map(f => f.slot), [0, 1]);
    A.throws(() => C.assignSlots([...ff, ff[0]], C.scene()));
    A.deepEqual(C.parseName('tile_ruins-549_m.png'), { stem: 'tile_ruins-549_m', base: 'tile_ruins-549', mask: true, group: 'tile_ruins', index: 549, canonical: 'tile_ruins-549' });
});
test('Layout includes tall and offset sprites, separates paint order from slot order', async () => {
    const { s, st } = await fixture(), g = s.scenes[0];
    s.frames[0].dy = -70;
    s.frames[1].dx = 30;
    const l = C.layout(s.frames, g.settings, k => st.get(k));
    A.ok(l.height >= 83);
    for (const p of l.placed) {
        A.ok(p.x >= 0 && p.y >= 0 && p.x + p.width <= l.width && p.y + p.height <= l.height);
    }
    A.deepEqual(l.paint.map(p => p.slot), [0, 1, 2]);
    A.deepEqual(C.layout(s.frames, { ...g.settings, order: 'descending' }, k => st.get(k)).paint.map(p => p.slot), [2, 1, 0]);
    A.throws(() => C.layout([s.frames[0], s.frames[0]], g.settings, k => st.get(k)));
});
test('Blit clipping all sides and nonintersection', () => {
    const src = C.image(2, 2, new Uint8Array(16).fill(55)), d = C.image(2, 2);
    C.blit(d, src, -1, -1);
    eq(d.data.slice(0, 4), [55, 55, 55, 55]);
    const before = new Uint8Array(d.data);
    for (const [x, y] of [[100, 0], [-100, 0], [0, 100], [0, -100]])
        C.blit(d, src, x, y);
    eq(before, d.data);
});
test('Source-over matches independent float formula at alpha boundaries', () => {
    for (const sa of [0, 1, 7, 127, 128, 254, 255])
        for (const da of [0, 1, 127, 255]) {
            const src = C.image(1, 1, new Uint8Array([13, 227, 89, sa])), dst = C.image(1, 1, new Uint8Array([233, 37, 157, da])), alpha = sa / 255 + da / 255 * (1 - sa / 255);
            C.blit(dst, src, 0, 0, true);
            if (sa === 0) {
                eq(dst.data, [233, 37, 157, da]);
                continue;
            }
            const expected = [0, 1, 2].map(c => Math.round((src.data[c] * (sa / 255) + [233, 37, 157][c] * (da / 255) * (1 - sa / 255)) / alpha));
            expected.push(Math.round(alpha * 255));
            eq(dst.data, expected);
        }
});
test('Crop rejects out-of-bounds; flip is involutive; resize is nearest-neighbor', () => {
    const a = C.image(2, 2, new Uint8Array(Array.from({ length: 16 }, (_, i) => i)));
    A.throws(() => C.crop(a, -1, 0, 1, 1));
    A.throws(() => C.crop(a, 0, 0, 3, 1));
    eq(C.flip(C.flip(a)).data, a.data);
    eq(C.flip(C.flip(a, false), false).data, a.data);
    const b = C.resize(a, 4, 4);
    eq(b.data.slice(0, 8), [0, 1, 2, 3, 0, 1, 2, 3]);
});
test('Trim keeps world anchor and transparent margins needed for valid pivots', () => {
    const a = C.image(10, 10);
    a.data.set([100, 200, 5, 255], (3 * 10 + 4) * 4);
    const r = C.trimRect(a, { x: .5, y: 0 });
    A.equal(r.x, 4);
    A.equal(r.y, 3);
    A.equal(r.height, 7);
    A.equal(r.pivot.y, 0);
    A.equal(r.x + r.width * r.pivot.x, 5);
    A.equal(r.y + r.height * (1 - r.pivot.y), 10);
});
test('Alpha diagnostics, explicit adjustments and channel views', () => {
    const a = C.image(2, 1, new Uint8Array([77, 88, 99, 0, 20, 40, 60, 127]));
    const st = C.alphaBounds(a);
    A.equal(st.hiddenRGB, 1);
    A.equal(st.partial, 1);
    eq(C.adjust(a).data, a.data);
    eq(C.adjust(a, { alphaMode: 'clearHidden' }).data.slice(0, 4), [0, 0, 0, 0]);
    eq(C.channel(a, 'a').data, [0, 0, 0, 255, 127, 127, 127, 255]);
    A.equal(C.difference(a, a).changed, 0);
    A.throws(() => C.adjust(a, { alphaMode: 'guess' }));
});
test('Split property: every assigned source pixel reassembles exactly across rectangle grids', () => {
    for (const [a, b] of [[1, 1], [2, 3], [5, 5], [8, 3]]) {
        const settings = C.scene({ a, b, width: 16, height: 8, padding: 0 }), src = C.image((a + b) * 8 + 4, (a + b) * 4 + 50), ax = a * 8 + 2, ay = src.height - 2, map = C.partition(src, settings, ax, ay, true);
        for (let i = 0; i < map.length; i++)
            if (map[i] >= 0)
                src.data.set([i % 251, (i * 13) % 253, 91, i % 254 + 1], i * 4);
        const result = C.split(src, map, settings, ax, ay), out = C.image(src.width, src.height);
        for (const t of result.tiles)
            C.blit(out, t.image, t.x, t.y, true);
        eq(out.data, src.data);
        A.equal(result.unassigned, 0);
    }
});
test('Split extends rear tiles but not the foreground beyond its bounds', () => {
    const src = C.image(100, 100), s = C.scene({ a: 1, b: 1, width: 64, height: 32 }), a = C.partition(src, s, 50, 90, true), b = C.partition(src, s, 50, 90, false);
    A.equal(a[10 * 100 + 50], 0);
    A.equal(b[10 * 100 + 50], -1);
    A.equal(a[95 * 100 + 50], -1);
});
test('Split blocks unassigned alpha and meaningful mask channels, even alpha zero', () => {
    const src = C.image(100, 100), mask = C.image(100, 100), s = C.scene({ a: 1, b: 1 }), map = C.partition(src, s, 50, 90, true);
    src.data.set([1, 2, 3, 1], 0);
    A.throws(() => C.split(src, map, s, 50, 90), /keinem/);
    src.data.fill(0);
    mask.data[0] = 3;
    A.throws(() => C.split(src, map, s, 50, 90, mask), /keinem/);
});
test('Ownership PNG is lossless; brush respects slot assignment and undo-copy', () => {
    const m = new Int32Array([-1, 0, 1, 255, 256, 4095]), img = C.ownershipImage(m, 3, 2);
    eq(C.ownershipMap(img, 4096), m);
    A.throws(() => C.ownershipMap(img, 2));
    const p = new Int32Array(100).fill(-1);
    C.paintMap(p, 10, 10, 5, 5, 2, 3);
    A.equal(p[55], 3);
    A.equal(p[0], -1);
});
test('Split rejects an owner wider than the fixed tile width', () => {
    const a = C.image(100, 100);
    a.data[3] = 255;
    const m = new Int32Array(10000).fill(-1);
    m[0] = 0;
    A.throws(() => C.split(a, m, C.scene({ a: 1, b: 1 }), 50, 90), /Tilebreite/);
});
test('Atlas deterministic, nonoverlapping, padded and aligned', () => {
    const items = Array.from({ length: 120 }, (_, i) => ({ id: 'f' + i, name: 'body-' + i, width: 3 + i % 27, height: 4 + i % 53 })), p = C.pack(items, { padding: 2, extrude: 1, maxSide: 512 });
    A.equal(p.width % 4, 0);
    A.equal(p.height % 4, 0);
    A.deepEqual(p, C.pack(items, { padding: 2, extrude: 1, maxSide: 512 }));
    for (let i = 0; i < p.placed.length; i++) {
        const a = p.placed[i];
        A.ok(a.x >= 2 && a.y >= 2);
        for (let j = i + 1; j < p.placed.length; j++) {
            const b = p.placed[j];
            A.ok(a.x + a.width + 2 <= b.x - 2 || b.x + b.width + 2 <= a.x - 2 || a.y + a.height + 2 <= b.y - 2 || b.y + b.height + 2 <= a.y - 2);
        }
    }
});
test('Atlas rejects impossible sizes and align-up over maximum', () => {
    A.throws(() => C.pack([{ width: 100, height: 100 }], { maxSide: 64 }));
    A.throws(() => C.pack([{ width: 64, height: 64 }], { padding: 0, extrude: 0, maxSide: 64, align: 100 }));
    A.throws(() => C.pack([{ width: 1, height: 1 }], { padding: 0, extrude: 1 }));
});
test('Atlas preserves RGBA and mask, edge extrusion and bottom-left rects', () => {
    const a = C.image(2, 2, new Uint8Array(Array.from({ length: 16 }, (_, i) => i))), p = C.pack([{ id: 'f', name: 'body_a-0', imageId: 'a', maskId: 'a', width: 2, height: 2, pivot: { x: .25, y: .125 } }], { padding: 2, extrude: 1, maxSide: 64 }), out = C.atlasImage(p, () => a), r = p.placed[0];
    eq(C.crop(out, r.x, r.y, 2, 2).data, a.data);
    eq(out.data.slice(((r.y - 1) * out.width + r.x - 1) * 4, ((r.y - 1) * out.width + r.x - 1) * 4 + 4), a.data.slice(0, 4));
    const d = C.atlasDefinition(p, 64);
    A.equal(d.frames[0].rect.y, p.height - r.y - 2);
    eq(C.atlasImage(p, () => a, true).data, out.data);
});
test('Unity metadata, fractional rectangles and packed mesh fail closed', () => {
    const r = C.parseMetadata({ m_Name: 'body_a-1', m_Rect: { m_X: 1, m_Y: 2, m_Width: 3.9, m_Height: 7.9 }, m_Pivot: { m_X: .1, m_Y: .2 }, m_PixelsToUnits: 64 });
    A.equal(r[0].pivot.x, .1);
    A.throws(() => C.atlasCropRect(r[0], { width: 100, height: 100 }), /ganzzahlig/);
    const packed = C.parseMetadata({ m_Name: 'body_a-1', m_Rect: { x: 0, y: 0, w: 3, h: 4 }, m_RD: {} });
    A.throws(() => C.atlasCropRect(packed[0], { width: 100, height: 100 }), /mesh/);
});
test('TexturePacker origin explicit, top-left rect transformed and unsafe trim blocked', () => {
    const raw = { frames: { 'body_a-1.png': { frame: { x: 2, y: 3, w: 4, h: 5 }, pivot: { x: .25, y: .75 } } } };
    A.throws(() => C.parseMetadata(raw), /Ursprung/);
    const row = C.parseMetadata(raw, { pivotOrigin: 'top-left' })[0];
    A.equal(row.pivot.y, .25);
    A.deepEqual(C.atlasCropRect(row, { width: 100, height: 100 }), { x: 2, y: 3, width: 4, height: 5 });
    raw.frames['body_a-1.png'].rotated = true;
    A.throws(() => C.atlasCropRect(C.parseMetadata(raw, { pivotOrigin: 'top-left' })[0], { width: 100, height: 100 }));
});
test('CSV BOM, quoting, semicolon, multiline and formula defense', () => {
    A.deepEqual(C.parseCSV(C.csvString([['source', 'target'], ['a,b', 'tile_a-1'], ['x\ny', 'z"z']])), [['source', 'target'], ['a,b', 'tile_a-1'], ['x\ny', 'z"z']]);
    A.deepEqual(C.parseCSV('a;b\r\n"x;y";z'), [['a', 'b'], ['x;y', 'z']]);
    A.ok(C.csvString([['=HYPERLINK()', '-1+2']]).includes("'=HYPERLINK()"));
    for (const s of ['a,b\n"unclosed,z', 'a\0b', '"a\0b"'])
        A.throws(() => C.parseCSV(s));
});
test('JSON rejects prototype pollution recursively', () => {
    A.throws(() => C.json('{"a":{"__proto__":{"polluted":true}}}'));
    A.throws(() => C.json('{"constructor":{}}'));
    A.equal({}.polluted, undefined);
});
test('PNG import grouping, masks, preservation and explicit source', async () => {
    const names = fs.readdirSync(path.join(P, 'series'));
    const e = names.map(name => ({ name, data: bytes('series/' + name) }));
    const r = await I.importPNGs(e, I.blank(), new I.AssetStore(), { source: 'shde' });
    A.equal(r.state.frames.length, 3);
    A.equal(r.state.scenes.length, 1);
    A.equal(r.state.scenes[0].source, 'shde');
    A.ok(r.state.frames.every(f => f.maskId));
    A.deepEqual(r.state.frames.map(f => f.slot), [0, 1, 2]);
    A.ok(r.state.frames.every(f => !f.targetConfirmed));
});
test('Failed import leaves existing state and store unchanged', async () => {
    const { s, st } = await fixture(), json = JSON.stringify(s), count = st.items.size;
    await A.rejects(I.importPNGs([{ name: 'new-0.png', data: bytes('c6_d8_i0.png') }, { name: 'bad-1.png', data: bytes('broken/broken-0.png') }], s, st));
    A.equal(JSON.stringify(s), json);
    A.equal(st.items.size, count);
});
test('Orphan masks, duplicate indices and inconsistent mask dimensions are rejected', async () => {
    for (const entries of [[{ name: 'a-1_m.png', data: bytes('c6_d8_i0.png') }], [{ name: 'a-1.png', data: bytes('c6_d8_i0.png') }, { name: 'a 1.png', data: bytes('c6_d8_i0.png') }], [{ name: 'a-1.png', data: bytes('c6_d8_i0.png') }, { name: 'a-1_m.png', data: bytes('adam_1_1.png') }]])
        await A.rejects(I.importPNGs(entries, I.blank(), new I.AssetStore()));
});
test('Metadata import does not fabricate complete status, target normalization', async () => {
    const { s, st } = await fixture();
    const r = I.applyMetadata(s, [{ name: 'body_test-0', pivot: { x: .2, y: .3 }, ppu: 64 }]);
    A.equal(r.state.frames[0].metadataStatus, 'imported');
    A.equal(s.frames[0].metadataStatus, 'assumed');
    r.state.frames[0].targetName = 'body_target-000';
    A.equal(I.validate(r.state, st).frames[0].targetName, 'body_target-0');
});
test('Mapping CSV commits exact names, is transactional, rejects ambiguity', async () => {
    const { s, st } = await fixture();
    const csv = I.mappingCSV(s);
    const r = I.importMapping(s, csv);
    A.equal(r.count, 3);
    A.deepEqual(r.state.frames.map(f => f.targetName), s.frames.map(f => f.targetName));
    A.throws(() => I.importMapping(s, 'source,target\nunknown.png,body_x-1'));
    A.equal(s.frames[0].targetName, 'body_target-0');
    const weird = I.clone(s);
    weird.frames[0].name = '=X.png';
    A.equal(I.importMapping(weird, I.mappingCSV(weird)).state.frames[0].name, '=X.png');
});
test('History undo/redo retains original and edited pixel buffers; invalid commit atomic', async () => {
    const { s, st } = await fixture(), h = new I.History(s, st), n = I.clone(h.state), next = st.fork();
    const orig = n.frames[0].imageId;
    n.frames[0].imageId = next.add(C.flip(st.get(orig)));
    const changed = n.frames[0].imageId;
    h.commit(n, next, 'flip');
    A.ok(h.store.has(orig) && h.store.has(changed));
    h.undo();
    A.equal(h.state.frames[0].imageId, orig);
    h.redo();
    A.equal(h.state.frames[0].imageId, changed);
    const invalid = I.clone(h.state);
    invalid.frames[0].slot = 100;
    const before = h.revision;
    A.throws(() => h.commit(invalid));
    A.equal(h.revision, before);
    h.undo();
    h.clearHistory();
    A.ok(!h.store.has(changed));
    A.ok(h.store.has(orig));
});
test('History caps at 50 snapshots', async () => {
    const { s, st } = await fixture(), h = new I.History(s, st);
    for (let i = 0; i < 60; i++) {
        const n = I.clone(h.state);
        n.project.name = String(i);
        h.commit(n);
    }
    A.equal(h.past.length, 50);
    for (let i = 0; i < 50; i++)
        A.ok(h.undo());
    A.equal(h.undo(), false);
});
test('Project ZIP roundtrip retains original PNG bytes, masks, refs and split map', async () => {
    const { s, st } = await fixture();
    s.frames[0].maskId = s.frames[0].originalMaskId = s.frames[0].imageId;
    const src = C.image(64, 64), key = st.add(src), map = st.add(C.ownershipImage(new Int32Array(4096).fill(-1), 64, 64));
    s.split = {
        imageId: key, mapId: map, maskId: null, settings: C.scene({ a: 1, b: 1 }), anchorX: 32, anchorY: 60, extend: true, group: 'tile_test', start: 0, source: 'custom'
    };
    s.references = [{ name: 'body_target-0', imageId: s.frames[0].imageId, maskId: null, pivot: { x: .2, y: .3 }, ppu: 64, width: 17, height: 13 }];
    const out = await I.readProject(await K.unzip(await I.writeProject(s, st)));
    A.deepEqual(out.state, I.validate(s, st));
    eq(await out.store.bytes(s.frames[0].originalId), bytes('c6_d8_i0.png'));
    A.equal(out.store.items.size, I.assetIds(s).size);
});
test('Project rejects changed asset SHA and missing files', async () => {
    const { s, st } = await fixture(), entries = await K.unzip(await I.writeProject(s, st));
    const altered = entries.map(e => ({ ...e, data: new Uint8Array(e.data) }));
    altered[1].data[0] ^= 1;
    await A.rejects(I.readProject(altered), /SHA/);
    await A.rejects(I.readProject(entries.slice(0, 1)), /fehlt/);
});
test('Legacy v0.1 keeps pixels, placement, original bytes and source uncertainty', async () => {
    const b = bytes('c6_d8_i0.png'), r = await I.legacyProject({
        format: 'shc-sprite-workbench', version: 1, settings: { a: 1, b: 1, width: 64, height: 32, padding: 8, order: 'ascending' }, tiles: [{ filename: 'tile_a-3.png', slot: 0, width: 17, height: 13, offsetX: 3, offsetY: -2, visible: true, pngBase64: K.bytesToBase64(b) }]
    });
    A.equal(r.state.frames[0].dx, 3);
    A.equal(r.state.frames[0].dy, -2);
    A.equal(r.state.scenes[0].source, 'custom');
    eq(await r.store.bytes(r.state.frames[0].originalId), b);
});
test('Preflight blocks unconfirmed targets, duplicate targets, mixed PPU and partial masks', async () => {
    const { s, st } = await fixture();
    s.frames[0].targetConfirmed = false;
    A.ok(I.preflight(s, st).some(i => i.code === 'UNCONFIRMED'));
    s.frames[0].targetConfirmed = true;
    s.frames[1].targetName = s.frames[0].targetName;
    A.ok(I.preflight(s, st).some(i => i.code === 'DUPLICATE_TARGET'));
    s.frames[1].targetName = 'body_target-1';
    s.frames[1].ppu = 128;
    A.ok(I.preflight(s, st).some(i => i.code === 'MIXED_PPU'));
    s.frames[1].ppu = 64;
    s.frames[0].maskId = s.frames[0].imageId;
    A.ok(I.preflight(s, st).some(i => i.code === 'PARTIAL_MASK'));
});
test('Single overrides demand real dimensions; mask materials fail closed', async () => {
    const { s, st } = await fixture();
    s.export.mode = 'sprites';
    A.ok(I.preflight(s, st).some(i => i.code === 'SPRITE_REFERENCE'));
    s.references = s.frames.map(f => ({ name: f.targetName, imageId: null, maskId: null, width: 17, height: 13, pivot: null, ppu: null }));
    A.ok(!I.preflight(s, st).some(i => i.level === 'error'));
    s.references[0].width = 18;
    A.ok(I.preflight(s, st).some(i => i.code === 'SPRITE_SIZE'));
    s.export.material = 'TeamColour';
    A.ok(I.preflight(s, st).some(i => i.code === 'MISSING_MASK'));
});
test('Mod info rejects bad identifiers and missing authors', () => {
    const s = I.blank();
    A.throws(() => I.modInfo(s));
    s.project.author = 'A';
    const info = I.modInfo(s);
    A.equal(info.Manifest, 0);
    A.equal(info.NetworkMode, 0);
    A.equal(info.AssetMode, 'Global');
    A.equal(info.Dependencies[0].GUID, '000shcdese');
    s.project.id = '../x';
    A.throws(() => I.modInfo(s));
});
test('Atlas mod ZIP and SEMOD have correct roots, bottom-left rects, hashes and no in-game claim', async () => {
    const { s, st } = await fixture(), r = await I.exportMod(s, st), e = await K.unzip(r.bytes);
    A.ok(e.some(e => e.name === 'BepInEx/plugins/sprite-port/info.json'));
    const ae = e.find(e => e.name.endsWith('/atlas.json')), ap = e.find(e => e.name.endsWith('/atlas.png')), atlas = await K.decodePNG(ap.data), rows = C.parseMetadata(C.json(K.decodeText(ae.data)));
    for (const row of rows) {
        const f = s.frames.find(f => f.targetName === row.name), rect = C.atlasCropRect(row, atlas);
        eq(C.crop(atlas, rect.x, rect.y, rect.width, rect.height).data, st.get(f.imageId).data);
    }
    A.equal(r.report.inGameTested, false);
    A.equal(r.report.mappings[0].originalSHA256, crypto.createHash('sha256').update(bytes('c6_d8_i0.png')).digest('hex'));
    const packed = await I.exportMod(s, st, { packed: true }), pe = await K.unzip(packed.bytes);
    A.ok(pe.some(e => e.name === 'info.json'));
    A.ok(pe.every(e => !e.name.startsWith('BepInEx')));
});
test('Single mod exports original PNG and raw masks without reencoding', async () => {
    const { s, st } = await fixture();
    s.export.mode = 'sprites';
    s.export.material = 'TeamColour';
    for (const f of s.frames) {
        f.maskId = f.imageId;
        s.references.push({ name: f.targetName, imageId: null, maskId: null, width: 17, height: 13, pivot: null, ppu: null });
    }
    const r = await I.exportMod(s, st), e = await K.unzip(r.bytes);
    eq(e.find(e => e.name.endsWith('body_target-0.png')).data, bytes('c6_d8_i0.png'));
    eq(e.find(e => e.name.endsWith('body_target-0_m.png')).data, bytes('c6_d8_i0.png'));
    A.equal(C.json(K.decodeText(e.find(e => e.name.endsWith('body_target-0.material.json')).data)).material, 'TeamColour');
});
test('Atlas reimport recovers color, mask, pivot and PPU', async () => {
    const { s, st } = await fixture();
    for (const f of s.frames)
        f.maskId = f.imageId;
    const entries = await I.atlasEntries(s.frames, st, s.export), r = await I.importAtlas(await K.unzip(K.zip(entries)), I.blank(), new I.AssetStore(), { source: 'shde' });
    A.equal(r.state.frames.length, 3);
    for (const f of r.state.frames) {
        eq(r.store.get(f.imageId).data, bytes('c6_d8_i0.rgba'));
        eq(r.store.get(f.maskId).data, bytes('c6_d8_i0.rgba'));
        A.equal(f.ppu, 64);
        A.equal(f.metadataStatus, 'imported');
    }
});
test('OpenRaster archive mimetype first, layers named and XML escaped', async () => {
    const { s, st } = await fixture();
    s.frames[0].name = 'a&b.png';
    s.frames[1].visible = false;
    const b = await I.exportORA(s.frames, s.scenes[0].settings, st), e = await K.unzip(b);
    A.equal(e[0].name, 'mimetype');
    A.equal(K.decodeText(e[0].data), 'image/openraster');
    const xml = K.decodeText(e.find(e => e.name === 'stack.xml').data);
    A.ok(xml.includes('a&amp;b.png'));
    A.ok(xml.includes('visibility="hidden"'));
    const thumb = await K.decodePNG(e.find(e => e.name === 'Thumbnails/thumbnail.png').data);
    A.ok(thumb.width <= 256 && thumb.height <= 256);
    const merged = await K.decodePNG(e.find(e => e.name === 'mergedimage.png').data), l = C.layout(s.frames, s.scenes[0].settings, k => st.get(k));
    eq(merged.data, C.compose(l, k => st.get(k)).data);
});
test('Reference metadata may precede its PNG without losing pivot or PPU', async () => {
    const s = I.applyMetadata(I.blank(), [{ name: 'body_target-0', rect: { w: 17, h: 13 }, pivot: { x: .25, y: .3 }, ppu: 128 }], { reference: true }).state;
    const r = await I.importPNGs([{ name: 'body_target-0.png', data: bytes('c6_d8_i0.png') }], s, new I.AssetStore(), { reference: true });
    A.equal(r.count, 1);
    A.equal(r.state.references.length, 1);
    A.equal(r.state.references[0].ppu, 128);
    A.equal(r.state.references[0].pivot.x, .25);
    A.ok(r.state.references[0].imageId);
});
test('Source metadata cannot overwrite another group with identical source names', async () => {
    const { s, st } = await fixture();
    const next = I.clone(s), newGroup = { ...s.scenes[0], id: 'other' };
    next.scenes.push(newGroup);
    next.frames.push({ ...next.frames[0], id: 'other_f', groupId: 'other' });
    const rows = [{ name: 'body_test-0', pivot: { x: .15, y: .2 }, ppu: 128 }];
    A.throws(() => I.applyMetadata(next, rows), /mehrdeutig/);
    const r = I.applyMetadata(next, rows, { groupIds: ['other'] });
    A.equal(r.state.frames[0].ppu, 64);
    A.equal(r.state.frames[3].ppu, 128);
});
test('Multiple source groups export duplicate filenames into separate folders', async () => {
    const { s, st } = await fixture();
    const f = { ...s.frames[0], id: 'other_f', groupId: 'other' };
    const e = await I.tileEntries([s.frames[0], f], st);
    A.equal(e[0].name, '01_body_test/body_test-0.png');
    A.equal(e[1].name, '02_body_test/body_test-0.png');
    eq(e[0].data, e[1].data);
    A.throws(() => K.zip([{ name: 'a.png', data: e[0].data }, { name: 'A.png', data: e[0].data }]));
});
test('Trim compensation survives project save and schema validation', async () => {
    const { s, st } = await fixture();
    s.frames[0].trimOffsetX = 3;
    s.frames[0].trimOffsetY = -2;
    s.frames[0].dx = 10;
    const r = await I.readProject(await K.unzip(await I.writeProject(s, st)));
    A.equal(r.state.frames[0].trimOffsetX, 3);
    A.equal(r.state.frames[0].trimOffsetY, -2);
    A.equal(r.state.frames[0].dx, 10);
});
test('Megabyte Base64 data is validated without a recursive pattern overflow', () => {
    const a = new Uint8Array(2 * 1024 * 1024);
    for (let i = 0; i < a.length; i++)
        a[i] = i % 251;
    const b = K.bytesToBase64(a);
    eq(K.base64ToBytes(b), a);
    A.throws(() => K.base64ToBytes('AAA=AAAA'));
});
test('Numeric limits and group capacity reject extra frames, without silent clipping', async () => {
    const { s, st } = await fixture();
    const n = I.clone(s);
    n.frames[0].slot = 4;
    A.throws(() => I.validate(n, st), /Raster zu klein/);
    const p = I.clone(s);
    p.frames[0].pivot.x = 2;
    A.throws(() => I.validate(p, st));
    const q = I.clone(s);
    q.frames[0].ppu = 0;
    A.throws(() => I.validate(q, st));
});
test('Actual supplied v0.1 demo imports all 25 originals and coordinates', async () => {
    const raw = C.json(fs.readFileSync(path.join(P, 'legacy-v0.1.json'), 'utf8')), r = await I.legacyProject(raw);
    A.equal(r.state.frames.length, 25);
    for (let i = 0; i < 25; i++) {
        const f = r.state.frames[i], old = raw.tiles[i];
        eq(await r.store.bytes(f.originalId), K.base64ToBytes(old.pngBase64));
        A.equal(f.slot, old.slot);
        A.equal(f.dx, old.offsetX);
        A.equal(f.dy, old.offsetY);
    }
});
test('4096-frame project roundtrip stays within explicit capacity; 4097 is rejected', async () => {
    const s = I.blank(), st = new I.AssetStore(), g = { id: 'capacity', name: 'body_capacity', source: 'custom', settings: C.scene({ a: 64, b: 64, width: 4, height: 2, category: 'unit' }) };
    s.scenes.push(g);
    const key = st.add(C.image(1, 1, new Uint8Array([103, 109, 117, 255])));
    for (let i = 0; i < 4096; i++) {
        const f = I.makeFrame(`body_capacity-${i}.png`, key, g.id, st);
        f.slot = i;
        s.frames.push(f);
    }
    const valid = I.validate(s, st);
    const out = await I.readProject(await K.unzip(await I.writeProject(valid, st)));
    A.equal(out.state.frames.length, 4096);
    A.equal(out.store.items.size, 1);
    s.frames.push({ ...s.frames[0], id: 'overflow' });
    A.throws(() => I.validate(s, st), /Zu viele/);
});
