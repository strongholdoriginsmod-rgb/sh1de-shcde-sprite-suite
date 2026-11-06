'use strict';
const { test } = require('node:test');
const A = require('node:assert/strict');
const C = require('../src/core.js'), K = require('../src/codec.js');
const I = require('../src/io.js'), D = require('../src/damage.js'), DI = require('../src/damage_io.js');

function fixture() {
    const store = new I.AssetStore(), s = I.blank();
    const src = C.image(64, 32);
    for (let y = 12; y < 28; y++)
        for (let x = 29; x < 35; x++)
            src.data.set([150, 110, 60, 255], (y * 64 + x) * 4);
    const imageId = store.add(src), gid = 'building';
    const group = { id: gid, name: 'tile_abbey', source: 'shcde',
        settings: C.scene({ a: 1, b: 1, width: 64, height: 32, category: 'building' }) };
    const frame = I.makeFrame('tile_abbey-0.png', imageId, gid, store);
    frame.targetName = 'tile_abbey-0'; frame.targetConfirmed = true;
    s.scenes.push(group); s.frames.push(frame);
    s.project.name = 'Damage Test'; s.project.author = 'Tester';
    return { s: I.validate(s, store), store, gid, frame, imageId };
}
function stageFixture(kind = 'mechanical', threshold = 75) {
    const f = fixture();
    const r = DI.createStage(f.s, f.store, f.gid, kind, threshold, 'Erster Schaden');
    return { ...f, s: r.state, store: r.store, stageId: r.stageId, sceneId: r.sceneId };
}
function damageCandidate(f, mutate = true) {
    const orig = DI.baseComposite(f.s, f.store, f.gid).image;
    const candidate = C.image(orig.width, orig.height, new Uint8Array(orig.data));
    if (mutate) {
        const x = 40, y = 27;
        const idx = (y * candidate.width + x) * 4;
        candidate.data[idx] = 205;
        candidate.data[idx + 1] = 40;
    }
    return candidate;
}

test('building selector and HP thresholds are deterministic, inclusive and severity ordered', () => {
    const profile = { stages: [
        { id: 'd0', kind: 'mechanical', hpAtOrBelow: 0 },
        { id: 'd75', kind: 'mechanical', hpAtOrBelow: 75 },
        { id: 'd40', kind: 'mechanical', hpAtOrBelow: 40 }
    ] };
    for (const [hp, id] of [[100, null], [76, null], [75, 'd75'], [41, 'd75'],
                            [40, 'd40'], [1, 'd40'], [0, 'd0']])
        A.equal(D.choose(profile, 'mechanical', hp)?.id ?? null, id);
    A.equal(D.choose(profile, 'fire', 30).id, 'd40', 'fire falls back only if no fire stage');
    profile.stages.push({ id: 'f80', kind: 'fire', hpAtOrBelow: 80 });
    A.equal(D.choose(profile, 'fire', 30).id, 'f80', 'explicit fire stages never mix with mechanical');
    A.equal(D.chooseHP(profile, 'mechanical', 20, 50).id, 'd40');
    A.throws(() => D.chooseHP(profile, 'mechanical', 51, 50));
    A.throws(() => D.choose(profile, 'other', 50));
});

test('new stage is an independent editable scene, without exporting default target names', () => {
    const f = stageFixture();
    const stage = DI.getStage(f.s, f.stageId).stage;
    A.equal(f.s.scenes.length, 2);
    A.equal(f.s.frames.length, 2);
    A.equal(stage.hpAtOrBelow, 75);
    A.equal(stage.kind, 'mechanical');
    A.equal(stage.status, 'draft');
    A.equal(f.s.frames[0].imageId, f.s.frames[1].imageId, 'initial immutable image buffer shared');
    A.equal(f.s.frames[1].targetName, '', 'no automatic duplicate SHCDE target override');
    A.notEqual(f.s.frames[1].id, f.s.frames[0].id);
    A.deepEqual(D.stageScenes(f.s.damageProfiles), new Set([f.sceneId]));
    A.equal(I.preflight(f.s, f.store).filter(x => x.level === 'error').length, 0);
});

test('stage requires a building with max 64px tile width', () => {
    const f = fixture();
    f.s.scenes[0].settings.width = 66;
    A.throws(() => DI.createStage(f.s, f.store, f.gid, 'fire', 75), /64/);
    const x = fixture();
    x.s.scenes[0].settings.category = 'unit';
    A.throws(() => DI.createStage(x.s, x.store, x.gid, 'mechanical', 50));
});

test('schema 2 accepts old projects without damageProfiles; rejects broken and duplicate damage entries', () => {
    const f = fixture();
    const old = I.clone(f.s);
    delete old.damageProfiles;
    A.deepEqual(I.validate(old, f.store).damageProfiles, []);
    const a = stageFixture();
    const duplicate = I.clone(a.s);
    duplicate.damageProfiles[0].stages.push({ ...duplicate.damageProfiles[0].stages[0], id: 'newid' });
    A.throws(() => I.validate(duplicate, a.store), /doppelt/i);
    const broken = I.clone(a.s);
    broken.damageProfiles[0].stages[0].hpAtOrBelow = 100;
    A.throws(() => I.validate(broken, a.store), /99/);
    const badScene = I.clone(a.s);
    badScene.scenes[1].settings.anchor = 'pivot';
    A.throws(() => I.validate(badScene, a.store), /Anker|anchor|Raster/i);
});

test('candidate mismatch is stored for review but never applied to tiles', () => {
    const f = stageFixture(), candidate = C.image(8, 8);
    candidate.data.set([200, 100, 0, 255], 0);
    const res = DI.withCandidate(f.s, f.store, f.stageId, candidate);
    A.equal(res.report.errors.some(s => s.includes('Canvasgröße')), true);
    A.throws(() => DI.applyCandidate(res.state, res.store, f.stageId), /Canvasgröße/);
    A.equal(f.s.frames.length, 2);
    A.equal(f.store.items.size, 1, 'original asset store unaffected');
});

test('candidate import, project SHA roundtrip, overlap split, approval and protected export', async () => {
    const f = stageFixture(), candidate = damageCandidate(f);
    const imported = DI.withCandidate(f.s, f.store, f.stageId, candidate);
    A.deepEqual(imported.report.errors, []);
    A.equal(imported.state.damageProfiles[0].stages[0].candidateId !== null, true);
    const bytes = await I.writeProject(imported.state, imported.store);
    const entries = await K.unzip(bytes);
    const reopened = await I.readProject(entries);
    A.equal(reopened.state.damageProfiles[0].stages[0].candidateId, imported.state.damageProfiles[0].stages[0].candidateId);
    const accepted = DI.applyCandidate(reopened.state, reopened.store, f.stageId);
    A.equal(accepted.state.frames.filter(x => x.groupId === f.sceneId).length, 1);
    A.ok(accepted.state.frames.filter(x => x.groupId === f.sceneId).every(x => accepted.store.get(x.imageId).width <= 64));
    A.equal(DI.getStage(accepted.state, f.stageId).stage.status, 'draft', 'technical pass is not manual approval');
    A.throws(() => DI.approveStage(accepted.state, accepted.store, f.stageId, '', false), /bestätigen/);
    const approved = DI.approveStage(accepted.state, accepted.store, f.stageId, 'Vergleich durchgeführt', true);
    A.equal(approved.state.damageProfiles[0].stages[0].status, 'approved');
    const pack = await DI.exportPackage(approved.state, approved.store);
    A.equal(pack.manifest.runtimeHookInstalled, false);
    A.equal(pack.manifest.buildings[0].stages[0].hpAtOrBelow, 75);
    A.equal(pack.manifest.buildings[0].stages[0].tiles.length, 1);
    const files = await K.unzip(pack.bytes);
    A.ok(files.some(x => x.name === 'damage-manifest.json'));
    A.ok(files.some(x => x.name.endsWith('/0000.png')));
    const mod = await I.exportMod(approved.state, approved.store);
    A.equal(mod.report.mappings.length, 1, 'damage scene is not installed as a global override');
    A.equal(mod.report.mappings[0].source, 'tile_abbey-0.png');
});

test('manual approval refuses untouched clones, stage edits automatically void approval', () => {
    const f = stageFixture();
    A.throws(() => DI.approveStage(f.s, f.store, f.stageId, '', true), /unverändertes/);
    const s = I.clone(f.s);
    const st = DI.getStage(s, f.stageId).stage;
    st.status = 'approved';
    const edited = I.clone(s);
    edited.frames[1].dy += 1;
    D.invalidateApprovals(s, edited);
    A.equal(edited.damageProfiles[0].stages[0].status, 'draft');
    const thresholdEdit = I.clone(s);
    thresholdEdit.damageProfiles[0].stages[0].hpAtOrBelow = 50;
    D.invalidateApprovals(s, thresholdEdit);
    A.equal(thresholdEdit.damageProfiles[0].stages[0].status, 'draft');
});

test('Codex bundle includes real source PNG, named model, unmodified reference and revision text', async () => {
    const f = stageFixture('fire', 40);
    f.s.damageProfiles[0].stages[0].changeRequest = 'Mehr verkohlte Dachbalken, keine Kameraänderung';
    const ref = DI.baseComposite(f.s, f.store, f.gid);
    const bundle = await DI.makeRequestBundle(f.s, f.store, f.stageId);
    const entries = await K.unzip(bundle.bytes);
    const request = JSON.parse(K.decodeText(entries.find(x => x.name === 'request.json').data));
    A.equal(request.model, 'gpt-image-2.6-sunburst');
    A.equal(request.referenceFiles[0], 'model_reference.png');
    A.equal(request.size, request.registration.width + 'x' + request.registration.height);
    A.equal(request.registration.sourceWidth, ref.image.width);
    A.ok(request.registration.scale >= 1);
    A.equal('input_fidelity' in request, false);
    A.match(request.prompt, /SPECIFIC REVISION REQUEST/);
    A.match(request.prompt, /FIRE damage/);
    const png = await K.decodePNG(entries.find(x => x.name === 'reference.png').data);
    A.deepEqual(Array.from(png.data), Array.from(ref.image.data));
    A.ok(entries.some(x => x.name === 'CODEX.md'));
    const model = await K.decodePNG(entries.find(x => x.name === 'model_reference.png').data);
    A.equal(model.width, request.registration.width);
    A.equal(model.height, request.registration.height);
    // Inverse registration: every original pixel is expanded by an integer factor.
    for (let y = 0; y < png.height; y++)
        for (let x = 0; x < png.width; x++) {
            const orig = (y * png.width + x) * 4;
            const registered = (((request.registration.top + y * request.registration.scale) * model.width) +
                request.registration.left + x * request.registration.scale) * 4;
            A.deepEqual(Array.from(model.data.subarray(registered, registered + 4)),
                Array.from(png.data.subarray(orig, orig + 4)));
        }
});

test('draft and rejected stages are excluded from damage manifest and standard mod output', async () => {
    const f = stageFixture();
    await A.rejects(DI.exportPackage(f.s, f.store), /keine freigegebenen/i);
    f.s.damageProfiles[0].stages[0].status = 'rejected';
    await A.rejects(DI.exportPackage(f.s, f.store));
    const mod = await I.exportMod(f.s, f.store);
    A.equal(mod.report.mappings.length, 1);
});
