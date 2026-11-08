/* Stronghold Sprite Editor. DOM and canvas view; all exports use the independent RGBA codec. */
(function () {
    'use strict';
    const C = window.SpriteCore, K = window.SpriteCodec, I = window.SpriteIO, D = window.SpriteDamage, DI = window.SpriteDamageIO, AI = window.SpriteAI, PE = window.SpritePivotEvidence, $ = id => document.getElementById(id);
    if (!window.crypto?.getRandomValues || !window.CompressionStream || !window.DecompressionStream || !window.structuredClone) {
        document.body.textContent = 'Dieser Browser unterstützt die benötigten lokalen Datei- und Kompressionsfunktionen nicht. Die HTML-Datei in einer aktuellen Chromium-basierten Desktop-Version öffnen.';
        return;
    }
    const nativeCallbacks = new WeakMap();
    let nativeApi = null, nativeLastError = null, nativeDispatch = false, nativeAbortSignal = null, nativePickedFiles = null;
    function nativeCheckpoint() {
        if (nativeDispatch && nativeAbortSignal?.aborted)
            throw Object.assign(new Error('Native command was canceled. Completed history entries remain undoable.'), { code: 'canceled' });
    }
    const el = (tag, props = {}, children = []) => {
        const n = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (k === 'text')
                n.textContent = v;
            else if (k === 'class')
                n.className = v;
            else if (k.startsWith('on'))
                n.addEventListener(k.slice(2), v);
            else if (k in n)
                n[k] = v;
            else
                n.setAttribute(k, String(v));
        }
        for (const child of children)
            n.append(child);
        return n;
    };
    let history = new I.History(I.blank(), new I.AssetStore()), groupId = '', selected = new Set(), lastSelected = null, view = 'scene', panel = 'properties', dirty = false, busy = false, modalHandler = null, pendingFiles = [], toastTimer = null, aborter = null;
    // Navigation-only deep link from the Suite. No imports, jobs or file writes.
    const requestedPanel = window.location.hash.replace(/^#/, '');
    if (['geometry', 'ai', 'damage'].includes(requestedPanel)) panel = requestedPanel;
    let damageBuildingId = '', damageKind = 'mechanical', damageHp = 100, damageApprovedOnly = false;
    let aiGoal = '', aiRestrictions = '', aiAssetClass = 'building', aiModel = AI.MODELS[0], aiVariants = 1, aiCandidates = [], aiCandidateIndex = 0, aiLastRequest = null;
    let legacyPivotFile = null, showLegacyPivot = true;
    let playing = false, animIndex = 0, lastFrameTime = 0, pivotTool = false, measureTool = false, measureStart = null, measurement = null, snapStep = 1, brushTool = false, brushMap = null, drag = null, spaceDown = false, renderQueued = false, model = null, layoutError = '', fitNext = true, atlasGroup = '';
    let recoveryCandidate = null, recoveryTimer = null, recoveryRunning = false, recoveryAgain = false, recoveryEnabled = true, sessionId = I.uid('s'), autosaveGeneration = 0;
    try {
        sessionId = sessionStorage.getItem('sprite-session') || sessionId;
        sessionStorage.setItem('sprite-session', sessionId);
    }
    catch (_e) {
    }
    const transforms = new Map(), visualCache = new Map();
    let visualPixels = 0;
    const state = () => history.state, store = () => history.store, currentGroup = () => state().scenes.find(g => g.id === groupId), groupFrames = () => state().frames.filter(f => f.groupId === groupId).sort((a, b) => a.slot - b.slot), chosen = () => state().frames.filter(f => selected.has(f.id)), primary = () => chosen()[0] || groupFrames()[0] || null;
    const getTransform = () => {
        if (!transforms.has(view))
            transforms.set(view, { zoom: 1, panX: 0, panY: 0 });
        return transforms.get(view);
    };
    function message(text, error = false) {
        clearTimeout(toastTimer);
        $('toast-text').textContent = text;
        $('toast').classList.toggle('error', error);
        $('toast').hidden = false;
        toastTimer = setTimeout(() => $('toast').hidden = true, error ? 14000 : 5000);
    }
    function report(e) {
        nativeLastError = e.message || String(e);
        console.error(e);
        if (e.name === 'AbortError')
            message('Vorgang abgebrochen.');
        else
            message(e.message || 'Unerwarteter Fehler.', true);
    }
    function mark() {
        dirty = true;
        scheduleRecovery();
    }
    function afterChange({ fit = false } = {}) {
        const ids = new Set(state().frames.map(f => f.id));
        selected = new Set([...selected].filter(id => ids.has(id)));
        if (!state().scenes.some(g => g.id === groupId))
            groupId = state().scenes[0]?.id || '';
        if (!selected.size && groupFrames().length)
            selected.add(groupFrames()[0].id);
        for (const [key, item] of visualCache)
            if (!store().has(item.assetId)) {
                visualCache.delete(key);
                visualPixels -= item.pixels;
            }
        fitNext = fitNext || fit;
        mark();
        render();
    }
    function commit(next, label = 'Bearbeitung', nextStore = store(), options = {}) {
        nativeCheckpoint();
        if (!options.keepDamageApproval)
            D.invalidateApprovals(state(), next);
        if (history.commit(next, nextStore, label))
            afterChange(options);
    }
    function edit(fn, label = 'Bearbeitung', options = {}) {
        const next = I.clone(state());
        fn(next);
        commit(next, label, store(), options);
    }
    async function task(title, fn) {
        nativeCheckpoint();
        if (busy)
            throw new Error('Ein anderer Vorgang läuft bereits.');
        busy = true;
        playing = false;
        aborter = new AbortController();
        const nativeSignal = nativeAbortSignal, cancelNative = () => aborter?.abort();
        nativeSignal?.addEventListener('abort', cancelNative, { once: true });
        $('busy-title').textContent = title;
        $('busy-detail').textContent = '';
        $('busy-progress').removeAttribute('value');
        $('busy-dialog').showModal();
        const opts = {
            signal: aborter.signal, progress: (n, total, name) => {
                $('busy-progress').max = total || 1;
                $('busy-progress').value = n;
                $('busy-detail').textContent = name || '';
            }
        };
        try {
            await I.tick();
            return await fn(opts);
        }
        finally {
            nativeSignal?.removeEventListener('abort', cancelNative);
            busy = false;
            aborter = null;
            $('busy-dialog').close();
            render();
        }
    }
    $('busy-cancel').onclick = () => aborter?.abort();
    $('busy-dialog').addEventListener('cancel', e => {
        e.preventDefault();
        aborter?.abort();
    });
    function download(data, name, type = 'application/octet-stream') {
        nativeCheckpoint();
        const blob = data instanceof Blob ? data : new Blob([data], { type });
        const url = URL.createObjectURL(blob), a = el('a', { href: url, download: C.safeName(name) });
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    function askFiles(accept, multiple = true, directory = false) {
        if (nativeDispatch) {
            if (nativePickedFiles) {
                const files = nativePickedFiles;
                nativePickedFiles = null;
                if (directory || (!multiple && files.length !== 1))
                    throw Object.assign(new Error('Native file selection needs the expected count and cannot impersonate a directory.'), { code: 'invalid' });
                return Promise.resolve(files);
            }
            const error = new Error('Files are required. Use project.open or files.import with explicit file data.');
            error.code = 'input_required';
            throw error;
        }
        return new Promise(resolve => {
            const input = $('file-input');
            input.value = '';
            input.accept = accept;
            input.multiple = multiple;
            input.webkitdirectory = directory;
            input.onchange = () => resolve([...input.files]);
            input.oncancel = () => resolve([]);
            input.click();
        });
    }
    function field(label, value, { type = 'text', min, max, step, name, options, wide = false, onchange, placeholder } = {}) {
        const f = el('div', { class: 'field' + (wide ? ' wide' : '') }), lid = I.uid('input'), l = el('label', { text: label, htmlFor: lid });
        let control;
        if (options) {
            control = el('select', { id: lid, name: name || '' });
            for (const option of options) {
                const [v, title] = Array.isArray(option) ? option : [option, option];
                control.append(el('option', { value: v, text: title }));
            }
            control.value = value;
        }
        else if (type === 'textarea')
            control = el('textarea', { id: lid, name: name || '', value: value ?? '' });
        else {
            control = el('input', { id: lid, type, name: name || '', value: value ?? '', autocomplete: 'off' });
            if (min !== undefined)
                control.min = min;
            if (max !== undefined)
                control.max = max;
            if (step !== undefined)
                control.step = step;
            if (placeholder)
                control.placeholder = placeholder;
        }
        if (onchange)
            control.addEventListener('change', () => {
                try {
                    onchange(type === 'number' ? control.value : control.value);
                }
                catch (e) {
                    report(e);
                    renderInspector();
                }
            });
        f.append(l, control);
        return f;
    }
    function checkbox(label, checked, name, onchange) {
        const input = el('input', { type: 'checkbox', name: name || '', checked }), lab = el('label', { class: 'check' }, [input, document.createTextNode(label)]);
        if (onchange)
            input.onchange = () => {
                try {
                    onchange(input.checked);
                }
                catch (e) {
                    report(e);
                    renderInspector();
                }
            };
        return lab;
    }
    const fields = (...children) => el('div', { class: 'fields' }, children), buttons = (...children) => el('div', { class: 'field-inline' }, children), button = (label, fn, props = {}) => {
        const control = el('button', { type: 'button', text: label, onclick: () => Promise.resolve().then(fn).catch(report), ...props });
        nativeCallbacks.set(control, fn);
        return control;
    }, note = text => el('p', { class: 'inspector-note', text });
    function section(title, children = []) {
        return el('section', { class: 'inspector-section' }, [el('h3', { text: title }), ...children]);
    }
    const line = (label, value) => el('div', { class: 'info-line' }, [el('span', { text: label }), el('span', { text: String(value) })]);
    function modal(title, content, submit, handler) {
        nativeApi?.invalidate();
        $('modal-form').querySelector('footer button').textContent = 'Abbrechen';
        $('modal-title').textContent = title;
        $('modal-content').replaceChildren(...(Array.isArray(content) ? content : [content]));
        $('modal-submit').textContent = submit || 'Übernehmen';
        $('modal-submit').hidden = !handler;
        $('modal-error').hidden = true;
        modalHandler = handler;
        if (!$('modal').open)
            $('modal').showModal();
    }
    function closeModal() {
        nativeApi?.invalidate();
        $('modal').close();
        modalHandler = null;
    }
    $('modal-form').onsubmit = async (e) => {
        e.preventDefault();
        if (!modalHandler)
            return;
        const handler = modalHandler, data = new FormData($('modal-form'));
        $('modal-submit').disabled = true;
        $('modal-error').hidden = true;
        try {
            await handler(data);
            if (modalHandler === handler)
                closeModal();
        }
        catch (err) {
            $('modal-error').textContent = err.message;
            $('modal-error').hidden = false;
        }
        finally {
            $('modal-submit').disabled = false;
        }
    };
    $('modal').addEventListener('close', () => {
        modalHandler = null;
    });
    function confirmDialog(title, text, callback) {
        modal(title, [el('p', { text })], 'Fortfahren', async () => {
            await callback();
        });
    }
    function setProject(result, name) {
        nativeCheckpoint();
        playing = false;
        aiCandidates = [];
        aiLastRequest = null;
        aiCandidateIndex = 0;
        legacyPivotFile = null;
        measureStart = measurement = null;
        history = new I.History(result.state, result.store);
        selected = new Set();
        groupId = state().scenes[0]?.id || '';
        if (groupFrames()[0])
            selected.add(groupFrames()[0].id);
        visualCache.clear();
        visualPixels = 0;
        dirty = false;
        transforms.clear();
        fitNext = true;
        animIndex = 0;
        view = 'scene';
        autosaveGeneration++;
        render();
        if (name)
            message(name);
    }
    async function saveProject() {
        await task('Projekt speichern', async (opts) => {
            const bytes = await I.writeProject(state(), store(), opts);
            download(bytes, C.safeName(state().project.name) + '.shsprite');
            dirty = false;
            message('Projektdatei ausgegeben.');
        });
    }
    function newProject() {
        const go = () => setProject({ state: I.blank(), store: new I.AssetStore() });
        if (dirty)
            confirmDialog('Neues Projekt', 'Ungespeicherte Änderungen werden verworfen. Die lokale Sicherung ist kein Ersatz für eine gespeicherte Projektdatei.', go);
        else
            go();
    }
    async function openProject(files = null) {
        const chosenFiles = files || await askFiles('.shsprite,.json,.zip', false);
        if (!chosenFiles.length)
            return;
        const go = async () => {
            let result;
            await task('Projekt öffnen', async (opts) => {
                const entries = await I.expandFiles(chosenFiles, opts);
                if (entries.length === 1 && /\.json$/i.test(entries[0].name)) {
                    const raw = C.json(K.decodeText(entries[0].data));
                    result = await I.legacyProject(raw, opts);
                }
                else
                    result = await I.readProject(entries, opts);
            });
            setProject(result, 'Projekt geöffnet.');
        };
        if (dirty)
            confirmDialog('Projekt öffnen', 'Ungespeicherte Änderungen am aktuellen Projekt werden verworfen.', go);
        else
            await go();
    }
    function projectDialog() {
        const p = state().project;
        modal('Projekteinstellungen', [
            fields(field('Projektname', p.name, { name: 'name', wide: true }), field('Autor', p.author, { name: 'author' }), field('Mod-ID', p.id, { name: 'id' }), field('Version', p.version, { name: 'version' }), field('Beschreibung', p.description, { name: 'description', type: 'textarea', wide: true }), field('Herkunft und Nutzungsrechte', p.provenance, { name: 'provenance', type: 'textarea', wide: true })),
            el('p', { text: 'Die Mod-ID bezeichnet den eigenen Modordner, nicht die interne Sprite-Gruppe. Herkunft und Freigaben werden in den Exportbericht übernommen.' })
        ], 'Speichern', data => {
            edit(s => {
                for (const k of ['name', 'author', 'id', 'version', 'description', 'provenance'])
                    s.project[k] = String(data.get(k));
            }, 'Projekteinstellungen');
        });
    }
    function importDialog(files = [], preset = 'png') {
        pendingFiles = files;
        const filesLabel = el('div', { class: 'file-selection', text: files.length ? `${files.length} Datei${files.length === 1 ? '' : 'en'} ausgewählt` : 'Keine Dateien ausgewählt' });
        const choose = async (dir) => {
            const picked = await askFiles('.png,.json,.zip,.csv,.shsprite', true, dir);
            if (picked.length) {
                pendingFiles = picked;
                filesLabel.textContent = `${picked.length} Dateien ausgewählt`;
            }
        };
        const kind = field('Import', preset, {
            name: 'kind', wide: true, options: [['png', 'PNG-Serie / ZIP'], ['reference', 'SHCDE-Zielreferenzen (PNG / ZIP)'], ['atlas', 'Atlas + JSON'], ['referenceAtlas', 'SHCDE-Zielatlas + JSON'], ['metadata', 'Quellmetadaten (JSON)'], ['referenceMetadata', 'SHCDE-Zielmetadaten (JSON)'], ['mapping', 'Zielzuordnung (CSV)'], ['split', 'Gesamtbild für Schnitt'], ['ownership', 'Schnittmaske (PNG)']]
        }), sourceField = field('Herkunft', 'shde', { name: 'source', options: [['shde', 'Stronghold: Definitive Edition'], ['custom', 'Eigene Assets'], ['shcde', 'Crusader: Definitive Edition']], wide: true });
        modal('Dateien importieren', [filesLabel, buttons(button('Dateien auswählen…', () => choose(false)), button('Ordner auswählen…', () => choose(true))), fields(kind, sourceField, field('TexturePacker-Pivot-Ursprung', 'auto', { name: 'pivotOrigin', wide: true, options: [['auto', 'Bei Bedarf ausdrücklich wählen'], ['top-left', 'Oben links'], ['bottom-left', 'Unten links']] })), el('div', { class: 'field-inline' }, [checkbox('Nummernlücken als freie Rasterplätze erhalten', true, 'preserve')]),
            el('p', {
                text: 'Farb-PNGs und zugehörige _m.png gemeinsam wählen. Atlasimport: ein Farb-PNG, eine JSON-Datei und optional eine gleich große Maske. Keine GM1-Dateien oder Unity-Archive.'
            })], 'Importieren', async (data) => {
            if (!pendingFiles.length)
                throw new Error('Zuerst Dateien auswählen.');
            const type = String(data.get('kind')), optsBase = { source: String(data.get('source')), preserve: !!data.get('preserve'), pivotOrigin: String(data.get('pivotOrigin')) };
            await task('Dateien importieren', async (opts) => {
                const entries = await I.expandFiles(pendingFiles, opts);
                let result;
                if (entries.some(e => e.name === 'project.json'))
                    throw new Error('Das ist ein Projektarchiv. Über Projekt → Öffnen laden.');
                if (['png', 'reference'].includes(type)) {
                    if (entries.some(e => /(^|\/)atlas\.json$/i.test(e.name)))
                        throw new Error('Atlas-Metadaten gefunden. Als Atlas + JSON importieren, nicht als einzelne Serie.');
                    result = await I.importPNGs(entries, state(), store(), { ...opts, ...optsBase, reference: type === 'reference' });
                    const jsons = entries.filter(e => /\.json$/i.test(e.name));
                    for (const j of jsons) {
                        if (/(^|\/)schnitt\.json$/i.test(j.name)) {
                            const cut = C.json(K.decodeText(j.data));
                            if (cut.format !== 'stronghold-sprite-cut' || cut.version !== 1 || !Array.isArray(cut.tiles))
                                throw new Error('Unbekannte Schnittmetadaten.');
                            for (const gid of result.groups) {
                                const g = result.state.scenes.find(g => g.id === gid);
                                g.settings = C.scene({ ...cut.settings, anchor: 'bottom' });
                                for (const f of result.state.frames.filter(f => f.groupId === gid)) {
                                    const row = cut.tiles.find(t => t.name === f.name);
                                    if (!row)
                                        throw new Error('Schnittmetadaten unvollständig.');
                                    f.slot = row.slot;
                                    f.dx = row.offsetX;
                                    f.dy = row.offsetY;
                                }
                            }
                        }
                        else {
                            const rows = C.parseMetadata(C.json(K.decodeText(j.data)), optsBase);
                            result.state = I.applyMetadata(result.state, rows, { reference: type === 'reference', groupIds: type === 'png' ? result.groups : null }).state;
                        }
                    }
                }
                else if (type === 'atlas' || type === 'referenceAtlas')
                    result = await I.importAtlas(entries, state(), store(), { ...opts, ...optsBase, reference: type === 'referenceAtlas' });
                else if (type === 'metadata' || type === 'referenceMetadata') {
                    const jsons = entries.filter(e => /\.json$/i.test(e.name));
                    if (!jsons.length)
                        throw new Error('Keine JSON-Metadaten gefunden.');
                    let next = I.clone(state()), count = 0;
                    for (const j of jsons) {
                        const r = I.applyMetadata(next, C.parseMetadata(C.json(K.decodeText(j.data)), optsBase), { reference: type === 'referenceMetadata', groupId: type === 'metadata' ? groupId : null });
                        next = r.state;
                        count += r.count;
                    }
                    result = { state: next, store: store(), count };
                }
                else if (type === 'mapping') {
                    if (entries.length !== 1 || !/\.csv$/i.test(entries[0].name))
                        throw new Error('Genau eine CSV-Datei auswählen.');
                    result = { ...I.importMapping(state(), K.decodeText(entries[0].data), groupId), store: store() };
                }
                else if (type === 'split') {
                    const colors = entries.filter(e => /\.png$/i.test(e.name) && !/_m\.png$/i.test(e.name));
                    if (colors.length !== 1)
                        throw new Error('Genau ein Gesamtbild auswählen.');
                    const next = store().fork(), imageId = await next.decode(colors[0].data, opts), img = next.get(imageId), maskEntry = entries.find(e => e.name.toLowerCase() === colors[0].name.replace(/\.png$/i, '_m.png').toLowerCase()), maskId = maskEntry ? await next.decode(maskEntry.data, opts) : null;
                    const settings = C.scene(currentGroup()?.settings || C.DEFAULT_SCENE), anchorX = Math.round(img.width / 2 + (settings.a - settings.b) * settings.width / 4), anchorY = img.height - settings.padding;
                    if (settings.width > 64)
                        throw new Error('Neue Schnitte mit Überlappung benötigen höchstens 64 Pixel Tilebreite. Raster vorher anpassen.');
                    const map = C.partition(img, settings, anchorX, anchorY, true), mapId = next.add(C.ownershipImage(map, img.width, img.height)), s = I.clone(state());
                    s.split = { imageId, maskId, mapId, settings, anchorX, anchorY, extend: true, overlap: 1, rearShare: true, group: 'tile_custom', start: 0, source: optsBase.source };
                    result = { state: s, store: next, count: 1 };
                }
                else if (type === 'ownership') {
                    if (!state().split)
                        throw new Error('Zuerst ein Gesamtbild für den Schnitt laden.');
                    if (entries.length !== 1 || !/\.png$/i.test(entries[0].name))
                        throw new Error('Genau eine Schnittmaske auswählen.');
                    const next = store().fork(), mapId = await next.decode(entries[0].data, opts), s = I.clone(state());
                    s.split.mapId = mapId;
                    result = { state: s, store: next, count: 1 };
                }
                if (!result)
                    throw new Error('Unbekannter Importmodus.');
                commit(result.state, 'Import', result.store, { fit: true });
                if (result.groups?.length) {
                    groupId = result.groups[0];
                    selected = new Set(result.state.frames.filter(f => f.groupId === groupId).slice(0, 1).map(f => f.id));
                }
                if (type === 'split' || type === 'ownership')
                    view = 'split';
                render();
                message(`${result.count} Einträge importiert.`);
            });
        });
    }
    function renderGroups() {
        const select = $('group-select'), value = groupId;
        select.replaceChildren();
        if (!state().scenes.length)
            select.append(el('option', { value: '', text: 'Keine Gruppe' }));
        for (const g of state().scenes)
            select.append(el('option', { value: g.id, text: `${g.name} · ${g.source === 'shde' ? 'SHDE' : g.source === 'shcde' ? 'SHCDE' : 'Eigene'}` }));
        select.value = value;
    }
    const filtered = () => {
        const term = $('search').value.toLocaleLowerCase('de');
        return groupFrames().filter(f => !term || f.name.toLocaleLowerCase('de').includes(term) || f.targetName.toLocaleLowerCase('de').includes(term));
    };
    function thumbnail(assetId) {
        const key = assetId + ':thumb';
        if (visualCache.has(key))
            return visualCache.get(key).canvas;
        const img = store().get(assetId), canvas = document.createElement('canvas');
        canvas.width = 36;
        canvas.height = 36;
        const ctx = canvas.getContext('2d'), scale = Math.min(1, 36 / img.width, 36 / img.height), raw = canvasFor(assetId, 'rgba');
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(raw, Math.floor((36 - img.width * scale) / 2), Math.floor((36 - img.height * scale) / 2), img.width * scale, img.height * scale);
        addVisual(key, canvas, assetId);
        return canvas;
    }
    function addVisual(key, canvas, assetId) {
        const pixels = canvas.width * canvas.height;
        visualCache.set(key, { canvas, assetId, pixels });
        visualPixels += pixels;
        while (visualPixels > 16777216 && visualCache.size > 1) {
            const [old, item] = visualCache.entries().next().value;
            visualCache.delete(old);
            visualPixels -= item.pixels;
        }
        return canvas;
    }
    function canvasFor(assetId, channel = 'rgba') {
        const key = assetId + ':' + channel, hit = visualCache.get(key);
        if (hit) {
            visualCache.delete(key);
            visualCache.set(key, hit);
            return hit.canvas;
        }
        const raw = C.channel(store().get(assetId), channel), canvas = document.createElement('canvas');
        canvas.width = raw.width;
        canvas.height = raw.height;
        canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(raw.data.buffer, raw.data.byteOffset, raw.data.length), raw.width, raw.height), 0, 0);
        return addVisual(key, canvas, assetId);
    }
    function rawCanvas(img) {
        const cv = document.createElement('canvas');
        cv.width = img.width;
        cv.height = img.height;
        cv.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(img.data.buffer, img.data.byteOffset, img.data.length), img.width, img.height), 0, 0);
        return cv;
    }
    function renderList() {
        const list = filtered(), space = $('asset-space'), scroller = $('asset-list');
        space.style.height = Math.max(list.length * 52, 1) + 'px';
        space.replaceChildren();
        const start = Math.max(0, Math.floor(scroller.scrollTop / 52) - 5), end = Math.min(list.length, Math.ceil((scroller.scrollTop + scroller.clientHeight) / 52) + 5);
        for (let i = start; i < end; i++) {
            const f = list[i], a = store().get(f.imageId), row = el('button', {
                class: 'asset-row' + (f.visible ? '' : ' hidden-asset'), role: 'option', 'aria-selected': selected.has(f.id), tabIndex: -1, title: f.name, 'data-frame-id': f.id, onclick: e => selectFrame(f.id, e)
            });
            row.style.top = (i * 52) + 'px';
            const cv = el('canvas', { class: 'asset-thumb', width: 36, height: 36, 'aria-hidden': 'true' });
            cv.getContext('2d').drawImage(thumbnail(f.imageId), 0, 0);
            row.append(cv, el('span', { class: 'asset-text' }, [el('span', { class: 'asset-name', text: f.name }), el('span', { class: 'asset-sub', text: `${a.width} × ${a.height}  ·  ${f.maskId ? 'Maske  ·  ' : ''}#${f.slot + 1}${f.locked ? '  ·  Gesperrt' : ''}` })]));
            space.append(row);
        }
        if (!list.length)
            space.append(el('div', { class: 'empty-files', text: state().frames.length ? 'Keine passenden Dateien.' : 'Noch keine Dateien.' }));
        $('file-count').textContent = `${list.length} Dateien${selected.size > 1 ? ' · ' + selected.size + ' gewählt' : ''}`;
    }
    function selectFrame(id, event = {}) {
        const list = filtered();
        if (event.shiftKey && lastSelected) {
            const a = list.findIndex(f => f.id === lastSelected), b = list.findIndex(f => f.id === id);
            if (a >= 0 && b >= 0) {
                if (!event.ctrlKey && !event.metaKey)
                    selected.clear();
                for (let i = Math.min(a, b); i <= Math.max(a, b); i++)
                    selected.add(list[i].id);
            }
        }
        else if (event.ctrlKey || event.metaKey) {
            if (selected.has(id))
                selected.delete(id);
            else
                selected.add(id);
        }
        else
            selected = new Set([id]);
        lastSelected = id;
        animIndex = 0;
        renderList();
        renderInspector();
        requestDraw();
    }
    function selectAll() {
        selected = new Set(filtered().map(f => f.id));
        renderList();
        renderInspector();
        requestDraw();
    }
    function frameUpdate(fn, label = 'Sprite-Eigenschaften') {
        if (!selected.size)
            throw new Error('Zuerst Sprites auswählen.');
        edit(s => {
            for (const f of s.frames)
                if (selected.has(f.id))
                    fn(f);
        }, label);
    }
    function sceneSetting(key, value) {
        edit(s => {
            const g = s.scenes.find(g => g.id === groupId);
            if (!g)
                throw new Error('Keine Gruppe ausgewählt.');
            g.settings[key] = value;
        }, 'Rastereinstellung', { fit: true });
    }
    function exportSetting(key, value) {
        edit(s => {
            s.export[key] = value;
        }, 'Exporteinstellung', { fit: view === 'atlas' });
    }
    const num = (label, value, onchange, opts = {}) => field(label, value, { type: 'number', step: 1, onchange, ...opts });
    function sceneSection() {
        const g = currentGroup();
        if (!g)
            return null;
        const s = g.settings;
        return section('Raster', [
            fields(num('Links', s.a, v => sceneSetting('a', C.integer(v, 'Links', 1, 64)), { min: 1, max: 64 }), num('Rechts', s.b, v => sceneSetting('b', C.integer(v, 'Rechts', 1, 64)), { min: 1, max: 64 }), num('Tilebreite · px', s.width, v => sceneSetting('width', C.integer(v, 'Tilebreite', 2, 2048)), { min: 2, max: 2048, step: 2 }), num('Rautenhöhe · px', s.height, v => sceneSetting('height', C.integer(v, 'Rautenhöhe', 2, 2048)), { min: 2, max: 2048, step: 2 }), field('Anker', s.anchor, { wide: true, options: [['bottom', 'Unten mittig'], ['pivot', 'Sprite-Pivot']], onchange: v => sceneSetting('anchor', v) }), field('Ebenenreihenfolge', s.order, { wide: true, options: [['ascending', 'Niedrige Nummer zuerst'], ['descending', 'Hohe Nummer zuerst']], onchange: v => sceneSetting('order', v) }), field('Assettyp', s.category, { options: [['building', 'Gebäude'], ['unit', 'Einheiten'], ['vegetation', 'Vegetation'], ['other', 'Sonstige']], onchange: v => sceneSetting('category', v) }), num('Export-Rand · px', s.padding, v => sceneSetting('padding', C.integer(v, 'Rand', 0, 1024)), { min: 0, max: 1024 })),
            buttons(button('Plätze zuordnen…', slotDialog)), note('64 × 32 ist ein Arbeitsraster. Höhe, Anker und Überlappung an Originaldateien prüfen.')
        ]);
    }
    function frameSection() {
        const ff = chosen(), f = ff[0];
        if (!f)
            return section('Sprite', [note('Datei links auswählen.')]);
        const a = store().get(f.imageId), stats = C.alphaBounds(a);
        return section(ff.length === 1 ? f.name : `${ff.length} Sprites ausgewählt`, [
            line('Abmessungen', `${a.width} × ${a.height} px`), line('Metadaten', { assumed: 'Nicht importiert', imported: 'Importiert', manual: 'Manuell' }[f.metadataStatus]),
            fields(num('Versatz X · px', f.dx, v => frameUpdate(x => x.dx = C.integer(v, 'Versatz X'))), num('Versatz Y · px', f.dy, v => frameUpdate(x => x.dy = C.integer(v, 'Versatz Y'))), num('Pivot X', f.pivot.x, v => frameUpdate(x => {
                x.pivot.x = C.number(v, 'Pivot X', 0, 1);
                x.metadataStatus = 'manual';
            }), { min: 0, max: 1, step: .001 }), num('Pivot Y', f.pivot.y, v => frameUpdate(x => {
                x.pivot.y = C.number(v, 'Pivot Y', 0, 1);
                x.metadataStatus = 'manual';
            }), { min: 0, max: 1, step: .001 }), num('Pixels per Unit', f.ppu, v => frameUpdate(x => {
                x.ppu = C.number(v, 'PPU', .001, 65536);
                x.metadataStatus = 'manual';
            }), { min: .001, max: 65536, step: .1 }), num('Rasterplatz', f.slot + 1, v => {
                const slot = C.integer(v, 'Rasterplatz', 1, 4096) - 1;
                if (ff.length !== 1)
                    throw new Error('Rasterplätze einzeln oder über „Plätze zuordnen“ bearbeiten.');
                edit(s => {
                    const a = s.frames.find(t => t.id === f.id), other = s.frames.find(t => t.groupId === groupId && t.slot === slot);
                    if (other)
                        other.slot = a.slot;
                    a.slot = slot;
                }, 'Rasterplatz tauschen');
            }, { min: 1, max: 4096 })),
            buttons(checkbox('Sichtbar', ff.every(t => t.visible), '', v => frameUpdate(x => x.visible = v)), checkbox('Gesperrt', ff.every(t => t.locked), '', v => frameUpdate(x => x.locked = v))),
            buttons(button('Transformieren…', transformDialog), button('Originalzustand', resetOriginal)),
            buttons(button('PNG ersetzen…', () => replaceImage(false), { disabled: ff.length !== 1 }), button('Maske laden…', () => replaceImage(true), { disabled: ff.length !== 1 })),
            ...(f.maskId ? [buttons(button('Maske entfernen', () => frameUpdate(x => x.maskId = null)))] : []),
            line('Teiltransparente Pixel', stats.partial.toLocaleString('de-DE')), line('RGB bei Alpha 0', stats.hiddenRGB.toLocaleString('de-DE'))
        ]);
    }
    function splitSection() {
        const r = state().split;
        if (!r)
            return section('Schnitt', [button('Gesamtbild laden…', () => importDialog([], 'split')), note('Die Schnittmaske bleibt eindeutig. Neue Tiles teilen einen 1-Pixel-Rand; hinterste Reihen dürfen innerhalb der 64-Pixel-Breite Bildbereiche gemeinsam enthalten. Verdeckte Originalpixel lassen sich nicht rekonstruieren.')]);
        const s = r.settings, change = (key, v) => edit(st => {
            st.split[key] = v;
            if (key === 'overlap' && v === 0)
                st.split.rearShare = false;
            if (key === 'rearShare' && v)
                st.split.overlap = 1;
        }, 'Schnittparameter'), setting = (key, v) => {
            const next = store().fork(), st = I.clone(state());
            st.split.settings = C.scene({ ...st.split.settings, [key]: v });
            const r = st.split, img = next.get(r.imageId), map = C.partition(img, r.settings, r.anchorX, r.anchorY, r.extend);
            r.mapId = next.add(C.ownershipImage(map, img.width, img.height));
            commit(st, 'Schnittraster', next);
        };
        let stats;
        try {
            const src = store().get(r.imageId);
            stats = C.splitAnalysis(src, brushMap || C.ownershipMap(store().get(r.mapId), s.a * s.b), s, r.anchorX, r.anchorY, r.maskId ? store().get(r.maskId) : null);
        }
        catch (e) {
            stats = { error: e.message };
        }
        return section('Schnittraster', [
            fields(num('Links', s.a, v => setting('a', C.integer(v, 'Links', 1, 64)), { min: 1, max: 64 }), num('Rechts', s.b, v => setting('b', C.integer(v, 'Rechts', 1, 64)), { min: 1, max: 64 }), num('Tilebreite · px', s.width, v => setting('width', C.integer(v, 'Tilebreite', 2, r.overlap ? 64 : 2048)), { min: 2, max: r.overlap ? 64 : 2048, step: 2 }), num('Rautenhöhe · px', s.height, v => setting('height', C.integer(v, 'Rautenhöhe', 2, 2048)), { min: 2, max: 2048, step: 2 }), num('Frontanker X', r.anchorX, v => change('anchorX', C.integer(v, 'Anker X'))), num('Frontanker Y', r.anchorY, v => change('anchorY', C.integer(v, 'Anker Y')))),
            buttons(checkbox('Hintere Flächen nach oben verlängern', r.extend, '', v => change('extend', v))), buttons(button('Raster anwenden', regenerateSplit)),
            fields(num('Tile-Überlappung · px', r.overlap ?? 0, v => change('overlap', C.integer(v, 'Überlappung', 0, 1)), { min: 0, max: 1, step: 1 })),
            buttons(checkbox('Hintere Reihen: halbe Tileflächen teilen', r.rearShare ?? false, '', v => change('rearShare', v))),
            fields(field('Zielgruppe', r.group, { wide: true, onchange: v => change('group', v) }), num('Startindex', r.start, v => change('start', C.integer(v, 'Startindex', 0, 1000000)), { min: 0, max: 1000000 })),
            ...(stats.error ? [note(stats.error)] : [
                line('Nicht zugeordnet', stats.unassigned.toLocaleString('de-DE') + ' Pixel'),
                line('Breite überschritten', stats.overwide + ' Tiles'),
                ...(r.overlap && stats.partialAlphaPixels ? [line('Teiltransparente Pixel ohne Doppelung', stats.partialAlphaPixels.toLocaleString('de-DE'))] : []),
                ...(r.overlap && stats.materialMaskPixels ? [line('Materialmasken-Pixel ohne Doppelung', stats.materialMaskPixels.toLocaleString('de-DE'))] : [])
            ]),
            buttons(button('Maske importieren…', () => importDialog([], 'ownership')), button('Schnitt exportieren', () => exportDirect('split'))), note('1 px Überlappung kopiert nur voll deckende Bildpixel in benachbarte 64-px-Tiles. Halbtransparente Pixel und Materialmasken bleiben eindeutig, damit keine Doppelkonturen entstehen. Hintere Reihen teilen zusätzliche Bildflächen. Ältere Projekte behalten ihren bisherigen Schnittmodus. Rasteränderungen ersetzen die manuelle Zuordnung.')
        ]);
    }
    function atlasGroups() {
        return [...new Set(state().frames.filter(f => f.visible).map(f => {
                try {
                    return C.targetName(f.targetName).group;
                }
                catch (_e) {
                    return '';
                }
            }).filter(Boolean))];
    }
    function atlasFrames() {
        const groups = atlasGroups();
        if (!groups.includes(atlasGroup)) {
            let preferred = '';
            try {
                preferred = C.targetName(primary()?.targetName).group;
            }
            catch (_e) {
            }
            atlasGroup = groups.includes(preferred) ? preferred : groups[0] || '';
        }
        return state().frames.filter(f => f.visible && f.targetName && C.targetName(f.targetName).group === atlasGroup);
    }
    function atlasSection() {
        const e = state().export;
        atlasFrames();
        return section('Atlas', [
            fields(field('Zielgruppe in der Vorschau', atlasGroup, { wide: true, options: atlasGroups(), onchange: v => {
                    atlasGroup = v;
                    fitNext = true;
                    requestDraw();
                } })),
            fields(num('Abstand · px', e.padding, v => exportSetting('padding', C.integer(v, 'Abstand', 0, 32)), { min: 0, max: 32 }), num('Randwiederholung', e.extrude, v => exportSetting('extrude', C.integer(v, 'Rand', 0, 32)), { min: 0, max: 32 }), field('Maximale Kantenlänge', String(e.maxSide), { wide: true, options: ['512', '1024', '2048', '4096', '8192'], onchange: v => exportSetting('maxSide', Number(v)) })), note('Ohne Rotation. Breite und Höhe durch vier teilbar. JSON-Rechtecke und Pivots verwenden den Ursprung links unten.')
        ]);
    }
    function targetSection() {
        const ff = chosen(), f = ff[0], contents = [];
        if (f) {
            const ref = state().references.find(r => r.name === f.targetName);
            contents.push(section(ff.length === 1 ? 'Zielzuordnung' : `${ff.length} Zielzuordnungen`, [
                ...(ff.length === 1 ? [fields(field('SHCDE-Sprite', f.targetName, { wide: true, placeholder: 'tile_ruins-549', onchange: v => frameUpdate(x => {
                            x.targetName = v ? C.targetName(v).name : '';
                            x.targetConfirmed = false;
                        }) }))] : []),
                buttons(button('Serie zuordnen…', mappingDialog)),
                ...(ref ? [line('Zielreferenz', ref.imageId ? 'PNG vorhanden' : 'Nur Metadaten'), line('Zielgröße', ref.width && ref.height ? `${ref.width} × ${ref.height} px` : 'Nicht bekannt'), line('Ziel-PPU', ref.ppu ?? 'Nicht bekannt'), buttons(button('Pivot / PPU übernehmen', adoptReferences))] : [note('Keine passende SHCDE-Zielreferenz geladen. Gleiche Nummern in SHDE und SHCDE belegen keine gleiche Zuordnung.')])
            ]));
        }
        contents.push(section('Zielreferenzen', [line('Geladen', state().references.length), buttons(button('PNG / ZIP laden…', () => importDialog([], 'reference')), button('Metadaten…', () => importDialog([], 'referenceMetadata'))), buttons(button('CSV importieren…', () => importDialog([], 'mapping')), button('CSV exportieren', () => exportDirect('csv')))]));
        contents.push(section('Modausgabe', [
            fields(field('Ersetzungsweg', state().export.mode, { wide: true, options: [['atlas', 'Atlas-Override'], ['sprites', 'Einzel-Sprite-Override']], onchange: v => exportSetting('mode', v) }), field('Material', state().export.material, { wide: true, options: C.MATERIALS, onchange: v => exportSetting('material', v) })), note('Maskenkanäle werden nicht automatisch erzeugt oder umgedeutet. Material im Spiel prüfen. Atlas-Overrides sind eine experimentelle Funktion des Script Extenders.')
        ]));
        return contents;
    }
    function renderChecks() {
        const issues = I.preflight(state(), store()), errors = issues.filter(i => i.level === 'error'), warnings = issues.filter(i => i.level === 'warning');
        const grouped = new Map();
        for (const i of issues) {
            const key = i.level + '|' + i.code + '|' + i.message;
            if (!grouped.has(key))
                grouped.set(key, { ...i, count: 0 });
            grouped.get(key).count++;
        }
        const nodes = [el('div', { class: 'issue-summary' }, [el('span', { class: errors.length ? 'error-text' : '', text: `${errors.length} Fehler` }), el('span', { class: warnings.length ? 'warning-text' : 'muted', text: `${warnings.length} Hinweise` })])];
        for (const i of [...grouped.values()].slice(0, 80)) {
            nodes.push(button('', () => {
                if (i.frameId) {
                    const f = state().frames.find(f => f.id === i.frameId);
                    groupId = f.groupId;
                    selected = new Set([f.id]);
                    render();
                }
            }, { class: 'issue ' + i.level }));
            const n = nodes[nodes.length - 1];
            n.append(el('span', { text: i.count > 1 ? `${i.count} Sprites` : i.name || 'Projekt' }), document.createTextNode(i.message));
        }
        if (!issues.length)
            nodes.push(note('Keine formalen Exportfehler gefunden. Die Prüfung ersetzt keinen Test im Spiel.'));
        if (grouped.size > 80)
            nodes.push(note('Weitere Hinweise stehen im exportierten Prüfbericht.'));
        nodes.push(button('Prüfbericht exportieren', () => exportDirect('report')), note('Geprüft werden Daten, Zuordnung und Exportregeln. Rendering, Animationsbedeutung und Nutzungsrechte sind keine automatisch verifizierbaren Eigenschaften.'));
        return section('Exportprüfung', nodes);
    }
    function damageOpenScene(sceneId, editTiles = false) {
        if (!state().scenes.some(g => g.id === sceneId))
            throw new Error('Schadensmodell-Gruppe fehlt.');
        groupId = sceneId;
        selected = new Set(state().frames.filter(f => f.groupId === groupId).slice(0, 1).map(f => f.id));
        view = 'scene';
        if (editTiles) panel = 'properties';
        fitNext = true;
        render();
    }
    function damageStageEdit(stageId, updater, label = 'Schadensstufe bearbeiten') {
        edit(s => {
            const stage = (s.damageProfiles || []).flatMap(p => p.stages).find(x => x.id === stageId);
            if (!stage) throw new Error('Schadensstufe fehlt.');
            updater(stage);
        }, label);
    }
    function damageCreateDialog() {
        if (!damageBuildingId) throw new Error('Zuerst ein Gebäude wählen.');
        modal('Schadensstufe hinzufügen', [
            note('Die neue Stufe übernimmt die bestehenden Tiles als unabhängige, bearbeitbare Szene. Der normale Mod-Export ignoriert sie.'),
            fields(field('Schadensart', damageKind, { name: 'kind', wide: true, options: [['mechanical', 'Mechanisch'], ['fire', 'Feuer']] }),
                num('Anzeigen ab HP ≤ %', 75, null, { name: 'hp', min: 0, max: 99 })),
            fields(field('Name der Stufe', '', { name: 'label', wide: true, placeholder: 'Beschädigt / schwer beschädigt / Ruine' }))
        ], 'Stufe erstellen', data => {
            const result = DI.createStage(state(), store(), damageBuildingId,
                String(data.get('kind')), C.integer(data.get('hp'), 'HP-Schwelle', 0, 99),
                String(data.get('label') || ''));
            commit(result.state, 'Schadensstufe angelegt', result.store);
            damageKind = String(data.get('kind'));
            damageOpenScene(result.sceneId);
            message('Schadensmodell angelegt; Tiles jetzt bearbeiten oder KI-Referenz exportieren.');
        });
    }
    const localCodex = document.querySelector('meta[name="spritesuite-local"]')?.content;
    let codexStatus = '';
    async function codexCall(action, body) {
        if (!localCodex) throw new Error('Öffne den Sprite-Editor über SpriteSuite, um Codex zu verbinden.');
        const headers = { 'X-SpriteSuite-Session': localCodex };
        if (body) headers['Content-Type'] = 'application/zip';
        const response = await fetch('/codex/' + action, { method: 'POST', headers, body });
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.error || 'Der lokale Codex-Auftrag ist fehlgeschlagen.');
        }
        return response;
    }
    async function codexAccount(action) {
        await task(action === 'login' ? 'Bei ChatGPT anmelden' : 'ChatGPT-Anmeldung prüfen', async () => {
            const result = await (await codexCall(action)).json();
            codexStatus = result.chatgptConnected ? 'Mit ChatGPT verbunden' : 'ChatGPT-Anmeldung erforderlich';
            message(codexStatus);
        });
    }
    async function generatedImage(bundle, name) {
        const response = await codexCall('generate', bundle.bytes);
        const bytes = new Uint8Array(await response.arrayBuffer());
        const entries = await K.unzip(bytes);
        const candidate = entries.find(entry => entry.name === 'candidate.png');
        if (!candidate) {
            download(bytes, C.safeName(name) + '_codex_rohbild.zip', 'application/zip');
            message('Codex-Bild als ZIP gespeichert. Rohbild vor der Übernahme ausrichten.', true);
            return null;
        }
        return { image: await K.decodePNG(candidate.data), bytes };
    }
    async function generateDamage(stageId, opts) {
        const { stage, base } = DI.getStage(state(), stageId);
        const bundle = await DI.makeRequestBundle(state(), store(), stageId, opts);
        const result = await generatedImage(bundle, base.name + '_' + stage.kind + '_' + stage.hpAtOrBelow);
        if (!result) return false;
        const draft = DI.withCandidate(state(), store(), stageId, result.image);
        let model;
        try {
            model = DI.applyCandidate(draft.state, draft.store, stageId);
        }
        catch (error) {
            commit(draft.state, 'Codex-Kandidat gespeichert', draft.store);
            message('Codex-Kandidat gespeichert. Tiles lassen sich nach Ausrichtung übernehmen. ' + error.message, true);
            return false;
        }
        commit(model.state, 'Codex-Schadensmodell erstellt', model.store);
        message('Codex-Schadensmodell als bearbeitbare Tiles gespeichert.');
        return true;
    }
    function damageBatchDialog() {
        modal('Schadensmodelle mit Codex erstellen', [
            note('Wähle die HP-Schwellen je Schadensart. Codex erhält das Original und, soweit vorhanden, das nächstmildere Modell. Pro Stufe wird ein Bild erzeugt.'),
            fields(field('Mechanische HP-Schwellen', damageKind === 'mechanical' ? '75, 40, 0' : '', {
                name: 'mechanical', wide: true, placeholder: '75, 40, 0'
            })),
            fields(field('Feuer-HP-Schwellen', damageKind === 'fire' ? '75, 40, 0' : '', {
                name: 'fire', wide: true, placeholder: '75, 40, 0'
            })),
            fields(field('Gewünschte Schadensdetails', '', { name: 'details', type: 'textarea', wide: true }))
        ], 'Mit Codex generieren', async data => {
            const baseId = damageBuildingId;
            const stages = [];
            for (const kind of ['mechanical', 'fire']) {
                const values = String(data.get(kind)).trim().split(/[\s,]+/).filter(Boolean);
                const thresholds = values.map(value => C.integer(value, 'HP-Schwelle', 0, 99));
                if (new Set(thresholds).size !== thresholds.length) throw new Error('HP-Schwellen dürfen je Schadensart nur einmal vorkommen.');
                for (const hp of thresholds.sort((a, b) => b - a)) stages.push({ kind, hp });
            }
            if (!stages.length) throw new Error('Mindestens eine HP-Schwelle eingeben.');
            await task('Schadensmodelle mit Codex erstellen', async opts => {
                let next = state();
                const ids = [], detail = String(data.get('details')).trim();
                const existing = next.damageProfiles.find(p => p.buildingGroupId === baseId)?.stages || [];
                if (stages.some(({ kind, hp }) => existing.some(s => s.kind === kind && s.hpAtOrBelow === hp)))
                    throw new Error('Eine gewählte HP-Stufe ist bereits vorhanden. Dort kannst du ein neues Bild erzeugen.');
                for (const { kind, hp } of stages) {
                    const created = DI.createStage(next, store(), baseId, kind, hp);
                    next = created.state;
                    ids.push(created.stageId);
                    DI.getStage(next, created.stageId).stage.changeRequest = detail;
                }
                commit(next, 'Codex-Schadensstufen angelegt');
                let done = 0, processed = 0;
                for (const id of ids) {
                    opts.signal.throwIfAborted();
                    const { stage } = DI.getStage(state(), id);
                    opts.progress(processed++, ids.length, stage.kind + ' · ' + stage.hpAtOrBelow + '% HP');
                    if (await generateDamage(id, opts)) done++;
                }
                opts.progress(ids.length, ids.length);
                message(done + ' / ' + ids.length + ' Codex-Schadensmodelle als Tiles gespeichert.', done < ids.length);
            });
        });
    }
    function buildingVersionDialog(mode) {
        const baseId = damageBuildingId;
        const base = state().scenes.find(scene => scene.id === baseId);
        modal('Neue Gebäudeversion', [
            fields(field('Name der Version', base.name + ' v2', { name: 'label', wide: true })),
            ...(mode === 'import' ? [] : [
                note('Das ausgewählte Gebäude dient als Vorlage für Stil, Typ, Raster und Perspektive.'),
                fields(field('Gewünschte Änderungen', '', { name: 'details', wide: true, type: 'textarea' }))
            ]),
            ...(mode === 'export' ? [] : [checkbox('Pixel außerhalb des Tile-Rasters ausblenden', false, 'fit')])
        ], mode === 'import' ? 'PNG wählen…' : mode === 'export' ? 'Codex-Anfrage exportieren' : 'Mit Codex generieren',
        async data => {
            const label = String(data.get('label')).trim();
            if (mode === 'import') {
                const files = await askFiles('.png', false);
                if (!files.length) return;
                await task('Gebäudeversion übernehmen', async opts => {
                    const image = await K.decodePNG(new Uint8Array(await files[0].arrayBuffer()), opts);
                    applyVersion(baseId, label, image, data.has('fit'));
                });
                return;
            }
            await task('Codex-Gebäudeversion vorbereiten', async opts => {
                const bundle = await DI.makeVersionBundle(state(), store(), baseId, String(data.get('details')), opts);
                if (mode === 'export') {
                    download(bundle.bytes, C.safeName(label || base.name) + '_codex.zip', 'application/zip');
                    return;
                }
                const result = await generatedImage(bundle, label || base.name);
                if (!result) return;
                try {
                    applyVersion(baseId, label, result.image, data.has('fit'));
                    if (data.has('fit'))
                        download(result.bytes, C.safeName(label || base.name) + '_codex_original.zip', 'application/zip');
                }
                catch (error) {
                    download(result.bytes, C.safeName(label || base.name) + '_codex.zip', 'application/zip');
                    throw error;
                }
            });
        });
    }
    function applyVersion(baseId, label, image, fit) {
        const result = DI.withBuildingVersion(state(), store(), baseId, label, image, fit);
        commit(result.state, 'Neue Gebäudeversion erstellt', result.store);
        damageBuildingId = result.sceneId;
        damageOpenScene(result.sceneId);
        const warnings = result.report.warnings;
        message(warnings.length ? warnings.join(' ') : 'Neue Gebäudeversion als bearbeitbare Tiles gespeichert.');
    }
    async function damageRequestBundle(stageId) {
        await task('Codex-Referenz vorbereiten', async opts => {
            const { stage, base } = DI.getStage(state(), stageId);
            const result = await DI.makeRequestBundle(state(), store(), stageId, opts);
            download(result.bytes, C.safeName(base.name + '_' + stage.kind + '_' + stage.hpAtOrBelow) + '_codex.zip');
            message('Referenz, Prompt und Codex-Anweisung exportiert.');
        });
    }
    async function damageImportCandidate(stageId) {
        const files = await askFiles('.png', false);
        if (!files.length) return;
        await task('Kandidatenbild prüfen', async opts => {
            if (files.length !== 1 || !/\.png$/i.test(files[0].name))
                throw new Error('Genau eine RGBA-PNG-Datei wählen.');
            const img = await K.decodePNG(new Uint8Array(await files[0].arrayBuffer()), opts);
            const result = DI.withCandidate(state(), store(), stageId, img);
            commit(result.state, 'Schadensmodell-Kandidat importiert', result.store);
            const problems = [...result.report.errors, ...result.report.warnings];
            message(problems.length ? 'Kandidat gespeichert, Prüfung: ' + problems.slice(0, 2).join(' ') :
                'Kandidat gespeichert. Original und Modell vergleichen, dann als Tiles übernehmen.', !!result.report.errors.length);
        });
    }
    async function damageApplyCandidate(stageId, fit = false) {
        await task('Schadensmodell als 64px-Tiles zerlegen', async () => {
            const result = DI.applyCandidate(state(), store(), stageId, fit);
            commit(result.state, 'Kandidat als Schadens-Tiles übernommen', result.store, { fit: true });
            const { scene } = DI.getStage(result.state, stageId);
            damageOpenScene(scene.id);
            message(result.clippedPixels ?
                'Tiles gespeichert. Ausgeblendete Pixel: ' + result.clippedPixels + '. Kandidaten-PNG bleibt im Projekt.' :
                'Kandidat pixelgenau und mit hinteren 1-px-Überlappungen zerlegt. Export ist direkt möglich.');
        });
    }
    function damagePreview(img, label) {
        const scale = Math.min(1, 235 / img.width, 200 / img.height);
        const width = Math.max(1, Math.round(img.width * scale));
        const height = Math.max(1, Math.round(img.height * scale));
        const small = width === img.width && height === img.height ? img : C.resize(img, width, height);
        const canvas = el('canvas', { class: 'damage-review-canvas', width, height,
            title: label, 'aria-label': label });
        canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(small.data), width, height), 0, 0);
        return el('div', { class: 'damage-review-image' }, [
            el('strong', { text: label }), canvas
        ]);
    }
    function damageApproveDialog(stageId) {
        const { stage, profile } = DI.getStage(state(), stageId);
        const review = DI.qualityReport(state(), store(), stageId);
        const closestApproved = profile.stages.filter(s => s.id !== stage.id &&
            s.kind === stage.kind && s.status === 'approved')
            .sort((a, b) => Math.abs(a.hpAtOrBelow - stage.hpAtOrBelow) -
                Math.abs(b.hpAtOrBelow - stage.hpAtOrBelow))[0] || null;
        const summary = [
            line('Sichtbar veränderte Pixel', (review.stats.changedPixels || 0).toLocaleString('de-DE')),
            line('Veränderung · % Original', (review.stats.visibleChangesPercent ?? 0) + '%'),
            ...(review.stats.structuralLossPixels === undefined ? [] : [
                line('Entfernte opake Originalpixel', review.stats.structuralLossPixels),
                line('Neue opake Bildpixel', review.stats.newOpaquePixels)
            ]),
            ...(review.stats.maskedPixels === undefined ? [] : [
                line('Maskenpixel ohne sichtbare Bilddeckung', review.stats.orphanMaskPixels)
            ])
        ];
        modal('Schadensmodell vergleichen · optionale Notiz', [
            el('div', { class: 'damage-review-gallery' }, [
                damagePreview(review.intact, 'Original'),
                ...(closestApproved ? [damagePreview(DI.baseComposite(state(), store(), closestApproved.sceneId).image,
                    'Bereits freigegeben · ' + closestApproved.hpAtOrBelow + '% HP')] : []),
                damagePreview(review.damaged, 'Schadensmodell')
            ]),
            ...summary,
            ...review.errors.map(msg => el('p', { class: 'error-text', text: msg })),
            ...review.warnings.map(msg => el('p', { class: 'warning-text', text: msg })),
            note('Vergleich und Notizen sind optional. Modelle können ohne Freigabe direkt verwendet und exportiert werden.'),
            fields(field('Notiz (optional)', stage.reviewNotes, { name: 'notes', type: 'textarea', wide: true }))
        ], 'Als geprüft markieren', data => {
            const result = DI.approveStage(state(), store(), stageId, data.get('notes'), data.has('confirmed'));
            commit(result.state, 'Schadensstufe freigegeben', result.store, { keepDamageApproval: true });
            message('Optionaler Vergleichsmarker gespeichert. Export ist unabhängig davon möglich.');
        });
    }
    function damageRemove(stageId) {
        const { stage } = DI.getStage(state(), stageId);
        confirmDialog('Schadensstufe entfernen', 'Nur diese Schadensstufe mit ihrer Szene entfernen? Im Projektverlauf kann sie rückgängig gemacht werden.', () => {
            edit(s => {
                for (const p of s.damageProfiles) p.stages = p.stages.filter(x => x.id !== stageId);
                s.damageProfiles = s.damageProfiles.filter(p => p.stages.length);
                s.scenes = s.scenes.filter(g => g.id !== stage.sceneId);
                s.frames = s.frames.filter(f => f.groupId !== stage.sceneId);
            }, 'Schadensstufe entfernt');
        });
    }
    async function damageExportPackage(includeDrafts = true) {
        await task('Schadensbibliothek exportieren', async opts => {
            const result = await DI.exportPackage(state(), store(), { ...opts, includeDrafts });
            const suffix = includeDrafts ? '_gebaeudeschaden.zip' : '_gebaeudeschaden_markiert.zip';
            download(result.bytes, C.safeName(state().project.name) + suffix);
            message(includeDrafts ? 'Alle Schadensstufen frei exportiert, einschließlich Entwürfen.' :
                'Freigegebene Stufen und HP-Manifest exportiert.');
        });
    }
    function damageSection() {
        const stageSceneIds = D.stageScenes(state().damageProfiles || []);
        const buildings = state().scenes.filter(g => g.settings.category === 'building' && !stageSceneIds.has(g.id));
        if (!buildings.length)
            return [section('Gebäudeschäden', [
                note('Zuerst eine Gebäude-PNG-Serie oder ein Projekt importieren. Schadenstufen sind zusätzliche Szenen, keine neuen Gameplay-Gebäude.'),
                buttons(button('Gebäudesprites importieren…', () => importDialog([], 'png')))
            ])];
        if (!buildings.some(g => g.id === damageBuildingId))
            damageBuildingId = buildings.some(g => g.id === groupId) ? groupId : buildings[0].id;
        const base = buildings.find(g => g.id === damageBuildingId);
        const profile = (state().damageProfiles || []).find(p => p.buildingGroupId === base.id);
        const previewProfile = profile && damageApprovedOnly ?
            { stages: profile.stages.filter(s => s.status === 'approved') } : profile;
        const selectedStage = D.choose(previewProfile, damageKind, damageHp);
        const info = [
            fields(field('Gebäude', damageBuildingId, { wide: true,
                options: buildings.map(g => [g.id, g.name]),
                onchange: v => { damageBuildingId = v; renderInspector(); } })),
            ...(profile ? [fields(field('Spiel-Gebäudetyp (optional)', profile.gameBuildingType ?? '', {
                wide: true, placeholder: 'Z. B. 108 – aus Zielspiel-Metadaten prüfen',
                onchange: v => edit(s => {
                    const p = s.damageProfiles.find(x => x.buildingGroupId === base.id);
                    p.gameBuildingType = String(v).trim() === '' ? null :
                        C.integer(v, 'Gebäudetyp im Spiel', 0, 4095);
                }, 'Spiel-Gebäudetyp zuordnen')
            }))] : []),
            fields(field('Schadensursache', damageKind, {
                options: [['mechanical', 'Mechanisch'], ['fire', 'Feuerschaden']],
                onchange: v => { damageKind = v; renderInspector(); }
            }), num('Verbleibende HP · %', damageHp, v => {
                damageHp = C.number(v, 'HP', 0, 100);
                renderInspector();
            }, { min: 0, max: 100 })),
            fields(field('Vorschau-Modus', damageApprovedOnly ? 'approved' : 'all', {
                wide: true, options: [['all', 'Alle Modelle einschließlich Entwürfen'],
                    ['approved', 'Nur als geprüft markierte Modelle']],
                onchange: v => { damageApprovedOnly = v === 'approved'; renderInspector(); }
            })),
            line('Freigabestatus', selectedStage ?
                ({draft:'Entwurf', approved:'Freigegeben', rejected:'Verworfen'}[selectedStage.status] || 'Entwurf') : 'Original'),
            line('Modell bei ' + damageHp + '% HP', selectedStage ? (selectedStage.label ||
                selectedStage.kind + ' ≤' + selectedStage.hpAtOrBelow + '%') : 'Original / unbeschädigt'),
            buttons(button('Vorschau anzeigen', () => damageOpenScene(selectedStage ? selectedStage.sceneId : base.id))),
            buttons(button('Neue Schadensstufe…', damageCreateDialog)),
            note('Schwellen gelten inklusive Grenzwert. Beispiel 75/40/0: 100–76 % intakt, 75–41 % leicht, 40–1 % schwer, 0 % zerstört. Feuer nutzt nur dann mechanische Stufen als Fallback, wenn keine Feuerstufe existiert.')
        ];
        const codexActions = [
            ...(localCodex ? [
                line('ChatGPT-Konto', codexStatus || 'Lokaler Codex-Client'),
                buttons(button('Bei ChatGPT anmelden…', () => codexAccount('login')),
                    button('Anmeldung prüfen', () => codexAccount('status'))),
                buttons(button('Schadensmodelle mit Codex erstellen…', damageBatchDialog),
                    button('Gebäudeversion mit Codex erstellen…', () => buildingVersionDialog('generate'))),
                note('Bildaufträge nutzen deinen ChatGPT-Tarif und gegebenenfalls Codex-Guthaben. Abbrechen stoppt weitere Aufträge nach dem laufenden Bild.')
            ] : [note('Für direkte Codex-Generierung den Sprite-Editor über SpriteSuite öffnen.')]),
            buttons(button('Gebäudeversion für Codex exportieren…', () => buildingVersionDialog('export')),
                button('PNG als Gebäudeversion importieren…', () => buildingVersionDialog('import')))
        ];
        const sections = [section('Gebäude und HP-Test', info), section('KI-Sprites mit Codex', codexActions)];
        const stages = profile ? profile.stages.filter(s => s.kind === damageKind) : [];
        if (!stages.length)
            sections.push(section('Schadensmodelle', [note('Für diesen Schadenstyp sind noch keine eigenen Stufen vorhanden.')]));
        for (const stage of stages) {
            const status = { draft: 'Entwurf', approved: 'Freigegeben', rejected: 'Verworfen' }[stage.status];
            sections.push(section((stage.label || damageKind) + ' · ' + status, [
                fields(num('Modell ab HP ≤ %', stage.hpAtOrBelow, v => damageStageEdit(stage.id, s => {
                    s.hpAtOrBelow = C.integer(v, 'HP-Schwelle', 0, 99);
                    s.status = 'draft';
                }), { min: 0, max: 99 })),
                fields(field('Bezeichnung', stage.label, { wide: true, onchange: v =>
                    damageStageEdit(stage.id, s => s.label = v) })),
                fields(field('Nachbesserung / Änderungswunsch', stage.changeRequest, {
                    type: 'textarea', wide: true, onchange: v =>
                        damageStageEdit(stage.id, s => s.changeRequest = v)
                })),
                line('Kandidaten-PNG', stage.candidateId ? 'Im Projekt gesichert' : 'Noch nicht vorhanden'),
                buttons(button('Tiles bearbeiten', () => damageOpenScene(stage.sceneId, true)),
                    button('Vorschau', () => damageOpenScene(stage.sceneId))),
                buttons(...(localCodex ? [button('Mit Codex generieren', () =>
                    task('Schadensmodell mit Codex erstellen', opts => generateDamage(stage.id, opts)))] : []),
                    button('Codex-Prompt + Original exportieren…', () => damageRequestBundle(stage.id))),
                buttons(button('Generiertes PNG importieren…', () => damageImportCandidate(stage.id)),
                    button('PNG als Tiles zerlegen', () => damageApplyCandidate(stage.id), { disabled: !stage.candidateId })),
                ...(stage.candidateId ? [
                    buttons(button('Kopie ans Tile-Raster anpassen', () => damageApplyCandidate(stage.id, true))),
                    note('Die Rasteranpassung blendet Pixel ohne Tile-Zuordnung aus. Das Kandidaten-PNG bleibt erhalten.'),
                    buttons(button('Kandidat verwerfen', () => damageStageEdit(stage.id,
                        s => { s.candidateId = null; s.status = 'draft'; })))
                ] : []),
                buttons(button('Vergleich und Notiz…', () => damageApproveDialog(stage.id)),
                    button('Verwerfen', () => damageStageEdit(stage.id, s => s.status = 'rejected'))),
                buttons(button('Stufe entfernen…', () => damageRemove(stage.id))),
                note('Prüfnotizen sind optional und an den damaligen Pixelstand gebunden. Geänderte Modelle bleiben direkt exportierbar.')
            ]));
        }
        sections.push(section('Ausgabe', [
            buttons(button('HP-Schadensmodelle exportieren…', () => damageExportPackage(true)),
                button('Nur markierte Schadensmodelle exportieren…', () => damageExportPackage(false))),
            note('Standardexport: alle Stufen einschließlich Entwürfen und verworfenen Varianten. Der optionale zweite Export filtert nur nach gesetztem Vergleichsmarker. Beide ZIPs sind eigenständige Grafikpakete.')
        ]));
        return sections;
    }
    function activeMeasurement() {
        const f = primary();
        return f && measurement && measurement.frameId === f.id &&
            measurement.imageId === f.imageId ? measurement : null;
    }
    function geometrySection() {
        const f = primary();
        if (!f) return section('Anker, Ebenen & Messungen', [
            note('Zum Vermessen zunächst links einen Sprite auswählen.')]);
        const img = store().get(f.imageId), p = C.pixelAnchor(f, img), m = activeMeasurement();
        return section('Anker, Ebenen & Messungen', [
            line('Bildgröße', img.width + ' × ' + img.height + ' px'),
            line('Pivot in Pixeln', p.x.toFixed(2) + ' / ' + p.y.toFixed(2)),
            line('Versatz', f.dx + ' / ' + f.dy + ' px'),
            fields(field('Fangraster · Pixel', String(snapStep), {
                wide: true, options: ['1', '2', '4', '8'],
                onchange: v => { snapStep = C.integer(v, 'Fangraster', 1, 8); renderInspector(); }
            })),
            buttons(button('Pivot auf Fangraster', () => {
                if (f.locked) throw new Error('Sprite ist gesperrt.');
                frameUpdate(x => {
                    x.pivot = C.pivotFromPixel(img,
                        C.snapCoordinate(p.x, snapStep), C.snapCoordinate(p.y, snapStep), false);
                    x.metadataStatus = 'manual';
                }, 'Pivot auf Pixelraster');
            }), button('Bodenmitte', () => {
                if (f.locked) throw new Error('Sprite ist gesperrt.');
                frameUpdate(x => {
                    x.pivot = { x: .5, y: 0 }; x.metadataStatus = 'manual';
                }, 'Bodenanker ausrichten');
            })),
            buttons(button('Zwei Bildpunkte messen', () => {
                selected = new Set([f.id]);
                measureTool = true;
                pivotTool = false;
                measureStart = null;
                $('compare').value = 'current';
                setView('sprite');
                render();
            }), button('Pivot per Mausklick', () => {
                selected = new Set([f.id]);
                pivotTool = true;
                measureTool = false;
                measureStart = null;
                $('compare').value = 'current';
                setView('sprite');
                render();
            })),
            ...(m ? [
                line('Gemessener Abstand X / Y', m.dx + ' / ' + m.dy + ' px'),
                line('Strecke', m.length.toFixed(2) + ' px'),
                line('Winkel', m.angleDegrees.toFixed(1) + '°'),
                buttons(button('Als Sprite-Versatz übernehmen…', () => {
                    if (f.locked) throw new Error('Sprite ist gesperrt.');
                    confirmDialog('Messung auf Versatz anwenden',
                        'Den gemessenen Abstand (' + m.dx + ', ' + m.dy +
                        ' px) zum bestehenden Versatz addieren? Original bleibt unverändert.',
                        () => frameUpdate(x => {
                            x.dx = C.integer(x.dx + m.dx, 'Versatz X');
                            x.dy = C.integer(x.dy + m.dy, 'Versatz Y');
                        }, 'Messung als Versatz übernehmen'));
                }), button('Messprotokoll exportieren', async () => {
                    const source = await store().bytes(f.imageId);
                    download(JSON.stringify({
                        schema: 'sprite-suite.geometry-measurement.v1',
                        frameName: f.name, imageSHA256: await K.sha256(source),
                        width: img.width, height: img.height,
                        pivot: { ...f.pivot }, snapStep, measurement: m,
                        approvedForGame: false
                    }, null, 2) + '\n', C.safeName(f.name) + '_messung.json', 'application/json');
                }))
            ] : [note(measureStart ? 'Startpunkt gesetzt. Zweiten Punkt im Bild anklicken.' :
                'Messmodus: Im Sprite-Bild nacheinander Start- und Endpunkt anklicken. ' +
                'Die Messung ändert keine Bilddaten oder Versätze.')]),
            note('Überlagerung und Transparenz im Sprite-Reiter vergleichen. Alte ' +
                 'Zinnenlineal-Messdateien bleiben als nachvollziehbare Importbelege erhalten.')
        ]);
    }
    /** Historical in-game ruler data is now a specialist input to this canvas. */
    function legacyPivotReview(frame = primary()) {
        if (!legacyPivotFile || !frame) return null;
        const found = legacyPivotFile.rows.filter(row =>
            PE.matchesFrame(row, frame));
        if (found.length !== 1) return null;
        return PE.review(found[0], state().frames, store());
    }
    async function loadLegacyPivotFile() {
        const files = await askFiles('.json', false);
        if (!files.length) return;
        if (files.length !== 1 || files[0].size > 2 * 1024 * 1024)
            throw new Error('Nur eine Zinnenlineal-JSON-Datei bis 2 MiB wählen.');
        await task('Zinnen-Messdaten ohne Spieländerung lesen', async opts => {
            const bytes = new Uint8Array(await files[0].arrayBuffer());
            K.aborted(opts.signal);
            const decoded = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
            const rows = PE.parseMeasurements(decoded);
            const sourceSHA256 = await K.sha256(bytes);
            legacyPivotFile = { rows, filename: C.safeName(files[0].name), sourceSHA256 };
            showLegacyPivot = true;
            panel = 'geometry';
            message(rows.length + ' historische Zinnenlineal-Messungen geladen; keine Sprites geändert.');
        });
    }
    function showLegacyPivotOverlay() {
        const review = legacyPivotReview();
        if (!review) throw new Error('Kein eindeutiger Zinnenlineal-Eintrag für diesen Sprite.');
        if (!['review', 'already'].includes(review.status))
            throw new Error(review.reason);
        showLegacyPivot = true;
        $('compare').value = 'current';
        setView('sprite');
        requestDraw();
    }
    function applyLegacyPivotReview() {
        const frame = primary(), file = legacyPivotFile, review = legacyPivotReview();
        if (!file || !frame || !review || review.status !== 'review')
            throw new Error('Keine prüfbare Pivot-Messung für den ausgewählten Sprite.');
        const boundImageId = frame.imageId, row = review.row;
        modal('Gemessenen Pivot einzeln übernehmen', [
            note('Geometrievorschlag aus ' + file.filename + '. Die Grafik bleibt unverändert; ' +
                'weder BC7-Atlas noch installierte SHCDE-Dateien werden verändert.'),
            line('Sprite', frame.name),
            line('Messung', row.name + ' · rechts ' + row.right + ' / hoch ' + row.up + ' px'),
            line('Ausgangspivot', row.oldPivot.x.toFixed(6) + ' / ' + row.oldPivot.y.toFixed(6)),
            line('Zielpivot', row.newPivot.x.toFixed(6) + ' / ' + row.newPivot.y.toFixed(6)),
            line('Messquellen-SHA', file.sourceSHA256.slice(0, 24) + '…'),
            damagePreview(store().get(frame.imageId), 'Arbeitsbild vor Pivotkorrektur'),
            fields(field('Notiz (optional)', '', { type: 'textarea', name: 'notes',
                wide: true, placeholder: 'Sichtprüfung der Grundlinie und Sprite-Position' }))
        ], 'Nur Arbeits-Pivot übernehmen', data => {
            const notes = String(data.get('notes') || '').trim();
            if (notes.length > 1200) throw new Error('Notiz überschreitet 1200 Zeichen.');
            const now = primary(), checked = legacyPivotReview();
            if (file !== legacyPivotFile || !now ||
                    now.id !== frame.id || now.imageId !== boundImageId ||
                    !checked || checked.status !== 'review' ||
                    checked.row.name !== row.name)
                throw new Error('Bild oder Messquelle hat sich geändert; Prüfung wiederholen.');
            const contentHash = I.imageContentSHA256(store().get(boundImageId));
            edit(next => {
                const updated = next.frames.find(item => item.id === frame.id);
                if (!updated || updated.locked || updated.imageId !== boundImageId)
                    throw new Error('Sprite gesperrt oder nicht mehr vorhanden.');
                updated.pivot = { ...row.newPivot };
                updated.metadataStatus = 'manual';
                updated.pivotEvidence = {
                    appliedImageId: boundImageId, measurementSHA256: file.sourceSHA256,
                    imageContentSHA256: contentHash, measuredFrameName: row.name,
                    proposedPivot: { ...row.newPivot }, reviewNotes: notes,
                    manualReview: false, approvedForGame: false
                };
            }, 'Zinnenlineal-Pivot nach visueller Prüfung');
            message('Messpivot in der Arbeitskopie übernommen; Original und Spiel unverändert.');
        });
    }
    function exportLegacyPivotReport() {
        const file = legacyPivotFile;
        if (!file) throw new Error('Keine Zinnenlineal-Messungen geladen.');
        const rows = PE.reviewAll(file.rows, state(), store()).map(result => ({
            name: result.row.name, frameId: result.frameId, frameName: result.frameName || null,
            status: result.status, reason: result.reason,
            measuredOld: result.row.oldPivot, measuredNew: result.row.newPivot,
            currentPivot: result.currentPivot || null,
            approvedForGame: false
        }));
        download(JSON.stringify({
            schema: 'sprite-suite.pivot-evidence-inspection.v1',
            measurementSHA256: file.sourceSHA256,
            measurementName: file.filename, rows,
            installedGameChanged: false, approvedForGame: false
        }, null, 2) + '\n', C.safeName(file.filename) + '_vergleich.json', 'application/json');
    }
    function legacyPivotSection() {
        const file = legacyPivotFile, frame = primary(), review = legacyPivotReview(frame);
        const items = [
            note('Historisches Zinnenlineal direkt im Geometrie-Editor. ' +
                'Bestehende Messungen werden nur lesend übernommen; keine automatische Atlasänderung.'),
            buttons(button('Zinnenlineal-JSON öffnen…', loadLegacyPivotFile))
        ];
        if (file) {
            items.push(line('Messdatei', file.filename),
                line('Messungen', file.rows.length),
                line('SHA-256', file.sourceSHA256.slice(0, 20) + '…'),
                buttons(button('Messungsbericht exportieren…', exportLegacyPivotReport),
                    button('Messdatei schließen', () => {
                        legacyPivotFile = null;
                        renderInspector();
                        requestDraw();
                    })));
            if (review) {
                items.push(line('Zugeordneter Frame', review.row.name),
                    line('Prüfstatus', review.status),
                    note(review.reason),
                    line('Aktueller Pivot', review.currentPivot.x.toFixed(6) +
                        ' / ' + review.currentPivot.y.toFixed(6)),
                    line('Messvorschlag', review.row.newPivot.x.toFixed(6) +
                        ' / ' + review.row.newPivot.y.toFixed(6)),
                    buttons(button('Anker-Overlay anzeigen', showLegacyPivotOverlay, {
                        disabled: !['review', 'already'].includes(review.status)
                    }), button('Gemessenen Pivot übernehmen…', applyLegacyPivotReview, {
                        disabled: review.status !== 'review'
                    })));
            } else
                items.push(note(frame ? 'Für diese Sprite-Gruppe wurde kein eindeutiger Messwert gefunden.' :
                    'Nach dem Import links einen Sprite auswählen.'));
        }
        if (frame?.pivotEvidence)
            items.push(line('Letzter Pivot-Prüfvermerk', frame.pivotEvidence.reviewNotes));
        return section('Zinnenlineal · Messdaten im gemeinsamen Editor', items);
    }
    function aiActiveCandidates() {
        const frame = primary();
        return frame ? aiCandidates.filter(row => row.frameId === frame.id &&
            row.sourceImageId === frame.imageId) : [];
    }
    async function aiExportRequest(generate = false) {
        const frame = primary();
        if (!frame) throw new Error('Zuerst einen Sprite auswählen.');
        const sourceImageId = frame.imageId;
        const settings = AI.options({ assetClass: aiAssetClass, goal: aiGoal,
            restrictions: aiRestrictions, model: aiModel, variants: aiVariants });
        let generatedFiles = null;
        await task('KI-Anfrage mit unveränderter Bildreferenz vorbereiten', async opts => {
            const sourcePNG = await store().bytes(sourceImageId, opts.signal);
            const payload = await AI.makeRequestBundle(store().get(sourceImageId), sourcePNG, settings);
            if (primary()?.id !== frame.id || primary()?.imageId !== sourceImageId)
                throw new Error('Sprite wurde während der Anfragevorbereitung geändert.');
            aiLastRequest = { frameId: frame.id, sourceImageId,
                request: payload.request, requestSHA256: payload.requestSHA256 };
            if (generate) {
                const response = await codexCall('generate', payload.bytes);
                const bytes = new Uint8Array(await response.arrayBuffer());
                const entries = await K.unzip(bytes);
                const candidates = entries.filter(entry => /^variant_0[1-4]\.png$/.test(entry.name));
                const names = new Set(candidates.map(entry => entry.name.replace(/\.png$/, '_meta.json')));
                download(bytes, C.safeName(frame.name) + '_codex_ergebnisse.zip', 'application/zip');
                if (!candidates.length)
                    throw new Error('Modellausgabe benötigt eine erneute Ausrichtungsprüfung. Rohbilder und Belege wurden gesichert.');
                generatedFiles = entries.filter(entry => candidates.includes(entry) || names.has(entry.name))
                    .map(entry => new File([entry.data], entry.name));
            } else {
                download(payload.bytes, C.safeName(frame.name) + '_ki_auftrag.zip');
                message('KI-Auftragsbundle exportiert.');
            }
        });
        if (generatedFiles) await aiImportCandidates(generatedFiles);
    }
    async function aiImportCandidates(generatedFiles = null) {
        const frame = primary();
        if (!frame) throw new Error('Zuerst einen Sprite auswählen.');
        const files = generatedFiles || await askFiles('.png,.json', true);
        if (!files.length) return;
        const pngs = files.filter(file => /\.png$/i.test(file.name));
        const metas = files.filter(file => /_meta\.json$/i.test(file.name));
        if (pngs.length < 1 || pngs.length > 4 ||
                files.length !== pngs.length + metas.length ||
                metas.length > pngs.length || files.length > 8)
            throw new Error('Bis vier PNG-Kandidaten und optional ihre _meta.json-Dateien wählen.');
        const fileNames = new Set(files.map(file => file.name.toLowerCase()));
        if (fileNames.size !== files.length)
            throw new Error('Doppelte Kandidatendateinamen.');
        const sourceImageId = frame.imageId;
        await task('Bildvarianten und Herkunftsnachweise prüfen', async opts => {
            const original = store().get(sourceImageId), incoming = [];
            const sourceSHA256 = await K.sha256(await store().bytes(sourceImageId, opts.signal));
            const planned = aiLastRequest?.frameId === frame.id &&
                aiLastRequest?.sourceImageId === sourceImageId ?
                aiLastRequest.requestSHA256 : null;
            let totalPixels = 0;
            const usedMetas = new Set();
            for (let index = 0; index < pngs.length; index++) {
                K.aborted(opts.signal);
                const file = pngs[index];
                if (file.size > C.LIMITS.fileBytes)
                    throw new Error('Kandidatenbild ist größer als das Dateibudget.');
                const bytes = new Uint8Array(await file.arrayBuffer());
                const image = await K.decodePNG(bytes, opts);
                totalPixels += image.width * image.height;
                if (totalPixels > C.LIMITS.totalPixels)
                    throw new Error('Kandidaten überschreiten das 32-Megapixel-Arbeitsbudget.');
                const checksum = await K.sha256(bytes);
                const metaName = file.name.replace(/\.png$/i, '_meta.json').toLowerCase();
                const metaFile = metas.find(candidate => candidate.name.toLowerCase() === metaName);
                let receipt = null, receiptSHA256 = null;
                if (metaFile) {
                    if (metaFile.size > 1024 * 1024)
                        throw new Error('KI-Manifest ist zu groß.');
                    const metaBytes = new Uint8Array(await metaFile.arrayBuffer());
                    const json = C.json(new TextDecoder('utf-8', { fatal: true }).decode(metaBytes));
                    receipt = AI.verifyCandidateMetadata(json, sourceSHA256, checksum, planned);
                    receiptSHA256 = await K.sha256(metaBytes);
                    usedMetas.add(metaName);
                }
                incoming.push({ frameId: frame.id, sourceImageId,
                    name: file.name, image, sha256: checksum, receipt,
                    receiptSHA256, sourceSHA256,
                    review: AI.reviewCandidate(original, image) });
                opts.progress(index + 1, pngs.length, file.name);
                await I.tick();
            }
            if (usedMetas.size !== metas.length)
                throw new Error('Ein KI-Metadatenbeleg besitzt keinen gleichnamigen PNG-Kandidaten.');
            if (primary()?.id !== frame.id || primary()?.imageId !== sourceImageId)
                throw new Error('Sprite wurde während des Imports geändert.');
            aiCandidates = incoming;
            aiCandidateIndex = 0;
            message('KI-Varianten und vorhandene SHA-Belege geprüft; keine Bilddatei übernommen.');
        });
    }
    function aiApprovalDialog() {
        const frame = primary(), candidates = aiActiveCandidates();
        if (!frame || !candidates.length) throw new Error('Kein passender Kandidat geladen.');
        const candidate = candidates[Math.min(aiCandidateIndex, candidates.length - 1)];
        const sourceImageId = frame.imageId;
        const review = AI.reviewCandidate(store().get(sourceImageId), candidate.image);
        if (review.errors.length)
            throw new Error('Kandidat blockiert: ' + review.errors.join(' '));
        const source = store().get(sourceImageId);
        const inspected = [
            damagePreview(source, 'Arbeitsoriginal'),
            damagePreview(candidate.image, 'Kandidat: ' + candidate.name)
        ];
        modal('KI-Kandidaten übernehmen', [
            el('div', { class: 'damage-review-gallery' }, inspected),
            line('Veränderte Pixel', review.stats.changedPixels),
            line('Geänderte Alphawerte', review.stats.alphaChanged),
            ...review.warnings.map(msg => el('p', { class: 'warning-text', text: msg })),
            line('Quell- und Manifestabgleich', candidate.receipt ?
                (candidate.receipt.requestMatched ?
                    'SHA von Quelle, Kandidat und Auftrag passen' :
                    'SHA von Quelle und Kandidat passen') :
                'Kein Generatorbeleg, Herkunft unbestätigt'),
            note('Nur die aktuelle Arbeitskopie wird ersetzt. Das Original und der Undo-Verlauf bleiben erhalten. ' +
                'Masken, Pivots und Spielkompatibilität müssen separat geprüft werden.'),
            fields(field('Notiz (optional)', '', {
                name: 'notes', type: 'textarea', wide: true,
                placeholder: 'Warum entspricht dieser Kandidat der Vorlage?'
            }))
        ], 'Kandidaten übernehmen', async data => {
            const notes = String(data.get('notes') || '').trim();
            if (notes.length > 1200) throw new Error('Notiz überschreitet 1200 Zeichen.');
            const current = primary();
            if (!current || current.id !== frame.id || current.imageId !== sourceImageId)
                throw new Error('Quelle hat sich geändert; Kandidat erneut prüfen.');
            if (current.locked) throw new Error('Gesperrter Sprite darf nicht ersetzt werden.');
            await task('Geprüfte Arbeitskopie übernehmen', async opts => {
                const sourcePNG = await store().bytes(sourceImageId, opts.signal);
                const currentSHA = await K.sha256(sourcePNG);
                if (current.id !== primary()?.id || current.imageId !== primary()?.imageId)
                    throw new Error('Sprite-Auswahl hat sich geändert.');
                const next = store().fork(), nextState = I.clone(state());
                const updated = nextState.frames.find(f => f.id === frame.id);
                updated.imageId = next.add(candidate.image);
                updated.aiGeneration = {
                    appliedImageId: updated.imageId,
                    sourceSHA256: currentSHA,
                    candidateSHA256: candidate.sha256,
                    imageContentSHA256: I.imageContentSHA256(candidate.image),
                    // A JSON receipt is self-declared, not a provider signature.
                    requestedModel: candidate.receipt?.modelClaim || 'unverified',
                    requestReferenceSHA256: candidate.receipt ?
                        candidate.sourceSHA256 : null,
                    requestSHA256: candidate.receipt?.requestSHA256 || null,
                    generatorMetadataSHA256: candidate.receiptSHA256 || null,
                    reviewNotes: notes,
                    manualReview: false, apiOriginVerified: false
                };
                updated.metadataStatus = 'manual';
                commit(nextState, 'KI-Kandidat übernehmen', next, { fit: true });
                aiCandidates = [];
                aiCandidateIndex = 0;
                aiLastRequest = null;
                view = 'sprite';
                message('KI-Kandidat übernommen. Bearbeitung und Export sind direkt möglich.');
            });
        });
    }
    async function aiAnimationAudit() {
        const frames = groupFrames();
        if (frames.length < 2) throw new Error('Mindestens zwei Animationsframes in der Gruppe benötigt.');
        if (frames.length > 256) throw new Error('Animationsprüfung auf 256 Frames begrenzt.');
        await task('Animation, Bodenanker und Alpha prüfen', async opts => {
            const copied = frames.map(f => ({
                name: f.name, image: store().get(f.imageId), pivot: { ...f.pivot }
            }));
            const audited = AI.analyzeSequence(copied);
            const hashes = [];
            for (const f of frames) {
                K.aborted(opts.signal);
                hashes.push({ name: f.name, pngSHA256: await K.sha256(
                    await store().bytes(f.imageId, opts.signal)) });
            }
            download(JSON.stringify({ ...audited,
                project: state().project.id, sourcePNG: hashes,
                sourceOnly: true, requireHumanReview: true,
                inGameTested: false, nativeAnimationTimingVerified: false
            }, null, 2) + '\n', C.safeName(groupId) + '_animation_qa.json',
            'application/json');
            message('Animierte Framefolge geprüft: ' + audited.warnings.length +
                ' Hinweise. Ergebnisse sind kein Ingame-Nachweis.');
        });
    }
    function aiSection() {
        const frame = primary();
        if (!frame) return [section('KI-Werkstatt', [
            note('Zuerst einen Sprite auswählen. Für die Generierung SpriteSuite mit dem lokalen Codex-Client öffnen.')
        ])];
        const candidates = aiActiveCandidates();
        const candidate = candidates[Math.min(aiCandidateIndex, candidates.length - 1)];
        return [
            section('1 · Briefing und Vorlage', [
                line('Original-/Arbeits-Sprite', frame.name),
                line('Arbeitsbild', store().get(frame.imageId).width + ' × ' +
                    store().get(frame.imageId).height + ' px'),
                fields(field('Assetklasse', aiAssetClass, {
                    wide: true, options: [
                        ['building', 'Gebäude'], ['unit', 'Einheiten / Frames'],
                        ['animation', 'Animationen / Richtungsframes'], ['texture', 'Texturen / Materialien'],
                        ['vegetation', 'Vegetation'], ['hud', 'HUD'],
                        ['ui', 'UI-Sprite / Icon'], ['other', 'Sonstige']
                    ], onchange: v => { aiAssetClass = v; }
                }), field('Modell', aiModel, {
                    wide: true, options: AI.MODELS, onchange: v => { aiModel = v; }
                })),
                fields(field('Gestaltungsziel', aiGoal, {
                    type: 'textarea', wide: true, onchange: v => { aiGoal = v; },
                    placeholder: 'Was soll geändert werden? Bezug zum Original genau benennen.'
                }), field('Muss erhalten bleiben', aiRestrictions, {
                    type: 'textarea', wide: true, onchange: v => { aiRestrictions = v; }
                })),
                fields(field('Getrennte Varianten', String(aiVariants), {
                    options: ['1', '2', '3', '4'],
                    onchange: v => { aiVariants = C.integer(v, 'Varianten', 1, 4); }
                })),
                ...(localCodex ? [
                    line('ChatGPT-Konto', codexStatus || 'Lokaler Codex-Client'),
                    buttons(button('Bei ChatGPT anmelden…', () => codexAccount('login')),
                        button('Anmeldung prüfen', () => codexAccount('status'))),
                    buttons(button('Varianten mit Codex erstellen…', () => aiExportRequest(true))),
                    note('Die Generierung nutzt die angemeldete ChatGPT-Sitzung. Verfügbarkeit und Kontolimits werden von Codex geprüft.')
                ] : [note('Für die direkte Generierung den Sprite-Editor über SpriteSuite öffnen.')]),
                buttons(button('KI-Auftragsbundle exportieren…', () => aiExportRequest())),
                note('Enthält unverändertes Referenz-PNG, registrierte Arbeitsvorlage, ' +
                    'Prompt, Prüfsummen und die Anleitung für Codex. Offline und ohne API-Kosten. ' +
                    'Jede Variante ist ein eigenständiger Kandidat und kann direkt übernommen werden.'),
                ...(aiLastRequest?.frameId === frame.id &&
                    aiLastRequest?.sourceImageId === frame.imageId ?
                    [line('Vorbereitete Modellanfrage', aiLastRequest.request.model +
                        ' · ' + aiLastRequest.request.variants + ' Variante(n)')] : [])
            ]),
            section('2 · Kandidaten vergleichen', [
                buttons(button('Kandidaten-PNGs importieren…', () => aiImportCandidates())),
                note('Optional die gleichnamigen *_meta.json-Dateien mit auswählen. ' +
                    'Die Prüfsummen werden mit Quelle und exportiertem Auftrag abgeglichen.'),
                ...(candidate ? [
                    fields(field('Variante', String(Math.min(aiCandidateIndex, candidates.length - 1)), {
                        wide: true, options: candidates.map((row, n) => [
                            String(n), (n + 1) + ' · ' + row.name
                        ]), onchange: v => { aiCandidateIndex = Number(v); renderInspector(); }
                    })),
                    damagePreview(candidate.image, 'Ungeprüfte Variante'),
                    line('Pixel verändert', candidate.review.stats.changedPixels),
                    line('Alpha verändert', candidate.review.stats.alphaChanged),
                    line('Pixelrisikoindikator (0–100; keine Freigabe)',
                        candidate.review.quality?.reviewRiskPoints ?? 'nicht vergleichbar'),
                    ...(candidate.review.quality ? [
                        line('Bodenlinienabweichung', candidate.review.quality.groundShift === null ?
                            'nicht vergleichbar' : candidate.review.quality.groundShift + ' px'),
                        line('Neue Pixel außerhalb Silhouette', candidate.review.quality.addedVisible),
                        line('Verdeckte RGB-Änderungen', candidate.review.quality.hiddenRGBChanges)
                    ] : []),
                    line('Manuelle Prüfreihenfolge nach Pixelrisiko', AI.rankCandidates(
                        store().get(frame.imageId), candidates).map(row =>
                            (row.index + 1) + ' (' + row.reviewRiskPoints + ')').join(' → ')),
                    line('Generatorbeleg', candidate.receipt ?
                        (candidate.receipt.requestMatched ?
                            'Quell- und Auftrags-SHA passen' :
                            'Quell-SHA passt, Auftrag nicht hier vorbereitet') :
                        'Ohne Manifest · Herkunft unbestätigt'),
                    note('Ein Manifest allein beweist nicht den API-Absender. ' +
                        'Vorhandene Herkunftsbelege und optionale Notizen werden übernommen.'),
                    ...candidate.review.errors.map(msg =>
                        el('p', { class: 'error-text', text: msg })),
                    ...candidate.review.warnings.map(msg =>
                        el('p', { class: 'warning-text', text: msg })),
                    buttons(button('Original + Variante übernehmen…', aiApprovalDialog, {
                        disabled: !!candidate.review.errors.length
                    })),
                    buttons(button('Varianten verwerfen', () => {
                        aiCandidates = [];
                        aiCandidateIndex = 0;
                        renderInspector();
                    }))
                ] : [note('Noch kein Kandidat geladen. Einen Kandidaten importieren und direkt übernehmen.')]),
                ...(frame.aiGeneration ?
                    [line('Letzte KI-Notiz', frame.aiGeneration.reviewNotes),
                     line('Quellnachweis', frame.aiGeneration.sourceSHA256.slice(0, 16) + '…')] : []),
                ...(groupFrames().length >= 2 ? [buttons(button(
                    'Animationsfolge auf Anker-/Alpha-Sprünge prüfen…', aiAnimationAudit))] : []),
                note('Kein automatischer Qualitäts- oder Rechte-Nachweis. Nach der Übernahme ' +
                    'sind Masken, Atlas, Animationsverlauf und die Darstellung im QA-Spiel zu testen.')
            ])
        ];
    }
    function renderInspector() {
        nativeApi?.invalidate();
        const root = $('inspector-content');
        root.replaceChildren();
        for (const b of document.querySelectorAll('[data-panel]'))
            b.classList.toggle('active', b.dataset.panel === panel);
        try {
            if (panel === 'target')
                root.append(...targetSection());
            else if (panel === 'damage')
                root.append(...damageSection());
            else if (panel === 'geometry')
                root.append(geometrySection(), legacyPivotSection());
            else if (panel === 'ai')
                root.append(...aiSection());
            else if (panel === 'checks')
                root.append(renderChecks());
            else {
                if (view === 'split')
                    root.append(splitSection());
                else if (view === 'atlas') {
                    root.append(atlasSection());
                    if (primary())
                        root.append(frameSection());
                }
                else {
                    if (view === 'scene') {
                        const s = sceneSection();
                        if (s)
                            root.append(s);
                    }
                    if (primary())
                        root.append(frameSection());
                    else
                        root.append(el('div', { class: 'inspector-empty', text: 'Dateien importieren, um Eigenschaften zu bearbeiten.' }));
                }
            }
        }
        catch (e) {
            root.append(note(e.message));
        }
    }
    function slotDialog() {
        const g = currentGroup();
        if (!g)
            throw new Error('Zuerst eine Gruppe auswählen.');
        modal('Rasterplätze zuordnen', [
            el('p', { text: `Alle Sprites in ${g.name} werden nach ihrer Quellnummer sortiert. Individuell vertauschte Plätze werden neu zugeordnet.` }),
            checkbox('Nummernlücken erhalten', true, 'preserve'), el('p', { text: 'Die Rastergröße bleibt erhalten. Ein zu großer Nummernbereich wird nicht abgeschnitten.' })
        ], 'Zuordnen', data => edit(s => {
            const gg = s.scenes.find(g => g.id === groupId), ff = s.frames.filter(f => f.groupId === groupId), mapped = C.assignSlots(ff, gg.settings, !!data.get('preserve'));
            for (const f of mapped)
                s.frames[s.frames.findIndex(x => x.id === f.id)] = f;
        }, 'Rasterplätze neu zuordnen'));
    }
    function mappingDialog() {
        const ff = chosen().sort((a, b) => a.slot - b.slot);
        if (!ff.length)
            throw new Error('Zuerst Sprites auswählen.');
        let t = { group: 'tile_custom', index: 0 };
        try {
            t = C.targetName(ff[0].targetName);
        }
        catch (_e) {
        }
        modal('Zielserie zuordnen', [
            el('p', {
                text: `${ff.length} ausgewählte Sprites. Reihenfolge: aktuelle Rasterplätze. Die Zielnamen müssen aus SHCDE stammen; Quellnummern sind keine verifizierte Übersetzung.`
            }),
            fields(field('SHCDE-GM-Gruppe', t.group, { name: 'group', wide: true }), field('Erster Zielindex', t.index, { name: 'start', type: 'number', min: 0, max: 1000000 })),
            el('div', { class: 'field-inline' }, [checkbox('Abstände der Quellnummern erhalten', false, 'gaps')])
        ], 'Zuordnen', data => {
            const group = String(data.get('group')), start = C.integer(data.get('start'), 'Zielindex', 0, 1000000), gaps = !!data.get('gaps');
            C.targetName(group + '-' + start);
            if (gaps && ff.some(f => f.index === null))
                throw new Error('Nicht alle Quellen besitzen eine Bildnummer.');
            const min = Math.min(...ff.map(f => f.index ?? 0));
            edit(s => {
                ff.forEach((old, i) => {
                    const f = s.frames.find(f => f.id === old.id);
                    f.targetName = C.targetName(group + '-' + (start + (gaps ? old.index - min : i))).name;
                    f.targetConfirmed = false;
                });
            }, 'Zielserie zuordnen');
        });
    }
    function adoptReferences() {
        frameUpdate(f => {
            const ref = state().references.find(r => r.name === f.targetName);
            if (!ref?.pivot || ref.ppu === null)
                throw new Error(`Vollständige Zielmetadaten fehlen: ${f.targetName}`);
            f.pivot = { ...ref.pivot };
            f.ppu = ref.ppu;
            f.metadataStatus = 'manual';
        }, 'Zielpivot und Skalierung übernehmen');
    }
    function resetOriginal() {
        frameUpdate(f => {
            if (f.locked)
                return;
            f.imageId = f.originalId;
            f.maskId = f.originalMaskId;
            f.pivot = { ...f.originalPivot };
            f.ppu = f.originalPPU;
            f.dx -= f.trimOffsetX || 0;
            f.dy -= f.trimOffsetY || 0;
            f.trimOffsetX = f.trimOffsetY = 0;
        }, 'Originalbilder wiederherstellen');
    }
    async function replaceImage(maskOnly) {
        const ff = chosen();
        if (ff.length !== 1)
            throw new Error('Genau einen Sprite auswählen.');
        if (ff[0].locked)
            throw new Error('Sprite ist gesperrt.');
        const files = await askFiles('.png', !maskOnly);
        if (!files.length)
            return;
        await task(maskOnly ? 'Maske laden' : 'PNG ersetzen', async (opts) => {
            const entries = await I.expandFiles(files, opts), next = store().fork(), s = I.clone(state()), f = s.frames.find(t => t.id === ff[0].id);
            if (maskOnly) {
                if (entries.length !== 1)
                    throw new Error('Genau eine Maske auswählen.');
                f.maskId = await next.decode(entries[0].data, opts);
            }
            else {
                const colors = entries.filter(e => !/_m\.png$/i.test(e.name));
                if (colors.length !== 1)
                    throw new Error('Ein Farbbild und optional dessen _m.png auswählen.');
                f.imageId = await next.decode(colors[0].data, opts);
                const mask = entries.find(e => e.name.toLowerCase() === colors[0].name.replace(/\.png$/i, '_m.png').toLowerCase());
                if (mask)
                    f.maskId = await next.decode(mask.data, opts);
                if (entries.length > (mask ? 2 : 1))
                    throw new Error('Nicht zuordenbare Zusatzdateien.');
            }
            commit(s, maskOnly ? 'Maske ersetzen' : 'Bild ersetzen', next, { fit: true });
        });
    }
    function transformDialog() {
        const ff = chosen().filter(f => !f.locked);
        if (!ff.length)
            throw new Error('Keine ungesperrten Sprites ausgewählt.');
        const scaleFields = fields(field('Skalierung · %', 100, { name: 'scale', type: 'number', min: 1, max: 800, step: .1 }), el('div', { class: 'field wide' }, [checkbox('PPU mitskalieren (Größe im Spiel beibehalten)', true, 'world')]));
        const adjustFields = fields(field('Helligkeit', 0, { name: 'brightness', type: 'number', min: -100, max: 100 }), field('Kontrast · %', 100, { name: 'contrast', type: 'number', min: 0, max: 200 }), field('Sättigung · %', 100, { name: 'saturation', type: 'number', min: 0, max: 200 }), field('RGB / Alpha', 'keep', {
            name: 'alphaMode', wide: true, options: [['keep', 'Unverändert (Straight Alpha)'], ['clearHidden', 'RGB bei Alpha 0 löschen'], ['premultiply', 'RGB mit Alpha multiplizieren'], ['unpremultiply', 'RGB durch Alpha dividieren']]
        }));
        const adjustNote = el('p', {
            text: 'Alpha-Umrechnung nur bei einem nachgewiesenen Bedarf. PNG erwartet unassoziierte Farbwerte; die Umrechnung ist keine allgemeine Reparatur. Maskenkanäle bleiben bei Farbkorrekturen unverändert.'
        });
        const operation = field('Operation', 'resize', {
            name: 'operation', wide: true, options: [['resize', 'Skalieren · Nächster Nachbar'], ['flipH', 'Horizontal spiegeln'], ['flipV', 'Vertikal spiegeln'], ['trim', 'Transparente Ränder entfernen'], ['adjust', 'Farbwerte / Alpha bearbeiten']]
        });
        const refresh = () => {
            const op = operation.querySelector('select').value;
            scaleFields.hidden = op !== 'resize';
            adjustFields.hidden = op !== 'adjust';
            adjustNote.hidden = op !== 'adjust';
        };
        operation.querySelector('select').onchange = refresh;
        refresh();
        modal('Sprites transformieren', [el('p', { text: `${ff.length} ungesperrte Sprites. Geometrische Änderungen werden auf Farb- und Maskenbilder gemeinsam angewendet. Originale bleiben erhalten.` }), fields(operation), scaleFields, adjustFields, adjustNote], 'Anwenden', async (data) => {
            await task('Sprites transformieren', async (opts) => {
                const s = I.clone(state()), next = store().fork(), op = String(data.get('operation'));
                for (let i = 0; i < ff.length; i++) {
                    K.aborted(opts.signal);
                    const f = s.frames.find(x => x.id === ff[i].id), img = next.get(f.imageId), mask = f.maskId ? next.get(f.maskId) : null, g = s.scenes.find(g => g.id === f.groupId);
                    let result, newMask = mask;
                    if (op === 'resize') {
                        const factor = C.number(data.get('scale'), 'Skalierung', 1, 800) / 100, w = Math.max(1, Math.round(img.width * factor)), h = Math.max(1, Math.round(img.height * factor));
                        result = C.resize(img, w, h);
                        if (mask)
                            newMask = C.resize(mask, w, h);
                        if (data.get('world'))
                            f.ppu *= factor;
                    }
                    else if (op === 'flipH' || op === 'flipV') {
                        const horizontal = op === 'flipH';
                        result = C.flip(img, horizontal);
                        if (mask)
                            newMask = C.flip(mask, horizontal);
                        if (horizontal)
                            f.pivot.x = 1 - f.pivot.x;
                        else
                            f.pivot.y = 1 - f.pivot.y;
                    }
                    else if (op === 'trim') {
                        let bounds = img;
                        if (mask) {
                            bounds = C.image(img.width, img.height, new Uint8Array(img.data));
                            for (let k = 0; k < bounds.data.length; k += 4)
                                if (mask.data[k] || mask.data[k + 1] || mask.data[k + 2] || mask.data[k + 3])
                                    bounds.data[k + 3] = 255;
                        }
                        const r = C.trimRect(bounds, f.pivot);
                        result = C.crop(img, r.x, r.y, r.width, r.height);
                        if (mask)
                            newMask = C.crop(mask, r.x, r.y, r.width, r.height);
                        if (g.settings.anchor === 'bottom') {
                            const dx = r.x + Math.floor(r.width / 2) - Math.floor(img.width / 2), dy = r.y + r.height - img.height;
                            f.dx += dx;
                            f.dy += dy;
                            f.trimOffsetX = (f.trimOffsetX || 0) + dx;
                            f.trimOffsetY = (f.trimOffsetY || 0) + dy;
                        }
                        f.pivot = r.pivot;
                    }
                    else if (op === 'adjust')
                        result = C.adjust(img, {
                            brightness: Number(data.get('brightness')), contrast: Number(data.get('contrast')), saturation: Number(data.get('saturation')), alphaMode: String(data.get('alphaMode'))
                        });
                    else
                        throw new Error('Unbekannte Transformation.');
                    f.imageId = next.add(result);
                    if (mask && newMask !== mask)
                        f.maskId = next.add(newMask);
                    if (op !== 'adjust')
                        f.metadataStatus = 'manual';
                    opts.progress(i + 1, ff.length, f.name);
                    await I.tick();
                }
                commit(s, 'Transformation', next, { fit: true });
            });
        });
    }
    function sceneToSplit() {
        const g = currentGroup(), ff = groupFrames().filter(f => f.visible);
        if (!g || !ff.length)
            throw new Error('Zuerst eine Gruppe mit sichtbaren Sprites auswählen.');
        const go = () => {
            const next = store().fork(), s = I.clone(state()), l = C.layout(ff, g.settings, k => next.get(k)), imageId = next.add(C.compose(l, k => next.get(k)));
            let maskId = null;
            if (ff.some(f => f.maskId))
                throw new Error('Für maskierte Quellen einzelne Ebenen beibehalten. Eine überlagerte Farbmaske kann nicht shaderneutral abgeflacht werden.');
            const img = next.get(imageId), settings = { ...g.settings, anchor: 'bottom' }, map = C.partition(img, settings, l.originX, l.originY, true);
            if (settings.width > 64)
                throw new Error('Neue Schnitte mit Überlappung benötigen höchstens 64 Pixel Tilebreite. Raster vorher anpassen.');
            s.split = {
                imageId, maskId, mapId: next.add(C.ownershipImage(map, img.width, img.height)), settings, anchorX: l.originX, anchorY: l.originY, extend: true, overlap: 1, rearShare: true, group: g.name, start: Math.min(...ff.map(f => f.index ?? 0)), source: g.source
            };
            commit(s, 'Aufbau als Schnittbild', next, { fit: true });
            view = 'split';
            render();
        };
        if (state().split)
            confirmDialog('Schnittbild ersetzen', 'Das vorhandene Schnittbild und seine Zuordnung werden ersetzt. Dieser Schritt ist rückgängig machbar.', go);
        else
            go();
    }
    function regenerateSplit() {
        const r = state().split;
        if (!r)
            throw new Error('Kein Schnittbild vorhanden.');
        const next = store().fork(), s = I.clone(state()), img = next.get(r.imageId), map = C.partition(img, r.settings, r.anchorX, r.anchorY, r.extend);
        s.split.mapId = next.add(C.ownershipImage(map, img.width, img.height));
        commit(s, 'Schnittflächen neu berechnen', next);
    }
    function deleteSelected() {
        if (!selected.size)
            return;
        const count = chosen().filter(f => !f.locked).length;
        if (!count)
            throw new Error('Ausgewählte Sprites sind gesperrt.');
        confirmDialog('Sprites entfernen', `${count} ausgewählte Sprites werden aus dem Projekt entfernt. Gesperrte Sprites bleiben erhalten.`, () => edit(s => {
            s.frames = s.frames.filter(f => !selected.has(f.id) || f.locked);
            s.scenes = s.scenes.filter(g => s.frames.some(f => f.groupId === g.id));
        }, 'Sprites entfernen', { fit: true }));
    }
    const exportTypes = [['merged', 'Gesamtbild · PNG'], ['tiles', 'Bearbeitete Tiles · ZIP'], ['originals', 'Unveränderte Originale · ZIP'], ['ora', 'Ebenen · OpenRaster'], ['atlas', 'Atlas + Metadaten · ZIP'], ['mod', 'Modpaket · ZIP'], ['semod', 'Modpaket · SEMOD'], ['csv', 'Zielzuordnung · CSV'], ['split', 'Schnitt · ZIP'], ['ownership', 'Schnittmaske · PNG'], ['report', 'Prüfbericht · JSON'], ['project', 'Projekt · SHSPRITE']];
    function exportDialog() {
        const type = field('Format', 'merged', { name: 'kind', wide: true, options: exportTypes }), scope = field('Umfang', 'group', { name: 'scope', wide: true, options: [['group', 'Aktuelle Gruppe'], ['selected', 'Ausgewählte Sprites'], ['all', 'Alle Gruppen']] }), details = el('p');
        const refresh = () => {
            const kind = type.querySelector('select').value, isMod = ['mod', 'semod'].includes(kind);
            scope.hidden = !['tiles', 'originals', 'atlas', 'csv'].includes(kind);
            if (isMod) {
                const issues = I.preflight(state(), store()), errors = issues.filter(i => i.level === 'error');
                details.textContent = `Alle sichtbaren Sprites · ${errors.length} Fehler · ${issues.length - errors.length} Hinweise. ` + (errors.length ? errors[0].message : 'Das Paket wird vorbereitet, nicht installiert.');
            }
            else
                details.textContent = {
                    merged: 'Aktuelle Gruppe, ohne Raster und Nummern. Unsichtbare Sprites werden nicht gezeichnet.', ora: 'Aktuelle Gruppe mit separaten, benannten Ebenen und gespeicherter Sichtbarkeit.', originals: 'Die ursprünglichen PNG-Dateien einschließlich Masken, ohne Neucodierung.', atlas: 'Pro Zielgruppe ein Atlas. Quelle→Ziel, Pivot und PPU vorher kontrollieren.', split: 'Alle Schnitt-Tiles und Positionsdaten. Unzugeordnete Bild- oder Maskenpixel sperren den Export.', ownership: 'RGB-Indexbild: 0 = nicht zugeordnet; Tile 1 = RGB(1,0,0). Nicht farbkorrigieren.', project: 'Originale, Bearbeitungen, Zielreferenzen und Schnittdaten in einer Projektdatei.', report: 'Formale Prüfungen, Hinweise und Projektmetadaten.'
                }[kind] || 'Sichtbare Sprites im gewählten Umfang.';
        };
        type.querySelector('select').onchange = refresh;
        refresh();
        modal('Exportieren', [fields(type, scope), details], 'Exportieren', async (data) => {
            const kind = String(data.get('kind'));
            await exportDirect(kind, String(data.get('scope') || 'group'));
        });
    }
    function exportFrames(scope = 'group', originals = false) {
        let frames = scope === 'all' ? state().frames : scope === 'selected' ? chosen() : groupFrames();
        if (!originals)
            frames = frames.filter(f => f.visible);
        if (!frames.length)
            throw new Error('Keine Sprites im gewählten Umfang.');
        return frames;
    }
    async function exportDirect(kind, scope = 'group') {
        if (kind === 'project') {
            await saveProject();
            return;
        }
        await task('Export vorbereiten', async (opts) => {
            const base = C.safeName(currentGroup()?.name || state().project.name), s = state(), st = store();
            let data, name, type = 'application/zip';
            if (kind === 'merged') {
                const g = currentGroup();
                if (!g)
                    throw new Error('Keine Gruppe ausgewählt.');
                const l = C.layout(groupFrames(), g.settings, k => st.get(k));
                data = await K.encodePNG(C.compose(l, k => st.get(k)), opts);
                name = base + '.png';
                type = 'image/png';
            }
            else if (kind === 'tiles' || kind === 'originals') {
                const ff = exportFrames(scope, kind === 'originals'), entries = await I.tileEntries(ff, st, { ...opts, originals: kind === 'originals' });
                if (kind === 'tiles')
                    entries.push({ name: 'zuordnung.csv', data: I.mappingCSV(s, ff) });
                data = K.zip(entries);
                name = base + (kind === 'originals' ? '_originale' : '_tiles') + '.zip';
            }
            else if (kind === 'ora') {
                const g = currentGroup();
                if (!g)
                    throw new Error('Keine Gruppe ausgewählt.');
                data = await I.exportORA(groupFrames(), g.settings, st, null, { ...opts, name: base });
                name = base + '.ora';
            }
            else if (kind === 'atlas') {
                const ff = exportFrames(scope), issues = I.preflight(s, st, ff, 'atlas').filter(i => i.level === 'error' && i.code !== 'UNCONFIRMED');
                if (issues.length)
                    throw new Error(issues[0].message);
                data = K.zip(await I.atlasEntries(ff, st, { ...s.export, ...opts }));
                name = base + '_atlas.zip';
            }
            else if (kind === 'mod' || kind === 'semod') {
                const result = await I.exportMod(s, st, { ...opts, packed: kind === 'semod' });
                data = result.bytes;
                name = result.filename;
            }
            else if (kind === 'csv') {
                data = I.mappingCSV(s, exportFrames(scope, true));
                name = base + '_zuordnung.csv';
                type = 'text/csv;charset=utf-8';
            }
            else if (kind === 'split') {
                const result = await I.exportSplit(s, st, opts);
                data = result.bytes;
                name = C.safeName(s.split.group) + '_schnitt.zip';
            }
            else if (kind === 'ownership') {
                if (!s.split)
                    throw new Error('Keine Schnittmaske vorhanden.');
                data = await st.bytes(s.split.mapId, opts.signal);
                name = C.safeName(s.split.group) + '_schnittmaske.png';
                type = 'image/png';
            }
            else if (kind === 'report') {
                data = JSON.stringify({
                    tool: 'Stronghold Sprite Editor', version: C.VERSION, project: s.project, target: 'Stronghold Crusader: Definitive Edition', inGameTested: false, issues: I.preflight(s, st)
                }, null, 2);
                name = C.safeName(s.project.name) + '_pruefung.json';
                type = 'application/json';
            }
            else
                throw new Error('Unbekanntes Exportformat.');
            K.aborted(opts.signal);
            download(data, name, type);
            message('Export ausgegeben: ' + name);
        });
    }
    function helpDialog() {
        const table = el('table', { class: 'help-table' }), rows = [['Import', 'PNG 1/2/4/8 Bit; RGB/RGBA, Graustufen, Palette und Adam7. 16-Bit-PNG und APNG werden ausdrücklich abgewiesen. ZIP: Store oder Deflate.'], ['Gebäude', 'Rasterplätze: vorne nach hinten, innerhalb jeder Diagonale links nach rechts. Zeichenreihenfolge und Nummerierung sind getrennte Einstellungen.'], ['Portierung', 'SHDE-Quellen mit SHCDE-Zielreferenzen abgleichen. Zielnamen müssen exakt zur internen GM-Gruppe passen. Keine automatische ID-Übersetzung zwischen den Spielen.'], ['Metadaten', 'Atlas-JSON des Script Extenders; einfache Unity/AssetRipper-Sprite-JSONs für Pivot und PPU. Rotierte, beschnittene oder mesh-gepackte Atlanten zuerst extern in Einzelbilder extrahieren.'], ['Masken', '_m.png wird unverändert mitgeführt. Gleiche Geometrie wie Farbbild. Keine automatische Erzeugung von Teamfarben- oder Vegetationskanälen.'], ['Schnitt', 'Manuell zuordnen: „Zuordnen“ aktivieren, Tile wählen und malen. Unzugeordnete Bild- und Maskenpixel blockieren den Export. Ein flaches Bild enthält keine verdeckten Originalpixel.'], ['Ausgabe', 'Atlas-Overrides / Einzel-Overrides für SHCDE Script Extender, PNG, ZIP, OpenRaster und CSV. Keine Änderung an Spielarchiven, keine DDS-Kompression, kein automatisches Workshop-Publishing.'], ['Projekt', 'SHSPRITE archiviert Originale und Bearbeitungen mit SHA-256. Alte v0.1-JSON-Projekte werden importiert. Browser-Sicherungen sind lokal und können vom Browser gelöscht werden.'], ['Grenzen', '16 Megapixel je Bild, 32 Megapixel an gehaltenen Bilddaten, 4096 Sprites, 128 MiB Eingabe. Exportarchive bis 192 MiB. Rückgängig: bis 50 Schritte; Bildbudget gilt auch für die Historie.']];
        for (const [a, b] of rows)
            table.append(el('tr', {}, [el('td', { text: a }), el('td', { text: b })]));
        const shortcut = el('table', { class: 'help-table' });
        for (const [a, b] of [['Strg S / O', 'Projekt speichern / öffnen'], ['Strg Z / Umschalt Z', 'Rückgängig / wiederholen'], ['Strg A', 'Alle gefilterten Sprites auswählen'], ['F / 1 / + / −', 'Einpassen / 100 % / Zoom'], ['Pfeiltasten', 'Sprites verschieben; Umschalt = 10 Pixel'], ['Leertaste + Ziehen', 'Arbeitsfläche verschieben'], ['Mausrad', 'Unter dem Mauszeiger zoomen'], ['Strg-Klick / Umschalt-Klick', 'Mehrfachauswahl / Bereich'], ['Entf', 'Ausgewählte ungesperrte Sprites entfernen']])
            shortcut.append(el('tr', {}, [el('td', { text: a }), el('td', { text: b })]));
        modal('Hilfe und Dateiformate', [el('p', { text: 'Stronghold Sprite Editor 1.0.0 · Verarbeitung lokal im Browser. Keine Netzwerkzugriffe, Konten, Telemetrie oder extern geladenen Bibliotheken.' }), table, el('h3', { class: 'help-heading', text: 'Tastatur und Maus' }), shortcut,
            el('h3', { class: 'help-heading', text: 'Technische Grundlagen' }), el('p', {
                text: 'Stand der Recherche: 29.09.2026. Der Script Extender bezeichnet seine Asset API als instabil und Atlas-Overrides als experimentell. Die Anwendung ist nicht mit dem Spielhersteller verbunden. Ein In-Game-Test wurde nicht durchgeführt.'
            }),
            el('a', {
                class: 'help-link', href: 'https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html', target: '_blank', rel: 'noopener noreferrer', text: 'SHCDE Script Extender · Asset API'
            }), el('p', { text: 'Weitere Quellen, Prüfanleitung, Dateispezifikation und reproduzierbare Tests befinden sich im vollständigen Paket.' })], null, null);
        $('modal-form').querySelector('footer button').textContent = 'Schließen';
    }
    let mapCache = null, overlayCache = null, brushOverlay = null;
    function splitMap() {
        const r = state().split;
        if (!r)
            return null;
        if (!mapCache || mapCache.id !== r.mapId)
            mapCache = { id: r.mapId, map: C.ownershipMap(store().get(r.mapId), r.settings.a * r.settings.b) };
        return mapCache.map;
    }
    function overlayPixel(slot, meaningful) {
        if (slot < 0)
            return meaningful ? [196, 62, 62, 150] : [0, 0, 0, 0];
        const hue = ((slot * 97 + 209) % 360) / 60, c = 150, x = c * (1 - Math.abs(hue % 2 - 1));
        let r = 0, g = 0, b = 0;
        if (hue < 1) {
            r = c;
            g = x;
        }
        else if (hue < 2) {
            r = x;
            g = c;
        }
        else if (hue < 3) {
            g = c;
            b = x;
        }
        else if (hue < 4) {
            g = x;
            b = c;
        }
        else if (hue < 5) {
            r = x;
            b = c;
        }
        else {
            r = c;
            b = x;
        }
        return [Math.round(r + 65), Math.round(g + 65), Math.round(b + 65), 85];
    }
    function makeOverlay(map, src, mask) {
        const img = C.image(src.width, src.height);
        for (let i = 0; i < map.length; i++) {
            const m = !!src.data[i * 4 + 3] || !!(mask && (mask.data[i * 4] || mask.data[i * 4 + 1] || mask.data[i * 4 + 2] || mask.data[i * 4 + 3]));
            img.data.set(overlayPixel(map[i], m), i * 4);
        }
        return rawCanvas(img);
    }
    function getOverlay() {
        if (brushOverlay)
            return brushOverlay;
        const r = state().split;
        if (!r)
            return null;
        const key = r.mapId + ':' + r.imageId + ':' + r.maskId;
        if (!overlayCache || overlayCache.key !== key)
            overlayCache = { key, canvas: makeOverlay(splitMap(), store().get(r.imageId), r.maskId ? store().get(r.maskId) : null) };
        return overlayCache.canvas;
    }
    function displaySpec(frame, kind = 'current') {
        const ch = $('channel').value, mask = ch.startsWith('mask'), channel = mask ? (ch === 'mask' ? 'rgba' : ch.slice(5)) : ch;
        let imageId = kind === 'original' ? (mask ? frame.originalMaskId : frame.originalId) : (mask ? frame.maskId : frame.imageId);
        return { imageId, channel };
    }
    function animationFrames() {
        const ff = chosen().length > 1 ? chosen() : groupFrames();
        return ff.filter(f => f.visible).sort((a, b) => a.slot - b.slot);
    }
    function alignedItems(specs) {
        let left = 0, top = 0, right = 1, bottom = 1;
        const items = [];
        for (const spec of specs) {
            if (!spec.imageId)
                continue;
            const img = store().get(spec.imageId), p = C.pixelAnchor({ pivot: spec.pivot }, img), x = -Math.round(p.x), y = -Math.round(p.y);
            left = Math.min(left, x);
            top = Math.min(top, y);
            right = Math.max(right, x + img.width);
            bottom = Math.max(bottom, y + img.height);
            items.push({ ...spec, x, y, width: img.width, height: img.height });
        }
        const pad = 12;
        left -= pad;
        top -= pad;
        right += pad;
        bottom += pad;
        C.dimensions(right - left, bottom - top);
        for (const p of items) {
            p.x -= left;
            p.y -= top;
        }
        return { width: right - left, height: bottom - top, items, anchorX: -left, anchorY: -top };
    }
    function buildModel() {
        layoutError = '';
        const g = currentGroup(), ff = groupFrames();
        let result = null;
        if (view === 'scene') {
            if (!g || !ff.length)
                return null;
            const l = C.layout(ff, g.settings, k => store().get(k));
            result = {
                ...l, items: l.paint.filter(p => p.frame.visible).map(p => ({ ...p, ...displaySpec(p.frame) })), grid: { settings: g.settings, x: l.originX, y: l.originY }, note: ''
            };
        }
        else if (view === 'sprite') {
            const f = primary();
            if (!f)
                return null;
            const cmp = $('compare').value, current = displaySpec(f), original = displaySpec(f, 'original'), ref = state().references.find(r => r.name === f.targetName), mask = $('channel').value.startsWith('mask'), reference = { imageId: mask ? ref?.maskId : ref?.imageId, channel: current.channel, pivot: ref?.pivot || f.pivot };
            if (cmp === 'difference') {
                if (!current.imageId || !original.imageId)
                    throw new Error('Für den Vergleich fehlen Bild- oder Maskendaten.');
                const a = store().get(current.imageId), b = store().get(original.imageId);
                if (a.width !== b.width || a.height !== b.height)
                    throw new Error('Der Pixelvergleich benötigt gleiche Abmessungen. Für Geometrievergleiche Original / Bearbeitet wechseln.');
                const key = 'difference:' + current.imageId + ':' + original.imageId;
                let cv = visualCache.get(key)?.canvas;
                if (!cv) {
                    const diff = C.difference(a, b);
                    cv = addVisual(key, rawCanvas(diff.image), current.imageId);
                }
                result = {
                    width: a.width + 24, height: a.height + 24, items: [{ canvas: cv, x: 12, y: 12, width: a.width, height: a.height, frame: f }], anchorX: 12 + f.pivot.x * a.width, anchorY: 12 + (1 - f.pivot.y) * a.height, note: 'Absolute Kanaldifferenz zum Original'
                };
            }
            else {
                const specs = cmp === 'original' ? [{ ...original, pivot: f.originalPivot, frame: f }] : cmp === 'reference' ? [{ ...reference, frame: f }] : cmp === 'overlay' ? [{ ...reference, frame: f, opacity: .55 }, { ...current, pivot: f.pivot, frame: f, opacity: .6 }] : [{ ...current, pivot: f.pivot, frame: f }];
                if (specs.some(s => !s.imageId))
                    throw new Error(cmp === 'reference' || cmp === 'overlay' ? 'Passende Zielreferenz oder Maske fehlt.' : 'Für diesen Sprite ist keine Maske geladen.');
                result = {
                    ...alignedItems(specs), note: cmp === 'overlay' ? 'Quelle und Ziel am Pivot · Pixelmaßstab, keine Shader-Vorschau' : cmp === 'original' ? 'Original' : cmp === 'reference' ? 'SHCDE-Zielreferenz' : ''
                };
            }
        }
        else if (view === 'animation') {
            const frames = animationFrames();
            if (!frames.length)
                return null;
            animIndex = Math.max(0, Math.min(animIndex, frames.length - 1));
            const all = frames.map(f => ({ ...displaySpec(f), pivot: f.pivot, frame: f }));
            const aligned = alignedItems(all);
            const current = frames[animIndex], previous = frames[(animIndex - 1 + frames.length) % frames.length], items = [];
            if ($('onion').checked && frames.length > 1) {
                const p = aligned.items.find(p => p.frame.id === previous.id);
                if (p)
                    items.push({ ...p, opacity: .25 });
            }
            const p = aligned.items.find(p => p.frame.id === current.id);
            if (p)
                items.push(p);
            result = { ...aligned, items, note: current.name };
            $('frame-slider').max = frames.length - 1;
            $('frame-slider').value = animIndex;
            $('frame-label').textContent = `${animIndex + 1} / ${frames.length}`;
        }
        else if (view === 'split') {
            const r = state().split;
            if (!r)
                return null;
            const img = store().get(r.imageId), maskMode = $('channel').value.startsWith('mask'), imageId = maskMode ? r.maskId : r.imageId, channel = maskMode ? ($('channel').value === 'mask' ? 'rgba' : $('channel').value.slice(5)) : $('channel').value;
            if (!imageId)
                throw new Error('Für das Schnittbild ist keine Farbmaske geladen.');
            result = {
                width: img.width, height: img.height, items: [{ imageId, channel, x: 0, y: 0, width: img.width, height: img.height }], grid: { settings: r.settings, x: r.anchorX, y: r.anchorY }, note: brushTool ? 'Tile zuordnen · Ziehen zum Malen' : ''
            };
            if ($('split-overlay').checked)
                result.overlay = getOverlay();
        }
        else if (view === 'atlas') {
            const frames = atlasFrames();
            if (!frames.length)
                return null;
            const pack = I.packFrames(frames, store(), state().export);
            result = {
                width: pack.width, height: pack.height, items: pack.placed.map(p => ({ ...p, frame: p, ...displaySpec(p) })), atlas: pack, note: `${atlasGroup} · ${frames.length} Sprites · alle Quellgruppen`
            };
        }
        if (result && drag?.kind === 'sprite') {
            const deltaX = Math.round(drag.dx), deltaY = Math.round(drag.dy);
            result.items = result.items.map(p => p.frame && selected.has(p.frame.id) && !p.frame.locked ? { ...p, x: p.x + deltaX, y: p.y + deltaY } : p);
        }
        return result;
    }
    function requestDraw() {
        if (renderQueued)
            return;
        renderQueued = true;
        requestAnimationFrame(() => {
            renderQueued = false;
            draw();
        });
    }
    function fitModel() {
        if (!model)
            return;
        const t = getTransform(), w = $('canvas-wrap').clientWidth, h = $('canvas-wrap').clientHeight;
        t.zoom = Math.max(.02, Math.min(16, Math.min((w - 60) / model.width, (h - 60) / model.height)));
        t.panX = t.panY = 0;
    }
    function screenTransform() {
        const t = getTransform(), w = $('canvas-wrap').clientWidth, h = $('canvas-wrap').clientHeight;
        return { ...t, x: w / 2 + t.panX - (model?.width || 0) * t.zoom / 2, y: h / 2 + t.panY - (model?.height || 0) * t.zoom / 2 };
    }
    function screenToImage(event) {
        const rect = $('viewport').getBoundingClientRect(), t = screenTransform();
        return { x: (event.clientX - rect.left - t.x) / t.zoom, y: (event.clientY - rect.top - t.y) / t.zoom };
    }
    function draw() {
        const cv = $('viewport'), wrap = $('canvas-wrap'), w = wrap.clientWidth, h = wrap.clientHeight, dpr = Math.min(3, devicePixelRatio || 1);
        if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
            cv.width = Math.round(w * dpr);
            cv.height = Math.round(h * dpr);
        }
        const ctx = cv.getContext('2d');
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, cv.width, cv.height);
        try {
            model = buildModel();
        }
        catch (e) {
            model = null;
            layoutError = e.message;
        }
        $('empty-state').hidden = !!model || !!layoutError;
        $('empty-state').querySelector('p').textContent = view === 'split' ? 'Gesamtbild für den Schnitt laden' : 'PNG-Dateien ablegen';
        $('canvas-note').hidden = !layoutError && !model?.note;
        $('canvas-note').textContent = layoutError || model?.note || '';
        if (!model) {
            $('status-middle').textContent = '';
            return;
        }
        if (fitNext) {
            fitModel();
            fitNext = false;
        }
        const t = screenTransform();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.translate(t.x, t.y);
        ctx.scale(t.zoom, t.zoom);
        ctx.imageSmoothingEnabled = false;
        for (const p of model.items) {
            if (!p.imageId && !p.canvas)
                continue;
            ctx.globalAlpha = p.opacity ?? 1;
            ctx.drawImage(p.canvas || canvasFor(p.imageId, p.channel), p.x, p.y);
        }
        ctx.globalAlpha = 1;
        if (model.overlay)
            ctx.drawImage(model.overlay, 0, 0);
        if (model.grid && $('show-grid').checked)
            drawGrid(ctx, model.grid, t.zoom);
        if ((view === 'sprite' || view === 'animation') && $('show-grid').checked && model.anchorX !== undefined) {
            ctx.strokeStyle = '#397db9';
            ctx.lineWidth = 1 / t.zoom;
            const len = 9 / t.zoom;
            ctx.beginPath();
            ctx.moveTo(model.anchorX - len, model.anchorY);
            ctx.lineTo(model.anchorX + len, model.anchorY);
            ctx.moveTo(model.anchorX, model.anchorY - len);
            ctx.lineTo(model.anchorX, model.anchorY + len);
            ctx.stroke();
        }
        if (view === 'sprite') {
            const f = primary(), item = [...model.items].reverse().find(p => p.frame?.id === f?.id);
            const m = activeMeasurement();
            const start = m?.start || (measureStart?.frameId === f?.id &&
                measureStart?.imageId === f?.imageId ? measureStart.point : null);
            if (item && start) {
                const ax = item.x + start.x, ay = item.y + start.y;
                ctx.strokeStyle = '#e58d1a';
                ctx.lineWidth = 2 / t.zoom;
                ctx.beginPath();
                ctx.arc(ax, ay, 4 / t.zoom, 0, 2 * Math.PI);
                if (m) {
                    ctx.moveTo(ax, ay);
                    ctx.lineTo(item.x + m.end.x, item.y + m.end.y);
                    ctx.arc(item.x + m.end.x, item.y + m.end.y,
                        4 / t.zoom, 0, 2 * Math.PI);
                }
                ctx.stroke();
                if (m && t.zoom > .16)
                    drawLabel(ctx, 'Δ ' + m.dx + ' / ' + m.dy + ' px',
                        ax + 9 / t.zoom, ay - 7 / t.zoom, t.zoom);
            }
        }
        if (view === 'sprite' && showLegacyPivot && legacyPivotFile &&
                $('compare').value === 'current') {
            const review = legacyPivotReview(), frame = primary();
            const item = model.items.find(p => p.frame?.id === frame?.id &&
                p.imageId === frame?.imageId);
            if (item && review && ['review', 'already'].includes(review.status)) {
                const proposed = review.row.newPivot;
                const currentAnchorX = item.x + frame.pivot.x * item.width;
                const currentAnchorY = item.y + (1 - frame.pivot.y) * item.height;
                const x = currentAnchorX - proposed.x * item.width;
                const y = currentAnchorY - (1 - proposed.y) * item.height;
                ctx.save();
                ctx.strokeStyle = '#da8322';
                ctx.fillStyle = '#da832217';
                ctx.lineWidth = 2 / t.zoom;
                ctx.setLineDash([5 / t.zoom, 3 / t.zoom]);
                ctx.fillRect(x, y, item.width, item.height);
                ctx.strokeRect(x, y, item.width, item.height);
                ctx.setLineDash([]);
                if (t.zoom > .14)
                    drawLabel(ctx, 'Messvorschlag · Pivot', x, y - 8 / t.zoom, t.zoom);
                ctx.restore();
            }
        }
        if (view === 'scene' || view === 'atlas')
            for (const p of model.items) {
                if (selected.has(p.frame?.id)) {
                    ctx.strokeStyle = '#3475bd';
                    ctx.lineWidth = 1.25 / t.zoom;
                    ctx.setLineDash([]);
                    ctx.strokeRect(p.x, p.y, p.width, p.height);
                }
                if (view === 'atlas' && $('show-grid').checked) {
                    ctx.strokeStyle = '#263e5560';
                    ctx.lineWidth = 1 / t.zoom;
                    ctx.strokeRect(p.x, p.y, p.width, p.height);
                }
                if (view === 'atlas' && $('show-labels').checked) {
                    drawLabel(ctx, String(p.frame.slot + 1), p.x + 2 / t.zoom, p.y + 12 / t.zoom, t.zoom);
                }
            }
        if (view === 'split' && brushTool && drag?.point) {
            ctx.strokeStyle = '#2f6caa';
            ctx.lineWidth = 1 / t.zoom;
            ctx.beginPath();
            ctx.arc(drag.point.x, drag.point.y, Number($('brush-radius').value) || 8, 0, Math.PI * 2);
            ctx.stroke();
        }
        $('zoom-value').textContent = Math.round(t.zoom * 100) + ' %';
        $('status-middle').textContent = `${model.width} × ${model.height} px`;
        cv.style.cursor = view === 'split' && brushTool ? 'crosshair' : view === 'sprite' && (pivotTool || measureTool) ? 'crosshair' : spaceDown || drag?.kind === 'pan' ? 'grab' : 'default';
    }
    function drawLabel(ctx, label, x, y, zoom) {
        ctx.font = `${11 / zoom}px -apple-system,Segoe UI,sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        const width = ctx.measureText(label).width;
        ctx.fillStyle = '#ffffffdd';
        ctx.fillRect(x - 3 / zoom, y - 11 / zoom, width + 6 / zoom, 15 / zoom);
        ctx.fillStyle = '#26384d';
        ctx.fillText(label, x, y);
    }
    function drawGrid(ctx, grid, zoom) {
        const s = C.scene(grid.settings), ps = C.positions(s);
        ctx.lineWidth = 1 / zoom;
        ctx.strokeStyle = $('background').value === 'dark' ? '#d3dce176' : '#526a807a';
        for (const p of ps) {
            const x = grid.x + p.x, y = grid.y + p.bottom;
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.lineTo(x - s.width / 2, y - s.height / 2);
            ctx.lineTo(x, y - s.height);
            ctx.lineTo(x + s.width / 2, y - s.height / 2);
            ctx.closePath();
            ctx.stroke();
            if ($('show-labels').checked && zoom > .18)
                drawLabel(ctx, String(p.slot + 1), x - 4 / zoom, y - s.height / 2 + 4 / zoom, zoom);
        }
    }
    function render() {
        renderGroups();
        renderList();
        renderInspector();
        $('project-title').textContent = state().project.name + (dirty ? ' •' : '');
        document.title = (dirty ? '• ' : '') + state().project.name + ' — Stronghold Sprite Editor';
        $('undo').disabled = !history.past.length || busy;
        $('redo').disabled = !history.future.length || busy;
        $('undo').title = history.past.length ? 'Rückgängig: ' + history.past[history.past.length - 1].label : 'Rückgängig (Strg Z)';
        for (const b of document.querySelectorAll('[data-view]')) {
            b.classList.toggle('active', b.dataset.view === view);
            b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false');
        }
        $('sprite-bar').hidden = view !== 'sprite';
        $('animation-bar').hidden = view !== 'animation';
        $('split-bar').hidden = view !== 'split';
        $('pivot-tool').setAttribute('aria-pressed', pivotTool);
        $('measure-tool').setAttribute('aria-pressed', measureTool);
        $('brush-tool').setAttribute('aria-pressed', brushTool);
        $('play').textContent = playing ? 'Pause' : 'Abspielen';
        $('status-left').textContent = currentGroup() ? `${currentGroup().name} · ${I.originLabel(currentGroup().source)}` : state().split && view === 'split' ? 'Schnittbild' : 'Keine Dateien';
        requestDraw();
    }
    function setView(next) {
        if (view === next)
            return;
        playing = false;
        if (next !== 'sprite') {
            measureTool = false;
            measureStart = null;
            pivotTool = false;
        }
        view = next;
        animIndex = 0;
        fitNext = !transforms.has(view);
        render();
    }
    function setPanel(next) {
        panel = next;
        renderInspector();
    }
    function zoom(factor, event = null) {
        if (!model)
            return;
        const tr = getTransform(), old = screenTransform(), next = Math.max(.02, Math.min(64, tr.zoom * factor));
        if (event) {
            const rect = $('viewport').getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top, cx = rect.width / 2, cy = rect.height / 2;
            tr.panX = x - cx - (x - cx - tr.panX) * (next / tr.zoom);
            tr.panY = y - cy - (y - cy - tr.panY) * (next / tr.zoom);
        }
        tr.zoom = next;
        requestDraw();
    }
    function hitFrame(point) {
        if (!model)
            return null;
        for (const p of [...model.items].reverse()) {
            if (!p.frame || !p.imageId)
                continue;
            const x = Math.floor(point.x - p.x), y = Math.floor(point.y - p.y), img = store().get(p.imageId);
            if (x >= 0 && y >= 0 && x < img.width && y < img.height && img.data[(y * img.width + x) * 4 + 3])
                return p.frame;
        }
        return null;
    }
    function paintStroke(point, from = null) {
        const r = state().split;
        if (!r || !brushMap)
            return;
        const src = store().get(r.imageId), slot = $('brush-erase').checked ? -1 : C.integer($('brush-slot').value, 'Tile', 1, r.settings.a * r.settings.b) - 1, radius = C.integer($('brush-radius').value, 'Radius', 1, 128), start = from || point, dist = Math.hypot(point.x - start.x, point.y - start.y), steps = Math.max(1, Math.ceil(dist / Math.max(1, radius / 2)));
        for (let i = 0; i <= steps; i++) {
            const x = start.x + (point.x - start.x) * i / steps, y = start.y + (point.y - start.y) * i / steps;
            C.paintMap(brushMap, src.width, src.height, x, y, radius, slot);
        }
        const x0 = Math.max(0, Math.floor(Math.min(point.x, start.x) - radius)), y0 = Math.max(0, Math.floor(Math.min(point.y, start.y) - radius)), x1 = Math.min(src.width, Math.ceil(Math.max(point.x, start.x) + radius + 1)), y1 = Math.min(src.height, Math.ceil(Math.max(point.y, start.y) + radius + 1));
        if (x1 > x0 && y1 > y0) {
            const data = new Uint8ClampedArray((x1 - x0) * (y1 - y0) * 4), mask = r.maskId ? store().get(r.maskId) : null;
            for (let y = y0; y < y1; y++)
                for (let x = x0; x < x1; x++) {
                    const i = y * src.width + x, m = !!src.data[i * 4 + 3] || !!(mask && (mask.data[i * 4] || mask.data[i * 4 + 1] || mask.data[i * 4 + 2] || mask.data[i * 4 + 3]));
                    data.set(overlayPixel(brushMap[i], m), ((y - y0) * (x1 - x0) + x - x0) * 4);
                }
            brushOverlay.getContext('2d').putImageData(new ImageData(data, x1 - x0, y1 - y0), x0, y0);
        }
    }
    function pointerDown(e) {
        if ((busy && !e.nativeGesture) || !model || ![0, 1].includes(e.button))
            return;
        e.preventDefault();
        $('viewport').focus();
        if (e.isTrusted) $('viewport').setPointerCapture(e.pointerId);
        const point = screenToImage(e), tr = getTransform();
        try {
            if (e.button === 1 || spaceDown) {
                drag = { kind: 'pan', x: e.clientX, y: e.clientY, panX: tr.panX, panY: tr.panY };
            }
            else if (view === 'split' && brushTool) {
                const r = state().split;
                if (!$('brush-erase').checked)
                    C.integer($('brush-slot').value, 'Tile', 1, r.settings.a * r.settings.b);
                brushMap = new Int32Array(splitMap());
                const overlay = getOverlay();
                brushOverlay = document.createElement('canvas');
                brushOverlay.width = model.width;
                brushOverlay.height = model.height;
                brushOverlay.getContext('2d').drawImage(overlay, 0, 0);
                drag = { kind: 'brush', point };
                paintStroke(point);
            }
            else if (view === 'sprite' && measureTool) {
                const f = primary(), p = [...model.items].reverse().find(p => p.frame?.id === f?.id);
                if (!f || !p) throw new Error('Kein Sprite zum Vermessen ausgewählt.');
                if (!['current', 'overlay'].includes($('compare').value))
                    throw new Error('Für eine Messung „Bearbeitet“ oder „Quelle + Ziel“ anzeigen.');
                const at = { x: C.snapCoordinate(point.x - p.x, snapStep),
                    y: C.snapCoordinate(point.y - p.y, snapStep) };
                if (at.x < 0 || at.x > p.width || at.y < 0 || at.y > p.height)
                    throw new Error('Messpunkt außerhalb des Bildes.');
                if (!measureStart || measureStart.frameId !== f.id ||
                        measureStart.imageId !== f.imageId) {
                    measureStart = { frameId: f.id, imageId: f.imageId, point: at };
                    measurement = null;
                }
                else {
                    measurement = { frameId: f.id, imageId: f.imageId,
                        ...C.measurePoints(measureStart.point, at, snapStep) };
                    measureStart = null;
                    measureTool = false;
                    panel = 'geometry';
                }
                render();
            }
            else if (view === 'sprite' && pivotTool) {
                const f = primary(), p = model.items.find(p => p.frame?.id === f?.id);
                if (!f || !p)
                    throw new Error('Kein bearbeitbarer Sprite ausgewählt.');
                if (f.locked)
                    throw new Error('Sprite ist gesperrt.');
                if ($('compare').value !== 'current')
                    throw new Error('Zum Setzen des Pivots „Bearbeitet“ anzeigen.');
                const nextPivot = C.pivotFromPixel(store().get(f.imageId), point.x - p.x, point.y - p.y, false);
                selected = new Set([f.id]);
                frameUpdate(a => {
                    a.pivot = { x: Math.round(nextPivot.x * 1e6) / 1e6, y: Math.round(nextPivot.y * 1e6) / 1e6 };
                    a.metadataStatus = 'manual';
                }, 'Pivot setzen');
            }
            else if (view === 'scene' || view === 'atlas') {
                const f = hitFrame(point);
                if (f) {
                    if (!selected.has(f.id) || e.ctrlKey || e.metaKey || e.shiftKey)
                        selectFrame(f.id, e);
                    if (view === 'scene' && !f.locked && selected.has(f.id))
                        drag = { kind: 'sprite', x: e.clientX, y: e.clientY, dx: 0, dy: 0, zoom: tr.zoom };
                }
                else
                    drag = { kind: 'pan', x: e.clientX, y: e.clientY, panX: tr.panX, panY: tr.panY };
            }
            else
                drag = { kind: 'pan', x: e.clientX, y: e.clientY, panX: tr.panX, panY: tr.panY };
            requestDraw();
        }
        catch (err) {
            drag = null;
            brushMap = brushOverlay = null;
            report(err);
        }
    }
    function pointerMove(e) {
        if (!drag)
            return;
        try {
            if (drag.kind === 'pan') {
                const t = getTransform();
                t.panX = drag.panX + e.clientX - drag.x;
                t.panY = drag.panY + e.clientY - drag.y;
            }
            else if (drag.kind === 'sprite') {
                drag.dx = (e.clientX - drag.x) / drag.zoom;
                drag.dy = (e.clientY - drag.y) / drag.zoom;
            }
            else if (drag.kind === 'brush') {
                const point = screenToImage(e);
                paintStroke(point, drag.point);
                drag.point = point;
            }
            requestDraw();
        }
        catch (err) {
            drag = null;
            brushMap = brushOverlay = null;
            report(err);
        }
    }
    $('viewport').addEventListener('pointerdown', pointerDown);
    $('viewport').addEventListener('pointermove', pointerMove);
    function endPointer(cancelled = false) {
        const d = drag;
        drag = null;
        if (!d)
            return;
        try {
            if (!cancelled && d.kind === 'sprite' && (Math.round(d.dx) || Math.round(d.dy)))
                frameUpdate(f => {
                    if (!f.locked) {
                        f.dx += Math.round(d.dx);
                        f.dy += Math.round(d.dy);
                    }
                }, 'Sprites verschieben');
            else if (!cancelled && d.kind === 'brush' && brushMap) {
                const s = I.clone(state()), next = store().fork(), img = next.get(s.split.imageId);
                s.split.mapId = next.add(C.ownershipImage(brushMap, img.width, img.height));
                brushMap = brushOverlay = null;
                commit(s, 'Schnittmaske malen', next);
            }
        }
        catch (e) {
            report(e);
        }
        finally {
            brushMap = brushOverlay = null;
            requestDraw();
        }
    }
    $('viewport').addEventListener('pointerup', () => endPointer());
    $('viewport').addEventListener('pointercancel', () => endPointer(true));
    $('viewport').addEventListener('wheel', e => {
        e.preventDefault();
        zoom(Math.exp(-e.deltaY * .0015), e);
    }, { passive: false });
    async function nativeCanvasGesture(request) {
        const { points, button, ctrlKey = false, shiftKey = false } = request;
        if (![0, 1].includes(button) || typeof ctrlKey !== 'boolean' || typeof shiftKey !== 'boolean' ||
            !Array.isArray(points) || !points.length || points.length > 256 || points.some(point =>
                !point || typeof point !== 'object' || Array.isArray(point) ||
                Object.keys(point).length !== 2 || !Object.hasOwn(point, 'x') || !Object.hasOwn(point, 'y') ||
                typeof point.x !== 'number' || typeof point.y !== 'number' ||
                !Number.isFinite(point.x) || !Number.isFinite(point.y) ||
                Math.abs(point.x) > 131072 || Math.abs(point.y) > 131072))
            throw Object.assign(new Error('Expected 1–256 finite model points, button 0/1 and boolean modifiers.'), { code: 'invalid' });
        let length = 0;
        for (let i = 1; i < points.length; i++) length += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
        if (length > 131072) throw Object.assign(new Error('Native gesture exceeds the path budget.'), { code: 'invalid' });
        if (busy || drag || brushMap || spaceDown)
            throw Object.assign(new Error('An existing user or editor operation is active.'), { code: 'busy' });
        await task('Canvas-Geste', async () => {
            nativeCheckpoint();
            draw();
            if (!model) throw Object.assign(new Error(layoutError || 'No native canvas model is available.'), { code: 'disabled' });
            // Bound native work before touching the original brush callbacks.
            if (view === 'split' && brushTool && button === 0) {
                const radius = C.integer($('brush-radius').value, 'Radius', 1, 128);
                if (points.some(p => p.x < 0 || p.y < 0 || p.x > model.width || p.y > model.height))
                    throw Object.assign(new Error('Brush points must be inside the split model.'), { code: 'invalid' });
                let work = 0;
                for (let i = 0; i < points.length; i++) {
                    const a = points[Math.max(0, i - 1)], b = points[i];
                    work += Math.min(model.width, Math.abs(b.x - a.x) + 2 * radius + 2) *
                        Math.min(model.height, Math.abs(b.y - a.y) + 2 * radius + 2) +
                        Math.hypot(b.x - a.x, b.y - a.y) * radius * 8;
                }
                if (work > C.LIMITS.pixels * 8)
                    throw Object.assign(new Error('Split brush gesture exceeds the native work budget.'), { code: 'invalid' });
            }
            const transform = screenTransform(), rect = $('viewport').getBoundingClientRect();
            const event = point => ({ clientX: rect.left + transform.x + point.x * transform.zoom,
                clientY: rect.top + transform.y + point.y * transform.zoom,
                button, ctrlKey, shiftKey, isTrusted: false, nativeGesture: true,
                preventDefault() {} });
            let started = false, completed = false;
            try {
                nativeCheckpoint();
                started = true;
                pointerDown(event(points[0]));
                for (let i = 1; i < points.length; i++) {
                    if (i % 8 === 0) await I.tick();
                    nativeCheckpoint();
                    if (nativeLastError) throw new Error(nativeLastError);
                    pointerMove(event(points[i]));
                }
                await I.tick();
                nativeCheckpoint();
                endPointer();
                completed = true;
            } finally {
                if (started && !completed) endPointer(true);
            }
        });
    }
    async function dbOpen() {
        if (!globalThis.indexedDB)
            throw new Error('IndexedDB nicht verfügbar.');
        return new Promise((resolve, reject) => {
            const r = indexedDB.open('StrongholdSpriteEditor', 1);
            r.onupgradeneeded = () => r.result.createObjectStore('recovery', { keyPath: 'id' });
            r.onsuccess = () => resolve(r.result);
            r.onerror = () => reject(r.error);
            r.onblocked = () => reject(new Error('Lokale Sicherung ist blockiert.'));
        });
    }
    async function dbAction(mode, fn) {
        const db = await dbOpen();
        try {
            return await new Promise((resolve, reject) => {
                const tx = db.transaction('recovery', mode), s = tx.objectStore('recovery');
                let request;
                try {
                    request = fn(s);
                }
                catch (e) {
                    tx.abort();
                    reject(e);
                    return;
                }
                tx.oncomplete = () => resolve(request?.result);
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error || new Error('Sicherung abgebrochen.'));
            });
        }
        finally {
            db.close();
        }
    }
    async function findRecovery() {
        try {
            const records = await dbAction('readonly', s => s.getAll());
            recoveryCandidate = records.sort((a, b) => b.updated - a.updated)[0] || null;
            if (recoveryCandidate) {
                $('recovery-text').textContent = `Lokale Sicherung: ${recoveryCandidate.name} · ${new Date(recoveryCandidate.updated).toLocaleString('de-DE')}`;
                $('recovery-bar').hidden = false;
            }
        }
        catch (_e) {
            recoveryEnabled = false;
            $('recovery-status').textContent = 'Ohne Autosicherung';
        }
    }
    function scheduleRecovery() {
        clearTimeout(recoveryTimer);
        if (!recoveryEnabled || (!state().frames.length && !state().split))
            return;
        recoveryTimer = setTimeout(() => saveRecovery().catch(e => {
            recoveryEnabled = false;
            $('recovery-status').textContent = 'Sicherung fehlgeschlagen';
            $('recovery-status').title = e.message + ' — Projektdatei über Speichern ausgeben.';
        }), 1700);
    }
    async function saveRecovery() {
        if (recoveryRunning) {
            recoveryAgain = true;
            return;
        }
        if (busy) {
            scheduleRecovery();
            return;
        }
        recoveryRunning = true;
        const snapshot = state(), assets = store().fork(), generation = autosaveGeneration;
        const rev = history.revision;
        try {
            $('recovery-status').textContent = 'Sichert…';
            const data = await I.writeProject(snapshot, assets);
            if (generation !== autosaveGeneration)
                return;
            await dbAction('readwrite', s => s.put({ id: sessionId, name: snapshot.project.name, updated: Date.now(), data }));
            const records = await dbAction('readonly', s => s.getAll());
            if (records.length > 6) {
                const remove = records.sort((a, b) => b.updated - a.updated).slice(6).filter(r => r.id !== sessionId);
                await dbAction('readwrite', s => {
                    for (const r of remove)
                        s.delete(r.id);
                });
            }
            $('recovery-status').textContent = 'Lokal gesichert';
            if (history.revision !== rev)
                recoveryAgain = true;
        }
        finally {
            recoveryRunning = false;
            if (recoveryAgain) {
                recoveryAgain = false;
                scheduleRecovery();
            }
        }
    }
    async function recover() {
        if (!recoveryCandidate)
            return;
        const go = async () => {
            const record = recoveryCandidate;
            let result;
            await task('Lokale Sicherung öffnen', async (opts) => result = await I.readProject(await K.unzip(record.data, opts), opts));
            setProject(result, 'Lokale Sicherung wiederhergestellt.');
            dirty = true;
            $('recovery-bar').hidden = true;
            render();
        };
        if (dirty)
            confirmDialog('Sicherung wiederherstellen', 'Ungespeicherte Änderungen des aktuellen Projekts werden ersetzt.', go);
        else
            await go();
    }
    async function discardRecovery() {
        if (recoveryCandidate) {
            await dbAction('readwrite', s => s.delete(recoveryCandidate.id));
            recoveryCandidate = null;
        }
        $('recovery-bar').hidden = true;
    }
    function demoData() {
        const s = I.blank(), st = new I.AssetStore(), gid = I.uid('g'), settings = C.scene({ a: 5, b: 5 }), ps = C.positions(settings);
        s.project = {
            name: 'Steinhof · Beispiel', author: '', id: 'sprite-beispiel', version: '1.0.0', description: 'Synthetische Beispieldaten für Geometrie und Bildprüfung.', provenance: 'Synthetische Testgrafiken des Editors. Keine Grafiken oder verifizierten Ziel-IDs aus Stronghold. Nicht als Spielmod verwenden.'
        };
        s.scenes.push({ id: gid, name: 'tile_beispiel', source: 'custom', settings });
        const polygon = (img, pts, color) => {
            const minY = Math.max(0, Math.floor(Math.min(...pts.map(p => p[1])))), maxY = Math.min(img.height, Math.ceil(Math.max(...pts.map(p => p[1]))));
            for (let y = minY; y < maxY; y++)
                for (let x = 0; x < img.width; x++) {
                    let inside = false;
                    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
                        const a = pts[i], b = pts[j];
                        if (((a[1] > y + .5) !== (b[1] > y + .5)) && (x + .5 < (b[0] - a[0]) * (y + .5 - a[1]) / (b[1] - a[1]) + a[0]))
                            inside = !inside;
                    }
                    if (inside) {
                        const noise = ((x * 13 + y * 7 + img.height * 3) % 9) - 4;
                        img.data.set([color[0] + noise, color[1] + noise, color[2] + noise, 255], (y * img.width + x) * 4);
                    }
                }
        };
        for (const p of ps) {
            const back = p.u === 4 || p.v === 4, h = back ? 112 : 32, img = C.image(64, h);
            polygon(img, [[32, h - 32], [64, h - 16], [32, h], [0, h - 16]], [132 + (p.slot % 3) * 5, 132 + (p.slot % 3) * 4, 113]);
            if (back) {
                const high = (p.u === 4 && p.v === 4) ? 14 : 24 + (p.slot % 3) * 7;
                polygon(img, [[0, h - 16], [32, h - 32], [32, high], [0, high + 16]], [151, 149, 135]);
                polygon(img, [[32, h - 32], [64, h - 16], [64, high + 16], [32, high]], [117, 119, 111]);
                polygon(img, [[0, high + 16], [32, high], [64, high + 16], [32, high + 32]], [179, 176, 158]);
                for (let y = high + 24; y < h - 28; y++)
                    for (let x = 2; x < 62; x++) {
                        const i = (y * 64 + x) * 4;
                        if (img.data[i + 3] && (y + Math.floor(Math.abs(x - 32) / 2)) % 13 === 0) {
                            img.data[i] = 91;
                            img.data[i + 1] = 94;
                            img.data[i + 2] = 89;
                        }
                    }
                if (p.slot % 3 === 1) {
                    polygon(img, [[24, h - 47], [35, h - 53], [35, h - 78], [24, h - 72]], [53, 61, 62]);
                }
            }
            else {
                for (let y = h - 27; y < h - 4; y++)
                    for (let x = 5; x < 59; x++) {
                        const i = (y * 64 + x) * 4;
                        if (img.data[i + 3] && ((x + y * 2 + p.slot * 3) % 31 === 0)) {
                            img.data[i] = 110;
                            img.data[i + 1] = 114;
                            img.data[i + 2] = 96;
                        }
                    }
            }
            const key = st.add(img), f = I.makeFrame(`tile_beispiel-${p.slot}.png`, key, gid, st);
            f.slot = p.slot;
            s.frames.push(f);
        }
        return { state: I.validate(s, st), store: st };
    }
    function loadDemo() {
        const go = () => {
            setProject(demoData());
            dirty = true;
            render();
        };
        if (dirty)
            confirmDialog('Beispiel öffnen', 'Das aktuelle Projekt wird durch synthetische Beispieldaten ersetzt.', go);
        else
            go();
    }
    const actions = {
        import: () => importDialog([], view === 'split' ? 'split' : 'png'), open: () => openProject(), save: saveProject, new: newProject, project: projectDialog, export: exportDialog, help: helpDialog, demo: loadDemo,
        undo: () => {
            if (history.undo())
                afterChange();
        }, redo: () => {
            if (history.redo())
                afterChange();
        }, fit: () => {
            fitNext = true;
            requestDraw();
        }, actual: () => {
            getTransform().zoom = 1;
            getTransform().panX = getTransform().panY = 0;
            requestDraw();
        }, 'zoom-in': () => zoom(1.25), 'zoom-out': () => zoom(.8),
        'select-all': selectAll, delete: deleteSelected, 'close-toast': () => $('toast').hidden = true, 'close-modal': closeModal,
        'toggle-files': () => $('files-panel').classList.toggle('open'), 'toggle-inspector': () => $('inspector').classList.toggle('open'),
        'pivot-tool': () => {
            pivotTool = !pivotTool;
            measureTool = false;
            measureStart = null;
            render();
        }, 'measure-tool': () => {
            measureTool = !measureTool;
            pivotTool = false;
            measureStart = null;
            panel = 'geometry';
            render();
        }, 'brush-tool': () => {
            brushTool = !brushTool;
            render();
        }, 'split-import': () => importDialog([], 'split'), 'scene-to-split': sceneToSplit, 'clear-history': () => confirmDialog('Historie leeren', 'Rückgängig- und Wiederholen-Schritte werden gelöscht. Originalbilder und aktuelles Projekt bleiben erhalten.', () => {
            history.clearHistory();
            render();
        }),
        'split-transfer': () => {
            const r = I.transferSplit(state(), store());
            commit(r.state, 'Schnitt als Tiles übernehmen', r.store, { fit: true });
            groupId = r.groupId;
            selected = new Set(r.state.frames.filter(f => f.groupId === groupId).slice(0, 1).map(f => f.id));
            view = 'scene';
            render();
        },
        'prev-frame': () => {
            const n = animationFrames().length;
            animIndex = n ? (animIndex - 1 + n) % n : 0;
            playing = false;
            render();
        }, 'next-frame': () => {
            const n = animationFrames().length;
            animIndex = n ? (animIndex + 1) % n : 0;
            playing = false;
            render();
        }, play: () => {
            if (!animationFrames().length)
                throw new Error('Keine sichtbaren Animationsframes.');
            playing = !playing;
            lastFrameTime = performance.now();
            render();
        },
        recover, 'discard-recovery': discardRecovery
    };
    document.addEventListener('click', e => {
        const action = e.target.closest('[data-action]'), viewButton = e.target.closest('[data-view]'), panelButton = e.target.closest('[data-panel]');
        if (action) {
            if (busy && action.dataset.action !== 'close-toast')
                return;
            document.querySelectorAll('details.menu').forEach(d => d.open = false);
            Promise.resolve().then(() => actions[action.dataset.action]?.()).catch(report);
        }
        else if (viewButton && !busy)
            setView(viewButton.dataset.view);
        else if (panelButton && !busy) {
            setPanel(panelButton.dataset.panel);
        }
        if (!e.target.closest('.menu'))
            document.querySelectorAll('details.menu').forEach(d => d.open = false);
    });
    $('group-select').onchange = () => {
        groupId = $('group-select').value;
        const matched = (state().damageProfiles || []).find(p => p.stages.some(s => s.sceneId === groupId));
        damageBuildingId = matched ? matched.buildingGroupId : groupId;
        selected = new Set(groupFrames().slice(0, 1).map(f => f.id));
        $('asset-list').scrollTop = 0;
        animIndex = 0;
        playing = false;
        fitNext = true;
        render();
    };
    $('search').oninput = () => {
        $('asset-list').scrollTop = 0;
        renderList();
    };
    $('asset-list').onscroll = () => renderList();
    for (const name of ['show-grid', 'show-labels', 'channel', 'compare', 'onion', 'split-overlay'])
        $(name).onchange = () => requestDraw();
    $('background').onchange = () => {
        $('canvas-wrap').className = 'canvas-wrap ' + $('background').value;
        requestDraw();
    };
    $('frame-slider').oninput = () => {
        animIndex = Number($('frame-slider').value);
        playing = false;
        render();
    };
    $('fps').onchange = () => {
        try {
            $('fps').value = C.integer($('fps').value, 'FPS', 1, 60);
        }
        catch (e) {
            $('fps').value = 12;
            report(e);
        }
    };
    function animate(time) {
        if (playing && !busy && !document.hidden && view === 'animation') {
            const fps = Number($('fps').value) || 12;
            if (time - lastFrameTime >= 1000 / fps) {
                const n = animationFrames().length;
                animIndex = n ? (animIndex + 1) % n : 0;
                lastFrameTime = time;
                requestDraw();
            }
        }
        requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
    document.addEventListener('keydown', e => {
        const input = e.target.closest('input,textarea,select,[contenteditable=true]'), dialogOpen = $('modal').open || $('busy-dialog').open;
        if (dialogOpen || busy)
            return;
        const cmd = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
        let action = null;
        if (cmd && key === 's') {
            action = saveProject;
        }
        else if (cmd && key === 'o')
            action = () => openProject();
        else if (cmd && key === 'n')
            action = newProject;
        else if (!input) {
            if (cmd && key === 'z')
                action = e.shiftKey ? actions.redo : actions.undo;
            else if (cmd && key === 'y')
                action = actions.redo;
            else if (cmd && key === 'a')
                action = selectAll;
            else if (key === 'delete')
                action = deleteSelected;
            else if (key === 'f')
                action = actions.fit;
            else if (key === '1')
                action = actions.actual;
            else if (key === '+' || key === '=')
                action = actions['zoom-in'];
            else if (key === '-')
                action = actions['zoom-out'];
            else if (e.code === 'Space') {
                e.preventDefault();
                spaceDown = true;
                requestDraw();
            }
            else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key) && view === 'scene' && selected.size) {
                const step = e.shiftKey ? 10 : 1;
                action = () => frameUpdate(f => {
                    if (f.locked)
                        return;
                    if (e.key === 'ArrowLeft')
                        f.dx -= step;
                    if (e.key === 'ArrowRight')
                        f.dx += step;
                    if (e.key === 'ArrowUp')
                        f.dy -= step;
                    if (e.key === 'ArrowDown')
                        f.dy += step;
                }, 'Sprites verschieben');
            }
        }
        if (action) {
            e.preventDefault();
            Promise.resolve().then(action).catch(report);
        }
    });
    document.addEventListener('keyup', e => {
        if (e.code === 'Space') {
            spaceDown = false;
            requestDraw();
        }
    });
    window.addEventListener('blur', () => {
        spaceDown = false;
        endPointer(true);
    });
    window.addEventListener('beforeunload', e => {
        if (dirty) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
    let dragDepth = 0;
    document.addEventListener('dragenter', e => {
        if (e.dataTransfer?.types.includes('Files')) {
            e.preventDefault();
            dragDepth++;
            $('drop-overlay').hidden = false;
        }
    });
    document.addEventListener('dragover', e => {
        if (e.dataTransfer?.types.includes('Files'))
            e.preventDefault();
    });
    document.addEventListener('dragleave', e => {
        if (e.dataTransfer?.types.includes('Files')) {
            dragDepth = Math.max(0, dragDepth - 1);
            if (!dragDepth)
                $('drop-overlay').hidden = true;
        }
    });
    document.addEventListener('drop', e => {
        e.preventDefault();
        dragDepth = 0;
        $('drop-overlay').hidden = true;
        if (busy || !e.dataTransfer?.files.length)
            return;
        const files = [...e.dataTransfer.files];
        if (files.length === 1 && /\.shsprite$/i.test(files[0].name))
            openProject(files).catch(report);
        else
            importDialog(files, view === 'split' ? 'split' : 'png');
    });
    new ResizeObserver(() => {
        requestDraw();
        renderList();
    }).observe($('canvas-wrap'));
    window.addEventListener('resize', requestDraw);
    window.SpriteEditor = Object.freeze({
        version: C.VERSION, inspect: () => ({
            state: I.clone(state()), selected: [...selected], groupId, view, panel, dirty, revision: history.revision, undo: history.past.length, redo: history.future.length, assetCount: store().items.size, pixels: store().pixels, playing, animIndex, model: model ? { width: model.width, height: model.height } : null
        })
    });
    function nativeFiles(files) {
        if (!Array.isArray(files) || !files.length || files.length > C.LIMITS.entries)
            throw Object.assign(new Error('Invalid native file count.'), { code: 'invalid' });
        let total = 0;
        return files.map(file => {
            if (!file || typeof file.name !== 'string' || typeof file.base64 !== 'string' ||
                Object.keys(file).some(k => !['name', 'base64'].includes(k)) ||
                !file.name || file.name.length > 255 || /[\\/\x00-\x1f]/.test(file.name) ||
                !/\.(png|json|zip|csv|shsprite)$/i.test(file.name) ||
                file.base64.length > Math.ceil(C.LIMITS.fileBytes / 3) * 4 ||
                file.base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(file.base64))
                throw Object.assign(new Error('Invalid native file name, type or byte budget.'), { code: 'invalid' });
            const raw = atob(file.base64);
            total += raw.length;
            if (!raw.length || raw.length > C.LIMITS.fileBytes || total > C.LIMITS.importBytes)
                throw Object.assign(new Error('Native file data exceeds the existing import budget.'), { code: 'invalid' });
            return new File([Uint8Array.from(raw, c => c.charCodeAt(0))], file.name);
        });
    }
    nativeApi = window.SpriteNativeAPI.create({
        document, sessionId: I.uid('native'), actions,
        historyRevision: () => history.revision, busy: () => busy || !!drag || !!brushMap || spaceDown,
        inspect: () => {
            if (renderQueued) draw();
            return { ...window.SpriteEditor.inspect(),
                model: model ? { width: model.width, height: model.height,
                    transform: screenTransform(), items: model.items.map((item, index) => ({
                        id: item.id || (item.frame ? item.frame.id + ':' + index : 'model-item-' + index), frameId: item.frame?.id || null,
                        x: item.x, y: item.y, width: item.width, height: item.height })) } : null,
                canvas: { drag: drag ? { kind: drag.kind } : null, brushActive: !!brushMap,
                    measurement: activeMeasurement() ? I.clone(activeMeasurement()) : null,
                    measureStart: measureStart ? I.clone(measureStart) : null,
                    pivotTool, measureTool, brushTool }
            };
        }, setView, setPanel, canvasGesture: nativeCanvasGesture,
        begin: signal => { nativeDispatch = true; nativeAbortSignal = signal; },
        end: () => { nativeDispatch = false; nativeAbortSignal = null; nativePickedFiles = null; },
        openFiles: files => openProject(nativeFiles(files)),
        importFiles: files => importDialog(nativeFiles(files), view === 'split' ? 'split' : 'png'),
        setSelection: frameIds => {
            if (!frameIds.length || frameIds.length > C.LIMITS.frames ||
                frameIds.some(id => typeof id !== 'string' || !id || id.length > 1024) ||
                new Set(frameIds).size !== frameIds.length)
                throw Object.assign(new Error('Select existing, distinct native frame IDs.'), { code: 'invalid' });
            const frames = frameIds.map(id => state().frames.find(frame => frame.id === id));
            if (frames.some(frame => !frame))
                throw Object.assign(new Error('Unknown native frame identity.'), { code: 'unknown' });
            if (frames.some(frame => frame.groupId !== frames[0].groupId))
                throw Object.assign(new Error('Native multi-selection belongs to one asset group.'), { code: 'invalid' });
            if (groupId !== frames[0].groupId) {
                $('group-select').value = frames[0].groupId;
                $('group-select').dispatchEvent(new Event('change', { bubbles: true }));
            }
            if ($('search').value) {
                $('search').value = '';
                $('search').dispatchEvent(new Event('input', { bubbles: true }));
            }
            frameIds.forEach((id, index) => selectFrame(id, { ctrlKey: index > 0 }));
        },
        modalOpen: () => $('modal').open,
        modalState: () => ({ open: $('modal').open, formId: $('modal').open ? 'modal-form' : null,
            title: $('modal-title').textContent,
            error: $('modal-error').hidden ? null : $('modal-error').textContent,
            submitEnabled: !$('modal-submit').hidden && !$('modal-submit').disabled }),
        clearError: () => { nativeLastError = null; },
        lastError: () => nativeLastError || ($('modal').open && !$('modal-error').hidden ? $('modal-error').textContent : null),
        submitForm: () => $('modal-form').onsubmit({ preventDefault() {} }),
        invokeControl: control => nativeCallbacks.has(control) ? nativeCallbacks.get(control)() : control.click(),
        invokeFiles: (control, files) => {
            if (!nativeCallbacks.has(control))
                throw Object.assign(new Error('This control has no native file callback; use project.open/files.import.'), { code: 'unknown' });
            nativePickedFiles = nativeFiles(files);
            return nativeCallbacks.get(control)();
        }
    });
    window.SuiteEditorAPI = nativeApi;
    render();
    findRecovery();
    window.SpriteNativeBridge.install(nativeApi);
})();
