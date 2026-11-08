/* Pure, offline SpriteSuite AI request, comparison and review contracts.
   Images are never sent over the network by the browser editor. */
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
    const ASSET_CLASSES = Object.freeze(['building', 'unit', 'vegetation', 'hud', 'ui', 'other']);
    const CLASS_PROMPTS = Object.freeze({
        building: 'Maintain the isometric game camera, building silhouette, ground contact, recognizable construction and tiered tiles.',
        unit: 'Preserve the complete subject pose, direction, frame registration and character size used in the game.',
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
        C.dimensions(img.width, img.height);
        const landscape = img.width > img.height * 1.25;
        const portrait = img.height > img.width * 1.25;
        const width = landscape ? 1536 : 1024, height = portrait ? 1536 : 1024;
        const scale = Math.floor(Math.min((width - 128) / img.width,
                                          (height - 128) / img.height));
        if (scale < 1) fail('Sprite zu groß für verlustfreie KI-Registrierung; erst Arbeitskopie vorbereiten.');
        return { width, height, scale, left: Math.floor((width - img.width * scale) / 2),
            top: height - 64 - img.height * scale, sourceWidth: img.width,
            sourceHeight: img.height };
    }
    function registeredImage(img, plan) {
        if (img.width !== plan.sourceWidth || img.height !== plan.sourceHeight)
            fail('Quellbild passt nicht zur Registrierungsplanung.');
        const canvas = C.image(plan.width, plan.height);
        const scaled = plan.scale === 1 ? img :
            C.resize(img, img.width * plan.scale, img.height * plan.scale);
        // Direct byte copy preserves hidden RGB and partially transparent pixels.
        // Alpha compositing would silently rewrite the image before generation.
        for (let y = 0; y < scaled.height; y++) {
            const start = y * scaled.width * 4;
            canvas.data.set(scaled.data.subarray(start, start + scaled.width * 4),
                ((y + plan.top) * canvas.width + plan.left) * 4);
        }
        return canvas;
    }
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
            format: 'sprite-suite.ai-image-edit', version: 1,
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
            'Bezahlte Generierung nur mit ausdruecklichem --execute UND --confirm-paid-requests.',
            'OPENAI_API_KEY ausschliesslich aus der Umgebung lesen; keine Schluessel in der Projektdatei.',
            'PNG-Kandidaten im Sprite Editor unter KI-Werkstatt importieren.',
            'Abmessung, Alpha, Geometrie und Originaltreue visuell pruefen; danach manuell uebernehmen.',
            'Keine automatische Mod-Installation oder Ingame-Freigabe.',
        ].join('\n');
        return { request, bytes: K.zip([
            { name: 'reference.png', data: original },
            { name: 'model_reference.png', data: registered },
            { name: 'request.json', data: JSON.stringify(request, null, 2) },
            { name: 'WORKFLOW.txt', data: guide }
        ]) };
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
        return { errors, warnings,
            stats: { changedPixels, alphaChanged, visible, originalVisible },
            needsManualReview: true, approved: false };
    }
    return Object.freeze({ MODELS, ASSET_CLASSES, options, canvasPlan, registeredImage,
        prompt, makeRequestBundle, reviewCandidate });
});
