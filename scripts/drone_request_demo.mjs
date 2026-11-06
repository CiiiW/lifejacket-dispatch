import {build} from 'esbuild';
import {createServer} from 'node:http';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url));
const output=join(root,'var','drone-request-preview');
await mkdir(output,{recursive:true});
await build({absWorkingDir:root,entryPoints:['clients/responder_console/tests/droneRequestsPreview.tsx'],
  bundle:true,outfile:join(output,'app.js'),platform:'browser',jsx:'automatic',
  define:{'process.env':'{}'},nodePaths:[join(root,'clients/responder_console/node_modules')]});
await writeFile(join(output,'index.html'),'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LifeJacket fictional drone requests</title></head><body style="margin:0"><div id="root"></div><script src="./app.js"></script></body></html>');
if(!process.argv.includes('--check')){
  const routes=new Map([['/', ['text/html',await readFile(join(output,'index.html'))]],
    ['/app.js',['text/javascript',await readFile(join(output,'app.js'))]]]);
  createServer((req,res)=>{
    res.setHeader('Cache-Control','no-store');
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src blob: data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'");
    const route=routes.get(new URL(req.url,'http://localhost').pathname);
    if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
    if(!route){res.writeHead(404);res.end();return;}
    res.writeHead(200,{'Content-Type':route[0]});res.end(req.method==='HEAD'?undefined:route[1]);
  }).listen(8084,'127.0.0.1',()=>console.log('Fictional UI only: http://127.0.0.1:8084/'));
}else console.log('Drone request UI fixture built.');
