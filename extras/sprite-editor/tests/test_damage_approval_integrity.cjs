'use strict';
const {test} = require('node:test');
const A = require('node:assert/strict');
const C = require('../src/core.js'), K = require('../src/codec.js');
const I = require('../src/io.js'), D = require('../src/damage.js'), DI = require('../src/damage_io.js');

function fixture() {
    const state=I.blank(), store=new I.AssetStore(), groupId='g_abbey';
    const img=C.image(64,32);
    for(let y=10;y<28;y++)for(let x=27;x<37;x++)
        img.data.set([120,90,45,255],(y*64+x)*4);
    const id=store.add(img);
    state.scenes.push({id:groupId,name:'tile_abbey',source:'custom',
        settings:C.scene({a:1,b:1,width:64,height:32,category:'building'})});
    const frame=I.makeFrame('tile_abbey-0.png',id,groupId,store);
    state.frames.push(frame);
    const created=DI.createStage(I.validate(state,store),store,groupId,'mechanical',75,'Leicht beschädigt');
    const next=I.clone(created.state);
    const clone=next.frames.find(f=>f.groupId===created.sceneId);
    const changed=C.image(img.width,img.height,new Uint8Array(img.data));
    for(let y=10;y<13;y++)for(let x=27;x<37;x++)
        changed.data.set([210,40,30,255],(y*64+x)*4);
    const imageId=created.store.add(changed);
    clone.imageId=clone.originalId=imageId;
    const checked=DI.approveStage(I.validate(next,created.store),created.store,created.stageId,
        'Vergleich und Ausrichtung geprüft',true);
    return {...checked,stageId:created.stageId, groupId, sceneId:created.sceneId};
}
test('an approved stage carries a content-bound SHA-256 fingerprint, survives SHSPRITE export and reload',async()=>{
    const f=fixture(), stage=DI.getStage(f.state,f.stageId).stage;
    A.equal(stage.status,'approved');
    A.match(stage.approvalDigest,/^[a-f0-9]{64}$/);
    A.equal(stage.approvalDigest,DI.approvalSignature(f.state,f.store,f.stageId));
    const pack=await DI.exportPackage(f.state,f.store);
    A.equal(pack.manifest.buildings[0].stages[0].approvalDigest,stage.approvalDigest);
    const saved=await I.writeProject(f.state,f.store);
    const reopened=await I.readProject(await K.unzip(saved));
    A.equal(reopened.state.damageProfiles[0].stages[0].approvalDigest,stage.approvalDigest);
    A.equal(reopened.state.damageProfiles[0].stages[0].status,'approved');
    const fresh=await DI.exportPackage(reopened.state,reopened.store);
    A.equal(fresh.manifest.buildings[0].stages[0].approvalDigest,stage.approvalDigest);
});
test('stage translation, original tile revisions, and in-place pixel mutations invalidate export without a UI commit',async()=>{
    const f=fixture();
    const scenario=[
        ['stage offset',s=>s.frames.find(x=>x.groupId===f.sceneId).dy+=1],
        ['base offset',s=>s.frames.find(x=>x.groupId===f.groupId).dx+=1],
        ['source settings',s=>{s.scenes.find(x=>x.id===f.groupId).settings.padding=2;}],
        ['damage kind',s=>{s.damageProfiles[0].stages[0].kind='fire';}],
        ['changed HP',s=>{s.damageProfiles[0].stages[0].hpAtOrBelow=40;}],
        ['new generator',s=>{s.damageProfiles[0].stages[0].model='gpt-image-2.6-flare';}],
        ['new revision request',s=>{s.damageProfiles[0].stages[0].changeRequest='Remove more roof';}],
        ['new game building type',s=>{s.damageProfiles[0].gameBuildingType=109;}]
    ];
    for(const [label,mutate] of scenario){
        const state=I.clone(f.state);
        mutate(state);
        await A.rejects(DI.exportPackage(state,f.store),/Freigabe.*gültig/,label);
    }
    const original=f.store.get(f.state.frames.find(x=>x.groupId===f.groupId).imageId);
    original.data[(12*64+29)*4]^=8;
    await A.rejects(DI.exportPackage(f.state,f.store),/Freigabe.*gültig/,
        'immutable buffers must be verified even if an external tool changed bytes in place');
    original.data[(12*64+29)*4]^=8;
    A.equal((await DI.exportPackage(f.state,f.store)).manifest.buildings.length,1);
});
test('legacy approved stages with missing fingerprints revert to draft on import, never silently export',async()=>{
    const f=fixture();
    const legacy=I.clone(f.state);
    delete legacy.damageProfiles[0].stages[0].approvalDigest;
    const normalized=I.validate(legacy,f.store);
    A.equal(normalized.damageProfiles[0].stages[0].status,'draft');
    A.equal(normalized.damageProfiles[0].stages[0].approvalDigest,null);
    await A.rejects(DI.exportPackage(normalized,f.store),/keine freigegebenen/);
    const reopened=await I.readProject(await K.unzip(await I.writeProject(normalized,f.store)));
    A.equal(reopened.state.damageProfiles[0].stages[0].status,'draft');
});
test('manual label edits keep valid approval; substantive editor edits must clear approval',async()=>{
    const f=fixture();
    const renamed=I.clone(f.state);
    renamed.damageProfiles[0].stages[0].label='Ruined abbey';
    D.invalidateApprovals(f.state,renamed);
    A.equal(renamed.damageProfiles[0].stages[0].status,'approved');
    await DI.exportPackage(renamed,f.store);
    const needsMoreDamage=I.clone(f.state);
    needsMoreDamage.damageProfiles[0].stages[0].changeRequest='Remove one more wall';
    D.invalidateApprovals(f.state,needsMoreDamage);
    A.equal(needsMoreDamage.damageProfiles[0].stages[0].status,'draft');
    A.equal(needsMoreDamage.damageProfiles[0].stages[0].approvalDigest,null);
    const differentModel=I.clone(f.state);
    differentModel.damageProfiles[0].stages[0].model='gpt-image-2.6-flare';
    D.invalidateApprovals(f.state,differentModel);
    A.equal(differentModel.damageProfiles[0].stages[0].status,'draft');
});
test('non-hash or malformed hash in user project is rejected instead of accepted as reviewed',()=>{
    const f=fixture(), corrupted=I.clone(f.state);
    corrupted.damageProfiles[0].stages[0].approvalDigest='not-really-a-hash';
    A.throws(()=>I.validate(corrupted,f.store),/Zustandsprüfsumme/);
});

test('quality review warns about mask pixels retained outside visible ruined material',()=>{
    const f=fixture(), st=I.clone(f.state), next=f.store.fork();
    const frame=st.frames.find(x=>x.groupId===f.sceneId);
    const img=next.get(frame.imageId);
    const edited=C.image(img.width,img.height,new Uint8Array(img.data));
    const mask=C.image(img.width,img.height);
    for(let y=16;y<19;y++)for(let x=27;x<37;x++){
        const i=(y*64+x)*4;
        edited.data.set([0,0,0,0],i);
        mask.data.set([44,55,66,255],i);
    }
    frame.imageId=next.add(edited);
    frame.maskId=next.add(mask);
    const report=DI.qualityReport(st,next,f.stageId);
    A.ok(report.stats.orphanMaskPixels>=30);
    A.ok(report.stats.structuralLossPixels>=30);
    A.ok(report.warnings.some(w=>w.includes('Materialmaske')));
    A.throws(()=>DI.approveStage(st,next,f.stageId,'',true),/Qualitätswarnungen/);
});

test('restored building silhouette in a worse damage stage is flagged against approved milder stage',()=>{
    const f=fixture(), s=I.clone(f.state), store=f.store.fork();
    const light=s.frames.find(x=>x.groupId===f.sceneId);
    const source=store.get(s.frames.find(x=>x.groupId===f.groupId).imageId);
    const removed=C.image(source.width,source.height,new Uint8Array(source.data));
    for(let y=10;y<13;y++)for(let x=27;x<37;x++)
        removed.data.set([0,0,0,0],(y*64+x)*4);
    light.imageId=store.add(removed);
    s.damageProfiles[0].stages[0].approvalDigest=DI.approvalSignature(s,store,f.stageId);
    const heavy=DI.createStage(s,store,f.groupId,'mechanical',40,'Schwerer Schaden');
    const heavyState=I.clone(heavy.state);
    const frame=heavyState.frames.find(x=>x.groupId===heavy.sceneId);
    const stronger=C.image(source.width,source.height,new Uint8Array(source.data));
    for(let y=19;y<23;y++)for(let x=27;x<37;x++){
        const i=(y*64+x)*4;
        stronger.data[i]=(stronger.data[i]+60)%255;
    }
    frame.imageId=store.add(stronger);
    const report=DI.qualityReport(heavyState,store,heavy.stageId);
    A.ok(report.warnings.some(w=>w.includes('zuvor entfernte opake Bildpixel')));
    A.throws(()=>DI.approveStage(heavyState,store,heavy.stageId,'',true),/Qualitätswarnungen/);
    A.equal(DI.approveStage(heavyState,store,heavy.stageId,
        'Unterschiedliche Ruinenkonturen manuell überprüft',true).state.damageProfiles[0]
        .stages.find(s=>s.id===heavy.stageId).status,'approved');
});
