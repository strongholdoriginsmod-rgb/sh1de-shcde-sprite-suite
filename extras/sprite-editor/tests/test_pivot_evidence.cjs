'use strict';
const {test} = require('node:test');
const a = require('node:assert/strict');
const C = require('../src/core.js'), K = require('../src/codec.js');
const I = require('../src/io.js'), P = require('../src/pivot_evidence.js');
const old = {x:.5,y:.25}, proposed = {x:.375,y:.1875};
const file = (changes={}) => ({
    schema:'zinnenlineal.versatz.v1',
    frames:[{
        name:'anim_castle 002', gruppe:'anim_castle', nummer:2,
        breite:64, hoehe:64, rechts:8, hoch:4,
        pivot_x:.5, pivot_y:.25, neu_pivot_x:.375, neu_pivot_y:.1875,
        pixel_je_einheit:64, ...changes
    }]
});
const data = (changes={}) => JSON.stringify(file(changes));
function project(pivot=old, extras={}) {
    const store = new I.AssetStore();
    const img = C.image(64,64);
    img.data.set([12,32,45,255],4 * (20 * 64 + 15));
    const imageId = store.add(img);
    const scene = {id:'scene',name:'castle',source:'shcde',
        settings:C.scene({a:1,b:1})};
    const state = I.blank();state.scenes.push(scene);
    const frame = I.makeFrame('anim_castle-2.png',imageId,scene.id,store,{pivot,ppu:64});
    Object.assign(frame,extras);
    state.frames.push(frame);
    return {state:I.validate(state,store),store,img,imageId};
}
test('Zinnenlineal values follow the original Python review contract', () => {
    const rows=P.parseMeasurements(data());
    a.equal(rows.length,1);
    a.equal(rows[0].group,'anim_castle');
    a.equal(rows[0].number,2);
    a.deepEqual(rows[0].newPivot,proposed);
    a.ok(Object.isFrozen(rows[0]));
    a.equal(P.EPSILON,2e-5);
});
test('adversarial measurements reject geometry corruption, types, duplicates', () => {
    for(const change of [
        {neu_pivot_x:.2}, {neu_pivot_y:.17}, {name:'..\\wrong-2'},
        {gruppe:'another'}, {nummer:3}, {rechts:8.25},
        {hoch:'4'}, {breite:0}, {hoehe:9000}, {pivot_y:Infinity},
        {pixel_je_einheit:0}, {pixel_je_einheit:-1}
    ]) {
        a.throws(()=>P.parseMeasurements(data(change)), /Zinnenlineal/);
    }
    a.throws(()=>P.parseMeasurements('{"schema":"bad","frames":[]}'),/Zinnenlineal/);
    a.throws(()=>P.parseMeasurements(JSON.stringify({
        ...file(),frames:[file().frames[0],file().frames[0]]
    })),/Doppelter Frame/);
    a.throws(()=>P.parseMeasurements(JSON.stringify({
        ...file(),frames:new Array(4097).fill(file().frames[0])
    })),/Zinnenlineal/);
    a.throws(()=>P.parseMeasurements('{"schema":"zinnenlineal.versatz.v1","frames":[{"__proto__":{}}]}'),/Unzulässiger JSON-Schlüssel/);
});
test('only exact original pivot and image geometry permit a visual review', () => {
    const rows=P.parseMeasurements(data());
    const original=project();
    a.equal(P.review(rows[0],original.state.frames,original.store).status,'review');
    const already=project(proposed);
    a.equal(P.review(rows[0],already.state.frames,already.store).status,'already');
    const moved=project({x:.7,y:.4});
    a.equal(P.review(rows[0],moved.state.frames,moved.store).status,'pivot_mismatch');
    const locked=project(old,{locked:true});
    a.equal(P.review(rows[0],locked.state.frames,locked.store).status,'locked');
    const absent=project(old);absent.state.frames[0].index=10;
    a.equal(P.review(rows[0],absent.state.frames,absent.store).status,'not_found');
    const duplicate=project(old);
    duplicate.state.frames.push({...duplicate.state.frames[0],id:'another-id'});
    a.equal(P.review(rows[0],duplicate.state.frames,duplicate.store).status,'ambiguous');
    const wrongDims=P.parseMeasurements(data({breite:32,rechts:4}))[0];
    a.equal(P.review(wrongDims,original.state.frames,original.store).status,'dimension_mismatch');
});
test('out-of-bound proposals are never silently normalized into a game pivot', () => {
    const rows=P.parseMeasurements(data({
        rechts:40,neu_pivot_x:-.125,hoch:4,neu_pivot_y:.1875
    }));
    const source=project();
    a.equal(P.review(rows[0],source.state.frames,source.store).status,'out_of_bounds');
});
test('source-bound manual pivot review persists in project and invalidates on changes', async () => {
    const {state,store,imageId,img}=project();
    const history=new I.History(state,store);
    const approved=I.clone(history.state);
    approved.frames[0].pivot=proposed;
    approved.frames[0].pivotEvidence={
        appliedImageId:imageId,measurementSHA256:'a'.repeat(64),
        imageContentSHA256:I.imageContentSHA256(img),
        measuredFrameName:'anim_castle 002',
        proposedPivot:proposed,
        reviewNotes:'Perspective and baseline checked',
        manualReview:true,approvedForGame:false
    };
    a.equal(history.commit(approved,store,'review'),true);
    a.equal(history.state.frames[0].pivotEvidence.approvedForGame,false);
    const archive=await I.writeProject(history.state,history.store);
    const loaded=await I.readProject(await K.unzip(archive));
    a.equal(loaded.state.frames[0].pivotEvidence.reviewNotes,'Perspective and baseline checked');
    a.equal(history.undo(),true);
    a.equal(history.state.frames[0].pivotEvidence,undefined);
    a.equal(history.redo(),true);
    const moved=I.clone(history.state);
    moved.frames[0].pivot={x:.1,y:.25};
    a.equal(I.validate(moved,history.store).frames[0].pivotEvidence,undefined);
    const forged=I.clone(history.state);
    forged.frames[0].pivotEvidence.approvedForGame=true;
    a.throws(()=>I.validate(forged,history.store),/Zinnenlineal-Nachweis/);
    store.get(imageId).data[4] = 99;
    a.throws(()=>I.validate(history.state,store),/Zinnenlineal-Nachweis/);
});


test('historical alternate suffix never targets a regular sprite', () => {
    const {state,store} = project();
    const alternate = P.parseMeasurements(data({name:'anim_castle 002x'}))[0];
    a.equal(P.review(alternate,state.frames,store).status,'not_found');
    const actualAlternate = {...state.frames[0], name:'anim_castle-002x.png'};
    a.equal(P.review(alternate,[actualAlternate],store).status,'review');
});
