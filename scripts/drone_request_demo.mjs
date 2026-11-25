import {build} from 'esbuild';
import {execFile} from 'node:child_process';
import {existsSync} from 'node:fs';
import {promisify} from 'node:util';
import {createServer} from 'node:http';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
const output=join(root,'var','drone-request-preview');
await mkdir(output,{recursive:true});
await build({absWorkingDir:root,entryPoints:['clients/responder_console/tests/droneRequestsPreview.tsx'],
  bundle:true,outfile:join(output,'app.js'),platform:'browser',jsx:'automatic',
  alias:{'react-native':'react-native-web'},define:{'process.env':'{}',__DEV__:'false'},nodePaths:[join(root,'clients/responder_console/node_modules')]});
await writeFile(join(output,'index.html'),'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="./app.css"><title>LifeJacket fictional drone requests</title></head><body style="margin:0"><div id="root"></div><script src="./app.js"></script></body></html>');
if(!process.argv.includes('--check')){
  const routes=new Map([['/', ['text/html',await readFile(join(output,'index.html'))]],
    ['/app.js',['text/javascript',await readFile(join(output,'app.js'))]],
    ['/app.css',['text/css',await readFile(join(output,'app.css'))]]]);
  const run = promisify(execFile);
  const venvPython = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const python = process.env.LIFEJACKET_DEMO_PYTHON || (existsSync(venvPython) ? venvPython : 'python3');
  createServer(async (req,res)=>{
    res.setHeader('Cache-Control','no-store');
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src blob: data:; media-src blob:; worker-src blob:; connect-src 'self'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'");
    const path = new URL(req.url,'http://localhost').pathname;
    if (path === '/patrol' && req.method === 'POST' && req.headers['content-type'] === 'application/json') {
      if (req.headers.origin && req.headers.origin !== 'http://127.0.0.1:8084') {
        res.writeHead(403).end();
        return;
      }
      let input = '';
      for await (const chunk of req) {
        input += chunk;
        if (input.length > 2048) {
          res.writeHead(413).end();
          return;
        }
      }
      try {
        const payload = JSON.parse(input);
        const {stdout} = await run(python, [join(root, 'scripts/preview_observation_patrol.py'), JSON.stringify(payload)], {
          cwd: root, env: {...process.env, PYTHONPATH: join(root, 'backend')}, timeout: 5000,
        });
        res.writeHead(200, {'Content-Type': 'application/json'}).end(stdout);
      } catch {
        res.writeHead(422, {'Content-Type': 'application/json'}).end(JSON.stringify({
          unavailable_reason: 'Patrol preview failed. Check that the demo Python environment has the backend dependencies.',
          plan: null, simulation: null,
        }));
      }
      return;
    }
    const route=routes.get(path);
    if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
    if(!route){res.writeHead(404);res.end();return;}
    res.writeHead(200,{'Content-Type':route[0]});res.end(req.method==='HEAD'?undefined:route[1]);
  }).listen(8084,'127.0.0.1',()=>console.log('Fictional UI only: http://127.0.0.1:8084/'));
}else console.log('Drone request UI fixture built.');
