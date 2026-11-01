import test from 'node:test';
import assert from 'node:assert/strict';
import { createPhoneReporterApi } from '../src/lib/phoneReporterApi.ts';

const draft = { draft_key: 'FICTIONAL-KEY', turn: { incident_id: 'case_a' } };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
test('draft credentials and fresh managed tokens use protected POST bodies, never URL or role claims', async () => {
  const requests = []; let count = 0;
  const user = { uid:'fixture', phoneNumber:'+12025550123', getIdToken:async()=>`fixture-token-${++count}` };
  const api = createPhoneReporterApi('https://example.org/api/', async (url, options) => { requests.push([url,options]); return json({}); });
  await api.turn(draft, { action:'read' }); await api.submit(draft,user,['text']); await api.reports(user); await api.status('case_a',user); await api.presence('case_a',user,'left');
  assert.equal(count,4);
  assert.deepEqual(requests.map(([url])=>url), ['https://example.org/api/reporter/drafts/case_a/turn','https://example.org/api/reporter/drafts/case_a/submit','https://example.org/api/reporter/reports','https://example.org/api/reporter/reports/case_a/status','https://example.org/api/reporter/reports/case_a/presence']);
  requests.forEach(([url,options])=>{ assert.equal(options.method,'POST'); assert.equal(options.cache,'no-store'); assert.equal(options.redirect,'error'); assert.equal(options.credentials,'same-origin'); assert.ok(!url.includes('TOKEN') && !url.includes('KEY')); });
  assert.equal(JSON.parse(requests[1][1].body).id_token,'fixture-token-1');
  assert.equal(JSON.parse(requests[1][1].body).phone_number,undefined);
});
test('invalid API locations and invalid IDs never make requests', () => {
  for(const base of ['http://example.org','https://name:pass@example.org','https://example.org?token=x','https://example.org#x']) assert.throws(()=>createPhoneReporterApi(base));
  let sent=0; const api=createPhoneReporterApi('http://localhost:8000',async()=>{sent++;return json({});});
  assert.throws(()=>api.status('../other',{getIdToken:async()=>''})); assert.equal(sent,0);
});
test('token lookup timeout sends no late request', async () => {
  let sent=0,resolveToken;
  const api=createPhoneReporterApi('https://example.org',async()=>{sent++;return json({});},10);
  const promise=api.reports({getIdToken:()=>new Promise((resolve)=>{resolveToken=resolve;})});
  await assert.rejects(promise,/timed out/); resolveToken('late'); await new Promise((resolve)=>setTimeout(resolve,20)); assert.equal(sent,0);
});
test('provider diagnostics are never echoed and mutations are never retried', async () => {
  let sent=0; const api=createPhoneReporterApi('https://example.org',async()=>{sent++;return json({detail:'SECRET DIAGNOSTIC'},503);});
  await assert.rejects(api.start(),/Reporting setup/); assert.equal(sent,1);
});
