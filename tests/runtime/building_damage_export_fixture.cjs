'use strict';
/* Integration fixture: genuine exported SpriteSuite ZIP -> runtime preflight.
 * Only writes an explicitly named new file; never touches game installations.
 */
const fs = require('node:fs');
const path = require('node:path');
const C = require('../../extras/sprite-editor/src/core.js');
const K = require('../../extras/sprite-editor/src/codec.js');
const I = require('../../extras/sprite-editor/src/io.js');
const DI = require('../../extras/sprite-editor/src/damage_io.js');
const output = process.argv[2];
if (!output || fs.existsSync(output)) {
    throw new Error('Provide a new output ZIP path; refusing to overwrite existing files.');
}

async function produce() {
    const originalFile = path.join(__dirname,
        '../../extras/sprite-editor/beispiele/Steinhof.shsprite');
    const entries = await K.unzip(new Uint8Array(fs.readFileSync(originalFile)));
    let { state, store } = await I.readProject(entries);
    const groupId = state.scenes[0].id;
    for (const [kind, hp, darkness] of [
        ['mechanical', 75, 0.48], ['fire', 40, 0.22]
    ]) {
        const result = DI.createStage(state, store, groupId, kind, hp,
            kind === 'fire' ? 'Nach Brand und Einsturz' : 'Strukturbruch');
        state = result.state;
        store = result.store;
        // Mapping must be part of the approved content-bound state, not added afterward.
        state.damageProfiles.find(profile => profile.buildingGroupId === groupId).gameBuildingType = 108;
        const original = DI.baseComposite(state, store, groupId).image;
        const candidate = C.image(original.width, original.height,
            new Uint8Array(original.data));
        let changed = 0;
        for (let i = 0; i < candidate.data.length && changed < 1100; i += 4) {
            if (candidate.data[i + 3] === 255) {
                candidate.data[i] = Math.round(candidate.data[i] * darkness);
                candidate.data[i + 1] = Math.round(candidate.data[i + 1] * darkness);
                candidate.data[i + 2] = Math.round(candidate.data[i + 2] * darkness);
                changed++;
            }
        }
        if (changed !== 1100) throw new Error('Insufficient opaque pixels for fixture.');
        const imported = DI.withCandidate(state, store, result.stageId, candidate);
        const split = DI.applyCandidate(imported.state, imported.store, result.stageId);
        const review = DI.qualityReport(split.state, split.store, result.stageId);
        if (review.errors.length)
            throw new Error('Fixture split not exact: ' + review.errors.join(' | '));
        const accepted = DI.approveStage(split.state, split.store,
            result.stageId, 'Testfreigabe nur für synthetische Beispiele', true);
        state = accepted.state;
        store = accepted.store;
    }
    const profile = state.damageProfiles.find(p => p.buildingGroupId === groupId);
    if (profile.gameBuildingType !== 108)
        throw new Error('Synthetic game building ID was not included in the approval state.');
    const clean = I.validate(state, store);
    const archive = await DI.exportPackage(clean, store);
    if (archive.manifest.runtimeHookInstalled !== false)
        throw new Error('Export must never claim an installed runtime hook.');
    fs.writeFileSync(output, Buffer.from(archive.bytes), {flag: 'wx'});
    console.log(JSON.stringify({
        fixture: output, gameBuildingType: 108,
        verifiedInGame: false,
        buildings: archive.manifest.buildings.length,
        stages: archive.manifest.buildings[0].stages.length,
        files: (await K.unzip(archive.bytes)).length
    }));
}
produce().catch(error => {
    console.error(error);
    process.exitCode = 2;
});
