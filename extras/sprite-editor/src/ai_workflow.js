/* Pure, offline SpriteSuite AI request, comparison and review contracts.
   Reference bundles and candidate receipts are shared by offline and local Codex flows. */
(function (root, factory) {
    'use strict';
    const C = typeof module === 'object' && module.exports ? require('./core.js') : root.SpriteCore;
    const K = typeof module === 'object' && module.exports ? require('./codec.js') : root.SpriteCodec;
    const api = factory(C, K);
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpriteAI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C, K) {
    'use strict';
    const MODELS = Object.freeze(['gpt-image-2.6-flare', 'gpt-image-2.6-sunburst']);
    const ASSET_CLASSES = Object.freeze(['building', 'unit', 'animation', 'texture', 'vegetation', 'hud', 'ui', 'other']);
    const CLASS_PROMPTS = Object.freeze({
        building: 'Maintain the isometric game camera, building silhouette, ground contact, recognizable construction and tiered tiles.',
        unit: 'Preserve the complete subject pose, direction, frame registration and character size used in the game.',
        animation: 'Preserve the frame pose, direction, ground anchor and character size. Generate one directional frame, never a contact sheet.',
        texture: 'Preserve material scale, texture bounds, tile alignment and readable original pixel structure.',
        vegetation: 'Maintain tree or vegetation ground anchor, scale, silhouette and correct alpha fringe.',
        hud: 'Preserve interface shape, alignment, pixel margins, state-specific contrast and icon legibility.',
        ui: 'Preserve icon bounds, pixel alignment, readability and independent transparent edges.',
        other: 'Preserve the source composition, perspective and registration.'
    });
    const fail = message => { throw new Error(message); };
    const readable = (value, label, min = 0, max = 4000) => {
        if (typeof value !== 'string' || value.trim().length < min ||
                value.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value))
            fail(label + ': ungültiger Text.');
        return value.trim();
    };
    function options(raw = {}) {
        const assetClass = raw.assetClass ?? 'other', model = raw.model ?? MODELS[0];
        if (!ASSET_CLASSES.includes(assetClass)) fail('Unbekannter Assettyp.');
        if (!MODELS.includes(model)) fail('Nicht freigegebenes Bildmodell.');
        const variants = C.integer(raw.variants ?? 1, 'Varianten', 1, 4);
        return { assetClass, model, variants,
            goal: readable(raw.goal, 'Gestaltungsziel', 8, 4000),
            restrictions: readable(raw.restrictions ?? '', 'Erhaltungsregeln', 0, 1600) };
    }
    function canvasPlan(img) {
        const plan = C.modelRegistrationPlan(img);
        if (!plan) fail('Sprite zu groß für verlustfreie KI-Registrierung; erst Arbeitskopie vorbereiten.');
        return plan;
    }
    const registeredImage = C.modelRegisteredImage;
    function prompt(img, plan, settings) {
        const r = 'x=' + plan.left + '..' + (plan.left + img.width * plan.scale) +
            ', y=' + plan.top + '..' + (plan.top + img.height * plan.scale);
        return [
            'Edit the provided original pixel sprite, not a new unrelated composition.',
            CLASS_PROMPTS[settings.assetClass],
            'User goal: ' + settings.goal,
            settings.restrictions ? 'Additional constraints: ' + settings.restrictions : '',
            'Output exactly ' + plan.width + 'x' + plan.height + ' PNG with transparency.',
            'The nearest-neighbour enlarged original occupies rectangle ' + r + '.',
            'Keep all edited art strictly within this source rectangle; transparent outside it.',
            'Do not move, rotate, re-center, crop, extend canvas or alter the ground baseline.',
            'Keep the sprite aligned so the image can be inverse-scaled by factor ' +
                plan.scale + ' and reviewed on its original ' + img.width + 'x' + img.height + ' grid.',
            'Keep hard silhouette edges, readable pixel art, and straight, non-premultiplied alpha.',
            'Do not add captions, watermarks, contact sheets or multiple variants in one PNG.',
            'Create exactly one candidate per request; each variant is a separate independent output.',
            'A human must compare against the source and explicitly approve before export to the game.'
        ].filter(Boolean).join('\n');
    }
    async function makeRequestBundle(img, originalPNG, raw = {}) {
        const settings = options(raw);
        const plan = canvasPlan(img);
        const original = originalPNG instanceof Uint8Array ? originalPNG : new Uint8Array(originalPNG);
        const header = K.pngHeader(original);
        if (header.width !== img.width || header.height !== img.height)
            fail('PNG-Quellabmessungen passen nicht zur Arbeitskopie.');
        const registered = await K.encodePNG(registeredImage(img, plan));
        const request = {
            format: 'sprite-suite.ai-image-edit', version: 1, provider: 'codex-chatgpt',
            assetClass: settings.assetClass, goal: settings.goal,
            restrictions: settings.restrictions, model: settings.model,
            variants: settings.variants, quality: 'high', complexity: 'high',
            background: 'transparent', output_format: 'png',
            size: plan.width + 'x' + plan.height,
            referenceWidth: img.width, referenceHeight: img.height,
            referenceSHA256: await K.sha256(original),
            modelReferenceSHA256: await K.sha256(registered),
            registration: plan, referenceFiles: ['model_reference.png'],
            prompt: prompt(img, plan, settings),
            requiresManualApproval: true, automaticInstallation: false
        };
        const guide = [
            'SpriteSuite KI-Werkstatt – Kandidatenauftrag',
            'Erst validieren (kostenfrei): python tools/suite_ai_codex.py --bundle request.zip --output neuer_ordner --dry-run',
            'Generierung nach ChatGPT-Anmeldung: python tools/suite_ai_codex.py --bundle request.zip --output neuer_ordner --execute',
            'Die lokale Codex-Sitzung verwendet das angemeldete ChatGPT-Konto und dessen aktuelle Limits.',
            'PNG-Kandidaten im Sprite Editor unter KI-Werkstatt importieren.',
            'Abmessung, Alpha, Geometrie und Originaltreue visuell pruefen; danach manuell uebernehmen.',
            'Keine automatische Mod-Installation oder Ingame-Freigabe.',
        ].join('\n');
        const requestBytes = K.encodeText(JSON.stringify(request, null, 2));
        const requestSHA256 = await K.sha256(requestBytes);
        return { request, requestSHA256, bytes: K.zip([
            { name: 'reference.png', data: original },
            { name: 'model_reference.png', data: registered },
            { name: 'request.json', data: requestBytes },
            { name: 'WORKFLOW.txt', data: guide }
        ]) };
    }
    /** Generator metadata is a self-declared, hash-checked receipt,
     * not a cryptographic signature from the image provider. */
    function verifyCandidateMetadata(raw, sourceSHA256, candidateSHA256, plannedSHA256 = null) {
        if (!raw || Array.isArray(raw) || typeof raw !== 'object' ||
                raw.format !== 'sprite-suite.ai-candidate' || raw.version !== 1)
            fail('Unbekanntes KI-Kandidatenmanifest.');
        const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
        if (!digest(sourceSHA256) || !digest(candidateSHA256) ||
                !digest(raw.requestSHA256) ||
                raw.referenceSHA256 !== sourceSHA256 ||
                raw.candidateSHA256 !== candidateSHA256)
            fail('Kandidat oder Quellbild passt nicht zum KI-Nachweis (SHA-256).');
        if (!MODELS.includes(raw.model) || !ASSET_CLASSES.includes(raw.assetClass) ||
                !Number.isSafeInteger(raw.variant) || raw.variant < 1 || raw.variant > 4 ||
                raw.needsManualReview !== true ||
                raw.inGameTested !== false || raw.originalGameModified !== false)
            fail('KI-Manifest enthält unzulässige Angaben.');
        if (!raw.registration || raw.registration.registered !== true ||
                raw.registration.candidateWritten !== true)
            fail('Kandidat hat keine gültige Rückregistrierung.');
        if (plannedSHA256 && raw.requestSHA256 !== plannedSHA256)
            fail('Kandidat gehört zu einem anderen KI-Auftrag.');
        return { sourceMatched: true, requestMatched: !!plannedSHA256,
            apiOriginVerified: false, modelClaim: raw.model,
            assetClass: raw.assetClass, variant: raw.variant,
            requestSHA256: raw.requestSHA256 };
    }
    /** Deterministic pixel-risk metrics; NEVER a game-compatibility or copyright score. */
    function visualRisk(original, candidate) {
        C.dimensions(original.width, original.height);
        C.dimensions(candidate.width, candidate.height);
        if (original.width !== candidate.width || original.height !== candidate.height)
            fail('Qualitätsvergleich benötigt identische Sprite-Abmessungen.');
        const a = original.data, b = candidate.data, width = original.width;
        let changedPixels = 0, changedAlpha = 0, added = 0, removed = 0;
        let hiddenRGBChanges = 0, sourceVisible = 0, targetVisible = 0;
        let sourceBaseline = -1, candidateBaseline = -1, sourcePartial = 0, targetPartial = 0;
        let sourceX = 0, sourceY = 0, targetX = 0, targetY = 0;
        for (let index = 0; index < a.length; index += 4) {
            const ordinal = index / 4, x = ordinal % width, y = Math.floor(ordinal / width);
            const oa = a[index + 3], ca = b[index + 3];
            const rgbChanged = a[index] !== b[index] ||
                a[index + 1] !== b[index + 1] || a[index + 2] !== b[index + 2];
            if (oa !== ca) changedAlpha++;
            if (rgbChanged || oa !== ca) changedPixels++;
            if (!oa && ca) added++;
            if (oa && !ca) removed++;
            if (!oa && !ca && rgbChanged) hiddenRGBChanges++;
            if (oa) {
                sourceVisible++;
                sourceX += x; sourceY += y;
                sourceBaseline = Math.max(sourceBaseline, y);
            }
            if (ca) {
                targetVisible++;
                targetX += x; targetY += y;
                candidateBaseline = Math.max(candidateBaseline, y);
            }
            if (oa > 0 && oa < 255) sourcePartial++;
            if (ca > 0 && ca < 255) targetPartial++;
        }
        const groundShift = sourceBaseline < 0 || candidateBaseline < 0 ?
            null : candidateBaseline - sourceBaseline;
        const centroidShift = !sourceVisible || !targetVisible ? null : {
            dx: (targetX / targetVisible) - (sourceX / sourceVisible),
            dy: (targetY / targetVisible) - (sourceY / sourceVisible)
        };
        const originalPixels = Math.max(sourceVisible, 1);
        const points = Math.min(100, Math.round(
            16 * Math.min(1, changedAlpha / originalPixels) +
            24 * Math.min(1, added / originalPixels) +
            24 * Math.min(1, removed / originalPixels) +
            12 * Math.min(1, hiddenRGBChanges / originalPixels) +
            14 * Math.min(1, Math.abs(groundShift ?? 0) / 4) +
            10 * Math.min(1, Math.hypot(centroidShift?.dx || 0, centroidShift?.dy || 0) /
                Math.max(1, Math.min(original.width, original.height) / 4))
        ));
        const warnings = [];
        if (groundShift !== null && Math.abs(groundShift) > 2)
            warnings.push('Bodenlinie um ' + groundShift + ' px verschoben: Pivot prüfen.');
        if (hiddenRGBChanges)
            warnings.push('Verdeckte RGB-Werte im volltransparenten Bereich geändert: Atlas/BC7-Ränder prüfen.');
        if (added)
            warnings.push('Neue sichtbare Pixel außerhalb der ursprünglichen Silhouette: Rand und Maske prüfen.');
        if (centroidShift && Math.hypot(centroidShift.dx, centroidShift.dy) >
                Math.max(2, Math.min(original.width, original.height) / 8))
            warnings.push('Sichtbarer Bildschwerpunkt deutlich verschoben: Pose/Ausrichtung prüfen.');
        if (sourcePartial !== targetPartial)
            warnings.push('Anzahl halbtransparenter Pixel geändert: Alpha-Fransen prüfen.');
        return { changedPixels, changedAlpha, addedVisible: added,
            removedVisible: removed, hiddenRGBChanges, sourceVisible, targetVisible,
            sourcePartial, targetPartial, groundShift,
            centroidShift, reviewRiskPoints: points,
            riskBand: points >= 50 ? 'high_review_risk' :
                points >= 15 ? 'moderate_review_risk' : 'low_observed_pixel_risk',
            warnings, approved: false, inGameTested: false };
    }
    /** Compare 1–4 alternatives without choosing or accepting any of them. */
    function rankCandidates(original, candidates) {
        if (!Array.isArray(candidates) || !candidates.length || candidates.length > 4)
            fail('Ranking benötigt ein bis vier Bildkandidaten.');
        const ranked = candidates.map((row, index) => {
            const image = row?.image || row;
            const report = reviewCandidate(original, image);
            return { index, name: row?.name || ('Variante ' + (index + 1)),
                reviewRiskPoints: report.quality?.reviewRiskPoints ?? 100,
                errors: report.errors.slice(), warnings: report.warnings.slice(),
                approved: false };
        });
        return ranked.sort((a, b) => (a.errors.length > 0) - (b.errors.length > 0) ||
            a.reviewRiskPoints - b.reviewRiskPoints || a.index - b.index);
    }
    /** One common frame-animation QA: anchor/baseline consistency, not motion synthesis. */
    function analyzeSequence(frames) {
        if (!Array.isArray(frames) || frames.length < 2 || frames.length > 256)
            fail('Animationsprüfung benötigt 2 bis 256 Frames.');
        const rows = frames.map((item, index) => {
            if (!item || !item.image) fail('Animationsframe ohne Bilddaten.');
            const img = item.image;
            C.dimensions(img.width, img.height);
            const anchor = C.pivot(item.pivot ?? { x:.5, y:0 });
            let visible = 0, right = -1, bottom = -1, left = img.width, top = img.height;
            for (let i = 3; i < img.data.length; i += 4) {
                if (!img.data[i]) continue;
                const ordinal = (i - 3) / 4, x = ordinal % img.width, y = Math.floor(ordinal / img.width);
                visible++; left = Math.min(left, x); right = Math.max(right, x);
                top = Math.min(top, y); bottom = Math.max(bottom, y);
            }
            return { index, name: String(item.name || index).slice(0, 150),
                width: img.width, height: img.height, visiblePixels: visible,
                anchor: { x: img.width * anchor.x, y: img.height * (1 - anchor.y) },
                bounds: visible ? { left, top, right, bottom } : null,
                relativeGroundY: visible ? bottom - img.height * (1 - anchor.y) : null };
        });
        const warnings = [];
        for (const row of rows)
            if (!row.visiblePixels) warnings.push({ frame:row.index, code:'empty_alpha', detail:'Transparentes Bild' });
        for (let i = 1; i < rows.length; i++) {
            const prev = rows[i - 1], row = rows[i];
            if (row.width !== prev.width || row.height !== prev.height)
                warnings.push({frame:i, code:'canvas_size_changed', detail:'Frame-Abmessungen weichen ab'});
            if (row.relativeGroundY !== null && prev.relativeGroundY !== null &&
                    Math.abs(row.relativeGroundY - prev.relativeGroundY) > 2)
                warnings.push({frame:i, code:'ground_jitter', detail:'Bodenanker variiert >2 px; möglicherweise beabsichtigte Bewegung'});
        }
        return { schema:'sprite-suite.animation-qa.v1', frames:rows, warnings,
            automatedReleaseApproval:false, nativeAnimationTested:false };
    }
    function reviewCandidate(original, candidate) {
        C.dimensions(original.width, original.height);
        C.dimensions(candidate.width, candidate.height);
        const errors = [], warnings = [];
        if (original.width !== candidate.width || original.height !== candidate.height)
            errors.push('Kandidat muss exakt die Originalabmessungen besitzen.');
        let changedPixels = 0, alphaChanged = 0, visible = 0, originalVisible = 0;
        if (!errors.length) for (let i = 0; i < original.data.length; i += 4) {
            if (original.data[i + 3]) originalVisible++;
            if (candidate.data[i + 3]) visible++;
            if (original.data[i + 3] !== candidate.data[i + 3]) alphaChanged++;
            if (original.data[i] !== candidate.data[i] ||
                original.data[i + 1] !== candidate.data[i + 1] ||
                original.data[i + 2] !== candidate.data[i + 2] ||
                original.data[i + 3] !== candidate.data[i + 3]) changedPixels++;
        }
        if (!errors.length && !changedPixels) errors.push('Kandidat ist unverändert.');
        if (!errors.length && !visible) errors.push('Kandidat ist vollständig transparent.');
        if (!errors.length && alphaChanged) warnings.push('Transparenz/Silhouette verändert: manuell prüfen.');
        if (!errors.length && changedPixels > original.width * original.height * .8)
            warnings.push('Mehr als 80 % der Pixel verändert: Stil und Originaltreue prüfen.');
        const quality = original.width === candidate.width && original.height === candidate.height ?
            visualRisk(original, candidate) : null;
        if (quality) warnings.push(...quality.warnings);
        return { errors, warnings, quality,
            stats: { changedPixels, alphaChanged, visible, originalVisible },
            needsManualReview: true, approved: false };
    }
    return Object.freeze({ MODELS, ASSET_CLASSES, options, canvasPlan, registeredImage,
        prompt, makeRequestBundle, verifyCandidateMetadata, reviewCandidate, visualRisk, rankCandidates, analyzeSequence });
});
