'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const C=require('../../extras/sprite-editor/src/core.js');
const K=require('../../extras/sprite-editor/src/codec.js');
const I=require('../../extras/sprite-editor/src/io.js');
const D=require('../../extras/sprite-editor/src/damage.js');
const Native=require('../../tools/building_damage_native_project.cjs');
const Drafts=require('../../tools/building_damage_native_drafts.cjs');

async function fixture() {
    const root=fs.mkdtempSync(path.join(os.tmpdir(),'shcde-visual-proof-'));
    const rawDir=path.join(root,'raw_sprites');
    fs.mkdirSync(rawDir);
    const ref={
        format:'spritesuite-shcde-original-graphics-visual-proof',
        version:1,readOnly:true,orientationVerifiedInGame:false,
        gameAssetSHA256:'a'.repeat(64),mappingSHA256:'b'.repeat(64),
        sourceGameLogSHA256:'c'.repeat(64),
        gameBuildingType:19,buildingId:19,globalId:901,
        graphicsGridA:2,graphicsGridB:2,
        drawnSpriteTileCount:4,nativeSpriteImages:{},
        orientations:[{orientation:'xy-u-v',spriteA:2,spriteB:2,
            reviewed:false,approvedForRenderer:false,slots:[]}]
    };
    for(let i=0;i<4;i++){
        const name='tile_buildings1 '+(200+i);
        const img=C.image(64,32);
        for(let y=10;y<32;y++)for(let x=10;x<48;x++) {
            const j=(y*64+x)*4;
            img.data.set([50+i*26,70+i*12,120-i*5,255],j);
        }
        const png=await K.encodePNG(img);
        const filename='tile_buildings1_'+(200+i)+'.png';
        fs.writeFileSync(path.join(rawDir,filename),Buffer.from(png));
        ref.nativeSpriteImages[name]={
            png:'raw_sprites/'+filename,
            pngSHA256:K.sha256Fallback(new Uint8Array(png)),
            rgbaSHA256:K.sha256Fallback(new Uint8Array(img.data)),
            width:64,height:32,pivotX:.5,pivotY:.5,ppu:64,
            unityPathId:9876+i,texture:'AllTileSprites'
        };
        ref.orientations[0].slots.push({
            tileId:300+i,x:10+i%2,y:20+Math.floor(i/2),
            sprite:name,inNativeFootprint:true
        });
    }
    const document=path.join(root,'original_sprite_reference.json');
    fs.writeFileSync(document,JSON.stringify(ref,null,2));
    return {root,ref,document};
}

async function withFixture(fn) {
    const f=await fixture();
    try {await fn(f);}
    finally {fs.rmSync(f.root,{recursive:true,force:true});}
}

test('native game originals are imported exactly as 4x4/2x2 source frames without damage approvals',async()=>{
    await withFixture(async f=>{
        const result=await Native.assemble(f.document,'xy-u-v',19);
        assert.equal(result.clean.frames.length,4);
        assert.equal(result.clean.scenes[0].settings.a,2);
        assert.equal(result.clean.scenes[0].settings.anchor,'pivot');
        assert.equal(result.clean.damageProfiles[0].gameBuildingType,19);
        assert.equal(result.clean.damageProfiles[0].stages.length,0);
        assert.ok(result.clean.frames.every(frame=>frame.targetName==='' &&
            frame.targetConfirmed===false &&
            frame.metadataStatus==='imported'));
        assert.ok(result.preview.width>40&&result.preview.height>40);
        const reopened=await I.readProject(await K.unzip(result.bytes));
        assert.equal(reopened.state.frames.length,4);
        assert.equal(reopened.state.damageProfiles[0].stages.length,0);
        assert.equal(D.choose(reopened.state.damageProfiles[0],'fire',40),null);
    });
});

test('unapproved original art cannot be confused with approved renderer or other type',async()=>{
    await withFixture(async f=>{
        const report=Native.loadReference(f.document,'xy-u-v',19);
        assert.equal(report.selected.slots.length,4);
        assert.throws(()=>Native.loadReference(f.document,'xy-u-v',108),
            /does not match/);
        assert.throws(()=>Native.loadReference(f.document,'xy+u+v',19),
            /Unapproved or incomplete/);
        f.ref.orientations[0].approvedForRenderer=true;
        fs.writeFileSync(f.document,JSON.stringify(f.ref));
        assert.throws(()=>Native.loadReference(f.document,'xy-u-v',19),
            /Unapproved or incomplete/);
    });
});

test('source project .shsprite and .ora export exclusively, keep all RGB pixels, never install',async()=>{
    await withFixture(async f=>{
        const result=await Native.assemble(f.document,'xy-u-v',19);
        const output=path.join(f.root,'new-authoring-output');
        const saved=await Native.publish(result,output);
        assert.equal(saved.result.gameDamageHookInstalled,false);
        assert.equal(saved.result.approvedDamageStages,0);
        assert.equal(saved.result.visualOrientationConfirmedByPlayer,false);
        for(const val of Object.values(saved.result.outputFiles)) {
            const content=fs.readFileSync(path.join(output,val.name));
            assert.equal(K.sha256Fallback(new Uint8Array(content)),val.sha256);
        }
        const project=fs.readFileSync(path.join(output,'SHCDE_Original_19.shsprite'));
        const reopened=await I.readProject(await K.unzip(new Uint8Array(project)));
        assert.equal(reopened.state.frames.length,4);
        await assert.rejects(()=>Native.publish(result,output),
            /Output exists/);
    });
});

test('two damage kinds and eight HP drafts generate offline request bundles without image approval',async()=>{
    await withFixture(async f=>{
        const native=await Native.assemble(f.document,'xy-u-v',19);
        const rawSource=path.join(f.root,'original.shsprite');
        fs.writeFileSync(rawSource,Buffer.from(native.bytes));
        const checksum=K.sha256Fallback(new Uint8Array(native.bytes));
        const generated=await Drafts.make(rawSource,checksum,19);
        assert.equal(generated.generation.length,8);
        assert.equal(generated.state.damageProfiles[0].stages.length,8);
        assert.ok(generated.state.damageProfiles[0].stages.every(x=>
            x.status==='draft' && x.approvalDigest===null && !x.candidateId));
        for(const input of generated.generation){
            const requestEntries=await K.unzip(input.bytes);
            const request=JSON.parse(K.decodeText(requestEntries.find(x=>x.name==='request.json').data));
            assert.equal(request.hpAtOrBelow,input.hpAtOrBelow);
            assert.equal(request.damageKind,input.kind);
            const spec=Drafts.LEVELS.find(level=>level.kind===input.kind && level.hp===input.hpAtOrBelow);
            assert.ok(request.prompt.includes(spec.instructions));
            assert.match(request.referenceSHA256,/^[0-9a-f]{64}$/);
            assert.ok(requestEntries.some(x=>x.name==='reference.png'));
            assert.ok(requestEntries.some(x=>x.name==='model_reference.png'));
            assert.ok(request.registration?.scale>=1);
            assert.equal(request.sequentialApprovalGate,undefined);
        }
        const out=path.join(f.root,'draft-output');
        const published=await Drafts.publish(generated,out);
        assert.equal(published.stages,8);
        assert.equal(published.approvedDamageStages,0);
        assert.equal(published.modelGenerationExecuted,false);
        const manifest=JSON.parse(fs.readFileSync(path.join(out,'draft_pipeline_manifest.json'),'utf8'));
        assert.equal(manifest.approvedDamageStages,0);
        assert.equal(manifest.generatedDamageAssets,0);
        assert.equal(manifest.requestCount,8);
        assert.equal(manifest.files.length,9);
        for(const item of manifest.files)
            assert.equal(K.sha256Fallback(new Uint8Array(
                fs.readFileSync(path.join(out,item.name)))),item.sha256);
    });
});

test('source-art tampering and synthetic game type are always rejected',async()=>{
    await withFixture(async f=>{
        const native=await Native.assemble(f.document,'xy-u-v',19);
        const filename=path.join(f.root,'original.shsprite');
        fs.writeFileSync(filename,Buffer.from(native.bytes));
        const originalHash=K.sha256Fallback(new Uint8Array(native.bytes));
        await assert.rejects(()=>Drafts.make(filename,'0'.repeat(64),19),/changed/);
        await assert.rejects(()=>Drafts.make(filename,originalHash,108),
            /STRUCT_GRANARY/);
        await assert.rejects(()=>Drafts.make(filename,originalHash,104),
            /STRUCT_GRANARY/);
        const pngFile=path.join(f.root,'raw_sprites','tile_buildings1_201.png');
        const before=fs.readFileSync(pngFile);
        fs.writeFileSync(pngFile,Buffer.from(before.map(x=>(x+1)%256)));
        await assert.rejects(()=>Native.assemble(f.document,'xy-u-v',19),
            /Native PNG changed/);
    });
});
