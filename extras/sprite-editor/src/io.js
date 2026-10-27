/* Stronghold Sprite Editor. Validated project model, transactional imports and exports. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ? require('./core.js') : root.SpriteCore;
    const K = typeof module === 'object' && module.exports ? require('./codec.js') : root.SpriteCodec;
    const api = factory(C, K);
    if (typeof module === 'object' && module.exports)
        module.exports = api;
    else
        root.SpriteIO = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C, K) {
    'use strict';
    const FORMAT = 'stronghold-sprite-editor', SCHEMA = 2;
    const uid = prefix => {
        if (globalThis.crypto?.randomUUID)
            return prefix + '_' + crypto.randomUUID().replace(/-/g, '');
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        return prefix + '_' + Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
    };
    const clone = value => structuredClone(value);
    const text = (value, label, max = 240) => {
        if (typeof value !== 'string' || value.length > max || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value))
            C.fail(`${label}: ungültiger Text.`);
        return value;
    };
    const id = value => {
        if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(value))
            C.fail('Ungültige interne ID.');
        return value;
    };
    const bool = (value, fallback = false) => value === undefined ? fallback : (typeof value === 'boolean' ? value : C.fail('Ungültiger Wahrheitswert.'));
    const source = value => ['shde', 'custom', 'shcde'].includes(value) ? value : C.fail('Unbekannte Assetherkunft.');
    const originLabel = s => ({ shde: 'Stronghold: Definitive Edition', shcde: 'Stronghold Crusader: Definitive Edition', custom: 'Eigene Assets' }[s] || s);
    const tick = () => new Promise(r => setTimeout(r, 0));
    function blank() {
        return {
            format: FORMAT, version: SCHEMA, project: { name: 'Unbenannt', author: '', id: 'sprite-port', version: '1.0.0', description: '', provenance: '' }, scenes: [], frames: [], references: [], split: null,
            export: { mode: 'atlas', material: 'Auto', padding: 2, extrude: 1, maxSide: 8192 }
        };
    }
    /** Asset buffers are shared by metadata snapshots, never mutated after registration. */
    /**
     * Shared image store. Treat returned pixel buffers as immutable.
     * fork() shares images, not the index; failed transactions can discard the fork.
     * History retention includes originals and snapshots when enforcing the budget.
     */
    class AssetStore {
        constructor() {
            this.items = new Map();
            this.pixels = 0;
        }
        get(key) {
            const a = this.items.get(key);
            if (!a)
                C.fail(`Bilddaten fehlen: ${String(key).slice(0, 80)}`);
            return a;
        }
        has(key) {
            return this.items.has(key);
        }
        add(img, key = uid('a')) {
            id(key);
            C.dimensions(img.width, img.height);
            if (this.has(key))
                C.fail('Doppelte Bild-ID.');
            if (this.pixels + img.width * img.height > C.LIMITS.totalPixels)
                C.fail('Bildbudget von 32 Megapixeln erreicht. Unbenötigte Gruppen entfernen oder ein neues Projekt anlegen.');
            if (!img.data || img.data.length !== img.width * img.height * 4)
                C.fail('Ungültige Bilddaten.');
            this.items.set(key, { ...img, id: key, warnings: img.warnings || [] });
            this.pixels += img.width * img.height;
            return key;
        }
        async decode(bytes, options = {}) {
            const h = K.pngHeader(bytes);
            if (this.pixels + h.width * h.height > C.LIMITS.totalPixels)
                C.fail('Import überschreitet das Bildbudget von 32 Megapixeln.');
            return this.add(await K.decodePNG(bytes, options));
        }
        async bytes(key, signal) {
            const a = this.get(key);
            K.aborted(signal);
            if (!a.bytes)
                a.bytes = await K.encodePNG(a, { signal });
            return a.bytes;
        }
        fork() {
            const s = new AssetStore();
            s.items = new Map(this.items);
            s.pixels = this.pixels;
            return s;
        }
        retain(keys) {
            for (const [key, a] of this.items)
                if (!keys.has(key)) {
                    this.items.delete(key);
                    this.pixels -= a.width * a.height;
                }
        }
    }
    function assetIds(state) {
        const ids = new Set();
        for (const f of state.frames)
            for (const k of ['imageId', 'originalId', 'maskId', 'originalMaskId'])
                if (f[k])
                    ids.add(f[k]);
        for (const r of state.references)
            for (const k of ['imageId', 'maskId'])
                if (r[k])
                    ids.add(r[k]);
        if (state.split)
            for (const k of ['imageId', 'maskId', 'mapId'])
                if (state.split[k])
                    ids.add(state.split[k]);
        return ids;
    }
    function validate(raw, store) {
        if (!raw || raw.format !== FORMAT || raw.version !== SCHEMA)
            C.fail('Nicht unterstützte Projektversion.');
        if (!Array.isArray(raw.frames) || !Array.isArray(raw.scenes) || !Array.isArray(raw.references))
            C.fail('Projektstruktur unvollständig.');
        if (raw.frames.length > C.LIMITS.frames || raw.references.length > C.LIMITS.frames || raw.scenes.length > 256)
            C.fail('Zu viele Projektobjekte.');
        const p = raw.project || {}, s = blank();
        s.project = {
            name: text(p.name, 'Projektname', 120), author: text(p.author, 'Autor', 120), id: text(p.id, 'Mod-ID', 80), version: text(p.version, 'Version', 40), description: text(p.description, 'Beschreibung', 4000), provenance: text(p.provenance, 'Herkunft', 12000)
        };
        const sceneIds = new Set(), frameIds = new Set(), refs = new Set();
        s.scenes = raw.scenes.map(g => {
            const gid = id(g.id);
            if (sceneIds.has(gid))
                C.fail('Doppelte Gruppe.');
            sceneIds.add(gid);
            return { id: gid, name: text(g.name, 'Gruppenname'), source: source(g.source), settings: C.scene(g.settings) };
        });
        s.frames = raw.frames.map(f => {
            const fid = id(f.id);
            if (frameIds.has(fid))
                C.fail('Doppelte Frame-ID.');
            frameIds.add(fid);
            const groupId = id(f.groupId);
            if (!sceneIds.has(groupId))
                C.fail('Sprite ohne Gruppe.');
            const imageId = id(f.imageId), originalId = id(f.originalId), img = store.get(imageId);
            store.get(originalId);
            const maskId = f.maskId ? id(f.maskId) : null, originalMaskId = f.originalMaskId ? id(f.originalMaskId) : null;
            if (maskId) {
                const m = store.get(maskId);
                if (m.width !== img.width || m.height !== img.height)
                    C.fail(`Maske hat eine andere Größe: ${f.name}`);
            }
            if (originalMaskId)
                store.get(originalMaskId);
            const rawTarget = text(f.targetName ?? '', 'Zielname'), target = rawTarget ? C.targetName(rawTarget).name : '';
            return {
                id: fid, groupId, name: text(f.name, 'Dateiname'), group: text(f.group, 'Quellgruppe'), index: f.index === null ? null : C.integer(f.index, 'Quellindex', 0, 100000000), slot: C.integer(f.slot, 'Rasterplatz', 0, 4095),
                imageId, originalId, maskId, originalMaskId, pivot: C.pivot(f.pivot), originalPivot: C.pivot(f.originalPivot || f.pivot), ppu: C.number(f.ppu, 'PPU', .001, 65536), originalPPU: C.number(f.originalPPU ?? f.ppu, 'Original-PPU', .001, 65536),
                metadataStatus: ['assumed', 'imported', 'manual'].includes(f.metadataStatus) ? f.metadataStatus : C.fail('Ungültiger Metadatenstatus.'), targetName: target, targetConfirmed: bool(f.targetConfirmed),
                dx: C.integer(f.dx, 'X-Versatz'), dy: C.integer(f.dy, 'Y-Versatz'), trimOffsetX: C.integer(f.trimOffsetX ?? 0, 'Trimversatz X'), trimOffsetY: C.integer(f.trimOffsetY ?? 0, 'Trimversatz Y'), visible: bool(f.visible, true), locked: bool(f.locked)
            };
        });
        for (const g of s.scenes) {
            const frames = s.frames.filter(f => f.groupId === g.id), slots = new Set();
            for (const f of frames) {
                if (f.slot >= g.settings.a * g.settings.b)
                    C.fail('Raster zu klein für belegte Plätze.');
                if (slots.has(f.slot))
                    C.fail('Rasterplatz doppelt belegt.');
                slots.add(f.slot);
            }
        }
        s.references = raw.references.map(r => {
            const name = C.targetName(r.name).name;
            if (refs.has(name.toLowerCase()))
                C.fail(`Doppelte Zielreferenz: ${name}`);
            refs.add(name.toLowerCase());
            const imageId = r.imageId ? id(r.imageId) : null, maskId = r.maskId ? id(r.maskId) : null, img = imageId ? store.get(imageId) : null;
            const width = img ? img.width : r.width === null ? null : C.integer(r.width, 'Referenzbreite', 1, C.LIMITS.side), height = img ? img.height : r.height === null ? null : C.integer(r.height, 'Referenzhöhe', 1, C.LIMITS.side);
            if (maskId) {
                const m = store.get(maskId);
                if (m.width !== width || m.height !== height)
                    C.fail('Zielmaske passt nicht zur Zielreferenz.');
            }
            return { name, imageId, maskId, width, height, pivot: r.pivot ? C.pivot(r.pivot) : null, ppu: r.ppu === null ? null : C.number(r.ppu, 'Referenz-PPU', .001, 65536) };
        });
        const e = raw.export || {};
        s.export = {
            mode: ['atlas', 'sprites'].includes(e.mode) ? e.mode : C.fail('Unbekannter Exportmodus.'), material: C.MATERIALS.includes(e.material) ? e.material : C.fail('Unbekanntes Material.'),
            padding: C.integer(e.padding, 'Atlasabstand', 0, 32), extrude: C.integer(e.extrude, 'Randwiederholung', 0, 32), maxSide: C.integer(e.maxSide, 'Maximale Atlasgröße', 64, 8192)
        };
        if (s.export.extrude > s.export.padding)
            C.fail('Randwiederholung überschreitet Atlasabstand.');
        if (raw.split) {
            const r = raw.split, img = store.get(id(r.imageId)), settings = C.scene(r.settings), maskId = r.maskId ? id(r.maskId) : null, mapId = id(r.mapId), map = store.get(mapId);
            if (map.width !== img.width || map.height !== img.height)
                C.fail('Schnittmaske hat eine andere Größe als das Bild.');
            C.ownershipMap(map, settings.a * settings.b);
            if (maskId) {
                const m = store.get(maskId);
                if (m.width !== img.width || m.height !== img.height)
                    C.fail('Schnittbild und Farbmaske haben unterschiedliche Größen.');
            }
            s.split = {
                imageId: r.imageId, mapId, maskId, settings, anchorX: C.integer(r.anchorX, 'Schnittanker X'), anchorY: C.integer(r.anchorY, 'Schnittanker Y'), extend: bool(r.extend, true), group: text(r.group, 'Schnittgruppe', 120), start: C.integer(r.start, 'Schnittstart', 0, 1000000), source: source(r.source)
            };
        }
        return s;
    }
    class History {
        constructor(state, store) {
            this.state = validate(state, store);
            this.store = store;
            this.past = [];
            this.future = [];
            this.revision = 0;
        }
        commit(state, store = this.store, label = 'Bearbeitung') {
            const clean = validate(state, store);
            if (JSON.stringify(clean) === JSON.stringify(this.state) && store === this.store)
                return false;
            this.past.push({ state: this.state, label });
            if (this.past.length > 50)
                this.past.shift();
            this.future = [];
            this.state = clean;
            this.store = store;
            this.revision++;
            this.gc();
            return true;
        }
        undo() {
            if (!this.past.length)
                return false;
            const p = this.past.pop();
            this.future.push({ state: this.state, label: p.label });
            this.state = p.state;
            this.revision++;
            this.gc();
            return true;
        }
        redo() {
            if (!this.future.length)
                return false;
            const p = this.future.pop();
            this.past.push({ state: this.state, label: p.label });
            this.state = p.state;
            this.revision++;
            this.gc();
            return true;
        }
        gc() {
            const keep = assetIds(this.state);
            for (const p of [...this.past, ...this.future])
                for (const a of assetIds(p.state))
                    keep.add(a);
            this.store.retain(keep);
        }
        clearHistory() {
            this.past = [];
            this.future = [];
            this.gc();
        }
    }
    function makeFrame(name, imageId, groupId, store, options = {}) {
        const n = C.parseName(name);
        const p = options.pivot || { x: .5, y: 0 };
        let proposed = '';
        try {
            proposed = C.targetName(n.canonical).name;
        }
        catch (_e) {
        }
        return {
            id: uid('f'), groupId, name, group: n.group, index: n.index, slot: 0, imageId, originalId: imageId, maskId: options.maskId || null, originalMaskId: options.maskId || null, pivot: { ...p }, originalPivot: { ...p }, ppu: options.ppu || 64, originalPPU: options.ppu || 64,
            metadataStatus: options.pivot && options.ppu ? 'imported' : 'assumed', targetName: proposed, targetConfirmed: false, dx: 0, dy: 0, visible: true, locked: false
        };
    }
    async function expandFiles(files, options = {}) {
        let size = 0;
        const all = [];
        for (const f of files) {
            K.aborted(options.signal);
            const data = f.data instanceof Uint8Array ? f.data : new Uint8Array(await f.arrayBuffer());
            size += data.length;
            if (size > C.LIMITS.importBytes)
                C.fail('Import überschreitet 128 MiB.');
            const name = f.webkitRelativePath || f.name;
            if (/\.(zip|ora|shsprite|semod)$/i.test(name)) {
                const entries = await K.unzip(data, options);
                all.push(...entries);
            }
            else {
                C.safePath(name);
                all.push({ name, data });
            }
        }
        if (all.length > C.LIMITS.entries)
            C.fail('Zu viele Dateien im Import.');
        const names = new Set();
        for (const e of all) {
            if (names.has(e.name.toLowerCase()))
                C.fail(`Datei mehrfach im Import: ${e.name}`);
            names.add(e.name.toLowerCase());
        }
        return all.filter(e => !e.name.startsWith('__MACOSX/') && !/(^|\/)\./.test(e.name));
    }
    async function importPNGs(entries, state, store, options = {}) {
        const out = clone(state), next = store.fork(), items = entries.filter(e => /\.png$/i.test(e.name));
        if (!items.length)
            C.fail('Keine PNG-Dateien gefunden.');
        const lookup = new Map(items.map(e => [e.name.replace(/\.png$/i, '').toLowerCase(), e])), usedMasks = new Set(), groups = new Map();
        for (let i = 0; i < items.length; i++) {
            const e = items[i], basename = e.name.split('/').pop(), parsed = C.parseName(basename);
            if (parsed.mask)
                continue;
            K.aborted(options.signal);
            options.progress?.(i + 1, items.length, basename);
            const imageId = await next.decode(e.data, options), stem = e.name.replace(/\.png$/i, ''), mask = lookup.get((stem + '_m').toLowerCase());
            let maskId = null;
            if (mask) {
                maskId = await next.decode(mask.data, options);
                usedMasks.add(mask.name);
                const a = next.get(imageId), b = next.get(maskId);
                if (a.width !== b.width || a.height !== b.height)
                    C.fail(`Maske passt nicht: ${mask.name}`);
            }
            if (options.reference) {
                const name = C.targetName(parsed.canonical).name;
                const existing = out.references.find(r => r.name.toLowerCase() === name.toLowerCase());
                if (existing?.imageId)
                    C.fail(`Zielreferenz schon vorhanden: ${name}`);
                const img = next.get(imageId);
                if (existing)
                    Object.assign(existing, { imageId, maskId, width: img.width, height: img.height });
                else
                    out.references.push({ name, imageId, maskId, width: img.width, height: img.height, pivot: null, ppu: null });
            }
            else {
                const folder = e.name.includes('/') ? e.name.slice(0, e.name.lastIndexOf('/')) : '', key = folder + '\n' + parsed.group;
                if (!groups.has(key))
                    groups.set(key, { id: uid('g'), name: parsed.group, source: source(options.source || 'shde'), frames: [] });
                const g = groups.get(key);
                g.frames.push(makeFrame(basename, imageId, g.id, next, { maskId }));
            }
            await tick();
        }
        for (const e of items)
            if (C.parseName(e.name.split('/').pop()).mask && !usedMasks.has(e.name))
                C.fail(`Maske ohne zugehöriges Farbbild: ${e.name}`);
        for (const g of groups.values()) {
            const settings = C.autoScene(g.frames, options.preserve !== false), frames = C.assignSlots(g.frames, settings, options.preserve !== false);
            out.scenes.push({ id: g.id, name: g.name, source: g.source, settings });
            out.frames.push(...frames);
        }
        if (out.frames.length > C.LIMITS.frames)
            C.fail('Maximal 4096 Sprites je Projekt.');
        return {
            state: validate(out, next), store: next, groups: [...groups.values()].map(g => g.id), count: options.reference ? items.filter(e => !C.parseName(e.name.split('/').pop()).mask).length : out.frames.length - state.frames.length
        };
    }
    function applyMetadata(state, rows, options = {}) {
        const out = clone(state);
        let matched = 0;
        for (const row of rows) {
            if (options.reference) {
                const name = C.targetName(row.name).name;
                let ref = out.references.find(r => r.name === name);
                if (!ref) {
                    ref = {
                        name, imageId: null, maskId: null, width: row.rect && Number.isInteger(row.rect.w) ? row.rect.w : null, height: row.rect && Number.isInteger(row.rect.h) ? row.rect.h : null, pivot: null, ppu: null
                    };
                    out.references.push(ref);
                }
                if (row.pivot)
                    ref.pivot = { ...row.pivot };
                if (row.ppu !== null)
                    ref.ppu = row.ppu;
                matched++;
            }
            else {
                const frames = out.frames.filter(f => (!options.groupId || f.groupId === options.groupId) && (!options.groupIds || options.groupIds.includes(f.groupId)) && C.parseName(f.name).canonical === row.name);
                if (frames.length > 1)
                    C.fail(`Metadatenquelle mehrdeutig: ${row.name}. Gruppen getrennt importieren.`);
                for (const f of frames) {
                    if (row.pivot) {
                        f.pivot = { ...row.pivot };
                        f.originalPivot = { ...row.pivot };
                    }
                    if (row.ppu !== null) {
                        f.ppu = row.ppu;
                        f.originalPPU = row.ppu;
                    }
                    f.metadataStatus = row.pivot && row.ppu !== null ? 'imported' : f.metadataStatus;
                    matched++;
                }
            }
        }
        if (!matched)
            C.fail('Keine übereinstimmenden Sprite-Namen in den Metadaten.');
        return { state: out, count: matched };
    }
    async function importAtlas(entries, state, store, options = {}) {
        const jsons = entries.filter(e => /\.json$/i.test(e.name)), pngs = entries.filter(e => /\.png$/i.test(e.name) && !/_m\.png$/i.test(e.name));
        if (jsons.length !== 1 || pngs.length !== 1)
            C.fail('Atlasimport benötigt genau ein Farb-PNG, eine JSON-Datei und optional ein gleichnamiges _m.png.');
        const rows = C.parseMetadata(C.json(K.decodeText(jsons[0].data)), options), next = store.fork(), out = clone(state), atlas = await K.decodePNG(pngs[0].data, options), maskEntry = entries.find(e => e.name.toLowerCase() === pngs[0].name.replace(/\.png$/i, '_m.png').toLowerCase());
        const mask = maskEntry ? await K.decodePNG(maskEntry.data, options) : null;
        if (mask && (mask.width !== atlas.width || mask.height !== atlas.height))
            C.fail('Atlas und Maske haben unterschiedliche Größen.');
        const groups = new Map();
        let total = 0;
        const rects = rows.map(row => C.atlasCropRect(row, atlas, options.origin || 'auto'));
        for (const r of rects)
            total += r.width * r.height * (mask ? 2 : 1);
        if (next.pixels + total > C.LIMITS.totalPixels)
            C.fail('Atlasbilder überschreiten das Bildbudget.');
        for (let i = 0; i < rows.length; i++) {
            K.aborted(options.signal);
            const row = rows[i], r = rects[i], name = row.name + '.png', imageId = next.add(C.crop(atlas, r.x, r.y, r.width, r.height)), maskId = mask ? next.add(C.crop(mask, r.x, r.y, r.width, r.height)) : null;
            if (options.reference) {
                const target = C.targetName(row.name).name;
                if (out.references.some(t => t.name === target))
                    C.fail(`Zielreferenz schon vorhanden: ${target}`);
                out.references.push({ name: target, imageId, maskId, width: r.width, height: r.height, pivot: row.pivot, ppu: row.ppu });
            }
            else {
                const group = C.parseName(name).group;
                if (!groups.has(group))
                    groups.set(group, { id: uid('g'), name: group, source: source(options.source || 'shde'), frames: [] });
                const g = groups.get(group);
                g.frames.push(makeFrame(name, imageId, g.id, next, { maskId, pivot: row.pivot, ppu: row.ppu }));
            }
            options.progress?.(i + 1, rows.length, name);
            await tick();
        }
        for (const g of groups.values()) {
            const settings = C.autoScene(g.frames, options.preserve !== false);
            out.scenes.push({ id: g.id, name: g.name, source: g.source, settings });
            out.frames.push(...C.assignSlots(g.frames, settings, options.preserve !== false));
        }
        return { state: validate(out, next), store: next, count: rows.length, groups: [...groups.values()].map(g => g.id) };
    }
    async function readProject(entries, options = {}) {
        const manifest = entries.find(e => e.name === 'project.json');
        if (!manifest)
            C.fail('project.json fehlt im Projektarchiv.');
        const m = C.json(K.decodeText(manifest.data));
        if (m.format !== FORMAT || m.version !== SCHEMA || !Array.isArray(m.assets))
            C.fail('Nicht unterstütztes Projektformat.');
        const s = new AssetStore(), seen = new Set();
        let n = 0;
        for (const a of m.assets) {
            const key = id(a.id);
            if (seen.has(key))
                C.fail('Doppelte Bild-ID im Projekt.');
            seen.add(key);
            const path = C.safePath(a.path);
            if (path !== `assets/${key}.png`)
                C.fail('Ungültiger Projekt-Bildpfad.');
            const entry = entries.find(e => e.name === path);
            if (!entry)
                C.fail(`Projektbild fehlt: ${path}`);
            if (typeof a.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(a.sha256) || await K.sha256(entry.data) !== a.sha256)
                C.fail(`SHA-256-Prüfung fehlgeschlagen: ${path}`);
            const h = K.pngHeader(entry.data);
            if (s.pixels + h.width * h.height > C.LIMITS.totalPixels)
                C.fail('Projekt überschreitet das Bildbudget.');
            s.add(await K.decodePNG(entry.data, options), key);
            options.progress?.(++n, m.assets.length, path);
            await tick();
        }
        const state = validate(m, s);
        if (assetIds(state).size !== s.items.size)
            C.fail('Projekt enthält unreferenzierte Bilddaten.');
        return { state, store: s };
    }
    async function writeProject(state, store, options = {}) {
        const s = validate(state, store), entries = [], assets = [];
        let i = 0, ids = [...assetIds(s)].sort();
        for (const key of ids) {
            K.aborted(options.signal);
            const data = await store.bytes(key, options.signal), path = `assets/${key}.png`;
            assets.push({ id: key, path, sha256: await K.sha256(data) });
            entries.push({ name: path, data });
            options.progress?.(++i, ids.length, path);
            await tick();
        }
        entries.unshift({ name: 'project.json', data: JSON.stringify({ ...s, createdWith: C.VERSION, assets }, null, 2) });
        return K.zip(entries);
    }
    async function legacyProject(raw, options = {}) {
        if (raw?.format !== 'shc-sprite-workbench' || raw.version !== 1 || !Array.isArray(raw.tiles))
            C.fail('Nicht unterstütztes Altprojekt.');
        const store = new AssetStore(), state = blank(), gid = uid('g'), settings = C.scene({ ...raw.settings, anchor: 'bottom', category: 'building' });
        state.project.name = 'Importiertes Projekt';
        state.scenes.push({ id: gid, name: 'Import', source: 'custom', settings });
        for (let i = 0; i < raw.tiles.length; i++) {
            const r = raw.tiles[i];
            K.aborted(options.signal);
            const key = await store.decode(K.base64ToBytes(r.pngBase64), options), img = store.get(key);
            if (img.width !== r.width || img.height !== r.height)
                C.fail('Bildgröße im Altprojekt widerspricht den PNG-Daten.');
            state.frames.push({ ...makeFrame(text(r.filename, 'Dateiname'), key, gid, store), slot: r.slot, dx: r.offsetX, dy: r.offsetY, visible: r.visible });
            options.progress?.(i + 1, raw.tiles.length, r.filename);
        }
        return { state: validate(state, store), store };
    }
    function mappingCSV(state, frames = state.frames) {
        return C.csvString([['source', 'target', 'pivot_x', 'pivot_y', 'ppu', 'offset_x', 'offset_y'], ...frames.map(f => [f.name, f.targetName, f.pivot.x, f.pivot.y, f.ppu, f.dx, f.dy])]);
    }
    function importMapping(state, csv, groupId = null) {
        const rows = C.parseCSV(csv);
        if (rows.length < 2)
            C.fail('CSV enthält keine Zuordnungen.');
        const headers = rows.shift().map(v => v.trim().toLowerCase()), index = k => headers.indexOf(k);
        if (index('source') < 0 || index('target') < 0)
            C.fail('CSV benötigt die Spalten source und target.');
        if (new Set(headers).size !== headers.length)
            C.fail('CSV-Spaltennamen sind doppelt.');
        const out = clone(state), used = new Set();
        let count = 0;
        for (const row of rows) {
            if (row.length !== headers.length)
                C.fail('CSV-Zeile hat eine abweichende Spaltenzahl.');
            const cell = row[index('source')], sourceName = /^'[=+@\t\r-]/.test(cell) ? cell.slice(1) : cell, matches = out.frames.filter(f => (!groupId || f.groupId === groupId) && (f.name === sourceName || C.parseName(f.name).canonical === sourceName));
            if (matches.length !== 1)
                C.fail(`Quelle nicht eindeutig gefunden: ${sourceName}`);
            const f = matches[0];
            if (used.has(f.id))
                C.fail(`Quelle mehrfach zugeordnet: ${sourceName}`);
            used.add(f.id);
            const target = row[index('target')];
            f.targetName = target ? C.targetName(target).name : '';
            f.targetConfirmed = !!target;
            for (const [col, prop] of [['ppu', 'ppu'], ['offset_x', 'dx'], ['offset_y', 'dy']])
                if (index(col) >= 0 && row[index(col)] !== '')
                    f[prop] = C.number(row[index(col)], col);
            for (const [col, prop] of [['pivot_x', 'x'], ['pivot_y', 'y']])
                if (index(col) >= 0 && row[index(col)] !== '') {
                    f.pivot[prop] = C.number(row[index(col)], col, 0, 1);
                    f.metadataStatus = 'manual';
                }
            count++;
        }
        return { state: out, count };
    }
    function preflight(state, store, frames = state.frames.filter(f => f.visible), mode = state.export.mode) {
        const issues = [], add = (level, code, message, f = null) => issues.push({ level, code, message, frameId: f?.id || null, name: f?.name || null });
        if (!frames.length)
            add('error', 'EMPTY', 'Keine sichtbaren Sprites für den Export.');
        const names = new Map(), groupPPU = new Map(), groups = new Set();
        for (const f of frames) {
            const a = store.get(f.imageId), g = state.scenes.find(g => g.id === f.groupId);
            let target;
            try {
                target = C.targetName(f.targetName);
            }
            catch (_e) {
                add('error', 'TARGET_NAME', 'Gültiger SHCDE-Zielname fehlt.', f);
                continue;
            }
            const ref = state.references.find(r => r.name === target.name);
            groups.add(target.group);
            const key = target.name.toLowerCase();
            if (names.has(key))
                add('error', 'DUPLICATE_TARGET', `Ziel mehrfach belegt: ${target.name}`, f);
            names.set(key, f);
            if (!ref && !f.targetConfirmed)
                add('error', 'UNCONFIRMED', 'Zielzuordnung weder durch Referenz belegt noch manuell bestätigt.', f);
            else if (!ref)
                add('warning', 'NO_REFERENCE', 'Ziel nur manuell zugeordnet; Existenz und Animation im Spiel ungeprüft.', f);
            if (f.metadataStatus === 'assumed')
                add('warning', 'ASSUMED_PIVOT', 'Pivot und PPU wurden nicht aus Quelldaten übernommen.', f);
            if (g?.settings.category === 'building' && a.width > 64)
                add('warning', 'BUILDING_WIDTH', 'Gebäude-Sprite breiter als das 64-px-Arbeitsraster der Vorlage.', f);
            if (mode === 'sprites') {
                if (!ref || ref.width === null || ref.height === null)
                    add('error', 'SPRITE_REFERENCE', 'Einzel-Override benötigt eine Zielreferenz mit exakten Abmessungen.', f);
                else if (a.width !== ref.width || a.height !== ref.height)
                    add('error', 'SPRITE_SIZE', `Einzel-Override: ${a.width} × ${a.height}, Ziel erwartet ${ref.width} × ${ref.height}.`, f);
                if (ref?.pivot && (Math.abs(f.pivot.x - ref.pivot.x) > 1e-8 || Math.abs(f.pivot.y - ref.pivot.y) > 1e-8))
                    add('warning', 'SPRITE_PIVOT', 'Einzel-Override übernimmt den Spielpivot; geänderter Projektpivot wird nicht übertragen.', f);
                if (ref?.ppu && f.ppu !== ref.ppu)
                    add('warning', 'SPRITE_PPU', 'Einzel-Override übernimmt die Spielskalierung; PPU wird nicht übertragen.', f);
            }
            if (mode === 'atlas') {
                if (groupPPU.has(target.group) && groupPPU.get(target.group) !== f.ppu)
                    add('error', 'MIXED_PPU', `Unterschiedliche PPU innerhalb der Zielgruppe ${target.group}.`, f);
                groupPPU.set(target.group, f.ppu);
            }
            if (['TeamColour', 'Foliage'].includes(state.export.material) && !f.maskId)
                add('error', 'MISSING_MASK', `${state.export.material} benötigt eine passende Maske.`, f);
            if (ref?.maskId && !f.maskId && state.export.material !== 'Plain')
                add('warning', 'LOST_MASK', 'Zielreferenz hat eine Maske, der Ersatz nicht.', f);
            if (state.export.material === 'Plain' && f.maskId)
                add('warning', 'IGNORED_MASK', 'Plain verwendet die vorhandene Maske nicht.', f);
            for (const w of a.warnings || [])
                add('warning', 'COLOR_PROFILE', w, f);
        }
        if (mode === 'atlas' && frames.length) {
            for (const group of groups) {
                const ff = frames.filter(f => {
                    try {
                        return C.targetName(f.targetName).group === group;
                    }
                    catch (_e) {
                        return false;
                    }
                });
                if (ff.some(f => f.maskId) && ff.some(f => !f.maskId))
                    add('error', 'PARTIAL_MASK', `Zielgruppe ${group}: Masken fehlen bei einzelnen Frames. Keine Maskenkanäle werden erfunden.`);
                try {
                    C.pack(ff.map(f => ({ ...f, width: store.get(f.imageId).width, height: store.get(f.imageId).height })), state.export);
                }
                catch (e) {
                    add('error', 'PACKING', `${group}: ${e.message}`);
                }
            }
        }
        return issues;
    }
    function modInfo(state) {
        const p = state.project;
        if (!/^[A-Za-z][A-Za-z0-9._-]{0,63}$/.test(p.id))
            C.fail('Mod-ID: mit einem Buchstaben beginnen, maximal 64 Zeichen; nur Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich.');
        if (!/^\d+\.\d+\.\d+$/.test(p.version))
            C.fail('Mod-Version muss dem Schema 1.0.0 entsprechen.');
        if (!p.name.trim() || !p.author.trim())
            C.fail('Projektname und Autor für das Modpaket eintragen.');
        return {
            GUID: p.id, Author: p.author, Name: p.name, Description: p.description, Version: p.version, Website: '', Manifest: 0, AssetMode: 'Global', NetworkMode: 0, Dependencies: [{ GUID: '000shcdese' }]
        };
    }
    function groupedTargets(frames) {
        const groups = new Map();
        for (const f of frames) {
            const group = C.targetName(f.targetName).group;
            if (!groups.has(group))
                groups.set(group, []);
            groups.get(group).push(f);
        }
        return groups;
    }
    function packFrames(frames, store, options) {
        return C.pack(frames.map(f => ({ ...f, width: store.get(f.imageId).width, height: store.get(f.imageId).height })), options);
    }
    async function atlasEntries(frames, store, options = {}, prefix = '') {
        const entries = [];
        for (const [group, ff] of groupedTargets(frames)) {
            K.aborted(options.signal);
            const packed = packFrames(ff, store, options), definition = C.atlasDefinition(packed, ff[0].ppu, options.material || 'Auto'), path = prefix + group + '/';
            entries.push({ name: path + 'atlas.png', data: await K.encodePNG(C.atlasImage(packed, key => store.get(key)), options) });
            if (ff.some(f => f.maskId))
                entries.push({ name: path + 'atlas_m.png', data: await K.encodePNG(C.atlasImage(packed, key => store.get(key), true), options) });
            entries.push({ name: path + 'atlas.json', data: JSON.stringify(definition, null, 2) });
            await tick();
        }
        return entries;
    }
    async function tileEntries(frames, store, options = {}) {
        const groups = [...new Set(frames.map(f => f.groupId))], names = frames.map(f => {
            const name = options.targets ? C.targetName(f.targetName).name + '.png' : C.safeName(f.name);
            return !options.targets && groups.length > 1 ? `${String(groups.indexOf(f.groupId) + 1).padStart(2, '0')}_${C.safeName(f.group)}/${name}` : name;
        }), entries = [];
        if (new Set(names.map(n => n.normalize('NFC').toLowerCase())).size !== names.length)
            C.fail('Gleichnamige Dateien innerhalb einer Gruppe. Gruppen getrennt exportieren oder Quellnamen korrigieren.');
        for (let i = 0; i < frames.length; i++) {
            const f = frames[i], key = options.originals ? f.originalId : f.imageId, maskKey = options.originals ? f.originalMaskId : f.maskId;
            entries.push({ name: names[i], data: await store.bytes(key, options.signal) });
            if (maskKey)
                entries.push({ name: names[i].replace(/\.png$/i, '') + '_m.png', data: await store.bytes(maskKey, options.signal) });
            options.progress?.(i + 1, frames.length, names[i]);
            await tick();
        }
        return entries;
    }
    async function exportMod(state, store, options = {}) {
        const frames = state.frames.filter(f => f.visible), issues = preflight(state, store, frames);
        const errors = issues.filter(i => i.level === 'error');
        if (errors.length)
            C.fail(`Modexport gesperrt: ${errors.length} Fehler. ${errors[0].message}`);
        const info = modInfo(state), base = options.packed ? '' : `BepInEx/plugins/${C.safeName(info.GUID)}/`, entries = [{ name: base + 'info.json', data: JSON.stringify(info, null, 2) }];
        if (state.export.mode === 'atlas')
            entries.push(...await atlasEntries(frames, store, { ...state.export, ...options }, base + 'Override/Atlas/'));
        else {
            const tiles = await tileEntries(frames, store, { ...options, targets: true });
            entries.push(...tiles.map(e => ({ ...e, name: base + 'Override/Sprites/' + e.name })));
            if (state.export.material !== 'Auto')
                for (const f of frames)
                    entries.push({ name: base + 'Override/Sprites/' + f.targetName + '.material.json', data: JSON.stringify({ material: state.export.material }, null, 2) });
        }
        const mappings = [];
        for (const f of frames) {
            const group = state.scenes.find(g => g.id === f.groupId);
            mappings.push({
                source: f.name, sourceGame: originLabel(group.source), target: f.targetName, originalSHA256: await K.sha256(await store.bytes(f.originalId, options.signal)), outputSHA256: await K.sha256(await store.bytes(f.imageId, options.signal)), pivot: f.pivot, pixelsPerUnit: f.ppu, mask: !!f.maskId, targetReference: state.references.some(r => r.name === f.targetName)
            });
        }
        const report = {
            tool: 'Stronghold Sprite Editor', version: C.VERSION, exportMode: state.export.mode, target: 'Stronghold Crusader: Definitive Edition', inGameTested: false, loader: 'SHCDE Script Extender', mappings, issues, provenance: state.project.provenance
        };
        entries.push({ name: base + 'port-report.json', data: JSON.stringify(report, null, 2) });
        entries.push({
            name: base + 'PORTIERUNG.txt', data: 'Ziel: Stronghold Crusader: Definitive Edition\nVoraussetzung: kompatibler SHCDE Script Extender mit BepInEx.\nKein Spieltest durch den Editor. Zielnamen, Animation, Pivot, Material und Masken im Spiel prüfen.\nAtlas-Overrides sind laut API-Dokumentation experimentell. Das Paket enthält PNG, keine DDS-Kompression.\nDie Quelldateien und Spielarchive werden nicht verändert. Mehrere globale Mods können einander überschreiben.\nDas Paket ist keine direkt veröffentlichbare Workshop-Karte.\n\nHerkunft / Nutzungsrechte:\n' + state.project.provenance + '\n'
        });
        return { bytes: K.zip(entries), issues, report, filename: C.safeName(info.GUID) + (options.packed ? '.semod' : '.zip') };
    }
    async function exportSplit(state, store, options = {}) {
        const r = state.split;
        if (!r)
            C.fail('Kein Schnittbild vorhanden.');
        const src = store.get(r.imageId), map = C.ownershipMap(store.get(r.mapId), r.settings.a * r.settings.b), result = C.split(src, map, r.settings, r.anchorX, r.anchorY, r.maskId ? store.get(r.maskId) : null), entries = [], layout = [];
        const group = C.targetName(r.group + '-' + r.start).group;
        for (const t of result.tiles) {
            const name = `${group}-${r.start + t.slot}.png`;
            entries.push({ name, data: await K.encodePNG(t.image, options) });
            if (t.mask)
                entries.push({ name: name.replace('.png', '_m.png'), data: await K.encodePNG(t.mask, options) });
            layout.push({ name, slot: t.slot, x: t.x, y: t.y, width: t.width, height: t.height, offsetX: 0, offsetY: t.dy, pivot: { x: .5, y: 0 } });
            await tick();
        }
        entries.push({
            name: 'schnitt.json', data: JSON.stringify({
                format: 'stronghold-sprite-cut', version: 1, sourceWidth: src.width, sourceHeight: src.height, settings: r.settings, anchorX: r.anchorX, anchorY: r.anchorY, tiles: layout
            }, null, 2)
        });
        return { bytes: K.zip(entries), result };
    }
    function transferSplit(state, store) {
        const r = state.split;
        if (!r)
            C.fail('Kein Schnittbild vorhanden.');
        const src = store.get(r.imageId), map = C.ownershipMap(store.get(r.mapId), r.settings.a * r.settings.b), res = C.split(src, map, r.settings, r.anchorX, r.anchorY, r.maskId ? store.get(r.maskId) : null), out = clone(state), next = store.fork(), gid = uid('g');
        C.targetName(r.group + '-' + r.start);
        out.scenes.push({ id: gid, name: r.group, source: r.source, settings: { ...r.settings, anchor: 'bottom' } });
        for (const t of res.tiles) {
            const imageId = next.add(t.image), maskId = t.mask ? next.add(t.mask) : null, f = makeFrame(`${r.group}-${r.start + t.slot}.png`, imageId, gid, next, { maskId });
            f.slot = t.slot;
            f.dy = t.dy;
            out.frames.push(f);
        }
        return { state: validate(out, next), store: next, groupId: gid };
    }
    async function exportORA(frames, settings, store, thumbnail, options = {}) {
        const l = C.layout(frames, settings, key => store.get(key)), entries = [{ name: 'mimetype', data: 'image/openraster' }], xmlEscape = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
        const layers = [];
        // OpenRaster lists the topmost layer first; our paint order is bottom to top.
        for (let i = 0; i < l.paint.length; i++) {
            const p = l.paint[i], path = `data/layer${String(i).padStart(4, '0')}.png`;
            entries.push({ name: path, data: await store.bytes(p.frame.imageId, options.signal) });
            layers.unshift(`<layer name="${xmlEscape(p.frame.name)}" src="${path}" x="${p.x}" y="${p.y}" opacity="1.0" visibility="${p.frame.visible ? 'visible' : 'hidden'}" composite-op="svg:src-over"/>`);
        }
        entries.push({
            name: 'stack.xml', data: `<?xml version="1.0" encoding="UTF-8"?>\n<image version="0.0.3" w="${l.width}" h="${l.height}" name="${xmlEscape(options.name || 'Sprites')}"><stack>${layers.join('')}</stack></image>`
        });
        const merged = C.compose(l, key => store.get(key));
        entries.push({ name: 'mergedimage.png', data: await K.encodePNG(merged, options) });
        const factor = Math.min(1, 256 / l.width, 256 / l.height);
        entries.push({
            name: 'Thumbnails/thumbnail.png', data: await K.encodePNG(C.resize(merged, Math.max(1, Math.round(l.width * factor)), Math.max(1, Math.round(l.height * factor))), options)
        });
        return K.zip(entries);
    }
    return {
        FORMAT, SCHEMA, uid, clone, blank, AssetStore, History, assetIds, validate, makeFrame, expandFiles, importPNGs, applyMetadata, importAtlas, readProject, writeProject, legacyProject,
        mappingCSV, importMapping, preflight, modInfo, packFrames, atlasEntries, tileEntries, exportMod, exportSplit, transferSplit, exportORA, originLabel, tick
    };
});
