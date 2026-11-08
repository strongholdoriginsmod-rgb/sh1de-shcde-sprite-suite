'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('../src/legacy_measurements.js');

function record() {
    return {
        name: 'anim_castle 002', gruppe: 'anim_castle', nummer: 2,
        rechts: 0, hoch: 18, breite: 333, hoehe: 165,
        pivot_x: 0, pivot_y: 1.10909091,
        neu_pivot_x: 0, neu_pivot_y: 1.0, pixel_je_einheit: 64.0
    };
}
const doc = entries => ({ schema: L.SCHEMA, erzeugt: '2026-09-04', frames: entries });
const frame = pivot => ({ name: 'anim_castle 002', pivot });
const img = (width=333,height=165) => ({width,height});

test('real historical Zinnenlineal format and displacement survive read-only import', () => {
    const original = doc([record()]);
    const snapshot = JSON.stringify(original);
    const parsed = L.parseDocument(original);
    assert.equal(parsed.rows.length, 1);
    assert.equal(parsed.rows[0].up, 18);
    assert.equal(parsed.rows[0].candidate.y, 1.0);
    const current = frame({x:0,y:1.10909091});
    const originalFrame = JSON.stringify(current);
    const found = L.forFrame(parsed, current, img());
    assert.equal(found.status, 'review');
    assert.equal(found.measure.dx, 0);
    assert.equal(found.measure.dy, -18);
    assert.equal(found.measure.start.y, 18);
    assert.equal(found.measure.end.y, 0);
    assert.equal(found.mayVisualize,true);
    assert.equal(JSON.stringify(original),snapshot);
    assert.equal(JSON.stringify(current),originalFrame);
});
test('already applied old pivot and reference drift are distinguished', () => {
    const parsed = L.parseDocument(doc([record()]));
    assert.equal(L.forFrame(parsed,frame({x:0,y:1}),img()).status,'already_applied');
    assert.equal(L.forFrame(parsed,frame({x:0,y:.75}),img()).status,'different_reference');
});
test('ambiguous or mismatched sources never produce a visual line', () => {
    const parsed = L.parseDocument(doc([record()]));
    assert.equal(L.forFrame(parsed,{name:'other 123',pivot:{x:0,y:1}},img()).status,'missing');
    const wrong = L.forFrame(parsed,frame({x:0,y:1}),img(222,165));
    assert.equal(wrong.status,'size_mismatch');
    assert.equal(wrong.measure,null);
    assert.equal(wrong.mayVisualize,undefined);
});
test('too long historic offsets may be reviewed but never rendered out of bounds', () => {
    const row = {...record(),rechts:1200,neu_pivot_x:-1200/333};
    const found=L.forFrame(L.parseDocument(doc([row])),frame({x:0,y:1}),img());
    assert.equal(found.mayVisualize,false);
    assert.equal(found.measure.dx,1200);
});
test('non-matching old schema is not accepted as a project', () => {
    for (const bad of [null, [], {}, {schema:'fake',frames:[]}, {schema:L.SCHEMA,frames:'abc'}])
        assert.throws(() => L.parseDocument(bad),/Zinnenlineal-Import/);
});
test('record cap and duplicates are rejected before matching', () => {
    assert.throws(() => L.parseDocument(doc(Array(4097).fill(record()))),/4096/);
    assert.throws(() => L.parseDocument(doc([record(),record()])),/Doppelter/);
});
test('names, group and integer fields use the historical Python semantics', () => {
    const cases=[
        ['name','../secret'],['name','anim-castle 2'],['gruppe','wrong'],
        ['nummer',3],['nummer','2'],['breite',0],['hoehe',10000],
        ['rechts',true],['hoch',12.4],['hoch',5000]
    ];
    for (const [key,value] of cases)
        assert.throws(() => L.parseDocument(doc([{...record(),[key]:value}])),
            /Zinnenlineal-Import/,key+'='+String(value));
});
test('untrusted pivots are checked, including formula, finite, bools and types', () => {
    for (const [key,value] of [
        ['pivot_x',true],['pivot_y','1'],['pivot_y',Infinity],['pivot_y',null],
        ['neu_pivot_x',.5],['neu_pivot_y',1.5],['neu_pivot_y',NaN],
        ['pixel_je_einheit',-4],['pixel_je_einheit','64']
    ])
        assert.throws(() => L.parseDocument(doc([{...record(),[key]:value}])),
            /Zinnenlineal-Import/,key);
});
test('old alt-name x suffix is supported without applying a correction', () => {
    const old={...record(),name:'anim_castle-002x'};
    const parsed=L.parseDocument(doc([old]));
    assert.equal(parsed.rows[0].name,old.name);
});
test('immutable measurement rows cannot be modified indirectly', () => {
    const parsed=L.parseDocument(doc([record()]));
    assert.ok(Object.isFrozen(parsed));
    assert.ok(Object.isFrozen(parsed.rows));
    assert.ok(Object.isFrozen(parsed.rows[0]));
    assert.ok(Object.isFrozen(parsed.rows[0].candidate));
    assert.throws(()=>{parsed.rows[0].right=99},TypeError);
});


test('SpriteSuite .png names and historical space separators map to the same verified frame', () => {
    const parsed = L.parseDocument(doc([record()]));
    const found = L.forFrame(parsed,{name:'anim_castle-002.png', pivot:{x:0,y:1.10909091}},img());
    assert.equal(found.status,'review');
    assert.equal(found.row.name,'anim_castle 002');
});
test('conflicting space-vs-dash historical aliases are never silently selected', () => {
    const rows=[record(),{...record(),name:'anim_castle-002'}];
    const parsed = L.parseDocument(doc(rows));
    const found = L.forFrame(parsed,{name:'anim_castle-002.png', pivot:{x:0,y:1}},img());
    assert.equal(found.status,'ambiguous');
    assert.equal(found.row,null);
});
