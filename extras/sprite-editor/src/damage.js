/* Building damage domain: pure, offline, backwards-compatible with SHSPRITE schema 2. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ? require('./core.js') : root.SpriteCore;
    const api = factory(C);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpriteDamage = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C) {
    'use strict';
    const KINDS = Object.freeze(['mechanical', 'fire']);
    const MODELS = Object.freeze(['gpt-image-2.6-sunburst', 'gpt-image-2.6-flare']);
    const fail = message => { throw new Error(message); };
    const ident = (value, label) => {
        if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(value))
            fail(label + ': ungültige ID.');
        return value;
    };
    const limited = (value, label, length) => {
        if (typeof value !== 'string' || value.length > length || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value))
            fail(label + ': ungültiger Text.');
        return value;
    };
    function stageScenes(profiles = []) {
        return new Set(profiles.flatMap(profile => profile.stages.map(stage => stage.sceneId)));
    }
    function validate(profiles = [], scenes = [], store = null) {
        if (!Array.isArray(profiles) || profiles.length > 128)
            fail('Höchstens 128 Gebäude-Schadensprofile erlaubt.');
        const sceneById = new Map(scenes.map(g => [g.id, g]));
        const seenBuildings = new Set(), usedScenes = new Set(), usedStages = new Set(), gameTypes = new Set();
        const clean = profiles.map(profile => {
            const buildingGroupId = ident(profile.buildingGroupId, 'Gebäudegruppe');
            const base = sceneById.get(buildingGroupId);
            if (!base || base.settings.category !== 'building')
                fail('Gebäudeschäden benötigen eine bestehende Gebäudegruppe.');
            if (seenBuildings.has(buildingGroupId))
                fail('Doppelte Gebäudeschadensgruppe.');
            seenBuildings.add(buildingGroupId);
            const gameBuildingType = profile.gameBuildingType === null || profile.gameBuildingType === undefined ?
                null : C.integer(profile.gameBuildingType, 'Gebäudetyp im Spiel', 0, 4095);
            if (gameBuildingType !== null && gameTypes.has(gameBuildingType))
                fail('Spiel-Gebäudetyp ist mehreren Gebäuden zugewiesen.');
            if (gameBuildingType !== null) gameTypes.add(gameBuildingType);
            if (!Array.isArray(profile.stages) || profile.stages.length > 32)
                fail('Höchstens 32 Schadensmodelle pro Gebäude.');
            const thresholds = new Set();
            return {
                buildingGroupId, gameBuildingType,
                stages: profile.stages.map(stage => {
                    const id = ident(stage.id, 'Schadensstufe'), sceneId = ident(stage.sceneId, 'Stufen-Szene');
                    if (usedStages.has(id)) fail('Doppelte Schadensstufen-ID.');
                    usedStages.add(id);
                    if (!KINDS.includes(stage.kind)) fail('Unbekannte Schadensart.');
                    const hpAtOrBelow = C.integer(stage.hpAtOrBelow, 'HP-Schwelle', 0, 99);
                    const key = stage.kind + ':' + hpAtOrBelow;
                    if (thresholds.has(key)) fail('Schadensart und HP-Schwelle sind doppelt.');
                    thresholds.add(key);
                    const scene = sceneById.get(sceneId);
                    if (!scene || scene.settings.category !== 'building' || sceneId === buildingGroupId)
                        fail('Schadensstufe benötigt eine eigene vorhandene Gebäudegruppe.');
                    if (usedScenes.has(sceneId)) fail('Schadensstufen dürfen keine Szene teilen.');
                    usedScenes.add(sceneId);
                    for (const prop of ['a', 'b', 'width', 'height', 'anchor', 'order'])
                        if (scene.settings[prop] !== base.settings[prop])
                            fail('Schadensmodell und Original haben unterschiedliche Raster-/Ankereinstellungen: ' + prop);
                    const candidateId = stage.candidateId === null || stage.candidateId === undefined ? null : ident(stage.candidateId, 'Kandidatenbild');
                    if (candidateId && store && !store.has(candidateId))
                        fail('Kandidatenbild fehlt.');
                    const requestedStatus = stage.status ?? 'draft';
                    if (!['draft', 'approved', 'rejected'].includes(requestedStatus))
                        fail('Unbekannter Freigabestatus.');
                    const suppliedDigest = stage.approvalDigest ?? null;
                    if (suppliedDigest !== null && (typeof suppliedDigest !== 'string' || !/^[a-f0-9]{64}$/.test(suppliedDigest)))
                        fail('Ungültige Zustandsprüfsumme der Schadensfreigabe.');
                    // Legacy approvals predate content binding. Never silently export them as reviewed.
                    const status = requestedStatus === 'approved' && !suppliedDigest ? 'draft' : requestedStatus;
                    const approvalDigest = status === 'approved' ? suppliedDigest : null;
                    const model = stage.model ?? MODELS[0];
                    if (!MODELS.includes(model)) fail('Unbekanntes GPT-Image-Modell.');
                    return {
                        id, sceneId, kind: stage.kind, hpAtOrBelow,
                        label: limited(stage.label ?? '', 'Stufenname', 120),
                        changeRequest: limited(stage.changeRequest ?? '', 'Nachbesserung', 2000),
                        reviewNotes: limited(stage.reviewNotes ?? '', 'Abnahmevermerk', 2000),
                        model, candidateId, status, approvalDigest
                    };
                }).sort((a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || b.hpAtOrBelow - a.hpAtOrBelow)
            };
        });
        for (const profile of clean)
            if (usedScenes.has(profile.buildingGroupId))
                fail('Die Originalgruppe eines Gebäudes ist als Schadensmodell vergeben.');
        return clean;
    }
    function choose(profile, kind, hpPercent) {
        if (!KINDS.includes(kind)) fail('Unbekannte Schadensart.');
        const hp = C.number(hpPercent, 'HP in Prozent', 0, 100);
        if (!profile) return null;
        const kindStages = profile.stages.filter(s => s.kind === kind);
        const stages = kind === 'fire' && !kindStages.length
            ? profile.stages.filter(s => s.kind === 'mechanical')
            : kindStages;
        let found = null;
        for (const stage of stages)
            if (hp <= stage.hpAtOrBelow && (!found || stage.hpAtOrBelow < found.hpAtOrBelow))
                found = stage;
        return found;
    }
    function chooseHP(profile, kind, current, maximum) {
        const hp = C.number(current, 'Aktuelle HP', 0);
        const max = C.number(maximum, 'Maximale HP', 0.0000001);
        if (hp > max) fail('Aktuelle HP dürfen Maximum nicht übersteigen.');
        return choose(profile, kind, hp * 100 / max);
    }
    function buildPrompt(original, stage, group, previous = null, registration = null) {
        const kind = stage.kind === 'fire' ? 'FIRE damage: soot, scorched beams, burned roofing and realistic flame-related collapse.' :
            'MECHANICAL damage: breaches, broken masonry, debris, impact damage and physically plausible structural failure.';
        const severity = stage.hpAtOrBelow <= 15 ? 'nearly destroyed, with major collapse while preserving the identity of the footprint' :
            stage.hpAtOrBelow <= 45 ? 'heavily damaged, with clearly missing structural sections' :
            stage.hpAtOrBelow <= 75 ? 'partially damaged, visibly worse than intact but still structurally recognizable' :
            'lightly damaged and unmistakably different from the intact building';
        return [
            'EDIT THE ATTACHED ORIGINAL REFERENCE, do not invent a new building.',
            'This is a Stronghold Crusader Definitive Edition mod sprite. Preserve the original asset\'s exact isometric camera angle, geometry, footprint, material palette, lighting direction, pixel-art texture, architectural identity, perspective and roof/wall orientation.',
            'Damage type: ' + kind,
            'At or below ' + stage.hpAtOrBelow + '% remaining HP the state must read as ' + severity + '.',
            previous ? 'An additional previous damage-state reference is attached. The new state must show monotonically more damage, NEVER a repaired or structurally restored part. Preserve all unchanged elements exactly.' :
                'Start from the intact original and change only what the indicated damage state requires.',
            'KEEP the FIRST reference image canvas size, object position, bottom-ground anchor, transparent alpha background and alignment exactly. Do not crop, resize, rotate, zoom, shift, add a background, ground plane, camera effects, text, labels, UI, watermark, figures or unrelated decorations.',
            'All transparent exterior pixels must remain transparent (straight alpha PNG). No black opaque seams, halos or stray isolated black pixels. Preserve crisp silhouette and non-damaged source pixels as faithfully as possible.',
            'The result will be split back into <=64-pixel-width tiles with a 1-pixel-safe overlap. Avoid disjoint fragments beyond the original tile footprint. Never fabricate hidden parts of the original asset.',
            'Building group: ' + group.name + '. Stage: ' + (stage.label || stage.kind + ' ' + stage.hpAtOrBelow + '%') + '.',
            original ? (registration ? 'True original art dimensions: ' + original.width + 'x' + original.height + ' pixels. The provided model template is ' + registration.width + 'x' + registration.height + ' pixels and will be inverse-scaled after output; the model output MUST match the first registered reference canvas.' :
                'Original dimensions: ' + original.width + 'x' + original.height + ' pixels. Exact matching dimensions are a mandatory import check.') : '',
            stage.changeRequest ? 'SPECIFIC REVISION REQUEST: ' + stage.changeRequest : '',
            'Return only an RGBA PNG image of the edited building; no explanations or multiple panels.'
        ].filter(Boolean).join('\n');
    }
    function checkCandidate(original, candidate) {
        const errors = [], warnings = [], stats = {};
        if (!candidate || !original) return { errors: ['Original und Kandidatenbild erforderlich.'], warnings, stats };
        if (candidate.width !== original.width || candidate.height !== original.height)
            errors.push('Die Canvasgröße muss unverändert ' + original.width + ' × ' + original.height + ' px sein.');
        if (candidate.width * candidate.height > C.LIMITS.pixels)
            errors.push('Kandidatenbild überschreitet das Bildbudget.');
        const a = C.alphaBounds(original), b = C.alphaBounds(candidate);
        stats.original = { visible: a.opaque + a.partial, bounds: [a.left, a.top, a.right, a.bottom] };
        stats.candidate = { visible: b.opaque + b.partial, bounds: [b.left, b.top, b.right, b.bottom] };
        if (b.empty) errors.push('Kandidatenbild ist vollständig transparent.');
        if (a.empty) errors.push('Original besitzt keine sichtbaren Pixel.');
        if (!a.empty && !b.empty && Math.abs(a.bottom - b.bottom) > 2)
            errors.push('Bodenanker verschoben: Unterkante weicht um mehr als zwei Pixel ab.');
        if (candidate.width === original.width && candidate.height === original.height) {
            let intersection = 0, orig = 0, opaqueOutside = 0, changed = 0, partial = 0;
            for (let i = 0; i < original.data.length; i += 4) {
                const sa = original.data[i + 3], ca = candidate.data[i + 3];
                if (sa > 0) orig++;
                if (sa > 0 && ca > 0) intersection++;
                if (sa === 0 && ca === 255) opaqueOutside++;
                if (ca > 0 && ca < 255) partial++;
                if (sa !== ca || (sa && ca && (original.data[i] !== candidate.data[i] ||
                    original.data[i + 1] !== candidate.data[i + 1] || original.data[i + 2] !== candidate.data[i + 2])))
                    changed++;
            }
            stats.intersectionFraction = orig ? intersection / orig : 0;
            stats.changedPixels = changed;
            stats.newOpaqueOutside = opaqueOutside;
            stats.partialAlpha = partial;
            if (orig && intersection / orig < .3)
                warnings.push('Weniger als 30 % der Originalsilhouette überlappt – Ausrichtung manuell prüfen.');
            if (opaqueOutside > Math.max(10, Math.floor(orig * .25)))
                warnings.push('Viele neue voll deckende Pixel außerhalb der Originalsilhouette – Hintergrund/Bruchstücke prüfen.');
            if (!changed) warnings.push('Kandidatenbild ist identisch mit dem Original.');
            if (partial) warnings.push('Teiltransparente Pixel: Überlappung darf Alpha nicht doppelt zeichnen.');
        }
        return { errors, warnings, stats };
    }
    function invalidateApprovals(before, after) {
        const oldScenes = new Map(before.scenes.map(g => [g.id, g.settings]));
        const oldFrames = new Map(before.frames.map(f => [f.id, f]));
        const oldStages = new Map((before.damageProfiles || []).flatMap(p => p.stages.map(s => [s.id, s])));
        const oldProfiles = new Map((before.damageProfiles || []).map(p => [p.buildingGroupId, p]));
        for (const profile of after.damageProfiles || [])
            for (const stage of profile.stages) {
                const old = oldStages.get(stage.id);
                if (!old || old.status !== 'approved' || stage.status !== 'approved')
                    continue;
                const changed = old.hpAtOrBelow !== stage.hpAtOrBelow ||
                    old.kind !== stage.kind ||
                    old.model !== stage.model ||
                    old.changeRequest !== stage.changeRequest ||
                    old.candidateId !== stage.candidateId ||
                    (oldProfiles.get(profile.buildingGroupId)?.gameBuildingType ?? null) !== (profile.gameBuildingType ?? null) ||
                    JSON.stringify(oldScenes.get(profile.buildingGroupId)) !== JSON.stringify(after.scenes.find(g => g.id === profile.buildingGroupId)?.settings) ||
                    JSON.stringify(before.frames.filter(f => f.groupId === profile.buildingGroupId)) !==
                        JSON.stringify(after.frames.filter(f => f.groupId === profile.buildingGroupId)) ||
                    JSON.stringify(oldScenes.get(stage.sceneId)) !== JSON.stringify(after.scenes.find(g => g.id === stage.sceneId)?.settings) ||
                    JSON.stringify(before.frames.filter(f => f.groupId === stage.sceneId)) !==
                        JSON.stringify(after.frames.filter(f => f.groupId === stage.sceneId)) ||
                    after.frames.some(f => f.groupId === stage.sceneId && !oldFrames.has(f.id));
                if (changed) {
                    stage.status = 'draft';
                    stage.approvalDigest = null;
                }
            }
        return after;
    }
    return { KINDS, MODELS, validate, stageScenes, choose, chooseHP, buildPrompt, checkCandidate, invalidateApprovals };
});
