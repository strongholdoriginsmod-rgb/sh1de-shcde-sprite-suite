'use strict';
// Actual standalone HTML, isolated Chromium profile, synthetic project only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const html = path.join(root, 'Stronghold_Sprite_Editor.html');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
    const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'spritesuite-native-'));
    const profile = path.join(temp, 'profile'), downloads = path.join(temp, 'downloads');
    fs.mkdirSync(downloads);
    let chrome, socket;
    const errors = [], network = [], checks = [];
    try {
        chrome = spawn(process.env.SPRITESUITE_CHROMIUM ||
            'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            ['--headless=new', '--no-first-run', '--disable-gpu', '--disable-background-networking',
             '--no-default-browser-check', '--disable-component-update', '--remote-allow-origins=*',
             '--user-data-dir=' + profile, '--remote-debugging-port=0', 'about:blank'],
            { stdio: 'ignore', windowsHide: true });
        let port;
        for (let i = 0; i < 130; i++) {
            try { port = Number(fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split(/\r?\n/)[0]); }
            catch (e) { if (!['EBUSY', 'EACCES', 'ENOENT'].includes(e.code)) throw e; }
            if (port) break;
            if (chrome.exitCode != null) throw Error('Browser exited before its debug endpoint.');
            await delay(100);
        }
        assert.ok(port, 'No isolated browser endpoint');
        const pages = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
        socket = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
        await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
        let serial = 0;
        const pending = new Map();
        socket.onmessage = event => {
            const m = JSON.parse(event.data);
            if (m.id && pending.has(m.id)) {
                const item = pending.get(m.id); pending.delete(m.id); clearTimeout(item.timer);
                if (m.error) item.reject(Error(JSON.stringify(m.error))); else item.resolve(m.result || {});
            } else if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text);
            else if (m.method === 'Network.requestWillBeSent' && /^https?:/.test(m.params.request.url)) network.push(m.params.request.url);
        };
        function send(method, params = {}) {
            return new Promise((resolve, reject) => {
                const id = ++serial, timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 30000);
                pending.set(id, { resolve, reject, timer });
                socket.send(JSON.stringify({ id, method, params }));
            });
        }
        async function evaluate(expression) {
            const out = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
            if (out.exceptionDetails) throw Error(JSON.stringify(out.exceptionDetails));
            return out.result?.value;
        }
        async function wait(expression) {
            for (let i = 0; i < 120; i++) { if (await evaluate(expression)) return; await delay(100); }
            throw Error('Browser condition timed out: ' + expression);
        }
        const execute = (operation, fields = {}) => evaluate('SuiteEditorAPI.execute(' + JSON.stringify({ operation, ...fields })
            .replace(/}$/, ',"expectedRevision":SuiteEditorAPI.inspect().revision}') + ')');
        await send('Runtime.enable'); await send('Page.enable'); await send('Network.enable');
        await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 720, deviceScaleFactor: 1, mobile: false });
        await send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloads });
        await send('Page.navigate', { url: pathToFileURL(html).href });
        await wait('!!window.SuiteEditorAPI');
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 0);
        assert.equal(await evaluate('SuiteEditorAPI.inspect().dirty'), false);
        assert.equal(await evaluate('SuiteEditorAPI.discover().operations.length'), 13);
        checks.push('API installation does not perform an action');
        assert.equal((await execute('action.invoke', { actionId: 'demo' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 25);
        const targets = await evaluate('SpriteEditor.inspect().state.frames.slice(-2).map(f=>f.id)');
        assert.equal((await execute('selection.set', { frameIds: targets })).ok, true);
        assert.deepEqual(await evaluate('SpriteEditor.inspect().selected'), targets);
        assert.equal((await execute('selection.set', { frameIds: [targets[0]] })).ok, true);
        checks.push('native selection helper reaches virtualized frame IDs and Ctrl-style multi-selection');
        const old = await evaluate('SuiteEditorAPI.inspect().revision');
        assert.equal((await execute('view.set', { viewId: 'sprite' })).ok, true);
        const stale = await evaluate('SuiteEditorAPI.execute(' + JSON.stringify({ operation: 'action.invoke', actionId: 'delete', expectedRevision: old }) + ')');
        assert.equal(stale.error.code, 'stale');
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 25);
        checks.push('stale mutation is rejected without changing source');
        let state = await evaluate('SuiteEditorAPI.inspect()');
        const field = state.controls.find(c => c.label === 'Versatz X · px');
        assert.ok(field);
        const before = state.state.frames.find(f => state.selected.includes(f.id)).dx;
        assert.equal((await execute('field.set', { fieldId: field.id, value: before + 7 })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.find(f=>SpriteEditor.inspect().selected.includes(f.id)).dx'), before + 7);
        assert.equal((await execute('action.invoke', { actionId: 'undo' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.find(f=>SpriteEditor.inspect().selected.includes(f.id)).dx'), before);
        checks.push('native DOM edit shares existing Undo');
        assert.equal((await execute('view.set', { viewId: 'animation' })).ok, true);
        assert.equal((await execute('action.invoke', { actionId: 'play' })).ok, true);
        const animationRevision = await evaluate('SuiteEditorAPI.inspect().revision');
        await delay(240);
        assert.equal(await evaluate('SuiteEditorAPI.inspect().revision'), animationRevision);
        assert.equal((await execute('action.invoke', { actionId: 'play' })).ok, true);
        assert.equal((await execute('view.set', { viewId: 'sprite' })).ok, true);
        checks.push('animation drawing does not rotate native revision tokens');
        const imageBefore = await evaluate('SpriteEditor.inspect().state.frames.find(f=>SpriteEditor.inspect().selected.includes(f.id)).imageId');
        const replace = (await evaluate('SuiteEditorAPI.inspect()')).controls.find(c => c.label === 'PNG ersetzen…');
        assert.equal((await execute('control.files', { controlId: replace.id, files: [{ name: 'replace-synthetic.png',
            base64: fs.readFileSync(path.join(__dirname, 'fixtures/c6_d8_i0.png')).toString('base64') }] })).ok, true);
        assert.notEqual(await evaluate('SpriteEditor.inspect().state.frames.find(f=>SpriteEditor.inspect().selected.includes(f.id)).imageId'), imageBefore);
        assert.equal((await execute('action.invoke', { actionId: 'undo' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.find(f=>SpriteEditor.inspect().selected.includes(f.id)).imageId'), imageBefore);
        checks.push('provided replacement PNG reaches original file-button callback and Undo');
        assert.equal((await execute('action.invoke', { actionId: 'project' })).ok, true);
        const form = await execute('form.read', { formId: 'modal-form' });
        const nameField = form.result.fields.find(f => f.name === 'name');
        assert.equal((await execute('form.fill', { formId: 'modal-form', values: { [nameField.id]: 'Native synthetic project' } })).ok, true);
        assert.equal((await execute('form.submit', { formId: 'modal-form' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.project.name'), 'Native synthetic project');
        assert.equal(await evaluate('document.getElementById("modal").open'), false);
        checks.push('existing form fill/submit commits its normal history');
        assert.equal((await execute('action.invoke', { actionId: 'save' })).ok, true);
        for (let i = 0; i < 100 && !fs.readdirSync(downloads).some(n => n.endsWith('.shsprite')); i++) await delay(100);
        assert.ok(fs.readdirSync(downloads).some(n => n.endsWith('.shsprite')));
        checks.push('native save uses existing project download');
        const downloadCount = fs.readdirSync(downloads).length;
        const projectBeforeCancel = await evaluate('JSON.stringify(SpriteEditor.inspect().state)');
        const canceledSave = await evaluate(`(async()=>{const controller=new AbortController();
            const result=SuiteEditorAPI.execute({operation:'action.invoke',actionId:'save',
                expectedRevision:SuiteEditorAPI.inspect().revision},{signal:controller.signal});
            controller.abort(); return await result;})()`);
        assert.equal(canceledSave.error.code, 'canceled');
        await delay(150);
        assert.equal(fs.readdirSync(downloads).length, downloadCount);
        assert.equal(await evaluate('JSON.stringify(SpriteEditor.inspect().state)'), projectBeforeCancel);
        checks.push('in-flight native cancellation prevents late download and preserves project source');
        const saved = fs.readdirSync(downloads).find(n => n.endsWith('.shsprite'));
        assert.equal((await execute('project.open', { files: [{ name: saved,
            base64: fs.readFileSync(path.join(downloads, saved)).toString('base64') }] })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 25);
        checks.push('file-dialog-free project.open uses existing project reader');
        const imported = await execute('files.import', { files: [{ name: 'native-source.png',
            base64: fs.readFileSync(path.join(__dirname, 'fixtures/c6_d8_i0.png')).toString('base64') }] });
        assert.equal(imported.ok, true);
        assert.equal((await execute('form.submit', { formId: 'modal-form' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 26);
        assert.equal((await execute('action.invoke', { actionId: 'undo' })).ok, true);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames.length'), 25);
        checks.push('provided PNG files import through native form and Undo');
        assert.equal((await execute('action.invoke', { actionId: 'open' })).error.code, 'input_required');
        checks.push('native file picker actions return input_required without hanging');
        await evaluate(`window.nativeReachable = function(node) {
            const parents=[]; for(let p=node.parentElement;p;p=p.parentElement) parents.push({p,x:p.scrollLeft,y:p.scrollTop});
            node.scrollIntoView({block:'nearest',inline:'nearest'});
            for(const {p,x,y} of parents) {
                const css=getComputedStyle(p);
                if ((p.scrollTop!==y && !['auto','scroll'].includes(css.overflowY)) ||
                    (p.scrollLeft!==x && !['auto','scroll'].includes(css.overflowX)))
                    return {error:'requires non-user-scrollable ancestor',id:node.id,text:node.textContent,ancestor:p.className};
            }
            const r=node.getBoundingClientRect();
            if(r.width<=0||r.height<=0||r.top<-.5||r.left<-.5||r.bottom>innerHeight+.5||r.right>innerWidth+.5)
                return {error:'outside viewport',text:node.textContent,rect:r.toJSON()};
            for(const {p} of parents) {
                const s=getComputedStyle(p),a=p.getBoundingClientRect();
                if((['hidden','auto','scroll'].includes(s.overflowY)&&(r.top<a.top-1||r.bottom>a.bottom+1))||
                   (['hidden','auto','scroll'].includes(s.overflowX)&&(r.left<a.left-1||r.right>a.right+1)))
                    return {error:'clipped by ancestor',text:node.textContent,ancestor:p.className,rect:r.toJSON(),clip:a.toJSON()};
            }
            return null;
        }`);
        for (const [width, height] of [[1280,480],[1024,540],[800,500],[640,360]]) {
            await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
            if (width <= 960 && !await evaluate('document.getElementById("inspector").classList.contains("open")'))
                assert.equal((await execute('action.invoke', { actionId: 'toggle-inspector' })).ok, true);
            for (const viewId of ['scene','sprite','animation','split','atlas']) {
                assert.equal((await execute('view.set', { viewId })).ok, true);
                const bad = await evaluate(`(()=>{for(const n of document.querySelectorAll('.app-header>button,.view-tabs button,.canvas-toolbar button,.context-bar button,.context-bar input,.context-bar select')) {
                    if(!n.getClientRects().length)continue; const error=nativeReachable(n);if(error)return error;}return null;})()`);
                assert.equal(bad, null, `${width}x${height} ${viewId}: ${JSON.stringify(bad)}`);
            }
            for (const panelId of ['properties','target','geometry','checks','damage','ai']) {
                assert.equal((await execute('panel.set', { panelId })).ok, true);
                const bad = await evaluate(`(()=>{const a=[...document.querySelectorAll('#inspector-content input,#inspector-content select,#inspector-content textarea,#inspector-content button')].filter(n=>n.getClientRects().length); return a.length?nativeReachable(a[a.length-1]):null;})()`);
                assert.equal(bad, null, `${width}x${height} ${panelId}: ${JSON.stringify(bad)}`);
            }
            const menuBad = await evaluate(`(()=>{for(const menu of document.querySelectorAll('details.menu')) {
                menu.querySelector('summary').click();
                for(const node of menu.querySelectorAll('button')) {if(!node.getClientRects().length)continue;
                    const error=nativeReachable(node);if(error)return error;}
                menu.open=false;
            }return null;})()`);
            assert.equal(menuBad, null, `${width}x${height} menu: ${JSON.stringify(menuBad)}`);
            assert.equal((await execute('action.invoke', { actionId: 'project' })).ok, true);
            const modalBad = await evaluate('nativeReachable(document.getElementById("modal-submit"))');
            assert.equal(modalBad, null, `${width}x${height} modal: ${JSON.stringify(modalBad)}`);
            assert.equal((await execute('action.invoke', { actionId: 'close-modal' })).ok, true);
            checks.push(`${width}x${height}: native toolbar/views/menu, six inspector panels and modal footer reachable`);
        }
        assert.deepEqual(errors, []); assert.deepEqual(network, []);
        fs.writeFileSync(path.join(root, 'tests/results/native-browser-report.json'), JSON.stringify({
            passed: true, checks, htmlSHA256: crypto.createHash('sha256').update(fs.readFileSync(html)).digest('hex'),
            pageErrors: errors, networkRequests: network, liveCodexCalled: false,
            source: 'synthetic built-in demo in fresh browser profile'
        }, null, 2) + '\n');
        console.log('PASS native editor API and short-height reachability: ' + checks.length + ' checks.');
    } finally {
        if (socket?.readyState === WebSocket.OPEN) { socket.send(JSON.stringify({ id: 99999, method: 'Browser.close' })); socket.close(); }
        if (chrome && chrome.exitCode == null) chrome.kill();
        await delay(300);
        if (!path.resolve(temp).startsWith(path.resolve(os.tmpdir()) + path.sep)) throw Error('Unsafe scratch cleanup path.');
        try { fs.rmSync(temp, { recursive: true, force: true }); } catch (_) {}
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
