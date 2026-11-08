'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const C = require('../src/core.js'), K = require('../src/codec.js'),
    I = require('../src/io.js'), DI = require('../src/damage_io.js');

async function sample() {
    const bytes = new Uint8Array(fs.readFileSync(path.join(__dirname, '../beispiele/Steinhof.shsprite')));
    return I.readProject(await K.unzip(bytes));
}
function equalVisible(a, b) {
    assert.equal(a.width, b.width);
    assert.equal(a.height, b.height);
    for (let i = 0; i < a.data.length; i += 4) {
        assert.equal(a.data[i + 3], b.data[i + 3], 'alpha at ' + (i / 4));
        if (a.data[i + 3])
            for (let c = 0; c < 3; c++)
                assert.equal(a.data[i + c], b.data[i + c], 'color at ' + (i / 4));
    }
}

test('real 5x5 Steinhof example maintains its exact original image geometry through 64px stage split', async () => {
    const loaded = await sample(), gid = loaded.state.scenes[0].id;
    const created = DI.createStage(loaded.state, loaded.store, gid, 'mechanical', 75, 'Schadentest');
    const original = DI.baseComposite(created.state, created.store, gid);
    const imported = DI.withCandidate(created.state, created.store, created.stageId, original.image);
    const applied = DI.applyCandidate(imported.state, imported.store, created.stageId);
    const stage = DI.baseComposite(applied.state, applied.store, created.sceneId);
    assert.deepEqual([stage.layout.left, stage.layout.top, stage.layout.width, stage.layout.height],
        [original.layout.left, original.layout.top, original.layout.width, original.layout.height]);
    equalVisible(stage.image, original.image);
    assert.equal(applied.state.frames.filter(f => f.groupId === created.sceneId).length, 25);
    assert.ok(applied.state.frames.filter(f => f.groupId === created.sceneId)
        .every(f => applied.store.get(f.imageId).width <= 64));
    assert.deepEqual(DI.qualityReport(applied.state, applied.store, created.stageId).errors,[]);
    assert.equal(DI.approveStage(applied.state, applied.store, created.stageId,
        '', false).state.damageProfiles[0].stages[0].status,'approved');
});

test('real Steinhof damage candidate survives pixel-exact split, quality and SHSPRITE roundtrip', async () => {
    const loaded = await sample(), gid = loaded.state.scenes[0].id;
    const created = DI.createStage(loaded.state, loaded.store, gid, 'fire', 40, 'Brandmodell');
    const original = DI.baseComposite(created.state, created.store, gid).image;
    const candidate = C.image(original.width, original.height, new Uint8Array(original.data));
    let changed = 0;
    for (let i = 0; i < candidate.data.length && changed < 900; i += 4)
        if (candidate.data[i + 3] === 255) {
            candidate.data[i] = Math.round(candidate.data[i] * 0.3);
            candidate.data[i + 1] = Math.round(candidate.data[i + 1] * 0.3);
            changed++;
        }
    assert.equal(changed, 900);
    const added = DI.withCandidate(created.state, created.store, created.stageId, candidate);
    const applied = DI.applyCandidate(added.state, added.store, created.stageId);
    const stage = DI.baseComposite(applied.state, applied.store, created.sceneId).image;
    equalVisible(stage, candidate);
    const review = DI.qualityReport(applied.state, applied.store, created.stageId);
    assert.deepEqual(review.errors, []);
    const ok = DI.approveStage(applied.state, applied.store, created.stageId,
        'Perspektive, Dach und Brandschäden anhand der Referenz geprüft.', true);
    const pack = await DI.exportPackage(ok.state, ok.store);
    assert.equal(pack.manifest.buildings[0].stages[0].damageKind, 'fire');
    assert.equal(pack.manifest.buildings[0].stages[0].hpAtOrBelow, 40);
    const saved = await I.writeProject(ok.state, ok.store);
    const opened = await I.readProject(await K.unzip(saved));
    equalVisible(DI.baseComposite(opened.state, opened.store, created.sceneId).image, candidate);
    assert.equal(opened.state.damageProfiles[0].stages[0].status, 'approved');
});
