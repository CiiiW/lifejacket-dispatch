import {build} from 'esbuild';
import {mkdir} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const output=root+'var/observation-workspace.test.mjs';
await mkdir(root+'var',{recursive:true});
await build({absWorkingDir:root,entryPoints:['scripts/tests/observationWorkspace.test.tsx'],
  bundle:true,outfile:output,platform:'node',format:'esm',jsx:'automatic',external:['jsdom'],
  nodePaths:[root+'clients/responder_console/node_modules'],
  banner:{js:"import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"}});
// Exit after all tests complete; React/jsdom may retain MessagePorts after unmount.
const result=spawnSync(process.execPath,['--test','--test-force-exit',output],{cwd:root,stdio:'inherit'});
process.exitCode=result.status??1;
