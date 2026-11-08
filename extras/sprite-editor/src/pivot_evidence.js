/* Legacy Zinnenlineal measurements inside the shared SpriteSuite canvas.
 * Pure data adapter: no filesystem, installed-game calls or atlas patches. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ?
        require('./core.js') : root.SpriteCore;
    const api = factory(C);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpritePivotEvidence = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
    'use strict';
    const SCHEMA = 'zinnenlineal.versatz.v1';
    const NAME = /^([A-Za-z][A-Za-z0-9_]{0,90})[ -]([0-9]{1,7})(x?)$/;
    const EPSILON = 2e-5;
    const LIMIT = 4096;
    const fail = detail => C.fail('Zinnenlineal: ' + detail);
    const finite = (value, label, max = 4) => {
        if (typeof value !== 'number' || !Number.isFinite(value) ||
                Math.abs(value) > max) fail(label + ': ungültige Zahl.');
        return value;
    };
    const integer = (value, label, min, max) => {
        if (typeof value !== 'number' || !Number.isSafeInteger(value) ||
                value < min || value > max) fail(label + ': ungültige Ganzzahl.');
        return value;
    };
    const near = (a, b) => Math.abs(a - b) <= EPSILON;

    function parseMeasurements(jsonText) {
        if (typeof jsonText !== 'string' || jsonText.length > 2 * 1024 * 1024)
            fail('Messdatei ist zu groß.');
        const raw = C.json(jsonText);
        if (!raw || Array.isArray(raw) || raw.schema !== SCHEMA ||
                !Array.isArray(raw.frames) || raw.frames.length > LIMIT)
            fail('Unbekanntes Messformat oder zu viele Einträge.');
        const names = new Set();
        return raw.frames.map((entry, index) => {
            if (!entry || Array.isArray(entry) || typeof entry !== 'object')
                fail('Eintrag ' + index + ' ist kein Objekt.');
            const match = typeof entry.name === 'string' ?
                NAME.exec(entry.name) : null;
            if (!match || entry.gruppe !== match[1])
                fail('Gruppen- oder Spritename ungültig.');
            const number = integer(entry.nummer, 'nummer', 0, 1000000);
            if (Number(match[2]) !== number) fail('Nummer widerspricht Dateinamen.');
            if (names.has(entry.name)) fail('Doppelter Frame: ' + entry.name);
            names.add(entry.name);
            const width = integer(entry.breite, 'breite', 1, 8192);
            const height = integer(entry.hoehe, 'hoehe', 1, 8192);
            const right = integer(entry.rechts, 'rechts', -4096, 4096);
            const up = integer(entry.hoch, 'hoch', -4096, 4096);
            const oldX = finite(entry.pivot_x, 'pivot_x');
            const oldY = finite(entry.pivot_y, 'pivot_y');
            const newX = finite(entry.neu_pivot_x, 'neu_pivot_x');
            const newY = finite(entry.neu_pivot_y, 'neu_pivot_y');
            if (!near(newX, oldX - right / width) ||
                    !near(newY, oldY - up / height))
                fail(entry.name + ': Korrektur widerspricht dem Messversatz.');
            if (Object.hasOwn(entry, 'pixel_je_einheit') &&
                    finite(entry.pixel_je_einheit, 'pixel_je_einheit', 2048) <= 0)
                fail('Pixel pro Einheit müssen positiv sein.');
            return Object.freeze({ name: entry.name, group: match[1], number,
                width, height, right, up,
                oldPivot: Object.freeze({ x: oldX, y: oldY }),
                newPivot: Object.freeze({ x: newX, y: newY }) });
        });
    }

    function review(row, frames, store) {
        const matches = frames.filter(frame => frame.group === row.group &&
            frame.index === row.number);
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
    return Object.freeze({ SCHEMA, EPSILON, parseMeasurements, review, reviewAll });
});
