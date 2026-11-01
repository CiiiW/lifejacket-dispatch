#!/usr/bin/env node
/** Fictional UI demos only. Never imports the backend, reads .env, or enables auth. */
import { build } from 'esbuild';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = join(root, 'var', 'local-network-demo');
const clients = { console: 'responder_console', reporter: 'reporter_app' };
const { values } = parseArgs({ options: { install: { type: 'boolean' }, check: { type: 'boolean' }, port: { type: 'string', default: '8082' } } });
const [major, minor] = process.versions.node.split('.').map(Number);
if (major < 24 || (major === 24 && minor < 3)) throw new Error('Use Node.js 24.3 or newer, matching the client lockfiles.');

if (values.install) {
  const npm = process.env.npm_execpath;
  if (!npm) throw new Error('Run npm run setup:demos from the repository root.');
  for (const folder of Object.values(clients)) {
    const result = spawnSync(process.execPath, [npm, 'ci', '--prefix', join(root, 'clients', folder)], { cwd: root, stdio: 'inherit' });
    if (result.error || result.status !== 0) throw new Error(`Dependency installation failed for ${folder}.`);
  }
  console.log('Demo dependencies installed. Run npm run demo:network.');
} else {
  for (const [name, folder] of Object.entries(clients)) {
    const client = join(root, 'clients', folder);
    try { await access(join(client, 'node_modules', 'react', 'package.json')); }
    catch { throw new Error('Client dependencies are missing. Run npm run setup:demos first.'); }
    const entry = name === 'console' ? 'networkPreview.tsx' : 'phoneReporterPreview.tsx';
    const directory = join(output, name);
    await mkdir(directory, { recursive: true });
    await build({
      absWorkingDir: client,
      entryPoints: [join(client, 'tests', entry)],
      bundle: true, outfile: join(directory, 'app.js'), platform: 'browser',
      define: { 'process.env': '{}' }, jsx: 'automatic',
      nodePaths: [join(client, 'node_modules')],
    });
    await writeFile(join(directory, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>LifeJacket fictional ${name} demo</title></head><body style="margin:0"><div id="root"></div><script src="./app.js"></script></body></html>`);
  }
  if (values.check) {
    console.log('Both fictional demos built successfully. No GCP credentials or backend needed.');
  } else {
    const port = Number(values.port);
    if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('Use --port with a number from 0 to 65535.');
    const routes = new Map();
    for (const name of Object.keys(clients)) {
      routes.set(`/${name}/`, ['text/html; charset=utf-8', await readFile(join(output, name, 'index.html'))]);
      routes.set(`/${name}/app.js`, ['text/javascript; charset=utf-8', await readFile(join(output, name, 'app.js'))]);
    }
    const home = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LifeJacket local demos</title><style>body{background:#0b132b;color:#f4f7fb;font:18px/1.6 system-ui;padding:36px;max-width:800px;margin:auto}a{color:#48cae4}li{margin:18px 0}</style></head><body><h1>LifeJacket local demos</h1><p>Fictional data only. No GCP login, real SMS, model calls, backend or database.</p><ul><li><a href="./console/">Rescue dashboard</a> — choose Fictional California Center, select a case and try confirmed response updates.</li><li><a href="./reporter/">Reporter app</a> — choose a completed fictional draft and use fixture SMS code 123456.</li></ul><p>The two demos are independent UI fixtures; they do not share case state. Backend authorization and persistence have separate automated tests.</p><p>Do not enter real personal details or upload real incident photos. Stop with Ctrl+C.</p></body></html>`;
    routes.set('/', ['text/html; charset=utf-8', Buffer.from(home)]);
    routes.set('/health', ['application/json', Buffer.from(JSON.stringify({ mode: 'fictional-ui-only', gcp_required: false }))]);
    const server = createServer((request, response) => {
      response.setHeader('Cache-Control', 'no-store');
      response.setHeader('X-Content-Type-Options', 'nosniff');
      response.setHeader('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'");
      if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405, { Allow: 'GET, HEAD' }); response.end(); return; }
      const path = new URL(request.url, 'http://localhost').pathname;
      if (path === '/console' || path === '/reporter') { response.writeHead(303, { Location: `.${path}/` }); response.end(); return; }
      const route = routes.get(path);
      if (!route) { response.writeHead(404); response.end(); return; }
      response.writeHead(200, { 'Content-Type': route[0] });
      response.end(request.method === 'HEAD' ? undefined : route[1]);
    });
    server.on('error', (error) => { console.error(error.code === 'EADDRINUSE' ? 'Port is busy. Run npm run demo:network -- --port 8083' : error.message); process.exitCode = 1; });
    server.listen(port, '127.0.0.1', () => {
      const actual = server.address().port;
      console.log(`LOCAL_DEMO_READY http://127.0.0.1:${actual}/`);
      console.log('Fictional UI only. Open this URL in your browser. Stop with Ctrl+C.');
    });
    process.on('SIGINT', () => server.close());
    process.on('SIGTERM', () => server.close());
  }
}
