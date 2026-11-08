'use strict';
// Real standalone HTML and original pointer callbacks, synthetic demo only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');

async function runVariant(filename) {
    const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'spritesuite-gesture-'));
    const profile = path.join(temp, 'profile');
    let browser, socket;
    const pageErrors = [], network = [], checks = [];
    try {
        browser = spawn(process.env.SPRITESUITE_CHROMIUM ||
            'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            ['--headless=new', '--no-first-run', '--disable-gpu', '--disable-background-networking',
             '--no-default-browser-check', '--disable-component-update', '--remote-allow-origins=*',
             '--user-data-dir=' + profile, '--remote-debugging-port=0', 'about:blank'],
            { stdio: 'ignore', windowsHide: true });
        let port;
        for (let i = 0; i < 130; i++) {
            try { port = Number(fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split(/\r?\n/)[0]); }
            catch (error) { if (!['ENOENT', 'EBUSY', 'EACCES'].includes(error.code)) throw error; }
            if (port) break;
            if (browser.exitCode !== null) throw Error('Headless browser exited before debug endpoint');
            await delay(100);
        }
        assert.ok(port, 'No isolated browser endpoint');
        const pages = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
        socket = new WebSocket(pages.find(item => item.type === 'page').webSocketDebuggerUrl);
        await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
        let serial = 0;
        const pending = new Map();
        socket.onmessage = event => {
            const message = JSON.parse(event.data);
            if (message.id && pending.has(message.id)) {
                const item = pending.get(message.id); pending.delete(message.id); clearTimeout(item.timer);
                if (message.error) item.reject(Error(JSON.stringify(message.error))); else item.resolve(message.result || {});
            } else if (message.method === 'Runtime.exceptionThrown') pageErrors.push(message.params.exceptionDetails.text);
            else if (message.method === 'Network.requestWillBeSent' && /^https?:/.test(message.params.request.url)) network.push(message.params.request.url);
        };
        function send(method, params = {}) {
            return new Promise((resolve, reject) => {
                const id = ++serial, timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 30000);
                pending.set(id, { resolve, reject, timer });
                socket.send(JSON.stringify({ id, method, params }));
            });
        }
        async function evaluate(expression) {
            const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
            if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
            return result.result?.value;
        }
        async function execute(operation, fields = {}) {
            const result = await evaluate('SuiteEditorAPI.execute({...'+JSON.stringify({ operation, ...fields })+
                ',expectedRevision:SuiteEditorAPI.inspect().revision})');
            assert.equal(result.ok, true, JSON.stringify(result));
            return result;
        }
        const inspect = () => evaluate('SuiteEditorAPI.inspect()');
        const action = actionId => execute('action.invoke', { actionId });
        const gesture = (points, button = 0) => execute('canvas.gesture', { points, button });
        async function fingerprint() {
            const result = await evaluate('(()=>{const s=SuiteEditorAPI.inspect();return {state:s.state,undo:s.undo,redo:s.redo,assets:s.assetCount,pixels:s.pixels,canvas:document.getElementById("viewport").toDataURL()};})()');
            return { state: sha(JSON.stringify(result.state)), canvas: sha(result.canvas),
                undo: result.undo, redo: result.redo, assets: result.assets, pixels: result.pixels };
        }
        await send('Runtime.enable'); await send('Page.enable'); await send('Network.enable');
        await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
        const html = path.join(root, filename);
        await send('Page.navigate', { url: pathToFileURL(html).href });
        for (let i = 0; i < 120; i++) { if (await evaluate('!!window.SuiteEditorAPI')) break; await delay(100); }
        assert.equal((await inspect()).state.frames.length, 0);
        assert.ok((await evaluate('SuiteEditorAPI.discover().operations.map(x=>x.id)')).includes('canvas.gesture'));
        await action('demo');
        await execute('view.set', { viewId: 'scene' });
        let current = await inspect();
        const items = [...current.model.items].reverse().filter(item => item.frameId);
        // Pick a genuinely opaque demo pixel in the topmost available frame.
        // Hit testing itself still runs in the original pointerDown callback.
        const target = items[0];
        await execute('selection.set', { frameIds: [target.frameId] });
        current = await inspect();
        let item = current.model.items.find(entry => entry.frameId === target.frameId);
        const start = { x: item.x + item.width / 2, y: item.y + item.height - 12 };
        const originalFrame = current.state.frames.find(frame => frame.id === target.frameId);
        const beforeDrag = await fingerprint();
        await gesture([start, { x: start.x + 5, y: start.y + 3 }, { x: start.x + 13, y: start.y + 9 }]);
        current = await inspect();
        const movedFrame = current.state.frames.find(frame => frame.id === target.frameId);
        assert.equal(movedFrame.dx, originalFrame.dx + 13);
        assert.equal(movedFrame.dy, originalFrame.dy + 9);
        assert.equal(current.undo, beforeDrag.undo + 1);
        const afterDrag = await fingerprint();
        assert.notEqual(afterDrag.state, beforeDrag.state);
        await action('undo');
        const undoneDrag = await fingerprint();
        assert.equal(undoneDrag.state, beforeDrag.state);
        assert.equal(undoneDrag.canvas, beforeDrag.canvas);
        await action('redo');
        assert.equal((await fingerprint()).state, afterDrag.state);
        await action('undo');
        checks.push('scene drag uses fixed model coordinates, one Undo entry and exact state/canvas restoration');

        await action('actual');
        const beforePan = await inspect();
        await gesture([{ x: 0, y: 0 }, { x: 8, y: 12 }, { x: 20, y: 25 }], 1);
        const afterPan = await inspect();
        assert.ok(Math.abs(afterPan.model.transform.panX - beforePan.model.transform.panX - 20 * beforePan.model.transform.zoom) < 1e-6);
        assert.ok(Math.abs(afterPan.model.transform.panY - beforePan.model.transform.panY - 25 * beforePan.model.transform.zoom) < 1e-6);
        assert.equal(afterPan.undo, beforePan.undo);
        await action('fit');
        const fitted = await inspect();
        assert.equal(fitted.model.transform.panX, 0); assert.equal(fitted.model.transform.panY, 0);
        checks.push('middle-button pan uses the initial transform without cumulative drift; Fit and history stay native');

        const rect = await evaluate('document.getElementById("viewport").getBoundingClientRect().toJSON()');
        const mouse = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        await send('Input.dispatchMouseEvent', { type: 'mousePressed', ...mouse, button: 'middle', buttons: 4, clickCount: 1 });
        assert.equal((await inspect()).canvas.drag.kind, 'pan');
        const rejected = await evaluate('SuiteEditorAPI.execute({operation:"canvas.gesture",points:[{x:1,y:1}],button:0,expectedRevision:SuiteEditorAPI.inspect().revision})');
        assert.equal(rejected.error.code, 'busy');
        assert.equal((await inspect()).canvas.drag.kind, 'pan');
        await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: mouse.x + 15, y: mouse.y + 11, button: 'middle', buttons: 4 });
        await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: mouse.x + 15, y: mouse.y + 11, button: 'middle', buttons: 0, clickCount: 1 });
        assert.equal((await inspect()).canvas.drag, null);
        checks.push('real trusted user drag rejects API interference and remains owned until its own pointerup');

        await execute('view.set', { viewId: 'sprite' });
        await action('fit');
        current = await inspect();
        item = current.model.items.find(entry => entry.frameId === target.frameId);
        const measurementUndo = current.undo;
        await action('measure-tool');
        await gesture([{ x: item.x + 8, y: item.y + 8 }]);
        assert.ok((await inspect()).canvas.measureStart);
        await gesture([{ x: item.x + 18, y: item.y + 20 }]);
        const measured = await inspect();
        assert.ok(measured.canvas.measurement);
        assert.equal(measured.canvas.measureStart, null);
        assert.equal(measured.undo, measurementUndo);
        checks.push('two separate native taps produce a measured segment without mutating history');

        const pivotBefore = await fingerprint();
        await action('pivot-tool');
        await gesture([{ x: item.x + 16, y: item.y + item.height * 0.25 }]);
        const pivotAfter = await fingerprint();
        assert.notEqual(pivotAfter.state, pivotBefore.state);
        assert.equal(pivotAfter.undo, pivotBefore.undo + 1);
        await action('undo');
        assert.equal((await fingerprint()).state, pivotBefore.state);
        await action('pivot-tool');
        checks.push('pivot tap reaches the original pivot callback and one native Undo restores the source');

        await execute('view.set', { viewId: 'scene' });
        await action('scene-to-split');
        assert.equal((await inspect()).view, 'split');
        await execute('field.set', { fieldId: 'brush-radius', value: 3 });
        await execute('field.set', { fieldId: 'brush-erase', value: true });
        await action('brush-tool');
        current = await inspect();
        const brushPoint = { x: Math.floor(current.model.width / 2), y: Math.floor(current.model.height / 2) };
        const brushBefore = await fingerprint();
        const oldMap = current.state.split.mapId;
        await gesture([brushPoint, { x: brushPoint.x + 8, y: brushPoint.y }, { x: brushPoint.x + 16, y: brushPoint.y + 6 }]);
        const brushAfter = await inspect();
        assert.notEqual(brushAfter.state.split.mapId, oldMap);
        assert.equal(brushAfter.undo, brushBefore.undo + 1);
        assert.equal(brushAfter.canvas.brushActive, false); assert.equal(brushAfter.canvas.drag, null);
        const brushPixels = await fingerprint();
        await action('undo');
        const brushUndone = await fingerprint();
        assert.equal(brushUndone.state, brushBefore.state);
        assert.equal(brushUndone.canvas, brushBefore.canvas);
        await action('redo');
        assert.equal((await fingerprint()).state, brushPixels.state);
        await action('undo');
        checks.push('split ownership brush uses the native raster path, one commit and exact state/canvas Undo/Redo');

        const beforeCancel = await fingerprint();
        const cancel = await evaluate(`(async()=>{
            const c=new AbortController();const s=SuiteEditorAPI.inspect();
            const p=SuiteEditorAPI.execute({operation:'canvas.gesture',button:0,
                points:Array.from({length:128},(_,i)=>({x:${brushPoint.x}+(i%2),y:${brushPoint.y}})),
                expectedRevision:s.revision},{signal:c.signal});
            let activeSeen=false;
            for(let i=0;i<150;i++){if(SuiteEditorAPI.inspect().canvas.brushActive){activeSeen=true;c.abort();break;}
                if(!SuiteEditorAPI.inspect().busy)break;await new Promise(r=>setTimeout(r,1));}
            c.abort();return {result:await p,activeSeen};})()`);
        assert.equal(cancel.activeSeen, true, 'Cancellation must observe an actual in-flight brush');
        assert.equal(cancel.result.error.code, 'canceled');
        const afterCancel = await fingerprint();
        assert.equal(afterCancel.state, beforeCancel.state);
        assert.equal(afterCancel.undo, beforeCancel.undo);
        assert.equal(afterCancel.assets, beforeCancel.assets);
        assert.equal((await inspect()).canvas.brushActive, false); assert.equal((await inspect()).canvas.drag, null);
        checks.push('in-flight brush abort discards only its preview, preserving state/store/history and allowing the next call');

        const invalidBefore = await fingerprint();
        for (const fields of [
            { points: [{ x: 1, y: 1 }], button: 2 }, { points: [{ x: true, y: 1 }], button: 0 },
            { points: [{ x: 1, y: 1, injected: true }], button: 0 }, { points: [], button: 0 },
            { points: [{ x: 1e100, y: 1 }], button: 0 }, { points: [{ x: 1, y: 1 }], button: 0, ctrlKey: 'yes' },
        ]) {
            const result = await evaluate('SuiteEditorAPI.execute({...'+JSON.stringify({ operation: 'canvas.gesture', ...fields })+',expectedRevision:SuiteEditorAPI.inspect().revision})');
            assert.equal(result.ok, false); assert.equal(result.error.code, 'invalid');
        }
        const infinite = await evaluate('SuiteEditorAPI.execute({operation:"canvas.gesture",button:0,points:[{x:Infinity,y:NaN}],expectedRevision:SuiteEditorAPI.inspect().revision})');
        assert.equal(infinite.error.code, 'invalid');
        const invalidAfter = await fingerprint();
        assert.equal(invalidAfter.state, invalidBefore.state); assert.equal(invalidAfter.undo, invalidBefore.undo);
        assert.equal((await inspect()).canvas.drag, null);
        checks.push('invalid point shapes, booleans, modifiers, infinities and huge finite coordinates are rejected without history changes');

        assert.deepEqual(pageErrors, []); assert.deepEqual(network, []);
        return { file: filename, passed: true, checks, pageErrors, externalNetworkRequests: network,
            htmlSHA256: sha(fs.readFileSync(html)), syntheticOnly: true, gameStarted: false,
            evidence: { beforeDrag, afterDrag, brushBefore, brushAfter: brushPixels, afterCancel } };
    } finally {
        if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ id: 999999, method: 'Browser.close' })); socket.close();
        }
        if (browser && browser.exitCode === null) browser.kill();
        await delay(300);
        const resolved = path.resolve(temp), parent = path.resolve(os.tmpdir());
        if (!resolved.startsWith(parent + path.sep) || !path.basename(resolved).startsWith('spritesuite-gesture-'))
            throw Error('Unsafe private browser cleanup path');
        try { fs.rmSync(resolved, { recursive: true, force: true }); } catch (_) {}
    }
}

(async () => {
    const variants = [];
    for (const filename of ['Stronghold_Sprite_Editor.html', 'Stronghold_Sprite_Editor_EN.html']) {
        variants.push(await runVariant(filename));
        console.log('PASS native canvas gesture: ' + filename + ' (' + variants.at(-1).checks.length + ' checks)');
    }
    fs.writeFileSync(path.join(__dirname, 'results/native-gesture-browser-report.json'), JSON.stringify({
        schema: 'spritesuite.native-gesture-browser-proof.v1', passed: true, variants,
        syntheticOnly: true, liveCodexCalled: false, gameStarted: false
    }, null, 2) + '\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
