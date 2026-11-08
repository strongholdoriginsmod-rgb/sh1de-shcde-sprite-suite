'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../src/core.js');
const K = require('../src/codec.js');
const I = require('../src/io.js');
const AI = require('../src/ai_workflow.js');

function sample() {
    const img = C.image(64, 32);
    for (let y = 3; y < 29; y++)
        for (let x = 6; x < 58; x++)
            img.data.set([x, 100, y, 255], (y * img.width + x) * 4);
    return img;
}
const task = {
    assetClass: 'building', model: 'gpt-image-2.6-flare', variants: 2,
    goal: 'Repair the stone battlements while preserving the original footprint.',
    restrictions: 'Keep the bottom ground baseline.'
};

test('pure pixel-space geometry is reversible and snapped', () => {
    const img = sample();
    assert.deepEqual(C.pivotFromPixel(img, 32, 32), { x: .5, y: 0 });
    assert.deepEqual(C.pivotFromPixel(img, 0, 0), { x: 0, y: 1 });
    assert.deepEqual(C.pivotFromPixel(img, 8.6, 10.3), { x: 9 / 64, y: 1 - 10 / 32 });
    assert.equal(C.snapCoordinate(14.3, 8), 16);
    assert.equal(C.snapCoordinate(-1.1, 1), -1);
    const result = C.measurePoints({x: 2,y: 5}, {x: 5,y: 9});
    assert.equal(result.length, 5);
    assert.equal(result.dx, 3);
    assert.equal(result.dy, 4);
    assert.ok(result.angleDegrees < 0);
    assert.throws(() => C.pivotFromPixel(img, -1, 1), /außerhalb/);
    assert.throws(() => C.measurePoints({x: 1,y:1}, null), /Anfang/);
    assert.throws(() => C.snapCoordinate(1, 0), /Snap/);
});

test('AI request registers RGBA without modifying original source', async () => {
    const img = sample(), original = new Uint8Array(img.data);
    const source = await K.encodePNG(img);
    const result = await AI.makeRequestBundle(img, source, task);
    const request = result.request;
    assert.equal(request.format, 'sprite-suite.ai-image-edit');
    assert.equal(request.referenceSHA256, await K.sha256(source));
    assert.equal(request.variants, 2);
    assert.equal(request.model, 'gpt-image-2.6-flare');
    assert.equal(request.requiresManualApproval, true);
    assert.equal(request.automaticInstallation, false);
    assert.equal(request.registration.scale >= 1, true);
    assert.match(request.prompt, /ground baseline/i);
    assert.match(request.prompt, /Repair the stone battlements/);
    const parts = await K.unzip(result.bytes);
    assert.deepEqual(new Set(parts.map(p => p.name)), new Set([
        'request.json', 'reference.png', 'model_reference.png', 'WORKFLOW.txt'
    ]));
    const payload = Object.fromEntries(parts.map(p => [p.name, p.data]));
    assert.deepEqual(Array.from(payload['reference.png']), Array.from(source));
    const registered = await K.decodePNG(payload['model_reference.png']);
    assert.equal(registered.width, request.registration.width);
    assert.equal(registered.height, request.registration.height);
    assert.deepEqual(Array.from(img.data), Array.from(original));
    const expected = AI.registeredImage(img, request.registration);
    assert.deepEqual(Array.from(registered.data), Array.from(expected.data));
});

test('model, asset class, variant count, and prompt must validate before export', async () => {
    for (const bad of [
        {model: 'fictitious'}, {variants: 0}, {variants: 5},
        {assetClass: '../..'}, {goal: 'short'},
        {goal: '\0invalid sufficiently long'},
    ]) {
        assert.throws(() => AI.options({...task,...bad}));
    }
    assert.throws(() => AI.canvasPlan(C.image(1800, 1800)), /zu groß/);
});

test('candidate review blocks wrong size, unchanged and fully transparent image', () => {
    const img = sample();
    const unchanged = AI.reviewCandidate(img, img);
    assert.ok(unchanged.errors.some(s => /unverändert/.test(s)));
    assert.ok(AI.reviewCandidate(img, C.image(20, 20)).errors.length);
    assert.ok(AI.reviewCandidate(img, C.image(64, 32)).errors.some(s => /transparent/.test(s)));
    const different = C.image(64, 32, new Uint8Array(img.data));
    different.data[(15 * img.width + 30) * 4] = 66;
    const checked = AI.reviewCandidate(img, different);
    assert.deepEqual(checked.errors, []);
    assert.equal(checked.stats.changedPixels, 1);
    assert.equal(checked.stats.alphaChanged, 0);
    assert.equal(checked.needsManualReview, true);
});

test('AI provenance survives validation and undo; disappears when pixels are replaced', async () => {
    const img = sample(), st = new I.AssetStore();
    const sourceId = st.add(img);
    const scene = {id:'ai-s',name:'AI sample',source:'custom',
        settings:C.scene({a:1,b:1,category:'building'})};
    const s = I.blank();
    s.scenes.push(scene);
    const frame = I.makeFrame('sample-1.png',sourceId,scene.id,st);
    s.frames.push(frame);
    const history = new I.History(s,st);
    const source = await K.encodePNG(img);
    const changed = C.image(64,32,new Uint8Array(img.data));
    changed.data[(15*64+15)*4] = 45;
    const nextSt = st.fork(), candidateId = nextSt.add(changed);
    const update = I.clone(history.state);
    update.frames[0].imageId = candidateId;
    update.frames[0].aiGeneration = {
        appliedImageId: candidateId,
        sourceSHA256: await K.sha256(source),
        candidateSHA256: await K.sha256(await K.encodePNG(changed)),
        imageContentSHA256: I.imageContentSHA256(changed),
        requestedModel: 'unverified', requestReferenceSHA256: null,
        reviewNotes: 'Visual checks completed', manualReview: true,
        apiOriginVerified: false
    };
    assert.equal(history.commit(update,nextSt,'KI-approved'),true);
    assert.equal(history.state.frames[0].aiGeneration.reviewNotes,'Visual checks completed');
    assert.equal(history.undo(),true);
    assert.equal(history.state.frames[0].aiGeneration,undefined);
    assert.equal(history.redo(),true);
    assert.equal(history.state.frames[0].aiGeneration.manualReview,true);
    const changedAgain = I.clone(history.state);
    changedAgain.frames[0].imageId = sourceId;
    const clean = I.validate(changedAgain,history.store);
    assert.equal(clean.frames[0].aiGeneration,undefined);
    const forged = I.clone(history.state);
    forged.frames[0].aiGeneration.apiOriginVerified = true;
    assert.throws(() => I.validate(forged,history.store), /nachweisbar/);
    const touched = I.clone(history.state);
    history.store.get(candidateId).data[0] ^= 1;
    assert.throws(() => I.validate(touched,history.store), /nachweisbar/);
});

test('request SHA is bound to the exact archived JSON bytes', async () => {
    const img = sample(), source = await K.encodePNG(img);
    const bundle = await AI.makeRequestBundle(img, source, task);
    const entries = await K.unzip(bundle.bytes);
    const data = entries.find(row => row.name === 'request.json').data;
    assert.equal(bundle.requestSHA256, await K.sha256(data));
});

test('AI candidate manifests are source- and request-bound but not provider signatures', async () => {
    const img = sample(), source = await K.encodePNG(img);
    const generated = await AI.makeRequestBundle(img, source, task);
    const candidate = C.image(64, 32, new Uint8Array(img.data));
    candidate.data[11] ^= 1;
    const candidateSHA = await K.sha256(await K.encodePNG(candidate));
    const metadata = {
        format: 'sprite-suite.ai-candidate', version: 1, variant: 1,
        assetClass: 'building', model: task.model,
        referenceSHA256: generated.request.referenceSHA256,
        requestSHA256: generated.requestSHA256,
        candidateSHA256: candidateSHA,
        registration: { registered: true, candidateWritten: true },
        needsManualReview: true, inGameTested: false, originalGameModified: false
    };
    const verified = AI.verifyCandidateMetadata(metadata, generated.request.referenceSHA256,
        candidateSHA, generated.requestSHA256);
    assert.equal(verified.sourceMatched, true);
    assert.equal(verified.requestMatched, true);
    assert.equal(verified.apiOriginVerified, false);
    for (const change of [
        {referenceSHA256:'a'.repeat(64)}, {candidateSHA256:'b'.repeat(64)},
        {requestSHA256:'c'.repeat(64)}, {assetClass:'made-up'},
        {variant:5}, {needsManualReview:false}, {inGameTested:true},
        {registration:{ registered:false,candidateWritten:true }}
    ]) {
        assert.throws(() => AI.verifyCandidateMetadata({...metadata,...change},
            generated.request.referenceSHA256,candidateSHA,generated.requestSHA256));
    }
    assert.equal(AI.verifyCandidateMetadata(metadata, generated.request.referenceSHA256,
        candidateSHA).requestMatched, false);
});
