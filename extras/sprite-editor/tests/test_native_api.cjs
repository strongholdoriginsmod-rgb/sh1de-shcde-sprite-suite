'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { create } = require('../src/native_api.js');

function fixture() {
    let version = 0, busy = false, modal = false, invoked = 0, submitted = 0;
    const changes = [], listeners = {};
    const form = { id: 'modal-form', checkValidity: () => true };
    const nodes = [];
    const doc = {
        defaultView: { Event: class { constructor(type) { this.type = type; } } },
        addEventListener: (name, callback) => { listeners[name] = callback; },
        getElementById: id => id === form.id ? form : nodes.find(n => n.id === id),
        querySelectorAll: selector => selector.startsWith('[data-') ? nodes.filter(n =>
            n.dataset[selector.slice(6, -1)]) : nodes
    };
    function control(id, type, extra = {}) {
        const n = { id, type, name: id, tagName: type === 'button' ? 'BUTTON' : 'INPUT',
            dataset: {}, value: '', min: '', max: '', maxLength: -1, textContent: id,
            labels: [{ textContent: id }], title: '', disabled: false, hidden: false,
            readOnly: false, isConnected: true, getClientRects: () => [{}],
            getAttribute: () => null, closest: () => n.form ? { id: 'modal' } : null,
            dispatchEvent: e => { changes.push([id, e.type, n.value]); listeners[e.type]?.(e); },
            click: () => { invoked++; }, ...extra };
        nodes.push(n);
        return n;
    }
    const number = control('amount', 'number', { value: '2', min: '1', max: '5' });
    const check = control('enabled', 'checkbox', { checked: false });
    control('native-button', 'button', { dataset: { action: 'existing' } });
    control('scene', 'button', { dataset: { view: 'scene' } });
    control('geometry', 'button', { dataset: { panel: 'geometry' } });
    const title = control('title', 'text', { form, value: 'Before' });
    const adapter = {
        document: doc, sessionId: 'isolated-page', historyRevision: () => version,
        inspect: () => ({ revision: version, selected: ['frame'] }), busy: () => busy,
        actions: { existing: () => { version++; invoked++; } },
        modalOpen: () => modal, modalState: () => ({ open: modal }),
        setView: () => { invoked++; }, setPanel: () => { invoked++; },
        canvasGesture: request => { changes.push(['canvas', request]); },
        submitForm: () => { submitted++; version++; modal = false; },
        invokeControl: n => n.click(), clearError: () => {}, lastError: () => null
    };
    const api = create(adapter);
    return { api, adapter, nodes, number, check, title, changes,
        busy: value => { busy = value; }, modal: value => { modal = value; },
        invoked: () => invoked, submitted: () => submitted,
        execute: (operation, fields = {}) => api.execute({ operation, ...fields, expectedRevision: api.inspect().revision }) };
}

test('installation only discovers native callbacks; revision tokens survive numeric history inspect', () => {
    const f = fixture();
    assert.equal(f.invoked(), 0);
    assert.equal(typeof f.api.inspect().revision, 'string');
    assert.equal(f.api.discover().operations.length, 13);
    assert.ok(f.api.discover().actions.some(a => a.id === 'existing'));
    assert.equal(f.invoked(), 0);
});
test('invocation uses existing callbacks and rejects stale commands', async () => {
    const f = fixture(), old = f.api.inspect().revision;
    assert.equal((await f.execute('action.invoke', { actionId: 'existing' })).ok, true);
    assert.equal(f.invoked(), 1);
    const stale = await f.api.execute({ operation: 'action.invoke', actionId: 'existing', expectedRevision: old });
    assert.equal(stale.error.code, 'stale');
    assert.equal(f.invoked(), 1);
});
test('field edits dispatch original input then change events and validate limits', async () => {
    const f = fixture();
    assert.equal((await f.execute('field.set', { fieldId: 'amount', value: 4 })).ok, true);
    assert.deepEqual(f.changes.map(c => c[1]), ['input', 'change']);
    assert.equal(f.number.value, '4');
    assert.equal((await f.execute('field.set', { fieldId: 'amount', value: 9 })).error.code, 'invalid');
    assert.equal(f.number.value, '4');
    assert.equal((await f.execute('field.set', { fieldId: 'enabled', value: true })).ok, true);
    assert.equal(f.check.checked, true);
});
test('unknown, disabled and busy commands never invoke native callbacks', async () => {
    const f = fixture();
    assert.equal((await f.execute('action.invoke', { actionId: 'missing' })).error.code, 'unknown');
    assert.equal((await f.execute('toString')).error.code, 'unknown');
    f.nodes.find(n => n.dataset.action === 'existing').disabled = true;
    assert.equal((await f.execute('action.invoke', { actionId: 'existing' })).error.code, 'disabled');
    f.busy(true);
    assert.equal((await f.execute('view.set', { viewId: 'scene' })).error.code, 'busy');
    assert.equal(f.invoked(), 0);
});
test('form reads/fills/submits use the active native form and prevent partial invalid batches', async () => {
    const f = fixture();
    f.modal(true);
    const read = await f.execute('form.read', { formId: 'modal-form' });
    assert.equal(read.result.fields[0].id, 'title');
    const bad = await f.execute('form.fill', { formId: 'modal-form', values: { title: 'After', missing: 'bad' } });
    assert.equal(bad.error.code, 'unknown');
    assert.equal(f.title.value, 'Before');
    assert.equal((await f.execute('form.fill', { formId: 'modal-form', values: { title: 'After' } })).ok, true);
    assert.equal((await f.execute('form.submit', { formId: 'modal-form' })).ok, true);
    assert.equal(f.submitted(), 1);
    assert.equal(f.title.value, 'After');
});
test('open modal blocks background native controls and navigation', async () => {
    const f = fixture();
    f.modal(true);
    assert.equal((await f.execute('field.set', { fieldId: 'amount', value: 3 })).error.code, 'disabled');
    assert.equal((await f.execute('view.set', { viewId: 'scene' })).error.code, 'disabled');
    assert.equal(f.invoked(), 0);
});
test('a rejected concurrent call cannot release the running native operation', async () => {
    const f = fixture(); let complete;
    f.adapter.actions.wait = () => new Promise(resolve => { complete = resolve; });
    const first = f.execute('action.invoke', { actionId: 'wait' });
    assert.equal(f.api.inspect().busy, true);
    assert.equal((await f.execute('action.invoke', { actionId: 'existing' })).error.code, 'busy');
    assert.equal(f.api.inspect().busy, true);
    complete(); assert.equal((await first).ok, true);
    assert.equal(f.api.inspect().busy, false);
});
test('an already canceled command invokes no existing callback', async () => {
    const f = fixture(), controller = new AbortController(); controller.abort();
    const result = await f.api.execute({ operation: 'action.invoke', actionId: 'existing',
        expectedRevision: f.api.inspect().revision }, { signal: controller.signal });
    assert.equal(result.error.code, 'canceled');
    assert.equal(f.invoked(), 0);
});
test('typed canvas gestures reach the existing adapter and optional modifiers stay optional', async () => {
    const f = fixture();
    const points = [{x:1,y:2},{x:4,y:8}];
    assert.equal((await f.execute('canvas.gesture', {points,button:0})).ok, true);
    assert.equal(f.changes[0][0], 'canvas');
    assert.deepEqual(f.changes[0][1].points, points);
    assert.equal((await f.execute('canvas.gesture', {points,button:0,ctrlKey:'yes'})).error.code, 'invalid');
    assert.equal(f.changes.length, 1);
});
