#!/usr/bin/env node
'use strict';
/**
 * Prepare two separate mechanical/fire damage progressions from exact native
 * SpriteSuite building source. Each draft starts with the original sprite.
 * Export separate request ZIPs with the reference and prompt for each stage.
 */
const fs = require('node:fs');
const path = require('node:path');
const K = require('../extras/sprite-editor/src/codec.js');
const I = require('../extras/sprite-editor/src/io.js');
const DI = require('../extras/sprite-editor/src/damage_io.js');

const LEVELS = Object.freeze([
    {kind:'mechanical', hp:80, label:'Kornkammer: leichte Einschläge',
        instructions:'Visibly chipped stone corners, cracked mortar and first broken wooden shutters; preserve all original roof straw and the exact base footprint.'},
    {kind:'mechanical', hp:45, label:'Kornkammer: schwere Breschen',
        instructions:'Clear breached exterior masonry, exposed masonry rubble and fractured shutter timbers, partially collapsed stone wall; retain recognizable original architectural geometry.'},
    {kind:'mechanical', hp:15, label:'Kornkammer: nahezu eingestürzt',
        instructions:'Severe structural loss in walls, floor-level rubble and broken supports; must be far more damaged than the 45 percent state; keep original lighting and pixel style.'},
    {kind:'mechanical', hp:0, label:'Kornkammer: mechanische Ruine',
        instructions:'A mostly demolished shell of the granary, very low preserved stone wall stubs, heaps of realistic stone rubble and shattered shutter wood; no magically restored sections.'},
    {kind:'fire', hp:85, label:'Kornkammer: erste Brandschäden',
        instructions:'Localized soot on the original stone and timber, first burned shutter corners and singed straw, without structural collapse or extra light sources.'},
    {kind:'fire', hp:50, label:'Kornkammer: durchgebrannter Dachraum',
        instructions:'Heavy charring of straw and timber, scorched shutter gaps and burned masonry, some realistically fallen debris; keep original perspective and ground anchor.'},
    {kind:'fire', hp:20, label:'Kornkammer: Brandschutt',
        instructions:'Widespread fire-damaged original wood and collapsed roof/balcony, intense blackened stone surfaces, broken burning remnants without transparent smoke obscuring the building.'},
    {kind:'fire', hp:0, label:'Kornkammer: ausgebrannte Ruine',
        instructions:'Almost total fire-related collapse, blackened low stone shell with ash and charred beams, coherent rubble, no restored original roof or walls.'}
]);

function require_(value, message) { if (!value) throw new Error(message); }
function parse(argv) {
    const out={};
    for(let i=0;i<argv.length;i+=2) {
        const key=argv[i], val=argv[i+1];
        require_(key && key.startsWith('--') && val!==undefined,'Expected --option value.');
        require_(out[key]===undefined,'Duplicate option '+key);
        out[key]=val;
    }
    for(const k of ['--project','--expected-sha256','--output','--expected-type'])
        require_(typeof out[k]==='string','Missing '+k);
    require_(Object.keys(out).every(k=>['--project','--expected-sha256','--output','--expected-type'].includes(k)),
        'Unknown option.');
    return out;
}

async function make(projectFile, expectedSha, expectedType) {
    // All textual prompts here describe original granary architecture.
    // Never silently rebrand e.g. a pond as a granary through a numeric field.
    require_(expectedType === 19,
        'This draft progression applies only to SHCDE STRUCT_GRANARY (game type 19).');
    require_(/^[a-f0-9]{64}$/.test(expectedSha),'Expected source project SHA-256 is missing.');
    const raw = fs.readFileSync(projectFile);
    require_(K.sha256Fallback(new Uint8Array(raw))===expectedSha,
        'Source project bytes changed since the checksum was recorded.');
    const source=await I.readProject(await K.unzip(new Uint8Array(raw)));
    let state=I.validate(source.state,source.store), store=source.store;
    require_(state.scenes.length===1 && state.damageProfiles.length===1 &&
        state.damageProfiles[0].gameBuildingType===expectedType &&
        state.damageProfiles[0].stages.length===0,
        'Expected the intact, native, unmodified building source project.');
    const baseId=state.scenes[0].id, base=DI.baseComposite(state,store,baseId);
    require_(state.scenes[0].settings.a*state.scenes[0].settings.b===state.frames.length &&
        state.frames.every(f=>store.get(f.imageId).width<=64 && !f.maskId),
        'Native source has unverified grid or mask policies.');
    const generation=[];
    for(const spec of LEVELS) {
        const result=DI.createStage(state,store,baseId,spec.kind,spec.hp,spec.label);
        state=I.clone(result.state);store=result.store;
        const profile=state.damageProfiles[0];
        const stage=profile.stages.find(row=>row.id===result.stageId);
        require_(!!stage,'New editable scene lacks corresponding damage profile.');
        stage.changeRequest=spec.instructions;
        stage.status='draft';
        stage.approvalDigest=null;
        state=I.validate(state,store);
        const bundle=await DI.makeRequestBundle(state,store,result.stageId);
        require_(bundle.request.damageKind===spec.kind &&
            bundle.request.hpAtOrBelow===spec.hp &&
            bundle.request.referenceWidth===base.image.width &&
            bundle.request.referenceHeight===base.image.height,
            'AI request is not registered to the original building.');
        generation.push({
            name: spec.kind + '_' + String(spec.hp).padStart(2, '0') + '_request.zip',
            bytes: bundle.bytes,
            kind: spec.kind,
            hpAtOrBelow: spec.hp,
            label: spec.label,
            originalSHA256: bundle.request.referenceSHA256,
            stageId: result.stageId,
            registration: bundle.request.registration
        });
    }
    const clean=I.validate(state,store), profile=clean.damageProfiles[0];
    require_(profile.stages.length===LEVELS.length &&
        profile.stages.every(stage=>stage.status==='draft' && !stage.approvalDigest) &&
        !profile.stages.some(stage=>stage.candidateId),
        'Unreviewed damage assets must never be marked approved.');
    const again=DI.baseComposite(clean,store,baseId);
    require_(K.sha256Fallback(new Uint8Array(again.image.data))===
        K.sha256Fallback(new Uint8Array(base.image.data)),
        'Native source was modified when creating damage scenes.');
    const projectBytes=await I.writeProject(clean,store);
    const reopened=await I.readProject(await K.unzip(projectBytes));
    require_(reopened.state.damageProfiles[0].stages.length===LEVELS.length &&
        reopened.state.damageProfiles[0].stages.every(stage=>stage.status==='draft'),
        'SHSPRITE roundtrip lost draft-only approval status.');
    return {projectBytes,generation,sourceProjectSHA256:expectedSha,
        buildingType:expectedType, state:clean, base, inputSceneId:baseId};
}

function writeExclusive(directory, relative, data) {
    const filename=path.join(directory,relative);
    require_(filename.startsWith(directory+path.sep),'Unsafe output path.');
    fs.writeFileSync(filename,data,{flag:'wx'});
    return {name:relative,sha256:K.sha256Fallback(new Uint8Array(fs.readFileSync(filename))),
        size:fs.statSync(filename).size};
}

async function publish(result, output) {
    const dest=path.resolve(output), temp=dest+'.building-'+process.pid+'.working';
    require_(!fs.existsSync(dest) && !fs.existsSync(temp),
        'Output already exists; refusing overwrite.');
    require_(fs.statSync(path.dirname(dest)).isDirectory(),'Output parent missing.');
    fs.mkdirSync(temp);
    try {
    fs.mkdirSync(path.join(temp,'requests'));
    const files=[];
    files.push(writeExclusive(temp,'Granary_19_DamageDrafts.shsprite',
        Buffer.from(result.projectBytes)));
    for(const item of result.generation)
        files.push(writeExclusive(temp,'requests/'+item.name,
            Buffer.from(item.bytes)));
    const manifest={
        format:'spritesuite-building-damage-draft-generation-requests',version:1,
        gameBuildingType:result.buildingType,
        nativeBaseSceneId:result.inputSceneId,
        sourceProjectSHA256:result.sourceProjectSHA256,
        modelGenerationExecuted:false,
        generatedDamageAssets:0,approvedDamageStages:0,
        requestCount:result.generation.length,
        visualOrientationVerifiedInGame:false,
        fullGameDamageModInstalled:false,
        requests:result.generation.map(({bytes,...details})=>details),
        files,
        note:'Each draft contains the original artwork and a prompt for the selected damage stage.'
    };
    writeExclusive(temp,'draft_pipeline_manifest.json',
        JSON.stringify(manifest,null,2)+'\n');
    require_(!fs.existsSync(dest),'Output appeared during creation.');
    fs.renameSync(temp,dest);
    return {output:dest,profile:result.buildingType,stages:manifest.requests.length,
        requests:manifest.requests.map(row=>row.name),
        approvedDamageStages:0,modelGenerationExecuted:false};
    } catch (error) {
        if (fs.existsSync(temp) && fs.lstatSync(temp).isDirectory() &&
            !fs.lstatSync(temp).isSymbolicLink())
            fs.rmSync(temp, { recursive:true, force:false });
        throw error;
    }
}

async function main(argv=process.argv.slice(2)) {
    const options=parse(argv);
    const expectedType=Number(options['--expected-type']);
    require_(Number.isInteger(expectedType) && expectedType>=0 && expectedType<=4095,
        'Invalid game building type.');
    const result=await make(options['--project'],
        options['--expected-sha256'],expectedType);
    console.log(JSON.stringify(await publish(result,options['--output']),
        null,2));
}
if(require.main===module) main().catch(error=>{
    console.error('Native damage drafts: '+error.message);
    process.exitCode=2;
});
module.exports={parse,make,publish,main,LEVELS};
