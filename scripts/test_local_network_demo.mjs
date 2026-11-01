import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('local launcher serves both fictional clients without exposing files or accepting mutations', { timeout: 60000 }, async () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const child = spawn(process.execPath, ['scripts/local_network_demo.mjs', '--port', '0'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', (chunk) => { stderr += chunk; });
  try {
    const base = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Local preview did not become ready.')), 45000);
      let output = '';
      child.stdout.on('data', (chunk) => { output += chunk; const match = output.match(/LOCAL_DEMO_READY (http:\/\/127\.0\.0\.1:[0-9]+\/)/); if (match) { clearTimeout(timer); resolve(match[1]); } });
      child.once('exit', (code) => { clearTimeout(timer); reject(new Error(`Preview exited (${code}): ${stderr}`)); });
    });
    const home = await fetch(base);
    assert.match(await home.text(), /Fictional data only/);
    assert.match(home.headers.get('content-security-policy'), /connect-src 'none'/);
    assert.equal(home.headers.get('cache-control'), 'no-store');
    for (const page of ['console/', 'reporter/']) {
      const response = await fetch(base + page);
      assert.equal(response.status, 200);
      assert.match(await response.text(), /LifeJacket fictional/);
      const bundle = await fetch(base + page + 'app.js');
      assert.equal(bundle.status, 200);
      assert.match(await bundle.text(), /Fictional/);
    }
    assert.deepEqual(await (await fetch(base + 'health')).json(), { mode: 'fictional-ui-only', gcp_required: false });
    for (const path of ['.env', 'package.json', 'backend/lifejacket/config.py']) assert.equal((await fetch(base + path)).status, 404);
    assert.equal((await fetch(base, { method: 'POST' })).status, 405);
    assert.equal(await (await fetch(base + 'console/', { method: 'HEAD' })).text(), '');
  } finally {
    child.kill('SIGTERM');
  }
});
