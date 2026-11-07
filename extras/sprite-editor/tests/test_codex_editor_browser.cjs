'use strict';
// Real Edge and loopback editor. The Codex image and auth events are test doubles.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { createInterface } = require('node:readline');
const app = require('node:path').resolve(__dirname, '../../..');
const fake = [
  'import sys',
  'sys.path.insert(0, "tools")',
  'from io import BytesIO',
  'from unittest.mock import patch',
  'from contextlib import contextmanager',
  'from types import SimpleNamespace',
  'from PIL import Image',
  'from building_damage_codex import result_files',
  'from sprite_editor_local import EditorServer',
  'def execute(req, refs, output):',
  '    assert req["provider"] == "codex-chatgpt"',
  '    assert len(refs) == (2 if req.get("damageKind") == "mechanical" and req["hpAtOrBelow"] == 30 else 1)',
  '    im = Image.open(BytesIO(refs[0][1])).convert("RGBA")',
  '    channel = im.getchannel("R").point(lambda x: (x + 30) % 256)',
  '    im = Image.merge("RGBA", (channel, im.getchannel("G"), im.getchannel("B"), im.getchannel("A")))',
  '    buf = BytesIO()',
  '    im.save(buf, "PNG")',
  '    meta, files = result_files(buf.getvalue(), "synthetic-test", req)',
  '    output.mkdir()',
  '    for name, data in files.items(): (output / name).write_bytes(data)',
  '    return meta',
  '@contextmanager',
  'def session(_):',
  '    yield SimpleNamespace(connected=lambda: True)',
  'with patch("sprite_editor_local.execute", execute), patch("sprite_editor_local.session", session), EditorServer(port=0) as server:',
  '    print(server.origin, flush=True)',
  '    server.serve_forever()'
].join('\n');
(async () => {
  const server = spawn(process.env.SPRITESUITE_TEST_PYTHON || 'python', ['-u', '-c', fake], { cwd: app, stdio: ['ignore','pipe','inherit'] });
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      createInterface({input: server.stdout}).once('line', resolve);
      server.once('exit', code => reject(new Error('Editor server exited: ' + code)));
      server.once('error', reject);
    });
    const blocked = await fetch(url + '/codex/status', {method:'POST',headers:{Origin:'https://other.invalid'}});
    assert.equal(blocked.status, 403);
    browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      headless:true, args:['--no-sandbox']});
    const page = await browser.newPage({viewport:{width:1200,height:900}});
    const errors = [], calls = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', req => {
      if (req.url().includes('/codex/')) calls.push(new URL(req.url()).pathname);
    });
    await page.goto(url + '/en');
    await page.waitForFunction(() => document.documentElement.lang === 'en');
    await page.locator('[data-action="demo"]').evaluate(e => e.click());
    await page.waitForFunction(() => SpriteEditor.inspect().state.scenes.length === 1);
    await page.locator('[data-panel="damage"]').click();
    await page.getByRole('button',{name:'Check sign-in',exact:true}).click();
    await page.getByText('Connected to ChatGPT',{exact:true}).first().waitFor();
    const snapshot = () => page.evaluate(() => SpriteEditor.inspect().state);
    const before = await snapshot();
    await page.getByRole('button',{name:'Create damage models with Codex…',exact:true}).click();
    await page.locator('#modal [name=mechanical]').fill('80,30');
    await page.locator('#modal [name=fire]').fill('70');
    await page.locator('#modal-submit').click();
    await page.waitForFunction(() => !document.getElementById('modal').open, undefined, {timeout:30000});
    const afterDamage = await snapshot();
    assert.equal(afterDamage.damageProfiles[0].stages.length,3);
    assert(afterDamage.damageProfiles[0].stages.every(s => s.candidateId && s.status === 'draft'));
    assert(afterDamage.frames.some(f => f.groupId === afterDamage.damageProfiles[0].stages[0].sceneId && f.metadataStatus === 'manual'));
    await page.getByRole('button',{name:'Create building version with Codex…',exact:true}).click();
    await page.locator('#modal [name=label]').fill('Warehouse v2');
    await page.locator('#modal-submit').click();
    await page.waitForFunction(() => SpriteEditor.inspect().state.scenes.some(s => s.name === 'Warehouse v2'));
    const after = await snapshot();
    assert.deepEqual(after.frames.filter(f => f.groupId === before.scenes[0].id), before.frames);
    assert.equal(after.scenes.length,5);
    assert.deepEqual(calls,['/codex/status','/codex/generate','/codex/generate','/codex/generate','/codex/generate']);
    assert.deepEqual(errors,[]);
    console.log('PASS Edge /en: login state, 2 mechanical + 1 fire editable damage scenes, prior image, independent version, original unchanged, cross-origin rejected');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });