/* Building damage scene workflow, optional full-image candidates and safe staged export. */
(function (root, factory) {
    'use strict';
    const node = typeof module === 'object' && module.exports;
    const api = factory(node ? require('./core.js') : root.SpriteCore,
        node ? require('./codec.js') : root.SpriteCodec,
        node ? require('./io.js') : root.SpriteIO,
        node ? require('./damage.js') : root.SpriteDamage);
    if (node) module.exports = api;
    else root.SpriteDamageIO = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (C, K, I, D) {
    'use strict';
    const fail = msg => { throw new Error(msg); };
    function getStage(state, id) {
        for (const profile of state.damageProfiles || [])
            for (const stage of profile.stages)
                if (stage.id === id)
                    return { profile, stage, base: state.scenes.find(g => g.id === profile.buildingGroupId),
                        scene: state.scenes.find(g => g.id === stage.sceneId) };
        fail('Schadensstufe ist nicht vorhanden.');
    }
    function baseComposite(state, store, groupId) {
        const group = state.scenes.find(g => g.id === groupId);
        if (!group) fail('Gebäudegruppe fehlt.');
        const frames = state.frames.filter(f => f.groupId === groupId);
        if (!frames.length) fail('Gebäudegruppe enthält keine Tiles.');
        const layout = C.layout(frames, group.settings, key => store.get(key));
        return { group, frames, layout, image: C.compose(layout, key => store.get(key)) };
    }
    function createStage(state, store, buildingGroupId, kind, hpAtOrBelow, label = '') {
        const base = state.scenes.find(g => g.id === buildingGroupId);
        if (!base || base.settings.category !== 'building')
            fail('Zuerst eine bestehende Gebäudegruppe auswählen.');
        if (base.settings.width > 64)
            fail('Die Gebäudegruppe muss vor neuen Stufen auf höchstens 64 px Tilebreite gebracht werden.');
        const baseFrames = state.frames.filter(f => f.groupId === buildingGroupId);
        if (!baseFrames.length) fail('Gebäude enthält keine Sprite-Tiles.');
        if (baseFrames.some(f => store.get(f.imageId).width > 64))
            fail('Das Gebäude enthält Sprites über 64 px; zuerst die Tile-Geometrie anpassen.');
        const out = I.clone(state), stageId = I.uid('d'), sceneId = I.uid('g');
        const groupName = 'damage_' + kind + '_' + hpAtOrBelow + '_' + stageId.slice(-6);
        out.scenes.push({ id: sceneId, name: groupName, source: base.source, settings: { ...base.settings } });
        for (const f of baseFrames) {
            out.frames.push({
                ...I.clone(f), id: I.uid('f'), groupId: sceneId, name: groupName + '-' + f.slot + '.png',
                group: groupName, index: f.slot, targetName: '', targetConfirmed: false,
                locked: false
            });
        }
        let profile = out.damageProfiles.find(p => p.buildingGroupId === buildingGroupId);
        if (!profile) {
            profile = { buildingGroupId, gameBuildingType: null, stages: [] };
            out.damageProfiles.push(profile);
        }
        profile.stages.push({
            id: stageId, sceneId, kind, hpAtOrBelow, label,
            changeRequest: '', reviewNotes: '', status: 'draft',
            model: D.MODELS[0], candidateId: null
        });
        return { state: I.validate(out, store), store, stageId, sceneId };
    }
    function withCandidate(state, store, stageId, image) {
        const out = I.clone(state), next = store.fork(), { stage } = getStage(out, stageId);
        C.dimensions(image.width, image.height);
        stage.candidateId = next.add(image);
        stage.status = 'draft';
        const { profile } = getStage(out, stageId);
        const base = baseComposite(state, store, profile.buildingGroupId);
        const report = D.checkCandidate(base.image, image);
        return { state: I.validate(out, next), store: next, report };
    }
    function applyCandidate(state, store, stageId) {
        const out = I.clone(state), { stage, base, scene } = getStage(out, stageId);
        if (!stage.candidateId) fail('Zuerst ein erzeugtes PNG als Kandidat importieren.');
        const ref = baseComposite(state, store, base.id), candidate = store.get(stage.candidateId);
        const report = D.checkCandidate(ref.image, candidate);
        if (report.errors.length) fail('Qualitätsprüfung: ' + report.errors.join(' '));
        const layout = ref.layout, settings = scene.settings;
        if (settings.width > 64) fail('Tilebreite überschreitet 64 px.');
        const map = C.partition(candidate, settings, layout.originX, layout.originY, true);
        const cut = C.split(candidate, map, settings, layout.originX, layout.originY, null,
            { overlap: 1, rearShare: true });
        const rebuilt = C.image(candidate.width, candidate.height);
        for (const t of cut.tiles) C.blit(rebuilt, t.image, t.x, t.y, true);
        // Ignore hidden RGB at alpha zero: only visible RGBA may differ.
        for (let i = 0; i < candidate.data.length; i += 4)
            if (candidate.data[i + 3] !== rebuilt.data[i + 3] ||
                (candidate.data[i + 3] && (candidate.data[i] !== rebuilt.data[i] ||
                    candidate.data[i + 1] !== rebuilt.data[i + 1] ||
                    candidate.data[i + 2] !== rebuilt.data[i + 2])))
                fail('Split-Rekonstruktion stimmt nicht pixelgenau; Kandidat unverändert lassen.');
        const next = store.fork();
        const oldFrames = out.frames.filter(f => f.groupId === stage.sceneId);
        const ppu = ref.frames[0].ppu;
        out.frames = out.frames.filter(f => f.groupId !== stage.sceneId);
        const positions = C.positions(settings);
        for (const t of cut.tiles) {
            const imageId = next.add(t.image), groupName = scene.name;
            const f = I.makeFrame(groupName + '-' + t.slot + '.png', imageId, scene.id, next, { ppu });
            const pos = positions[t.slot];
            f.originalId = imageId;
            f.slot = t.slot;
            f.dx = t.x - (layout.originX + pos.x - t.width / 2);
            f.dy = t.y - (layout.originY + pos.bottom - t.height);
            f.pivot = { x: .5, y: 0 };
            f.originalPivot = { x: .5, y: 0 };
            f.metadataStatus = 'manual';
            f.targetName = '';
            f.targetConfirmed = false;
            out.frames.push(f);
        }
        // C.layout normalizes every group to its own geometric extents. A
        // freshly split stage may have less transparent headroom than the
        // original. Preserve the exact original canvas by padding ONE upper
        // tile with transparent rows, without changing its visible pixels,
        // 64px width, bottom anchor, or any neighbouring tile coordinates.
        const stageFrames = out.frames.filter(f => f.groupId === stage.sceneId);
        let stageLayout = C.layout(stageFrames, settings, key => next.get(key));
        const missingHeadroom = stageLayout.top - ref.layout.top;
        if (stageLayout.left !== ref.layout.left ||
            stageLayout.bottom !== ref.layout.bottom ||
            stageLayout.width !== ref.layout.width || missingHeadroom < 0)
            fail('Schadensmodell verlässt die Original-Canvasgeometrie. Keine stillschweigende Verschiebung.');
        if (missingHeadroom > 0) {
            const upper = stageLayout.placed.reduce((best, item) =>
                !best || item.y < best.y ? item : best, null);
            if (!upper)
                fail('Keine Stufen-Tiles für die Geometrieanpassung.');
            const img = next.get(upper.frame.imageId);
            const padded = C.image(img.width, img.height + missingHeadroom);
            C.blit(padded, img, 0, missingHeadroom);
            const id = next.add(padded);
            const f = stageFrames.find(item => item.id === upper.frame.id);
            f.imageId = f.originalId = id;
            stageLayout = C.layout(stageFrames, settings, key => next.get(key));
        }
        if (stageLayout.top !== ref.layout.top ||
            stageLayout.left !== ref.layout.left ||
            stageLayout.width !== ref.layout.width ||
            stageLayout.height !== ref.layout.height)
            fail('Stufengeometrie weicht von der Originalfläche ab.');
        const stageImage = C.compose(stageLayout, key => next.get(key));
        for (let i = 0; i < candidate.data.length; i += 4) {
            const a = candidate.data, b = stageImage.data;
            if (a[i + 3] !== b[i + 3] || (a[i + 3] &&
                (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2])))
                fail('Die bearbeitbare Gebäudegruppe ist nicht pixelgleich zum importierten Gesamtbild.');
        }
        // Never carry a colour/team material mask over a changed silhouette.
        stage.status = 'draft';
        const hadMasks = oldFrames.some(f => f.maskId);
        if (hadMasks) report.warnings.push('Original hatte Masken. Neue Tiles erhalten keine erfundenen Materialmasken; vor Abnahme manuell nachbearbeiten.');
        return { state: I.validate(out, next), store: next, report, seamStats: cut.seamStats };
    }
    function qualityReport(state, store, stageId) {
        const { profile, stage, base, scene } = getStage(state, stageId);
        const intact = baseComposite(state, store, base.id).image;
        const damaged = baseComposite(state, store, scene.id).image;
        const result = D.checkCandidate(intact, damaged);
        const pixels = result.stats.original?.visible || 0;
        const percent = stage.hpAtOrBelow;
        // These are minimum evidence checks, NOT a substitute for an expert
        // visual judgement of actual structural or fire damage.
        const fraction = percent <= 15 ? 0.035 : percent <= 45 ? 0.015 :
            percent <= 75 ? 0.0075 : 0.0025;
        const minimum = pixels ? Math.min(pixels, Math.max(4, Math.ceil(pixels * fraction))) : 0;
        const actual = result.stats.changedPixels || 0;
        result.stats.minimumVisibleChanges = minimum;
        result.stats.visibleChangesPercent = pixels ? Math.round(actual * 10000 / pixels) / 100 : 0;
        if (actual < minimum)
            result.errors.push('Für den gewählten Zerstörungsgrad sind nur ' + actual +
                ' von mindestens ' + minimum + ' sichtbar veränderten Pixeln vorhanden. Modell weiter beschädigen.');
        if (result.errors.length) return { ...result, intact, damaged };
        for (const other of profile.stages) {
            if (other.id === stage.id || other.kind !== stage.kind || other.status !== 'approved')
                continue;
            const otherScene = state.scenes.find(g => g.id === other.sceneId);
            if (!otherScene) continue;
            const prev = D.checkCandidate(intact, baseComposite(state, store, otherScene.id).image);
            const count = prev.stats.changedPixels || 0;
            if (other.hpAtOrBelow > percent && actual < count)
                result.warnings.push('Diese stärker zerstörte Stufe unterscheidet sich in weniger Pixeln vom Original als die bereits freigegebene mildere Stufe bei ' +
                    other.hpAtOrBelow + '% HP. Zerstörungsreihenfolge bildlich prüfen.');
            if (other.hpAtOrBelow < percent && actual > count)
                result.warnings.push('Diese mildere Stufe unterscheidet sich in mehr Pixeln vom Original als die bereits freigegebene stärkere Stufe bei ' +
                    other.hpAtOrBelow + '% HP. Zerstörungsreihenfolge bildlich prüfen.');
        }
        return { ...result, intact, damaged };
    }

    function approveStage(state, store, stageId, notes, visualConfirmed) {
        if (visualConfirmed !== true)
            fail('Visuelle Prüfung von Schäden, Perspektive, Bodenanker und Reihenfolge ausdrücklich bestätigen.');
        const out = I.clone(state), { stage, profile, base, scene } = getStage(out, stageId);
        const frames = out.frames.filter(f => f.groupId === scene.id);
        const original = out.frames.filter(f => f.groupId === base.id);
        if (!frames.length) fail('Schadensmodell ohne Tiles.');
        if (frames.length > scene.settings.a * scene.settings.b)
            fail('Schadensmodell enthält zu viele Rasterplätze.');
        if (frames.some(f => store.get(f.imageId).width > 64))
            fail('Schadensmodell enthält Tile-Breiten über 64 px.');
        if (original.some(f => f.maskId) && frames.some(f => !f.maskId))
            fail('Materialmasken fehlen im Schadensmodell. Die fehlenden Masken müssen manuell bearbeitet werden.');
        if (frames.length === original.length &&
            frames.every(f => {
                const same = original.find(o => o.slot === f.slot);
                return same && same.imageId === f.imageId;
            }))
            fail('Das Modell ist ein unverändertes Original-Klon; vor Freigabe Schäden anlegen.');
        const ids = new Set(), slots = new Set();
        for (const f of frames) {
            if (ids.has(f.id) || slots.has(f.slot)) fail('Doppelte Tiles im Schadensmodell.');
            ids.add(f.id); slots.add(f.slot);
        }
        const review = qualityReport(out, store, stageId);
        if (review.errors.length)
            fail('Qualitätsprüfung: ' + review.errors.join(' '));
        if (review.warnings.length && !String(notes || '').trim())
            fail('Qualitätswarnungen müssen geprüft und im Abnahmevermerk dokumentiert werden.');
        stage.reviewNotes = String(notes || '').slice(0, 2000);
        stage.status = 'approved';
        return { state: I.validate(out, store), store };
    }
    function modelCanvasPlan(img) {
        // Pixel-exact, reversible registration: integer nearest-neighbour scale,
        // a transparent border and a fixed bottom-centre image anchor.
        // The original remains a separate unmodified asset in the bundle.
        const landscape = img.width > img.height * 1.25;
        const portrait = img.height > img.width * 1.25;
        const width = landscape ? 1536 : 1024, height = portrait ? 1536 : 1024;
        const scale = Math.floor(Math.min((width - 128) / img.width, (height - 128) / img.height));
        if (scale < 1) return null; // Very large originals: do not perform lossy downsampling.
        return { width, height, scale,
            left: Math.floor((width - img.width * scale) / 2),
            top: height - 64 - img.height * scale,
            sourceWidth: img.width, sourceHeight: img.height };
    }
    function modelCanvas(img, plan) {
        if (img.width !== plan.sourceWidth || img.height !== plan.sourceHeight)
            fail('Die Registrierungsvorlage passt nicht zum Gebäude.');
        const out = C.image(plan.width, plan.height);
        const scaled = plan.scale === 1 ? img :
            C.resize(img, img.width * plan.scale, img.height * plan.scale);
        C.blit(out, scaled, plan.left, plan.top);
        return out;
    }
    async function makeRequestBundle(state, store, stageId, options = {}) {
        const { stage, profile, base } = getStage(state, stageId);
        const original = baseComposite(state, store, profile.buildingGroupId);
        const sameKind = profile.stages.filter(s => s.kind === stage.kind &&
            s.hpAtOrBelow > stage.hpAtOrBelow && s.status === 'approved')
            .sort((a, b) => a.hpAtOrBelow - b.hpAtOrBelow);
        const previous = sameKind[0] || null;
        const entries = [{ name: 'reference.png', data: await K.encodePNG(original.image, options) }];
        const plan = modelCanvasPlan(original.image), referenceFiles = [];
        if (plan) {
            const model = modelCanvas(original.image, plan);
            entries.push({ name: 'model_reference.png', data: await K.encodePNG(model, options) });
            referenceFiles.push('model_reference.png');
        }
        else
            referenceFiles.push('reference.png');
        if (previous) {
            const p = baseComposite(state, store, previous.sceneId);
            if (p.image.width === original.image.width && p.image.height === original.image.height) {
                const name = plan ? 'model_previous.png' : 'previous.png';
                const img = plan ? modelCanvas(p.image, plan) : p.image;
                entries.push({ name, data: await K.encodePNG(img, options) });
                referenceFiles.push(name);
            }
        }
        if (stage.candidateId) {
            const image = store.get(stage.candidateId);
            if (image.width === original.image.width && image.height === original.image.height) {
                const name = plan ? 'model_candidate.png' : 'candidate.png';
                entries.push({ name, data: await K.encodePNG(plan ? modelCanvas(image, plan) : image, options) });
                referenceFiles.push(name);
            }
            else if (plan && image.width === plan.width && image.height === plan.height) {
                entries.push({ name: 'model_candidate.png', data: await store.bytes(stage.candidateId, options.signal) });
                referenceFiles.push('model_candidate.png');
            }
        }
        const registeredPrompt = plan ?
            'REFERENCE 1 IS A TRANSPARENT REGISTERED CANVAS (model_reference.png) with nearest-neighbour enlarged original. ' +
            'Produce exactly ' + plan.width + 'x' + plan.height + ' pixels. ' +
            'Keep everything within the source rectangle x=' + plan.left + '..' + (plan.left + original.image.width * plan.scale) +
            ', y=' + plan.top + '..' + (plan.top + original.image.height * plan.scale) +
            ' on this same canvas; preserve its ground baseline and transparent exterior. ' +
            'The editor will inverse-scale this rectangle by factor ' + plan.scale +
            ' to the exact original pixel grid; preserve crisp pixel texture. ' +
            'Do not move, zoom, crop, shift, re-center or add shadows outside the registered sprite.\\n' : '';
        const request = {
            format: 'stronghold-building-damage-request', version: 1,
            model: stage.model, quality: 'high', background: 'transparent', output_format: 'png',
            size: plan ? plan.width + 'x' + plan.height : 'auto', complexity: 'high',
            registration: plan,
            buildingGroup: base.name, buildingGroupId: base.id, stageId: stage.id, damageKind: stage.kind,
            hpAtOrBelow: stage.hpAtOrBelow,
            referenceWidth: original.image.width, referenceHeight: original.image.height,
            referenceSHA256: await K.sha256(entries[0].data),
            prompt: registeredPrompt + D.buildPrompt(original.image, stage, base, previous, plan),
            referenceFiles
        };
        entries.push({ name: 'request.json', data: JSON.stringify(request, null, 2) });
        entries.push({ name: 'CODEX.md', data:
            'Codex kann dieses Bundle mit dem Projektadapter verarbeiten:\n' +
            'python tools/building_damage_codex.py --bundle <bundle.zip> --output <neuer-ordner> --dry-run\n' +
            'Zum kostenpflichtigen echten Image-2.6-Edit nur auf ausdrückliche Anweisung:\n' +
            'python tools/building_damage_codex.py --bundle <bundle.zip> --output <neuer-ordner> --execute\n' +
            'OPENAI_API_KEY muss außerhalb der Projektdatei in der Umgebung liegen.\n' +
            'candidate.png im Editor importieren, Form/Alpha/Tiles prüfen und explizit abnehmen.\n' +
            'Der Editor sendet niemals selbst Netzwerkanfragen.\n'
        });
        return { bytes: K.zip(entries), request };
    }
    async function exportPackage(state, store, options = {}) {
        const entries = [], buildings = [];
        for (const profile of state.damageProfiles || []) {
            const base = state.scenes.find(g => g.id === profile.buildingGroupId);
            const stages = [];
            for (const stage of profile.stages.filter(x => x.status === 'approved')) {
                const scene = state.scenes.find(g => g.id === stage.sceneId);
                const frames = state.frames.filter(f => f.groupId === stage.sceneId)
                    .sort((a, b) => a.slot - b.slot);
                if (!frames.length || frames.some(f => store.get(f.imageId).width > 64))
                    fail('Nicht exportierbare Stage: ' + stage.id);
                const target = 'damage/' + base.id + '/' + stage.kind + '/' + stage.hpAtOrBelow + '/';
                const tiles = [];
                for (const f of frames) {
                    const name = target + String(f.slot).padStart(4, '0') + '.png';
                    const data = await store.bytes(f.imageId, options.signal);
                    entries.push({ name, data });
                    const m = { slot: f.slot, image: name, sha256: await K.sha256(data),
                        dx: f.dx, dy: f.dy, pivot: f.pivot, ppu: f.ppu };
                    if (f.maskId) {
                        m.mask = target + String(f.slot).padStart(4, '0') + '_m.png';
                        const maskData = await store.bytes(f.maskId, options.signal);
                        m.maskSha256 = await K.sha256(maskData);
                        entries.push({ name: m.mask, data: maskData });
                    }
                    tiles.push(m);
                }
                stages.push({
                    id: stage.id, damageKind: stage.kind, hpAtOrBelow: stage.hpAtOrBelow,
                    scene: stage.sceneId, label: stage.label, model: stage.model,
                    reviewNotes: stage.reviewNotes, settings: scene.settings, tiles
                });
            }
            if (stages.length)
                buildings.push({ id: base.id, name: base.name, intactScene: base.id,
                    gameBuildingType: profile.gameBuildingType ?? null, gameBuildingTypeVerifiedInGame: false, stages });
        }
        if (!buildings.length) fail('Noch keine freigegebenen Schadensmodelle.');
        const manifest = {
            format: 'stronghold-building-damage-library', version: 1,
            target: 'Stronghold Crusader: Definitive Edition',
            runtimeHookInstalled: false, hpUnit: 'percent_of_maximum_hp',
            rule: 'Use lowest threshold T where current HP percent <= T; otherwise show intact. Fire uses mechanical fallback only if no fire stages exist.',
            buildings
        };
        entries.unshift({ name: 'damage-manifest.json', data: JSON.stringify(manifest, null, 2) });
        entries.push({ name: 'README.txt', data:
            'Freigegebene Schadenssprites und HP-Auswahlmanifest. KEINE aktive SHCDE-Runtime-Umschaltung.\n' +
            'Zur Darstellung im Spiel ist eine separat geprüfte Gebäude-/Schadensereignis-Renderer-Integration nötig.\n' +
            'Tiles max. 64 px, beim Zerlegen mit 1px Overlap und allen hinteren Reihen.\n' });
        return { bytes: K.zip(entries), manifest };
    }
    return { getStage, baseComposite, createStage, withCandidate, applyCandidate,
        qualityReport, approveStage, makeRequestBundle, exportPackage };
});
