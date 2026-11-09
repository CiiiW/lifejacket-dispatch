import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../clients/responder_console/package.json',import.meta.url));
const {build}=require('esbuild');
const root=fileURLToPath(new URL('../',import.meta.url));
await mkdir(root+'var/drone-stream-preview',{recursive:true});
await build({absWorkingDir:root,entryPoints:['clients/responder_console/tests/droneStreamPreview.tsx'],bundle:true,
  outfile:root+'var/drone-stream-preview/app.js',platform:'browser',jsx:'automatic',define:{'process.env':'{}'},
  nodePaths:[root+'clients/responder_console/node_modules']});
await writeFile(root+'var/drone-stream-preview/index.html',
  '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LifeJacket stream rehearsal</title><style>'+
  'body{margin:0;background:#092332;color:#eaf4f7;font:16px system-ui}h1,h2,h3{line-height:1.2}label{display:flex;flex-direction:column;gap:6px;margin:12px 0}input,select,button{font:inherit;padding:10px;border-radius:7px;border:1px solid #63818c;background:#113547;color:white}button{cursor:pointer;margin:6px 8px 6px 0;background:#146d83}button:disabled{opacity:.45;cursor:default}.lj-panel,.lj-notice{padding:16px;background:#143a4b;border-radius:10px;margin:16px 0}.lj-muted,.lj-meta{color:#afc8d1}.lj-case{display:flex;flex-direction:column;text-align:left}.lj-error{color:#ffc0a9}dt{font-weight:bold}dd{margin:4px 0 12px}a{color:#61d7ec}form{max-width:680px}' +
  '</style></head><body><div id="root"></div><script src="./app.js"></script></body></html>');
console.log('Built connected synthetic stream rehearsal UI.');
