'use strict';
// Real Edge smoke: file:// loading, UI stage creation, HP preview, Codex ZIP, import, EN.
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const puppeteer = require('puppeteer');
const K = require('../src/codec.js');
const ROOT = path.resolve(__dirname, '..');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const URL_DE = 'file:///' + path.join(ROOT, 'Stronghold_Sprite_Editor.html').replace(/\\/g, '/');
const URL_EN = 'file:///' + path.join(ROOT, 'Stronghold_Sprite_Editor_EN.html').replace(/\\/g, '/');
function nap(ms = 200) { return new Promise(done => setTimeout(done, ms)); }
async function state(page) { return page.evaluate(() => window.SpriteEditor.inspect().state); }
async function clickLabel(page, label) {
    const ok = await page.evaluate(label => {
        const buttons = [...document.querySelectorAll('button')];
        const b = buttons.find(x => x.textContent.trim() === label);
        if (!b) return false;
        b.click();
        return true;
    }, label);
    assert.equal(ok, true, 'Missing button: ' + label);
}
async function field(page, label, value) {
    const ok = await page.evaluate(({label, value}) => {
        const f = [...document.querySelectorAll('.field')].find(x => x.querySelector('label')?.textContent.trim() === label);
        const node = f?.querySelector('input, select, textarea');
        if (!node) return false;
        node.value = String(value);
        node.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }, {label, value});
    assert.equal(ok, true, 'Missing field ' + label);
}
async function wait(page, check, timeout = 10000) {
    try { await page.waitForFunction(check, { timeout, polling: 80 }); }
    catch (e) {
        const diagnostic = await page.evaluate(() => ({ error: document.querySelector('#modal-error')?.textContent,
            modal: document.querySelector('#modal')?.open, toast: document.querySelector('#toast')?.textContent,
            toastHidden: document.querySelector('#toast')?.hidden,
            stage: window.SpriteEditor?.inspect()?.state?.damageProfiles?.[0]?.stages?.[0] }));
        throw new Error('Timed out: ' + JSON.stringify(diagnostic));
    }
}
async function waitForZip(dir, suffix, timeout = 20000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        const list = fs.readdirSync(dir).filter(x => x.endsWith(suffix) && !x.endsWith('.crdownload'));
        if (list.length) return path.join(dir, list[0]);
        await nap(100);
    }
    throw new Error('Download timeout: ' + suffix);
}
async function run() {
    assert(fs.existsSync(EDGE), 'Edge browser unavailable');
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'shcde-damage-browser-'));
    const errors = [], requests = [], checks = [];
    const browser = await puppeteer.launch({
        executablePath: EDGE, headless: true, pipe: true,
        args: ['--no-sandbox', '--disable-extensions', '--disable-background-networking',
            '--edge-skip-compat-layer-relaunch', '--do-not-de-elevate', '--disable-edgeupdater']
    });
    try {
        const page = await browser.newPage();
        page.on('pageerror', e => errors.push(String(e)));
        page.on('request', r => { if (/^https?:/i.test(r.url())) requests.push(r.url()); });
        const cdp = await page.target().createCDPSession();
        await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: tmp });
        await page.setViewport({width: 1440, height: 960});
        await page.goto(URL_DE, {waitUntil:'load'});
        await wait(page, () => !!window.SpriteEditor);
        assert.equal(page.url(), URL_DE, 'Actual file:// navigation');
        checks.push('Editor direkt via file:// geladen');
        await page.evaluate(() => document.querySelector('[data-action="demo"]').click());
        await wait(page, () => window.SpriteEditor.inspect().state.scenes.length === 1);
        assert.equal((await state(page)).frames.length, 25);
        checks.push('Gebäude-Demo geladen');
        await page.evaluate(() => document.querySelector('[data-panel="damage"]').click());
        await wait(page, () => document.querySelector('.inspector-content')?.innerText.includes('Gebäude und HP-Test'));
        await clickLabel(page, 'Neue Schadensstufe…');
        await wait(page, () => document.querySelector('#modal').open);
        await page.evaluate(() => {
            document.querySelector('#modal [name="kind"]').value = 'mechanical';
            document.querySelector('#modal [name="hp"]').value = '75';
            document.querySelector('#modal [name="label"]').value = 'Leichte Schäden';
        });
        await page.evaluate(() => document.querySelector('#modal-submit').click());
        await wait(page, () => window.SpriteEditor.inspect().state.damageProfiles[0]?.stages.length === 1);
        await wait(page, () => !document.querySelector('#modal').open);
        let st = await state(page);
        let s = st.damageProfiles[0].stages[0];
        assert.equal(s.hpAtOrBelow,75);
        assert.equal(s.kind,'mechanical');
        assert.equal(st.scenes.length,2);
        assert.equal(st.frames.length,50);
        assert.equal(st.frames.filter(f => f.groupId === s.sceneId).every(f => !f.targetName),true);
        checks.push('Stufe inklusive Clone, Scene und HP-Schwelle erstellt');
        await field(page, 'Spiel-Gebäudetyp (optional)', 108);
        await wait(page, () => window.SpriteEditor.inspect().state.damageProfiles[0].gameBuildingType === 108);
        checks.push('Expliziter Gebäudetyp wird mit dem Profil gespeichert');

        await clickLabel(page, 'Alle HP-Schadensmodelle exportieren…');
        const freeZip = await waitForZip(tmp, '_gebaeudeschaden_alle.zip');
        const freeFiles = await K.unzip(new Uint8Array(fs.readFileSync(freeZip)));
        const freeManifest = JSON.parse(K.decodeText(freeFiles.find(e => e.name === 'damage-manifest.json').data));
        assert.equal(freeManifest.exportMode, 'all-stages');
        assert.equal(freeManifest.buildings[0].stages[0].reviewStatus, 'draft');
        assert.equal(freeManifest.buildings[0].stages[0].contentApproved, false);
        assert(freeFiles.some(e => e.name.endsWith('/0000.png')));
        fs.unlinkSync(freeZip);
        checks.push('Freier ZIP-Export umfasst auch unbearbeitete Entwürfe ohne Pflichtfreigabe');

        await field(page, 'Verbleibende HP · %', 80);
        assert((await page.$eval('.inspector-content', n=>n.innerText)).includes('Original / unbeschädigt'));
        await field(page, 'Verbleibende HP · %', 60);
        assert((await page.$eval('.inspector-content', n=>n.innerText)).includes('Leichte Schäden'));
        checks.push('HP-Vorschau 80 % intakt / 60 % beschädigt');
        await field(page, 'Vorschau-Modus', 'approved');
        assert((await page.evaluate(() => [...document.querySelectorAll('.info-line')]
            .find(e => e.querySelector('span')?.textContent.startsWith('Modell bei'))?.textContent)).includes('Original / unbeschädigt'));
        await field(page, 'Vorschau-Modus', 'all');
        checks.push('Freigabe-Vorschau unterdrückt unfertige Schadensmodelle');

        await page.screenshot({path:path.join(tmp, 'damage-de.png')});
        await clickLabel(page, 'Codex-Prompt + Original exportieren…');
        const codexZip = await waitForZip(tmp, '_codex.zip');
        const entries = await K.unzip(new Uint8Array(fs.readFileSync(codexZip)));
        const request = JSON.parse(K.decodeText(entries.find(e => e.name==='request.json').data));
        assert.equal(request.model,'gpt-image-2.6-sunburst');
        assert.equal(request.hpAtOrBelow,75);
        assert.equal(request.referenceFiles[0],'model_reference.png');
        assert.equal(request.registration.width,1536); // 5x5 horizontal building composite
        assert(entries.some(e=>e.name==='reference.png'));
        assert(entries.some(e=>e.name==='model_reference.png'));
        const original = entries.find(e=>e.name==='reference.png').data;
        const candidatePath = path.join(tmp, 'candidate_source.png');
        fs.writeFileSync(candidatePath, original);
        checks.push('Codex ZIP mit unverändertem Original, Modellreferenz und Prompt');

        const chooser = page.waitForFileChooser();
        await clickLabel(page, 'Generiertes PNG importieren…');
        await (await chooser).accept([candidatePath]);
        await wait(page, () => !!window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].candidateId);
        await wait(page, () => !document.querySelector('#busy-dialog').open);
        await nap(100);
        s=(await state(page)).damageProfiles[0].stages[0];
        assert.equal(s.status, 'draft');
        checks.push('Kandidat über echten Dateidialog importiert, nicht automatisch freigegeben');

        // An identical candidate must not be considered a meaningful damage state.
        await page.evaluate(() => { window.__damageImageBefore = window.SpriteEditor.inspect().state.frames.find(f =>
            f.groupId === window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].sceneId).imageId; });
        await clickLabel(page, 'PNG als Tiles zerlegen');
        await wait(page, () => window.SpriteEditor.inspect().state.frames.find(f =>
            f.groupId === window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].sceneId).imageId !== window.__damageImageBefore);
        await clickLabel(page, 'Qualität abnehmen…');
        await wait(page, () => document.querySelector('#modal').open);
        assert.equal(await page.$$eval('.damage-review-canvas', nodes => nodes.length), 2);
        await page.evaluate(() => {
            document.querySelector('#modal [name="confirmed"]').checked = true;
            document.querySelector('#modal-submit').click();
        });
        await wait(page, () => !document.querySelector('#modal-error').hidden);
        const refusal = await page.$eval('#modal-error', n => n.textContent);
        assert(/identisch|Original|veränderten Pixeln|Modell weiter beschädigen/.test(refusal), refusal);
        await page.evaluate(() => document.querySelector('[data-action="close-modal"]').click());
        checks.push('Identisches KI-Bild wird trotz ausdrücklichem Klick nicht freigegeben');

        // Change a real opaque pixel and import it through the same user flow.
        const changed = await K.decodePNG(original);
        let changedCount = 0;
        for (let i = 0; i < changed.data.length && changedCount < 800; i += 4)
            if (changed.data[i + 3] === 255) {
                changed.data[i] = Math.round(changed.data[i] * 0.45);
                changed.data[i + 1] = Math.round(changed.data[i + 1] * 0.45);
                changedCount++;
            }
        assert(changedCount >= 200, 'synthetic building needs opaque structure for visible damage');
        const modifiedPath = path.join(tmp, 'candidate_modified.png');
        fs.writeFileSync(modifiedPath, await K.encodePNG(changed));
        const decodedChanged = await K.decodePNG(new Uint8Array(fs.readFileSync(modifiedPath)));
        const decodedOriginal = await K.decodePNG(original);
        assert.notDeepEqual(Array.from(decodedChanged.data), Array.from(decodedOriginal.data), 'PNG modification must survive codec');
        await page.evaluate(id => { window.__damageCandidateBefore = id; }, s.candidateId);
        const chooserChanged = page.waitForFileChooser();
        await clickLabel(page, 'Generiertes PNG importieren…');
        await (await chooserChanged).accept([modifiedPath]);
        await nap(200);
        await wait(page, () => window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].candidateId !== window.__damageCandidateBefore);
        await wait(page, () => !document.querySelector('#busy-dialog').open);
        await nap(100);
        await page.evaluate(() => { window.__damageImageBefore = window.SpriteEditor.inspect().state.frames.find(f =>
            f.groupId === window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].sceneId).imageId; });
        await clickLabel(page, 'PNG als Tiles zerlegen');
        await wait(page, () => window.SpriteEditor.inspect().state.frames.find(f =>
            f.groupId === window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].sceneId).imageId !== window.__damageImageBefore);
        await clickLabel(page, 'Qualität abnehmen…');
        await wait(page, () => document.querySelector('#modal').open);
        assert.equal(await page.$$eval('.damage-review-canvas', nodes => nodes.length), 2);
        await page.evaluate(() => {
            document.querySelector('#modal [name="confirmed"]').checked = true;
            document.querySelector('#modal [name="notes"]').value = 'Technische und visuelle Prüfung bestätigt';
            document.querySelector('#modal-submit').click();
        });
        try {
            await wait(page, () => window.SpriteEditor.inspect().state.damageProfiles[0].stages[0].status === 'approved', 3500);
        } catch (e) {
            const diagnostic = await page.evaluate(() => ({ error: document.querySelector('#modal-error')?.textContent,
                modal: document.querySelector('#modal')?.open, toast: document.querySelector('#toast')?.textContent,
                stage: window.SpriteEditor.inspect().state.damageProfiles[0].stages[0] }));
            throw new Error('Cannot approve modified stage: ' + JSON.stringify(diagnostic));
        }
        checks.push('Verändertes Schadensmodell nur nach manueller Abnahme freigegeben');
        assert.match((await state(page)).damageProfiles[0].stages[0].approvalDigest, /^[a-f0-9]{64}$/);
        await field(page, 'Vorschau-Modus', 'approved');
        assert((await page.evaluate(() => [...document.querySelectorAll('.info-line')]
            .find(e => e.querySelector('span')?.textContent.startsWith('Modell bei'))?.textContent)).includes('Leichte Schäden'));
        await field(page, 'Vorschau-Modus', 'all');
        checks.push('Freigegebene Vorschau und Pixelzustandsprüfsumme sind gültig');

        await clickLabel(page, 'HP-Schadensmodelle exportieren…');
        const damageZip = await waitForZip(tmp, '_gebaeudeschaden.zip');
        const damageEntries = await K.unzip(new Uint8Array(fs.readFileSync(damageZip)));
        const manifest = JSON.parse(K.decodeText(damageEntries.find(x => x.name === 'damage-manifest.json').data));
        assert.equal(manifest.runtimeHookInstalled, false);
        assert.equal(manifest.buildings.length, 1);
        assert.equal(manifest.buildings[0].stages.length, 1);
        assert.equal(manifest.buildings[0].stages[0].hpAtOrBelow, 75);
        assert.match(manifest.buildings[0].stages[0].approvalDigest, /^[a-f0-9]{64}$/);
        assert.equal(manifest.buildings[0].gameBuildingType, 108);
        assert.equal(manifest.buildings[0].gameBuildingTypeVerifiedInGame, false);
        checks.push('Freigegebenes HP-Schadenspaket enthält korrektes Manifest und Tiles');

        // Create a distinct fire state with its own threshold and independent tile scene.
        await clickLabel(page, 'Neue Schadensstufe…');
        await wait(page, () => document.querySelector('#modal').open);
        await page.evaluate(() => {
            document.querySelector('#modal [name="kind"]').value = 'fire';
            document.querySelector('#modal [name="hp"]').value = '40';
            document.querySelector('#modal [name="label"]').value = 'Brandschaden';
        });
        await page.evaluate(() => document.querySelector('#modal-submit').click());
        await wait(page, () => window.SpriteEditor.inspect().state.damageProfiles[0]?.stages.length === 2);
        st=await state(page);
        assert.deepEqual(st.damageProfiles[0].stages.map(x=>x.kind),['mechanical','fire']);
        assert.equal(st.scenes.length,3);
        checks.push('Eigener Feuer-Zweig mit 40-%-Grenze');

        const en = await browser.newPage();
        en.on('pageerror', e=>errors.push(String(e)));
        await en.goto(URL_EN, {waitUntil:'load'});
        await wait(en, () => !!window.SpriteEditor);
        await en.evaluate(() => document.querySelector('[data-action="demo"]').click());
        await wait(en,()=>window.SpriteEditor.inspect().state.scenes.length===1);
        await en.evaluate(() => document.querySelector('[data-panel="damage"]').click());
        await nap(350);
        const translated = await en.$eval('[data-panel="damage"]', e=>e.textContent.trim());
        assert.equal(translated,'Damage');
        assert((await en.$eval('.inspector-content',n=>n.innerText)).includes('Building and HP preview'));
        checks.push('Englische Oberfläche zeigt Damage-Workflow');
        assert.deepEqual(errors,[], 'Browser JavaScript errors');
        assert.deepEqual(requests,[], 'No network requests by the editor');
        checks.push('Kein Browserfehler / keine Netzwerkanfragen');
        const report = { pass: true, checks, directFileUrl: true, pageErrors: errors, networkRequests: requests,
            htmlSHA256: require('node:crypto').createHash('sha256').update(fs.readFileSync(path.join(ROOT, 'Stronghold_Sprite_Editor.html'))).digest('hex'),
            browser: await browser.version(), inGameTested: false, apiCalled: false };
        const resultDir = path.join(ROOT, 'tests', 'results');
        fs.mkdirSync(resultDir, {recursive: true});
        fs.writeFileSync(path.join(resultDir, 'damage-browser-report.json'), JSON.stringify(report,null,2)+'\n','utf8');
        console.log(JSON.stringify(report, null, 2));
    } finally {
        await browser.close();
        // Keep temporary screenshots only for the duration of this test;
        // deliverables remain the source and build artifacts in git.
        fs.rmSync(tmp,{recursive:true,force:true});
    }
}
run().catch(err=>{console.error(err.stack || err);process.exitCode=1;});
