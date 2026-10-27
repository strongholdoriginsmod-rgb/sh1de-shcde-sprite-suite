/* Stronghold Sprite Editor. DOM and canvas view; all exports use the independent RGBA codec. */
(function () {
    'use strict';
    const C = window.SpriteCore, K = window.SpriteCodec, I = window.SpriteIO, $ = id => document.getElementById(id);
    if (!window.crypto?.getRandomValues || !window.CompressionStream || !window.DecompressionStream || !window.structuredClone) {
        document.body.textContent = 'Dieser Browser unterstützt die benötigten lokalen Datei- und Kompressionsfunktionen nicht. Die HTML-Datei in einer aktuellen Chromium-basierten Desktop-Version öffnen.';
        return;
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
    let playing = false, animIndex = 0, lastFrameTime = 0, pivotTool = false, brushTool = false, brushMap = null, drag = null, spaceDown = false, renderQueued = false, model = null, layoutError = '', fitNext = true, atlasGroup = '';
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
        if (history.commit(next, nextStore, label))
            afterChange(options);
    }
    function edit(fn, label = 'Bearbeitung', options = {}) {
        const next = I.clone(state());
        fn(next);
        commit(next, label, store(), options);
    }
    async function task(title, fn) {
        if (busy)
            throw new Error('Ein anderer Vorgang läuft bereits.');
        busy = true;
        playing = false;
        aborter = new AbortController();
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
        const blob = data instanceof Blob ? data : new Blob([data], { type });
        const url = URL.createObjectURL(blob), a = el('a', { href: url, download: C.safeName(name) });
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    function askFiles(accept, multiple = true, directory = false) {
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
    const fields = (...children) => el('div', { class: 'fields' }, children), buttons = (...children) => el('div', { class: 'field-inline' }, children), button = (label, fn, props = {}) => el('button', { type: 'button', text: label, onclick: () => Promise.resolve().then(fn).catch(report), ...props }), note = text => el('p', { class: 'inspector-note', text });
    function section(title, children = []) {
        return el('section', { class: 'inspector-section' }, [el('h3', { text: title }), ...children]);
    }
    const line = (label, value) => el('div', { class: 'info-line' }, [el('span', { text: label }), el('span', { text: String(value) })]);
    function modal(title, content, submit, handler) {
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
        playing = false;
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
                    const map = C.partition(img, settings, anchorX, anchorY, true), mapId = next.add(C.ownershipImage(map, img.width, img.height)), s = I.clone(state());
                    s.split = { imageId, maskId, mapId, settings, anchorX, anchorY, extend: true, group: 'tile_custom', start: 0, source: optsBase.source };
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
            return section('Schnitt', [button('Gesamtbild laden…', () => importDialog([], 'split')), note('Das Bild wird in disjunkte Tiles zerlegt. Verdeckte Originalpixel lassen sich aus einem flachen PNG nicht rekonstruieren.')]);
        const s = r.settings, change = (key, v) => edit(st => {
            st.split[key] = v;
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
            fields(num('Links', s.a, v => setting('a', C.integer(v, 'Links', 1, 64)), { min: 1, max: 64 }), num('Rechts', s.b, v => setting('b', C.integer(v, 'Rechts', 1, 64)), { min: 1, max: 64 }), num('Tilebreite · px', s.width, v => setting('width', C.integer(v, 'Tilebreite', 2, 2048)), { min: 2, max: 2048, step: 2 }), num('Rautenhöhe · px', s.height, v => setting('height', C.integer(v, 'Rautenhöhe', 2, 2048)), { min: 2, max: 2048, step: 2 }), num('Frontanker X', r.anchorX, v => change('anchorX', C.integer(v, 'Anker X'))), num('Frontanker Y', r.anchorY, v => change('anchorY', C.integer(v, 'Anker Y')))),
            buttons(checkbox('Hintere Flächen nach oben verlängern', r.extend, '', v => change('extend', v))), buttons(button('Raster anwenden', regenerateSplit)),
            fields(field('Zielgruppe', r.group, { wide: true, onchange: v => change('group', v) }), num('Startindex', r.start, v => change('start', C.integer(v, 'Startindex', 0, 1000000)), { min: 0, max: 1000000 })),
            ...(stats.error ? [note(stats.error)] : [line('Nicht zugeordnet', stats.unassigned.toLocaleString('de-DE') + ' Pixel'), line('Breite überschritten', stats.overwide + ' Tiles')]),
            buttons(button('Maske importieren…', () => importDialog([], 'ownership')), button('Schnitt exportieren', () => exportDirect('split'))), note('Rastergrößenänderungen und „Raster anwenden“ ersetzen die manuelle Zuordnung. Änderungen bleiben rückgängig machbar. Schnittflächen werden als RGB-Indexbild gespeichert.')
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
                buttons(button('Serie zuordnen…', mappingDialog)), buttons(checkbox('Zielnamen manuell bestätigt', ff.every(x => x.targetConfirmed), '', v => frameUpdate(x => x.targetConfirmed = v))),
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
    function renderInspector() {
        const root = $('inspector-content');
        root.replaceChildren();
        for (const b of document.querySelectorAll('[data-panel]'))
            b.classList.toggle('active', b.dataset.panel === panel);
        try {
            if (panel === 'target')
                root.append(...targetSection());
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
            el('div', { class: 'field-inline' }, [checkbox('Abstände der Quellnummern erhalten', false, 'gaps')]), el('div', { class: 'field-inline' }, [checkbox('Zielnamen manuell geprüft', false, 'confirmed')])
        ], 'Zuordnen', data => {
            const group = String(data.get('group')), start = C.integer(data.get('start'), 'Zielindex', 0, 1000000), gaps = !!data.get('gaps'), confirmed = !!data.get('confirmed');
            C.targetName(group + '-' + start);
            if (gaps && ff.some(f => f.index === null))
                throw new Error('Nicht alle Quellen besitzen eine Bildnummer.');
            const min = Math.min(...ff.map(f => f.index ?? 0));
            edit(s => {
                ff.forEach((old, i) => {
                    const f = s.frames.find(f => f.id === old.id);
                    f.targetName = C.targetName(group + '-' + (start + (gaps ? old.index - min : i))).name;
                    f.targetConfirmed = confirmed;
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
            s.split = {
                imageId, maskId, mapId: next.add(C.ownershipImage(map, img.width, img.height)), settings, anchorX: l.originX, anchorY: l.originY, extend: true, group: g.name, start: Math.min(...ff.map(f => f.index ?? 0)), source: g.source
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
        const type = field('Format', 'merged', { name: 'kind', wide: true, options: exportTypes }), scope = field('Umfang', 'group', { name: 'scope', wide: true, options: [['group', 'Aktuelle Gruppe'], ['selected', 'Ausgewählte Sprites'], ['all', 'Alle Gruppen']] }), details = el('p'), warnings = el('div', { class: 'field-inline' }, [checkbox('Hinweise geprüft; In-Game-Test folgt.', false, 'ack')]);
        const refresh = () => {
            const kind = type.querySelector('select').value, isMod = ['mod', 'semod'].includes(kind);
            scope.hidden = !['tiles', 'originals', 'atlas', 'csv'].includes(kind);
            warnings.hidden = !isMod;
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
        modal('Exportieren', [fields(type, scope), details, warnings], 'Exportieren', async (data) => {
            const kind = String(data.get('kind'));
            if (['mod', 'semod'].includes(kind) && !data.get('ack'))
                throw new Error('Exporthinweise bestätigen.');
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
        cv.style.cursor = view === 'split' && brushTool ? 'crosshair' : view === 'sprite' && pivotTool ? 'crosshair' : spaceDown || drag?.kind === 'pan' ? 'grab' : 'default';
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
        $('brush-tool').setAttribute('aria-pressed', brushTool);
        $('play').textContent = playing ? 'Pause' : 'Abspielen';
        $('status-left').textContent = currentGroup() ? `${currentGroup().name} · ${I.originLabel(currentGroup().source)}` : state().split && view === 'split' ? 'Schnittbild' : 'Keine Dateien';
        requestDraw();
    }
    function setView(next) {
        if (view === next)
            return;
        playing = false;
        view = next;
        animIndex = 0;
        fitNext = !transforms.has(view);
        render();
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
    $('viewport').addEventListener('pointerdown', e => {
        if (busy || !model || ![0, 1].includes(e.button))
            return;
        e.preventDefault();
        $('viewport').focus();
        $('viewport').setPointerCapture(e.pointerId);
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
            else if (view === 'sprite' && pivotTool) {
                const f = primary(), p = model.items.find(p => p.frame?.id === f?.id);
                if (!f || !p)
                    throw new Error('Kein bearbeitbarer Sprite ausgewählt.');
                if (f.locked)
                    throw new Error('Sprite ist gesperrt.');
                if ($('compare').value !== 'current')
                    throw new Error('Zum Setzen des Pivots „Bearbeitet“ anzeigen.');
                const x = C.number((point.x - p.x) / p.width, 'Pivot X', 0, 1), y = C.number(1 - (point.y - p.y) / p.height, 'Pivot Y', 0, 1);
                selected = new Set([f.id]);
                frameUpdate(a => {
                    a.pivot = { x: Math.round(x * 1e6) / 1e6, y: Math.round(y * 1e6) / 1e6 };
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
    });
    $('viewport').addEventListener('pointermove', e => {
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
    });
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
            panel = panelButton.dataset.panel;
            renderInspector();
        }
        if (!e.target.closest('.menu'))
            document.querySelectorAll('details.menu').forEach(d => d.open = false);
    });
    $('group-select').onchange = () => {
        groupId = $('group-select').value;
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
    render();
    findRecovery();
})();
