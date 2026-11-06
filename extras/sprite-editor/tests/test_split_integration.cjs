'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const C=require('../src/core.js');
const I=require('../src/io.js');
const K=require('../src/codec.js');

function fixture(overlap=1,rearShare=true){
    const settings=C.scene({a:3,b:3,width:64,height:32,padding:0});
    const src=C.image(224,170),anchorX=112,anchorY=151;
    const map=C.partition(src,settings,anchorX,anchorY,true);
    for(let i=0;i<map.length;i++)if(map[i]>=0){
        const o=i*4;
        src.data.set([(i*3)%256,(i*11)%256,93,(i%7===0?128:255)],o);
    }
    const store=new I.AssetStore();
    const imageId=store.add(src),mapId=store.add(C.ownershipImage(map,src.width,src.height));
    const state=I.blank();
    state.split={imageId,mapId,maskId:null,settings,anchorX,anchorY,
                 extend:true,overlap,rearShare,group:'tile_custom',start:540,
                 source:'custom'};
    return {state:I.validate(state,store),store,src,map,settings,anchorX,anchorY};
}
test('new split project preserves overlap policy through SHSPRITE project roundtrip',async()=>{
    const {state,store}=fixture();
    assert.equal(state.split.overlap,1);
    assert.equal(state.split.rearShare,true);
    const saved=await I.writeProject(state,store);
    const reopened=await I.readProject(await K.unzip(saved));
    assert.equal(reopened.state.split.overlap,1);
    assert.equal(reopened.state.split.rearShare,true);
    assert.equal(reopened.state.split.anchorX,state.split.anchorX);
    const before=await I.exportSplit(state,store);
    const after=await I.exportSplit(reopened.state,reopened.store);
    assert.deepEqual(Buffer.from(before.bytes),Buffer.from(after.bytes),
       'zip must be deterministic across project roundtrip');
});
test('exported split ZIP includes overlap metadata, 64px PNGs, and no pixel loss',async()=>{
    const {state,store,src}=fixture();
    const built=await I.exportSplit(state,store);
    assert.ok(built.result.seamStats.edgeSamples>0);
    assert.ok(built.result.seamStats.rearSharedSamples>0);
    const entries=await K.unzip(built.bytes);
    assert.equal(entries.length,10);
    const meta=JSON.parse(K.decodeText(entries.find(e=>e.name==='schnitt.json').data));
    assert.equal(meta.version,1);
    assert.equal(meta.overlap,1);
    assert.equal(meta.rearShare,true);
    assert.equal(meta.seamStats.edgeSamples,built.result.seamStats.edgeSamples);
    const expected=C.image(src.width,src.height);
    for(const row of meta.tiles){
        assert.equal(row.width,64);
        const file=entries.find(e=>e.name===row.name);
        assert.ok(file);
        const png=await K.decodePNG(file.data);
        assert.equal(png.width,64);
        assert.equal(png.height,row.height);
        C.blit(expected,png,row.x,row.y,true);
    }
    assert.deepEqual(Array.from(expected.data),Array.from(src.data));
});
test('transfer split does not expand bitmaps or corrupt project/scene geometry',()=>{
    const {state,store,src}=fixture();
    const out=I.transferSplit(state,store);
    assert.equal(out.state.frames.length,9);
    const settings=out.state.scenes[0].settings;
    assert.equal(settings.width,64);
    for(const frame of out.state.frames){
        const img=out.store.get(frame.imageId);
        assert.equal(img.width,64);
        assert.ok(img.height>0);
        assert.equal(frame.slot>=0&&frame.slot<9,true);
    }
    assert.equal(out.state.split.overlap,1);
});
test('old cut projects retain disjoint samples even after reopening',async()=>{
    const {state,store}=fixture(0,false);
    delete state.split.overlap;
    delete state.split.rearShare;
    const clean=I.validate(state,store);
    assert.equal(clean.split.overlap,0);
    assert.equal(clean.split.rearShare,false);
    const saved=await I.readProject(await K.unzip(await I.writeProject(clean,store)));
    assert.equal(saved.state.split.overlap,0);
    assert.equal(saved.state.split.rearShare,false);
    const zip=await I.exportSplit(saved.state,saved.store);
    const entries=await K.unzip(zip.bytes);
    const metadata=JSON.parse(K.decodeText(entries.find(e=>e.name==='schnitt.json').data));
    assert.equal(metadata.overlap,0);
    assert.equal(metadata.rearShare,false);
    assert.equal(zip.result.seamStats.edgeSamples,0);
    assert.equal(zip.result.seamStats.rearSharedSamples,0);
});
test('transparent RGB bleed fills only unused alpha-0 RGB, never changes opacity or source',()=>{
    const s=C.scene({a:1,b:1,width:64,height:32,padding:0});
    const src=C.image(64,64),anchorX=32,anchorY=62,map=C.partition(src,s,anchorX,anchorY,true);
    const pixel=(40*src.width+32)*4;
    src.data.set([247,45,90,255],pixel);
    const raw=Array.from(src.data);
    const result=C.split(src,map,s,anchorX,anchorY,null,{overlap:1,rearShare:true});
    assert.equal(result.tiles.length,1);
    assert.ok(result.seamStats.transparentRGBBleed>0);
    const tile=result.tiles[0];
    const inside=(x,y)=>(y-tile.y)*tile.width*4+(x-tile.x)*4;
    const near=inside(32,39);
    assert.deepEqual(Array.from(tile.image.data.slice(near,near+4)),[247,45,90,0]);
    assert.deepEqual(Array.from(src.data),raw);
    const reconstructed=C.image(src.width,src.height);
    C.blit(reconstructed,tile.image,tile.x,tile.y,true);
    assert.deepEqual(Array.from(reconstructed.data),raw);
});
