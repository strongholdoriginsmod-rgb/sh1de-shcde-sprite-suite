'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const C = require('../src/core.js'), AI = require('../src/ai_workflow.js');
function image() {
    const result = C.image(32,32);
    for(let y=9;y<=23;y++) for(let x=10;x<=21;x++)
        result.data.set([70,100,120,255], (y*32+x)*4);
    return result;
}
function clone(img) { return C.image(img.width,img.height,new Uint8Array(img.data)); }

test('pixel QA treats hidden RGB/BC7 halo risks as warnings, not approval', () => {
    const before = image(), after = clone(before);
    after.data.set([255,0,0,0],0);
    const result = AI.reviewCandidate(before,after);
    assert.deepEqual(result.errors,[]);
    assert.equal(result.quality.hiddenRGBChanges,1);
    assert.equal(result.quality.changedPixels,1);
    assert.ok(result.quality.warnings.some(x=>/RGB|BC7/.test(x)));
    assert.equal(result.needsManualReview,true);
    assert.equal(result.quality.approved,false);
    assert.equal(result.quality.inGameTested,false);
    assert.ok(result.quality.reviewRiskPoints >= 0 && result.quality.reviewRiskPoints <=100);
});
test('ground baseline drift, silhouette added and alpha fringe are measured', () => {
    const before=image(),after=clone(before);
    after.data.set([80,120,150,128],(29*32+15)*4);
    const q=AI.visualRisk(before,after);
    assert.equal(q.groundShift,6);
    assert.equal(q.addedVisible,1);
    assert.ok(q.warnings.some(x=>/Bodenlinie/.test(x)));
    assert.ok(q.warnings.some(x=>/Silhouette/.test(x)));
    assert.equal(q.targetPartial,1);
    assert.ok(q.reviewRiskPoints >= 0);
});
test('ranking is deterministic but does not select or approve candidates', () => {
    const before=image();
    const low=clone(before),high=clone(before);
    low.data[(11*32+12)*4]=79;
    for(let y=0;y<32;y++) for(let x=0;x<32;x++)
        high.data[(y*32+x)*4+3]=255;
    const order=AI.rankCandidates(before,[
        {name:'silhouette-drift',image:high},
        {name:'small-edit',image:low},
    ]);
    assert.equal(order[0].name,'small-edit');
    assert.equal(order[1].name,'silhouette-drift');
    assert.ok(order.every(x=>!x.approved));
    assert.throws(()=>AI.rankCandidates(before,[]));
    assert.throws(()=>AI.rankCandidates(before,Array.from({length:5},()=>({image:low}))));
});
test('sequence QA reports anchored bottom jitter and empty alpha frame', () => {
    const a=image(),b=clone(a);
    const second=clone(b);
    for(let y=9;y<=23;y++)for(let x=10;x<=21;x++) second.data[(y*32+x)*4+3]=0;
    for(let y=13;y<=27;y++)for(let x=10;x<=21;x++) second.data.set([70,100,120,255],(y*32+x)*4);
    const result=AI.analyzeSequence([
        {name:'frame0',image:a,pivot:{x:.5,y:0}},
        {name:'frame1',image:second,pivot:{x:.5,y:0}},
        {name:'frame2',image:C.image(32,32),pivot:{x:.5,y:0}}
    ]);
    assert.equal(result.frames.length,3);
    assert.ok(result.warnings.some(x=>x.code==='ground_jitter'));
    assert.ok(result.warnings.some(x=>x.code==='empty_alpha'));
    assert.equal(result.automatedReleaseApproval,false);
    assert.equal(result.nativeAnimationTested,false);
    assert.throws(()=>AI.analyzeSequence([a]));
    assert.throws(()=>AI.analyzeSequence(Array(257).fill({image:a})));
});
