/* Read-only adapter for the actual in-game Zinnenlineal displacement file.
 * No game or source image changes. The old tool may remain installed, but its
 * measurements can now be reviewed in the common geometry inspector. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ? require('./core.js') : root.SpriteCore;
    const api = factory(C);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpriteLegacyMeasurements = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
    'use strict';
    const SCHEMA = 'zinnenlineal.versatz.v1';
    const MAX_BYTES = 2 * 1024 * 1024, MAX_RECORDS = 4096, EPSILON = 2e-5;
    const NAME = /^([A-Za-z][A-Za-z0-9_]{0,90})[ -]([0-9]{1,7})(x?)$/;
    function fail(reason) { throw new Error('Zinnenlineal-Import: ' + reason); }
    function integer(value, key, min, max) {
        if (typeof value !== 'number' || !Number.isInteger(value) ||
                value < min || value > max) fail(key + ' ist keine zulässige Ganzzahl.');
        return value;
    }
    function finite(value, key, max = 100) {
        if (typeof value !== 'number' || !Number.isFinite(value) ||
                Math.abs(value) > max) fail(key + ' ist keine zulässige Zahl.');
        return value;
    }
    function parseDocument(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
                raw.schema !== SCHEMA || !Array.isArray(raw.frames) ||
                raw.frames.length > MAX_RECORDS)
            fail('Unbekanntes Format oder mehr als 4096 Einträge.');
        const seen = new Set();
        const rows = raw.frames.map((entry, index) => {
            if (!entry || typeof entry !== 'object' || Array.isArray(entry))
                fail('Eintrag ' + (index + 1) + ' ist kein Objekt.');
            const match = typeof entry.name === 'string' ? NAME.exec(entry.name) : null;
            if (!match || entry.gruppe !== match[1])
                fail('Sprite-Name und Gruppe stimmen nicht überein.');
            const number = integer(entry.nummer, 'nummer', 0, 1000000);
            if (Number(match[2]) !== number) fail('Sprite-Nummer stimmt nicht überein.');
            if (seen.has(entry.name)) fail('Doppelter Frame/Sprite-Eintrag: ' + entry.name);
            seen.add(entry.name);
            const width = integer(entry.breite, 'breite', 1, 8192);
            const height = integer(entry.hoehe, 'hoehe', 1, 8192);
            const right = integer(entry.rechts, 'rechts', -4096, 4096);
            const up = integer(entry.hoch, 'hoch', -4096, 4096);
            const original = { x: finite(entry.pivot_x, 'pivot_x', 4),
                y: finite(entry.pivot_y, 'pivot_y', 4) };
            const candidate = { x: finite(entry.neu_pivot_x, 'neu_pivot_x', 4),
                y: finite(entry.neu_pivot_y, 'neu_pivot_y', 4) };
            if (Math.abs(candidate.x - (original.x - right / width)) > EPSILON ||
                    Math.abs(candidate.y - (original.y - up / height)) > EPSILON)
                fail('Kandidat widerspricht gemessenem Versatz: ' + entry.name);
            if (Object.prototype.hasOwnProperty.call(entry, 'pixel_je_einheit') &&
                    finite(entry.pixel_je_einheit, 'pixel_je_einheit', 2048) <= 0)
                fail('Pixel pro Einheit müssen positiv sein.');
            return Object.freeze({ name: entry.name, group: entry.gruppe, number,
                width, height, right, up,
                original: Object.freeze(original), candidate: Object.freeze(candidate) });
        });
        return Object.freeze({ schema: SCHEMA, rows: Object.freeze(rows) });
    }
    function forFrame(parsed, frame, img) {
        if (!parsed || parsed.schema !== SCHEMA || !Array.isArray(parsed.rows) ||
                !frame || !img) fail('Unvollständiger Mess-/Frame-Kontext.');
        // Sprite Editor stores .png and may use '-' where old Unity wrote ' '.
        // Match by verified group/index/alt suffix; conflicting historical
        // aliases are ambiguous and must never silently select one proposal.
        const stem = typeof frame.name === 'string' ? frame.name.replace(/\.png$/i, '') : '';
        const parts = NAME.exec(stem);
        const matches = parsed.rows.filter(r => r.name === stem || (parts &&
            r.group === parts[1] && r.number === Number(parts[2]) &&
            r.name.endsWith('x') === !!parts[3]));
        if (matches.length !== 1)
            return { status: matches.length ? 'ambiguous' : 'missing', row: null, measure: null };
        const row = matches[0];
        if (row.width !== img.width || row.height !== img.height)
            return { status: 'size_mismatch', row, measure: null };
        const actual = frame.pivot || {};
        const same = target => ['x', 'y'].every(key =>
            typeof actual[key] === 'number' && Number.isFinite(actual[key]) &&
            Math.abs(actual[key] - target[key]) <= EPSILON);
        const status = same(row.candidate) ? 'already_applied' :
            same(row.original) ? 'review' : 'different_reference';
        // Browser Y increases DOWN; Unity/Zinnenlineal "hoch" increases UP.
        // This is a review line, never an implicit new pivot or sprite move.
        const start = { x: Math.max(0, -row.right), y: Math.max(0, row.up) };
        const end = { x: start.x + row.right, y: start.y - row.up };
        const inside = [start, end].every(p =>
            p.x >= 0 && p.y >= 0 && p.x <= img.width && p.y <= img.height);
        return { status, row, measure: C.measurePoints(start, end),
            mayVisualize: inside };
    }
    return Object.freeze({ SCHEMA, MAX_BYTES, MAX_RECORDS, EPSILON, parseDocument, forFrame });
});
