/** Synthetic capacity fixture. Rebuilt from the documented editor data model. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const C = require('../src/core.js');
const I = require('../src/io.js');
(async () => {
    const state = I.blank(), store = new I.AssetStore();
    const group = { id: 'capacity', name: 'body_capacity', source: 'custom', settings: C.scene({ a: 64, b: 64, width: 4, height: 2, category: 'unit' }) };
    state.scenes.push(group);
    const key = store.add(C.image(1, 1, new Uint8Array([103, 109, 117, 255])));
    for (let index = 0; index < 4096; index++) {
        const frame = I.makeFrame(`body_capacity-${index}.png`, key, group.id, store);
        frame.slot = index;
        state.frames.push(frame);
    }
    fs.writeFileSync(path.join(__dirname, 'fixtures', 'capacity.shsprite'), await I.writeProject(state, store));
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
