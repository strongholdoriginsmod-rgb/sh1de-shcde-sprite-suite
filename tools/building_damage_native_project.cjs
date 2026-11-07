#!/usr/bin/env node
'use strict';
/**
 * Package exact UnityPy-extracted, SHA-checked native SHCDE sprites into an
 * editable SpriteSuite building source project. Never treat an orientation
 * hypothesis as a released renderer mapping or invent approved damage tiers.
 *
 * Run: node tools/building_damage_native_project.cjs
 *   --reference <original_sprite_reference.json>
 *   --orientation <geometry candidate> --expected-type <id>
 *   --output <new directory>
 */
const fs = require('node:fs');
const path = require('node:path');
const C = require('../extras/sprite-editor/src/core.js');
const K = require('../extras/sprite-editor/src/codec.js');
const I = require('../extras/sprite-editor/src/io.js');
const D = require('../extras/sprite-editor/src/damage.js');

const FORMAT = 'spritesuite-shcde-original-graphics-visual-proof';
const PATH_RX = /^raw_sprites\/(tile_buildings1|tile_buildings2|tile_goods)_[0-9]{1,4}\.png$/;
const VALID_SHA = /^[a-f0-9]{64}$/;
const IDENT = /^[A-Za-z0-9_-]{1,80}$/;

function fail(message) { throw new Error(message); }
function require_(value, reason) { if (!value) fail(reason); }
function attrs(argv) {
    const args = {};
    for (let i = 0; i < argv.length; i += 2) {
        const key = argv[i], value = argv[i+1];
        require_(key && key.startsWith('--') && value !== undefined, 'Expected --field value pairs.');
        require_(args[key] === undefined, 'Repeated command argument.');
        args[key] = value;
    }
    for (const x of ['--reference','--orientation','--expected-type','--output'])
        require_(typeof args[x] === 'string', 'Required: ' + x);
    for (const key of Object.keys(args))
        require_(['--reference','--orientation','--expected-type','--output'].includes(key),
            'Unknown argument ' + key);
    return args;
}

function loadReference(refFile, orientation, expectedType) {
    const report = JSON.parse(fs.readFileSync(refFile, 'utf8'));
    require_(report.format === FORMAT && report.version === 1 &&
        report.readOnly === true && report.orientationVerifiedInGame === false,
        'Unsupported or overclaimed original sprite reference.');
    require_(Number.isInteger(expectedType) &&
        report.gameBuildingType === expectedType &&
        Number.isInteger(report.buildingId) &&
        Number.isInteger(report.globalId) &&
        expectedType >= 0 && expectedType <= 4095,
        'Original source does not match the requested game building type.');
    require_(VALID_SHA.test(report.gameAssetSHA256) &&
        VALID_SHA.test(report.mappingSHA256) &&
        VALID_SHA.test(report.sourceGameLogSHA256),
        'Original assets require exact provenance SHA-256.');
    if (report.gameBuildingTypeName != null)
        require_(/^STRUCT_[A-Z0-9_]{1,80}$/.test(report.gameBuildingTypeName) &&
            VALID_SHA.test(report.gameBuildingTypeCatalogSHA256),
            'Native building type label requires pinned SHCDESE catalog.');
    require_(Array.isArray(report.orientations) &&
        report.orientations.length >= 1 && report.orientations.length <= 8 &&
        typeof report.nativeSpriteImages === 'object',
        'Original image mapping is incomplete.');
    const selected = report.orientations.find(item =>
        item.orientation === orientation && item.reviewed === false &&
        item.approvedForRenderer === false);
    require_(selected &&
        selected.spriteA * selected.spriteB === report.drawnSpriteTileCount &&
        selected.spriteA >= 1 && selected.spriteA <= 64 &&
        selected.spriteB >= 1 && selected.spriteB <= 64 &&
        selected.slots.length === report.drawnSpriteTileCount,
        'Unapproved or incomplete selected visual orientation.');
    const slots = new Set(), nativeNames = new Set();
    for (const item of selected.slots) {
        const name = item.sprite, meta = report.nativeSpriteImages[name];
        require_(typeof name === 'string' &&
            /^tile_(?:buildings1|buildings2|goods) [0-9]{1,4}$/.test(name),
            'Unsafe source sprite name.');
        require_(meta && PATH_RX.test(meta.png) &&
            VALID_SHA.test(meta.pngSHA256) &&
            VALID_SHA.test(meta.rgbaSHA256) &&
            Number.isInteger(meta.width) && meta.width <= 64 &&
            Number.isInteger(meta.height) && meta.height >= 1 &&
            Number.isFinite(meta.pivotX) && meta.pivotX >= 0 && meta.pivotX <= 1 &&
            Number.isFinite(meta.pivotY) && meta.pivotY >= 0 && meta.pivotY <= 1 &&
            meta.ppu > 0 && meta.ppu <= 65536,
            'Unverified source PNG metadata or image geometry.');
        require_(item.tileId >= 0 && Number.isSafeInteger(item.tileId) &&
            Number.isSafeInteger(item.x) && Number.isSafeInteger(item.y),
            'Invalid native graphical tile coordinate.');
        require_(!slots.has(item.tileId), 'Duplicate native target tile ID.');
        slots.add(item.tileId);
        nativeNames.add(name);
    }
    require_(nativeNames.size === report.drawnSpriteTileCount,
        'Duplicate game sprite image (cannot be treated as separately verified geometry).');
    return { report, selected };
}

async function assemble(reference, orientation, expectedType) {
    const reportFile = path.resolve(reference);
    const { report, selected } = loadReference(reportFile, orientation, expectedType);
    const base = path.dirname(reportFile);
    const store = new I.AssetStore(), state = I.blank();
    const sceneId = 'g_native_' + expectedType;
    state.project.name = 'SHCDE Native Source – ' +
        (report.gameBuildingTypeName || expectedType) +
        ' / Orientation ' + orientation;
    state.project.author = 'SpriteSuite (original assets, not damaged)';
    state.scenes.push({
        id: sceneId,
        name: 'SHCDE Original · building type ' + expectedType,
        source: 'shcde',
        settings: C.scene({
            a: selected.spriteA, b: selected.spriteB,
            width: 64, height: 32, padding: 0, order: 'ascending',
            anchor: 'pivot', category: 'building'
        })
    });
    state.damageProfiles.push({ buildingGroupId: sceneId,
        gameBuildingType: expectedType, stages: [] });
    for (let slot = 0; slot < selected.slots.length; slot++) {
        const tile = selected.slots[slot], name = tile.sprite;
        const meta = report.nativeSpriteImages[name];
        const resolved = path.resolve(base, meta.png.replaceAll('/',path.sep));
        require_(resolved.startsWith(base + path.sep),
            'Source tile escaped the asset reference directory.');
        require_(fs.statSync(resolved).isFile() && !fs.lstatSync(resolved).isSymbolicLink(),
            'Source PNG is not an ordinary file.');
        const bytes = new Uint8Array(fs.readFileSync(resolved));
        require_(K.sha256Fallback(bytes) === meta.pngSHA256,
            'Native PNG changed since source pixel export: ' + name);
        const img = await K.decodePNG(bytes);
        require_(img.width === meta.width && img.height === meta.height,
            'Native image geometry mismatch: ' + name);
        require_(K.sha256Fallback(new Uint8Array(img.data)) === meta.rgbaSHA256,
            'Original RGBA pixels differ from proven Unity game sprite: ' + name);
        const imageId = store.add(img);
        const frame = I.makeFrame(
            name.replace(' ', '-') + '.png',
            imageId, sceneId, store,
            { pivot: { x: meta.pivotX, y: meta.pivotY }, ppu: meta.ppu });
        frame.slot = slot;
        frame.targetName = ''; frame.targetConfirmed = false;
        frame.dx = 0; frame.dy = 0;
        state.frames.push(frame);
    }
    const clean = I.validate(state, store);
    const errors = I.preflight(clean, store).filter(m => m.level === 'error');
    // This is an authoring SOURCE, not a game override. Intentional
    // missing target names must block premature vanilla/atlas export.
    require_(errors.length === clean.frames.length &&
        errors.every(row => row.code === 'TARGET_NAME'),
        'Native source project has unexpected game-export problems: ' +
        JSON.stringify(errors.slice(0, 3)));
    require_(clean.damageProfiles.length === 1 &&
        clean.damageProfiles[0].gameBuildingType === expectedType &&
        clean.damageProfiles[0].stages.length === 0,
        'Original asset cannot contain approved or invented damage stages.');
    const layout = C.layout(clean.frames, clean.scenes[0].settings,
        id => store.get(id));
    const preview = C.compose(layout, id => store.get(id));
    const bytes = await I.writeProject(clean, store);
    const reopened = await I.readProject(await K.unzip(bytes));
    require_(reopened.state.frames.length === selected.slots.length &&
        reopened.state.damageProfiles[0].stages.length === 0,
        'Source project did not survive SHSPRITE roundtrip.');
    const afterLayout = C.layout(reopened.state.frames,
        reopened.state.scenes[0].settings, id => reopened.store.get(id));
    const after = C.compose(afterLayout, id => reopened.store.get(id));
    require_(preview.width === after.width && preview.height === after.height &&
        K.sha256Fallback(new Uint8Array(preview.data)) ===
        K.sha256Fallback(new Uint8Array(after.data)),
        'Native source image changed in project roundtrip.');
    require_(D.choose(clean.damageProfiles[0], 'mechanical', 40) === null &&
        D.choose(clean.damageProfiles[0], 'fire', 40) === null,
        'Source project fabricated a damage tier.');
    return { clean, store, bytes, preview, source: report,
        selected, sceneId, layout };
}

async function publish(result, dest) {
    const directory = path.resolve(dest);
    require_(!fs.existsSync(directory), 'Output exists; refusing to overwrite.');
    require_(fs.statSync(path.dirname(directory)).isDirectory(),
        'Output parent directory is missing.');
    const tempDirectory = directory + '.building-' + process.pid + '.working';
    require_(!fs.existsSync(tempDirectory),
        'Temporary output already exists; refuse overwrite.');
    fs.mkdirSync(tempDirectory);
    try {
    const type = result.source.gameBuildingType;
    const root = 'SHCDE_Original_' + type;
    const outputs = {
        project: root + '.shsprite',
        ora: root + '.ora',
        preview: root + '_Preview.png',
        report: root + '_Provenance.json',
    };
    fs.writeFileSync(path.join(tempDirectory, outputs.project),
        Buffer.from(result.bytes), { flag: 'wx' });
    const ora = await I.exportORA(result.clean.frames,
        result.clean.scenes[0].settings, result.store, null,
        { name: result.clean.project.name });
    fs.writeFileSync(path.join(tempDirectory, outputs.ora),
        Buffer.from(ora), { flag: 'wx' });
    fs.writeFileSync(path.join(tempDirectory, outputs.preview),
        Buffer.from(await K.encodePNG(result.preview)), { flag: 'wx' });
    const document = {
        format:'spritesuite-native-building-source',
        version:1, originalSource:result.source.format,
        gameBuildingType:type,
        gameBuildingTypeName:result.source.gameBuildingTypeName || null,
        buildingTypeCatalogSHA256:result.source.gameBuildingTypeCatalogSHA256 || null,
        gameBuildingTypeObservedInGame:true,
        buildingId:result.source.buildingId,
        globalId:result.source.globalId,
        previewedOrientation:result.selected.orientation,
        visualOrientationConfirmedByPlayer:false,
        inGameSpriteSlotMappingVerified:false,
        approvedDamageStages:0,
        gameDamageHookInstalled:false,
        noGameFilesModified:true,
        sourceAssetSHA256:result.source.gameAssetSHA256,
        originalMappingSHA256:result.source.mappingSHA256,
        gameEvidenceSHA256:result.source.sourceGameLogSHA256,
        outputFiles:Object.fromEntries(Object.entries(outputs)
            .filter(([key]) => key !== 'report')
            .map(([key,name])=>
              [key,{name, sha256:K.sha256Fallback(new Uint8Array(
                  fs.readFileSync(path.join(tempDirectory,name))))}])),
        note:'Editable ORIGINAL native sprite art, not a released or approved damaged building. Graphical orientation requires visual and in-game review.'
    };
    fs.writeFileSync(path.join(tempDirectory, outputs.report),
        JSON.stringify(document,null,2)+'\n',{flag:'wx'});
    require_(!fs.existsSync(directory), 'Final output folder appeared during export.');
    fs.renameSync(tempDirectory, directory);
    return { directory, result:document };
    } catch (error) {
        if (fs.existsSync(tempDirectory) && fs.lstatSync(tempDirectory).isDirectory() &&
            !fs.lstatSync(tempDirectory).isSymbolicLink())
            fs.rmSync(tempDirectory, { recursive:true, force:false });
        throw error;
    }
}

async function main(argv=process.argv.slice(2)) {
    const opts=attrs(argv);
    const t=Number(opts['--expected-type']);
    require_(Number.isInteger(t), 'Invalid expected game type.');
    const result=await assemble(opts['--reference'],opts['--orientation'],t);
    const {directory,result:published}=await publish(result,opts['--output']);
    console.log(JSON.stringify({
        directory,
        sourceGraphicTiles:result.selected.slots.length,
        nativeScene:result.sceneId,
        orientation:result.selected.orientation,
        spriteEditorProject:published.outputFiles.project.name,
        oriLayers:published.outputFiles.ora.name,
        preview:published.outputFiles.preview.name,
        visualOrientationConfirmedByPlayer:false,
        gameDamageHookInstalled:false
    },null,2));
}

if (require.main === module) {
    main().catch(err => { console.error('Native source conversion: '+err.message);
        process.exitCode=2; });
}
module.exports={attrs,loadReference,assemble,publish,main};
