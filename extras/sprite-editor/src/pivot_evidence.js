/* Legacy Zinnenlineal measurements inside the shared SpriteSuite canvas.
 * Pure data adapter: no filesystem, installed-game calls or atlas patches. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ?
        require('./core.js') : root.SpriteCore;
    const L = typeof module === 'object' && module.exports ?
        require('./legacy_measurements.js') : root.SpriteLegacyMeasurements;
    const api = factory(C, L);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpritePivotEvidence = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C, L) {
    'use strict';
    const SCHEMA = 'zinnenlineal.versatz.v1';
    const EPSILON = L.EPSILON;
    const near = (a, b) => Math.abs(a - b) <= EPSILON;
    function parseMeasurements(jsonText) {
        if (typeof jsonText !== 'string' || jsonText.length > L.MAX_BYTES)
            C.fail('Zinnenlineal: Messdatei ist zu groß.');
        return L.parseDocument(C.json(jsonText)).rows.map(row => Object.freeze({
            name: row.name, group: row.group, number: row.number,
            width: row.width, height: row.height, right: row.right, up: row.up,
            oldPivot: row.original, newPivot: row.candidate
        }));
    }
    function matchesFrame(row, frame) {
        const name = /^([A-Za-z][A-Za-z0-9_]{0,90})[ -]([0-9]{1,7})(x?)$/;
        const measured = name.exec(row.name);
        const current = name.exec(String(frame.name).replace(/\.png$/i, ''));
        const parsedName = C.parseName(frame.name);
        const metadataMatches = frame.group === row.group && frame.index === row.number ||
            frame.index === null && parsedName.index === null && frame.group === parsedName.group;
        return !!(metadataMatches && measured && current && measured[1] === current[1] &&
            Number(measured[2]) === Number(current[2]) && measured[3] === current[3]);
    }

    function review(row, frames, store) {
        const matches = frames.filter(frame => matchesFrame(row, frame));
        if (!matches.length)
            return { row, status: 'not_found', frameId: null, reason:
                'Kein exakt passender Gruppen-/Frame-Index im aktuellen Projekt.' };
        if (matches.length !== 1)
            return { row, status: 'ambiguous', frameId: null, reason:
                'Mehrere Frames mit demselben Namen/Index: nicht automatisch zuordnen.' };
        const frame = matches[0], image = store.get(frame.imageId);
        const result = { row, frameId: frame.id, frameName: frame.name,
            imageId: frame.imageId, currentPivot: { ...frame.pivot },
            status: 'blocked', reason: '' };
        if (image.width !== row.width || image.height !== row.height) {
            result.status = 'dimension_mismatch';
            result.reason = 'Maße aus der Messdatei stimmen nicht mit dem PNG überein.';
        }
        else if (frame.locked) {
            result.status = 'locked';
            result.reason = 'Gesperrtes Sprite nicht automatisch korrigieren.';
        }
        else if (row.newPivot.x < 0 || row.newPivot.x > 1 ||
                row.newPivot.y < 0 || row.newPivot.y > 1) {
            result.status = 'out_of_bounds';
            result.reason = 'Vorgeschlagener Pivot liegt außerhalb des normierten Bereichs.';
        }
        else if (near(frame.pivot.x, row.newPivot.x) &&
                 near(frame.pivot.y, row.newPivot.y)) {
            result.status = 'already';
            result.reason = 'Aktueller Pivot entspricht bereits der Messkorrektur.';
        }
        else if (near(frame.pivot.x, row.oldPivot.x) &&
                 near(frame.pivot.y, row.oldPivot.y)) {
            result.status = 'review';
            result.reason = 'Messvorschlag ist geometrisch passend; visuelle Prüfung erforderlich.';
        }
        else {
            result.status = 'pivot_mismatch';
            result.reason = 'Aktueller Pivot stimmt weder mit Ausgangs- noch Zielwert überein.';
        }
        // This does not attest the measured asset's provenance or current game build.
        result.approvedForGame = false;
        return result;
    }
    function reviewAll(rows, state, store) {
        return rows.map(row => review(row, state.frames, store));
    }
    return Object.freeze({ SCHEMA, EPSILON, parseMeasurements, matchesFrame, review, reviewAll });
});
