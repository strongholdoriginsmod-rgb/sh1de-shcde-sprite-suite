/* Authenticated loopback transport. Heartbeats never choose an editor tab. */
(function (root) {
    'use strict';
    function install(api, doc = document) {
        const meta = doc.querySelector('meta[name="spritesuite-local"]');
        if (!meta || root.location.protocol !== 'http:' || root.location.hostname !== '127.0.0.1') return null;
        const token = meta.content, pageId = root.crypto.randomUUID(), running = new Map();
        let polling = false, activateNext = false, activated = false, stopped = false;
        const button = doc.getElementById('native-connect');
        const snapshot = () => ({ state: api.inspect(), discovery: api.discover() });
        async function post(path, data) {
            const response = await root.fetch(path, { method: 'POST', cache: 'no-store',
                credentials: 'same-origin', headers: { 'Content-Type': 'application/json',
                    'X-SpriteSuite-Session': token }, body: JSON.stringify(data),
                signal: AbortSignal.timeout(10000) });
            if (!response.ok) throw Error('Native loopback connection unavailable.');
            return response.json();
        }
        async function perform(command) {
            if (running.has(command.id) || command.deadline <= Date.now()) return;
            const controller = new AbortController();
            running.set(command.id, controller);
            let timer;
            try {
                const lease = await post('/native/result', { pageId, id: command.id, phase: 'started' });
                if (!lease.execute || stopped || command.deadline <= Date.now()) return;
                timer = setTimeout(() => controller.abort(), Math.max(0, command.deadline - Date.now()));
                const result = await api.execute(command.request, { signal: controller.signal });
                await post('/native/result', { pageId, id: command.id, result, snapshot: snapshot() });
            } catch (_) {
                controller.abort();
            } finally {
                clearTimeout(timer);
                running.delete(command.id);
            }
        }
        async function poll() {
            if (stopped || polling) return;
            polling = true;
            try {
                const claim = activateNext;
                activateNext = false;
                const response = await post('/native/poll', { pageId, title: doc.title,
                    activate: claim, snapshot: snapshot() });
                activated = activated || response.active;
                if (button) {
                    button.hidden = false;
                    button.textContent = response.active ? 'Mit Suite-Assistent verbunden' : 'Assistent verbinden';
                }
                for (const id of response.canceledIds || []) running.get(id)?.abort();
                for (const command of response.commands || []) void perform(command);
            } catch (_) {
                if (button) { button.hidden = false; button.textContent = 'Assistent verbinden'; }
            } finally { polling = false; }
        }
        function connect(event) {
            if (!event.isTrusted) return;
            activateNext = true;
            void poll();
        }
        function focus(event) {
            if (activated && event.isTrusted && doc.hasFocus()) connect(event);
        }
        function dispose() {
            stopped = true;
            clearInterval(timer);
            for (const controller of running.values()) controller.abort();
            button?.removeEventListener('click', connect);
            root.removeEventListener('focus', focus);
        }
        button?.addEventListener('click', connect);
        root.addEventListener('focus', focus);
        root.addEventListener('pagehide', dispose, { once: true });
        const timer = setInterval(poll, 700);
        void poll();
        return Object.freeze({ dispose });
    }
    root.SpriteNativeBridge = Object.freeze({ install });
})(typeof window === 'object' ? window : globalThis);
