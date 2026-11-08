/* Native editor controls: no model, image logic, script evaluation or network. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.SpriteNativeAPI = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
    'use strict';
    const SCHEMA = 'spritesuite.editor.native.v1';
    const operations = {
        'project.open': { files: { type: 'array', items: { type: 'object', required: ['name', 'base64'],
            additionalProperties: false, properties: { name: { type: 'string' }, base64: { type: 'string' } } } } },
        'files.import': { files: { type: 'array', items: { type: 'object', required: ['name', 'base64'],
            additionalProperties: false, properties: { name: { type: 'string' }, base64: { type: 'string' } } } } },
        'selection.set': { frameIds: { type: 'array', minItems: 1, maxItems: 4096,
            uniqueItems: true, items: { type: 'string' } } },
        'canvas.gesture': {
            points: { type: 'array', minItems: 1, maxItems: 256, items: { type: 'object',
                additionalProperties: false, required: ['x', 'y'], properties: {
                    x: { type: 'number', minimum: -131072, maximum: 131072 },
                    y: { type: 'number', minimum: -131072, maximum: 131072 } } } },
            button: { type: 'number', enum: [0, 1] },
            ctrlKey: { type: 'boolean', default: false }, shiftKey: { type: 'boolean', default: false }
        },
        'action.invoke': { actionId: { type: 'string' } },
        'view.set': { viewId: { type: 'string' } },
        'panel.set': { panelId: { type: 'string' } },
        'field.set': { fieldId: { type: 'string' }, value: {} },
        'control.invoke': { controlId: { type: 'string' } },
        'control.files': { controlId: { type: 'string' }, files: { type: 'array', items: {
            type: 'object', required: ['name', 'base64'], additionalProperties: false,
            properties: { name: { type: 'string' }, base64: { type: 'string' } } } } },
        'form.read': { formId: { type: 'string' } },
        'form.fill': { formId: { type: 'string' }, values: { type: 'object' } },
        'form.submit': { formId: { type: 'string' } }
    };
    const optional = (operation, key) => operation === 'canvas.gesture' && ['ctrlKey', 'shiftKey'].includes(key);
    function create(adapter) {
        const doc = adapter.document, ids = new WeakMap();
        let generation = 0, serial = 0, executing = false;
        const invalidate = () => { generation++; };
        const revision = () => adapter.sessionId + ':' + adapter.historyRevision() + ':' + generation;
        const fail = (code, message) => { const error = new Error(message); error.code = code; throw error; };
        const visible = node => !node.hidden && !!node.getClientRects().length;
        const idFor = node => {
            if (!ids.has(node)) ids.set(node, node.id || ('native-control-' + (++serial)));
            return ids.get(node);
        };
        const label = node => [...(node.labels || [])].map(n => n.textContent.trim()).join(' ') ||
            node.getAttribute('aria-label') || node.title || node.name || node.textContent.trim().slice(0, 160);
        const blocked = node => !!node.disabled || !visible(node) ||
            (adapter.modalOpen() && !node.closest('#modal'));
        const controls = () => [...doc.querySelectorAll('input,select,textarea,button')]
            .filter(n => n.id !== 'native-connect' && !['file', 'password', 'hidden'].includes(n.type));
        const find = id => {
            const node = controls().find(n => idFor(n) === id);
            if (!node) fail('unknown', 'Unknown or replaced native control: ' + id);
            if (blocked(node)) fail('disabled', 'Native control is disabled or hidden: ' + id);
            return node;
        };
        const valueOf = node => node.type === 'checkbox' ? !!node.checked :
            ['number', 'range'].includes(node.type) && node.value !== '' ? Number(node.value) : node.value;
        function describe(node) {
            const schema = { type: node.type === 'checkbox' ? 'boolean' :
                ['number', 'range'].includes(node.type) ? 'number' : 'string' };
            if (node.tagName === 'SELECT') schema.enum = [...node.options].map(o => o.value);
            if (schema.type === 'number') {
                if (node.min !== '') schema.minimum = Number(node.min);
                if (node.max !== '') schema.maximum = Number(node.max);
            }
            return { id: idFor(node), label: label(node), type: node.type || node.tagName.toLowerCase(),
                name: node.name || null, formId: node.form?.id || null,
                enabled: !blocked(node), visible: visible(node), readOnly: !!node.readOnly,
                value: node.tagName === 'BUTTON' ? undefined : valueOf(node), valueSchema: schema };
        }
        function inspect() {
            return { ...adapter.inspect(), schema: SCHEMA, revision: revision(), historyRevision: adapter.historyRevision(),
                busy: !!adapter.busy() || executing,
                controls: controls().map(describe), modal: adapter.modalState() };
        }
        function discover() {
            const actions = Object.keys(adapter.actions).map(id => {
                const nodes = [...doc.querySelectorAll('[data-action]')].filter(n => n.dataset.action === id);
                return { id, label: nodes.map(label).find(Boolean) || id,
                    enabled: !adapter.busy() && (!nodes.length || nodes.some(n => !n.disabled)) };
            });
            const navigation = kind => [...doc.querySelectorAll('[data-' + kind + ']')]
                .map(n => ({ id: n.dataset[kind], label: label(n), enabled: !n.disabled }));
            return { schema: SCHEMA, revision: revision(), actions,
                views: navigation('view'), panels: navigation('panel'),
                coverage: { nativeHistory: true, fileImports: ['project.open', 'files.import'],
                    selection: 'selection.set uses the existing frame selection helper',
                    fields: 'Current visible native fields and buttons are discovered by ID; edits use their original callbacks.',
                    canvas: 'canvas.gesture invokes existing pointer handlers in model coordinates; one point is a tap, multiple points one stroke. Measurement uses two separate taps.',
                    pointerOnly: [] },
                operations: Object.entries(operations).map(([id, properties]) => ({ id, inputSchema: {
                    type: 'object', additionalProperties: false,
                    required: ['operation', ...Object.keys(properties).filter(key => !optional(id, key)), ...(id === 'form.read' ? [] : ['expectedRevision'])],
                    properties: { operation: { const: id }, expectedRevision: { type: 'string' }, ...properties }
                } })) };
        }
        function validateValue(node, value) {
            if (node.tagName === 'BUTTON' || node.readOnly) fail('disabled', 'Control is not editable.');
            const schema = describe(node).valueSchema;
            if (typeof value !== schema.type || (schema.type === 'number' && !Number.isFinite(value)))
                fail('invalid', 'Value does not match the native field type.');
            if (schema.enum && !schema.enum.includes(value)) fail('invalid', 'Unknown select option.');
            if (typeof value === 'number' && (value < (schema.minimum ?? -Infinity) || value > (schema.maximum ?? Infinity)))
                fail('invalid', 'Value is outside the native field limits.');
            if (typeof value === 'string' && node.maxLength >= 0 && value.length > node.maxLength)
                fail('invalid', 'Value exceeds the native field length.');
        }
        function fill(node, value) {
            validateValue(node, value);
            if (!node.isConnected) fail('stale', 'Native field was replaced. Inspect the editor again.');
            if (node.type === 'checkbox') node.checked = value;
            else node.value = String(value);
            node.dispatchEvent(new doc.defaultView.Event('input', { bubbles: true }));
            node.dispatchEvent(new doc.defaultView.Event('change', { bubbles: true }));
        }
        function form(id) {
            if (id !== 'modal-form' || !adapter.modalOpen()) fail('unknown', 'No active native form: ' + id);
            return doc.getElementById(id);
        }
        async function execute(request, options = {}) {
            let entered = false;
            const initialHistoryRevision = adapter.historyRevision();
            try {
                if (options.signal?.aborted) fail('canceled', 'Native command was canceled before dispatch.');
                if (!request || typeof request !== 'object' || Array.isArray(request)) fail('invalid', 'Expected a command object.');
                if (!Object.hasOwn(operations, request.operation)) fail('unknown', 'Unknown native operation.');
                const keys = operations[request.operation];
                if (Object.keys(request).some(k => !['operation', 'expectedRevision', ...Object.keys(keys)].includes(k)) ||
                    Object.keys(keys).some(k => !optional(request.operation, k) && !Object.hasOwn(request, k))) fail('invalid', 'Unexpected or missing command fields.');
                for (const [key, schema] of Object.entries(keys))
                    if (Object.hasOwn(request, key) && schema.type && (schema.type === 'array' ? !Array.isArray(request[key]) :
                        (request[key] === null || typeof request[key] !== schema.type || Array.isArray(request[key]))))
                        fail('invalid', 'Invalid command field: ' + key);
                if (request.operation !== 'form.read' && request.expectedRevision !== revision())
                    fail('stale', 'The editor changed. Inspect again before editing.');
                if (executing || adapter.busy()) fail('busy', 'A native editor operation is running.');
                if (request.operation === 'form.read') {
                    const nativeForm = form(request.formId);
                    return { ok: true, revision: revision(), result: { formId: request.formId,
                        fields: controls().filter(n => n.form === nativeForm && n.tagName !== 'BUTTON').map(describe) } };
                }
                executing = true;
                entered = true;
                adapter.begin?.(options.signal);
                adapter.clearError();
                const op = request.operation;
                if (op === 'canvas.gesture') {
                    if (adapter.modalOpen()) fail('disabled', 'Finish the open native dialog first.');
                    await adapter.canvasGesture(request);
                } else if (op === 'selection.set') {
                    if (adapter.modalOpen()) fail('disabled', 'Finish the open native dialog first.');
                    await adapter.setSelection(request.frameIds);
                } else if (op === 'project.open' || op === 'files.import') {
                    if (adapter.modalOpen()) fail('disabled', 'Finish the open native dialog first.');
                    await (op === 'project.open' ? adapter.openFiles : adapter.importFiles)(request.files);
                } else if (op === 'action.invoke') {
                    const action = adapter.actions[request.actionId];
                    if (!Object.hasOwn(adapter.actions, request.actionId)) fail('unknown', 'Unknown native action.');
                    if (adapter.modalOpen() && !['close-modal', 'close-toast'].includes(request.actionId))
                        fail('disabled', 'Finish the open native dialog first.');
                    if (!discover().actions.find(a => a.id === request.actionId)?.enabled) fail('disabled', 'Native action is disabled.');
                    await action();
                } else if (op === 'view.set' || op === 'panel.set') {
                    if (adapter.modalOpen()) fail('disabled', 'Finish the open native dialog first.');
                    const kind = op === 'view.set' ? 'views' : 'panels', id = request.viewId ?? request.panelId;
                    const target = discover()[kind].find(n => n.id === id);
                    if (!target) fail('unknown', 'Unknown native navigation target.');
                    if (!target.enabled) fail('disabled', 'Native navigation is disabled.');
                    await (op === 'view.set' ? adapter.setView : adapter.setPanel)(id);
                } else if (op === 'field.set') fill(find(request.fieldId), request.value);
                else if (op === 'control.invoke' || op === 'control.files') {
                    const node = find(request.controlId);
                    if (node.tagName !== 'BUTTON') fail('invalid', 'Expected a native button.');
                    if (op === 'control.files') await adapter.invokeFiles(node, request.files);
                    else if (node.type === 'submit' && node.form?.id === 'modal-form') await adapter.submitForm();
                    else await adapter.invokeControl(node);
                } else if (op === 'form.fill') {
                    const target = form(request.formId), nodes = Object.entries(request.values).map(([id, value]) => {
                        const node = find(id);
                        if (node.form !== target) fail('invalid', 'Field does not belong to the active form.');
                        validateValue(node, value);
                        return [node, value];
                    });
                    for (const [node, value] of nodes) fill(node, value);
                } else if (op === 'form.submit') {
                    const target = form(request.formId);
                    if (adapter.modalState().submitEnabled === false) fail('disabled', 'Native form submit is disabled.');
                    if (!target.checkValidity()) fail('invalid', 'Native form validation failed.');
                    await adapter.submitForm();
                }
                if (adapter.lastError()) fail('native_error', adapter.lastError());
                if (options.signal?.aborted) fail('canceled', 'Native command was canceled; completed changes are not rolled back.');
                invalidate();
                executing = false;
                return { ok: true, revision: revision(), result: inspect() };
            } catch (error) {
                return { ok: false, revision: revision(), error: {
                    code: options.signal?.aborted ? 'canceled' :
                        typeof error.code === 'string' ? error.code : 'native_error',
                    ...(options.signal?.aborted ? { completedChanges: adapter.historyRevision() !== initialHistoryRevision } : {}),
                    message: String(error.message || error).slice(0, 2000) } };
            } finally { if (entered) { executing = false; adapter.end?.(); } }
        }
        // Observe only user/native UI events. No action is invoked by installation.
        doc.addEventListener('input', invalidate, true);
        doc.addEventListener('change', invalidate, true);
        return Object.freeze({ discover, inspect, execute, invalidate });
    }
    return Object.freeze({ SCHEMA, create });
});
