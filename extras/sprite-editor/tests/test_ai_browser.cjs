'use strict';
// Real, dependency-free Edge/Chromium UI smoke for the standalone file:// build.
// Uses only Node 24 standard APIs and an isolated temporary browser profile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { pathToFileURL } = require('node:url');
const K = require('../src/codec.js');
const root = path.join(__dirname, '..');
const html = path.join(root, 'Stronghold_Sprite_Editor.html');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const edge = process.env.SPRITESUITE_CHROMIUM ||
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';

(async () => {
    if (!fs.existsSync(edge)) throw new Error('Edge binary missing; set SPRITESUITE_CHROMIUM.');
    const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'sprite-editor-edge-'));
    const profile = path.join(temp, 'profile'), downloads = path.join(temp, 'downloads');
    fs.mkdirSync(downloads);
    let chrome, socket;
    const errors = [], network = [];
    try {
        chrome = spawn(edge, ['--headless=new', '--no-first-run', '--disable-gpu',
            '--disable-background-networking', '--no-default-browser-check',
            '--disable-component-update', '--remote-allow-origins=*',
            '--user-data-dir=' + profile, '--remote-debugging-port=0', 'about:blank'], {
            stdio: 'ignore', windowsHide: true
        });
        let port;
        for (let i = 0; i < 130; i++) {
            const portfile = path.join(profile, 'DevToolsActivePort');
            if (fs.existsSync(portfile)) {
                try {
                    port = Number(fs.readFileSync(portfile, 'utf8').split(/\r?\n/)[0]);
                    if (Number.isSafeInteger(port) && port > 0) break;
                } catch (error) {
                    if (!['EBUSY', 'EACCES', 'ENOENT'].includes(error.code)) throw error;
                }
            }
            if (chrome.exitCode != null) throw new Error('Browser exited: ' + chrome.exitCode);
            await sleep(100);
        }
        if (!port) throw new Error('Edge DevToolsActivePort unavailable.');
        const tabs = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
        const page = tabs.find(t => t.type === 'page');
        assert.ok(page?.webSocketDebuggerUrl, 'No headless page');
        socket = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((resolve, reject) => {
            socket.onopen = resolve;
            socket.onerror = reject;
        });
        let command = 0;
        const pending = new Map();
        socket.onmessage = event => {
            const message = JSON.parse(event.data);
            if (message.id) {
                const item = pending.get(message.id);
                if (item) {
                    pending.delete(message.id);
                    if (message.error) item.reject(Error(JSON.stringify(message.error)));
                    else item.resolve(message.result || {});
                }
            } else if (message.method === 'Runtime.exceptionThrown')
                errors.push(message.params.exceptionDetails.text);
            else if (message.method === 'Network.requestWillBeSent') {
                const url = message.params.request?.url || '';
                if (/^https?:/i.test(url)) network.push(url);
            }
        };
        function send(method, params = {}) {
            const id = ++command;
            return new Promise((resolve, reject) => {
                pending.set(id, { resolve, reject });
                socket.send(JSON.stringify({ id, method, params }));
            });
        }
        async function evaluate(expression) {
            const result = await send('Runtime.evaluate', {
                expression, returnByValue: true, awaitPromise: true
            });
            if (result.exceptionDetails)
                throw Error('Browser exception: ' + JSON.stringify(result.exceptionDetails));
            return result.result?.value;
        }
        async function wait(expression, ms = 12000) {
            const until = Date.now() + ms;
            while (Date.now() < until) {
                if (await evaluate(expression)) return;
                await sleep(110);
            }
            throw new Error('Timeout waiting for: ' + expression);
        }
        await send('Emulation.setDeviceMetricsOverride', {width:1440,height:960,deviceScaleFactor:1,mobile:false});
        await send('Page.enable');
        await send('Runtime.enable');
        await send('Network.enable');
        await send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloads });
        await send('Page.navigate', { url: pathToFileURL(html).href });
        await wait('typeof SpriteEditor !== "undefined" && !!document.getElementById("inspector")');
        assert.equal((await evaluate('SpriteEditor.inspect().state.frames.length')), 0);
        assert.ok(await evaluate('document.querySelector("[data-panel=geometry]") && document.querySelector("[data-panel=ai]")'));
        await evaluate('document.querySelector("[data-action=demo]").click()');
        await wait('SpriteEditor.inspect().state.frames.length === 25');
        const before = await evaluate('SpriteEditor.inspect().state.frames[0].imageId');
        const originalId = await evaluate('SpriteEditor.inspect().state.frames[0].originalId');
        // Legacy ruler evidence must be imported into the SAME geometry canvas,
        // never patched into an installed game or a separate atlas tool.
        const rulerFile = path.join(downloads, 'zinnen-versatz.json');
        fs.writeFileSync(rulerFile, JSON.stringify({
            schema: 'zinnenlineal.versatz.v1',
            frames: [{
                name: 'tile_beispiel 000', gruppe: 'tile_beispiel', nummer: 0,
                breite: 64, hoehe: 32, rechts: 8, hoch: 0,
                pivot_x: .5, pivot_y: 0,
                neu_pivot_x: .375, neu_pivot_y: 0
            }]
        }), 'utf8');
        await evaluate('document.querySelector("[data-panel=geometry]").click()');
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Zinnenlineal-JSON öffnen"))).click()');
        const rulerDom = await send('DOM.getDocument');
        const rulerInput = await send('DOM.querySelector', {
            nodeId: rulerDom.root.nodeId, selector: '#file-input'
        });
        await send('DOM.setFileInputFiles', {
            files: [rulerFile], nodeId: rulerInput.nodeId
        });
        await wait('document.getElementById("inspector-content").innerText.includes("Prüfstatus")');
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("review")'));
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Anker-Overlay anzeigen"))).click()');
        await wait('SpriteEditor.inspect().view === "sprite"');
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Gemessenen Pivot übernehmen"))).click()');
        await wait('document.getElementById("modal").open');
        assert.equal(await evaluate('document.querySelectorAll("#modal input[type=checkbox]").length'),0);
        await evaluate('(() => { document.querySelector("#modal [name=notes]").value="";' +
            'document.getElementById("modal-submit").click(); })()');
        await wait('SpriteEditor.inspect().state.frames[0].pivot.x === 0.375');
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames[0].pivotEvidence.manualReview'), false);
        await evaluate('document.getElementById("undo").click()');
        await wait('SpriteEditor.inspect().state.frames[0].pivot.x === 0.5');
        await evaluate('document.getElementById("redo").click()');
        await wait('SpriteEditor.inspect().state.frames[0].pivotEvidence?.manualReview === false');
        await evaluate('document.getElementById("undo").click()');
        await wait('SpriteEditor.inspect().state.frames[0].pivot.x === 0.5');
        await evaluate('document.querySelector("[data-view=sprite]").click()');
        await evaluate('document.querySelector("[data-panel=geometry]").click()');
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("Anker, Ebenen")'));
        await evaluate('document.querySelector("[data-action=measure-tool]").click()');
        assert.equal(await evaluate('document.getElementById("measure-tool").getAttribute("aria-pressed")'), 'true');
        await evaluate('document.querySelector("[data-panel=ai]").click()');
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("Briefing")'));
        await evaluate('(() => { const t = document.querySelector("#inspector-content textarea");' +
            't.value="x"; ' +
            't.dispatchEvent(new Event("change", {bubbles: true})); })()');
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("KI-Auftragsbundle"))).click()');
        let requestZip;
        for (let i = 0; i < 240; i++) {
            const files = fs.readdirSync(downloads).filter(name => /_ki_auftrag\.zip$/.test(name));
            if (files.length) {
                requestZip = path.join(downloads, files[0]); break;
            }
            await sleep(100);
        }
        assert.ok(requestZip, 'AI ZIP not downloaded from UI');
        const entries = await K.unzip(new Uint8Array(fs.readFileSync(requestZip)));
        const payload = Object.fromEntries(entries.map(entry => [entry.name, entry.data]));
        const request = JSON.parse(K.decodeText(payload['request.json']));
        assert.equal(request.automaticInstallation, false);
        assert.equal(request.goal,'x');
        assert.equal(request.requiresManualApproval,false);
        assert.equal(request.referenceSHA256, await K.sha256(payload['reference.png']));
        const original = await K.decodePNG(payload['reference.png']);
        const modified = { width: original.width, height: original.height,
            data: new Uint8Array(original.data) };
        modified.data[0] ^= 1;
        const candidate = path.join(downloads, 'smoke_candidate.png');
        const candidateBytes = await K.encodePNG(modified);
        fs.writeFileSync(candidate, Buffer.from(candidateBytes));
        const requestSHA256 = await K.sha256(payload['request.json']);
        const manifest = path.join(downloads, 'smoke_candidate_meta.json');
        fs.writeFileSync(manifest, JSON.stringify({
            format:'sprite-suite.ai-candidate',version:1,variant:1,
            assetClass:request.assetClass,model:request.model,
            referenceSHA256:request.referenceSHA256,requestSHA256,
            candidateSHA256:await K.sha256(candidateBytes),
            registration:{registered:true,candidateWritten:true},
            needsManualReview:true,inGameTested:false,originalGameModified:false
        }), 'utf8');
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Kandidaten-PNGs"))).click()');
        const dom = await send('DOM.getDocument');
        const input = await send('DOM.querySelector', {
            nodeId: dom.root.nodeId, selector: '#file-input'
        });
        await send('DOM.setFileInputFiles', { files: [candidate, manifest], nodeId: input.nodeId });
        await wait('document.getElementById("inspector-content").innerText.includes("Ungeprüfte Variante")');
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("Quell- und Auftrags-SHA passen")'));
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("Pixelrisikoindikator")'));
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Original + Variante"))).click()');
        await wait('document.getElementById("modal").open');
        assert.equal(await evaluate('document.querySelectorAll("#modal input[type=checkbox]").length'),0);
        await evaluate('(() => { document.querySelector("#modal [name=notes]").value="x";' +
            'document.getElementById("modal-submit").click(); })()');
        await wait('SpriteEditor.inspect().state.frames[0].imageId !== ' + JSON.stringify(before));
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames[0].originalId'),
            originalId, 'Original altered by candidate acceptance');
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames[0].aiGeneration.manualReview'), false);
        assert.equal(await evaluate('SpriteEditor.inspect().state.frames[0].aiGeneration.requestSHA256'),
            requestSHA256, 'Accepted candidate lost the exact request digest');
        await evaluate('document.getElementById("undo").click()');
        await wait('SpriteEditor.inspect().state.frames[0].imageId === ' + JSON.stringify(before));
        await evaluate('document.getElementById("redo").click()');
        await wait('SpriteEditor.inspect().state.frames[0].aiGeneration?.manualReview === false');
        await evaluate('([...document.querySelectorAll("#inspector-content button")]' +
            '.find(b => b.textContent.includes("Animationsfolge auf Anker"))).click()');
        let sequenceFile;
        for (let i = 0; i < 100; i++) {
            sequenceFile = fs.readdirSync(downloads).find(name => name.endsWith('_animation_qa.json'));
            if (sequenceFile) break;
            await sleep(100);
        }
        assert.ok(sequenceFile,'Animation QA report download missing');
        const sequence = JSON.parse(fs.readFileSync(path.join(downloads,sequenceFile),'utf8'));
        assert.equal(sequence.frames.length,25);
        assert.equal(sequence.nativeAnimationTimingVerified,false);
        await send('Page.navigate', {
            url: pathToFileURL(path.join(root, 'Stronghold_Sprite_Editor_EN.html')).href + '#ai'
        });
        await wait('document.querySelector("[data-panel=ai]")?.textContent.trim() === "AI workshop"');
        assert.equal(await evaluate('SpriteEditor.inspect().panel'), 'ai',
            'Suite deep-link must navigate without executing any tool');
        await evaluate('document.querySelector("[data-action=demo]").click()');
        await wait('SpriteEditor.inspect().state.frames.length === 25');
        await evaluate('document.querySelector("[data-panel=ai]").click()');
        assert.ok(await evaluate('document.getElementById("inspector-content").innerText.includes("Brief and reference")'),
            'New AI inspector must be translated in EN standalone HTML');
        assert.deepEqual(errors, [], 'Browser JavaScript runtime errors');
        assert.deepEqual(network, [], 'Browser made unexpected http(s) requests');
        const reportRoot = path.join(root,'tests/results');
        const screenshot = await send('Page.captureScreenshot',{format:'png'});
        fs.writeFileSync(path.join(reportRoot,'ai-geometry-edge.png'),Buffer.from(screenshot.data,'base64'));
        fs.writeFileSync(path.join(reportRoot,'ai-browser-report.json'),JSON.stringify({
            passed:true,browser:(await send('Browser.getVersion')).product,
            htmlSHA256:await K.sha256(new Uint8Array(fs.readFileSync(html))),
            checks:['historical pivot import','visible overlay','manual pivot receipt','pivot undo and redo',
                'offline request source SHA','candidate metadata SHA','pixel quality risks',
                'manual candidate approval','original preserved','candidate undo and redo',
                'animation sequence QA download','English deep-link'],
            pageErrors:errors,networkRequests:network,liveCodexCalled:false,inGameTested:false
        },null,2)+'\n');
        console.log('PASS standalone Edge file:// UI: geometry + AI bundle + candidate review + undo/redo, no network.');
        console.log('PASS source SHA-256, original preserved and content-bound review provenance.');
        console.log('BROWSER_UI_PASS');
    } finally {
        if (socket?.readyState === WebSocket.OPEN) {
            try { socket.send(JSON.stringify({ id: 99999, method: 'Browser.close' })); } catch (_e) {}
            socket.close();
        }
        if (chrome && chrome.exitCode == null) chrome.kill();
        await sleep(200);
        try { fs.rmSync(temp, { recursive: true, force: true }); } catch (_e) {}
    }
})().catch(error => { console.error('BROWSER_UI_FAIL', error); process.exitCode = 1; });
