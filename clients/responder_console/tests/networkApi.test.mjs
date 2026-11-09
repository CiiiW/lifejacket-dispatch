import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createNetworkApi,
  NetworkError,
  networkErrorMessage,
} from '../src/lib/networkApi.ts';

const person = {
  uid: 'fictional-user',
  getIdToken: async () => 'fictional-managed-token',
};
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status });

test('every request uses a fresh token and the selected organization header, never URL credentials', async () => {
  const requests = [];
  let tokens = 0;
  const api = createNetworkApi(
    'https://example.org/proxy/8920/',
    {
      uid: 'fixture',
      getIdToken: async () => `fixture-${++tokens}`,
    },
    'center_A',
    async (url, options) => {
      requests.push([url, options]);
      return json({});
    },
  );
  await api.me();
  await api.cases('my_center', 50);
  await api.case('case_1');
  await api.report('case_1');
  assert.equal(tokens, 4);
  assert.deepEqual(
    requests.map(([url]) => url),
    [
      'https://example.org/proxy/8920/access/me',
      'https://example.org/proxy/8920/network/cases?scope=my_center&limit=50&offset=50',
      'https://example.org/proxy/8920/network/cases/case_1',
      'https://example.org/proxy/8920/network/reports/case_1',
    ],
  );
  requests.forEach(([url, options], index) => {
    assert.equal(options.headers.Authorization, `Bearer fixture-${index + 1}`);
    assert.equal(options.headers['X-LifeJacket-Organization'], 'center_A');
    assert.equal(options.method, 'GET');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.redirect, 'error');
    assert.equal(options.credentials, 'same-origin');
    assert.ok(!url.includes('fixture-'));
  });
});

test('personal context omits organization and does not invent a role', async () => {
  let headers;
  await createNetworkApi(
    'http://localhost:8000',
    person,
    null,
    async (_, options) => {
      headers = options.headers;
      return json({ role: 'reporter' });
    },
  ).me();
  assert.deepEqual(headers, {
    Authorization: 'Bearer fictional-managed-token',
  });
});

for (const status of [401, 403, 404, 503]) {
  test(`HTTP ${status} has no retry, no legacy fallback and no provider diagnostic leak`, async () => {
    const calls = [];
    const api = createNetworkApi(
      'https://example.org',
      person,
      'A',
      async (url) => {
        calls.push(url);
        return json({ detail: 'SECRET PROVIDER DIAGNOSTIC' }, status);
      },
    );
    await assert.rejects(api.case('case_1'), (error) => {
      assert.ok(error instanceof NetworkError);
      assert.equal(error.status, status);
      assert.ok(!networkErrorMessage(error).includes('SECRET'));
      return true;
    });
    assert.deepEqual(calls, ['https://example.org/network/cases/case_1']);
  });
}

test('cancelling during token lookup never sends the late token', async () => {
  let finish;
  let calls = 0;
  const waiting = new Promise((resolve) => {
    finish = resolve;
  });
  const api = createNetworkApi(
    'https://example.org',
    { uid: 'fixture', getIdToken: () => waiting },
    null,
    async () => {
      calls++;
      return json({});
    },
  );
  const abort = new AbortController();
  const request = api.me(abort.signal);
  abort.abort();
  finish('fictional-late-token');
  await assert.rejects(request, { name: 'AbortError' });
  assert.equal(calls, 0);
});

test('no empty token or invalid case/query can cause an anonymous request', async () => {
  let calls = 0;
  const transport = async () => {
    calls++;
    return json({});
  };
  const api = createNetworkApi('https://example.org', person, null, transport);
  await assert.rejects(
    createNetworkApi(
      'https://example.org',
      { uid: 'fixture', getIdToken: async () => '' },
      null,
      transport,
    ).me(),
    { status: 401 },
  );
  for (const id of ['..', '../other', 'a/b', '?token=x', ''])
    assert.throws(() => api.case(id));
  assert.throws(() => api.cases('outside_scope', 0));
  assert.throws(() => api.cases('all_allowed', -1));
  assert.throws(() => api.cases('all_allowed', 100001));
  assert.equal(calls, 0);
});

test('only configured HTTPS or loopback endpoints are accepted', () => {
  for (const base of [
    'http://example.org',
    'https://user:secret@example.org',
    'https://example.org?key=secret',
    'https://example.org#token',
    'file:///tmp/cases',
  ]) {
    assert.throws(() => createNetworkApi(base, person, null));
  }
  assert.throws(() =>
    createNetworkApi('https://example.org', person, 'A\nX-Role:noaa'),
  );
});

test('a stalled token refresh times out without sending any request', async () => {
  let calls = 0;
  const api = createNetworkApi(
    'https://example.org',
    {
      uid: 'fixture',
      getIdToken: () => new Promise(() => {}),
    },
    null,
    async () => {
      calls++;
      return json({});
    },
    5,
  );
  await assert.rejects(api.me(), { name: 'AbortError' });
  assert.equal(calls, 0);
});

test('response mutation sends explicit confirmation and revision once, with managed authorization', async () => {
  const requests = [];
  const api = createNetworkApi(
    'https://example.org',
    person,
    'A',
    async (url, options) => {
      requests.push([url, options]);
      return json({});
    },
  );
  await api.response('case_1');
  await api.contact('case_1');
  await api.changeResponse('case_1', 3, 'animal_located', null);
  assert.equal(requests.length, 3);
  assert.equal(
    requests[2][0],
    'https://example.org/network/cases/case_1/response',
  );
  assert.equal(requests[2][1].method, 'PATCH');
  assert.deepEqual(JSON.parse(requests[2][1].body), {
    revision: 3,
    phase: 'animal_located',
    confirmed: true,
    closure_reason: null,
  });
  assert.equal(
    requests[2][1].headers.Authorization,
    'Bearer fictional-managed-token',
  );
  assert.equal(requests[2][1].headers['X-LifeJacket-Organization'], 'A');
  assert.throws(() => api.changeResponse('case_1', -1, 'accepted', null));
});

test('drone request writes carry managed auth, revisions and multipart evidence', async () => {
  const requests = [];
  const api = createNetworkApi('https://example.org', person, 'center_A',
    async (url, options) => { requests.push({url,options}); return json({}); });
  await api.drones.create('case_1', {purpose:'verification',request_key:'one'});
  await api.drones.change('case_1','request_1',{revision:3,status:'approved',confirmed:true});
  const evidence = new FormData();
  evidence.set('metadata', JSON.stringify({revision:4}));
  evidence.set('photo',new Blob(['synthetic'],{type:'image/png'}),'frame.png');
  await api.drones.upload('case_1','request_1',evidence);
  assert.deepEqual(requests.map(x=>x.options.method),['POST','PATCH','POST']);
  assert.equal(requests[2].options.body,evidence);
  assert.equal(requests[2].options.headers['Content-Type'],undefined);
  for (const {options} of requests) {
    assert.equal(options.headers.Authorization,'Bearer fictional-managed-token');
    assert.equal(options.headers['X-LifeJacket-Organization'],'center_A');
  }
  assert.equal(JSON.parse(requests[1].options.body).revision,3);
});
test('drone evidence fetch keeps authorization on the image request', async () => {
  let sent;
  const api=createNetworkApi('https://example.org',person,'center_A',async(url,options)=>{
    sent={url,options}; return new Response(new Blob(['image']));
  });
  const image=await api.drones.photo('case_1','request_1','evidence_1');
  assert.equal(await image.text(),'image');
  assert.equal(sent.options.method,'GET');
  assert.equal(sent.options.headers.Authorization,'Bearer fictional-managed-token');
  assert.equal(sent.options.cache,'no-store');
});


test('stream actions stay on the same case and use managed headers without putting publish keys in URLs',async()=>{
  const calls=[];
  const api=createNetworkApi('https://example.org',person,'A',async(url,options)=>{
    calls.push({url,options});return json({});
  }).drones;
  await api.streams('case_1','request_1');
  await api.openStream('case_1','request_1',{revision:3,label:'Rehearsal'});
  await api.streamPreview('case_1','request_1','stream_1');
  await api.captureStream('case_1','request_1','stream_1',{revision:4,frame_id:'exact-frame',description:'Review'});
  await api.endStream('case_1','request_1','stream_1',{revision:5});
  const base='https://example.org/network/cases/case_1/drone-requests/request_1/streams';
  assert.deepEqual(calls.map(c=>[c.url,c.options.method]),[
    [base,'GET'],[base,'POST'],[base+'/stream_1/preview','GET'],
    [base+'/stream_1/capture','POST'],[base+'/stream_1/end','POST']]);
  for(const call of calls){
    assert.equal(call.options.headers.Authorization,'Bearer fictional-managed-token');
    assert.equal(call.options.headers['X-LifeJacket-Organization'],'A');
    assert.equal(call.options.cache,'no-store');
  }
  assert.equal(JSON.parse(calls[3].options.body).frame_id,'exact-frame');
  assert.throws(()=>api.streamPreview('case_1','request_1','../other'));
});


test('saved-frame analysis and reminder retries carry case-scoped managed authorization',async()=>{
  const calls=[];
  const api=createNetworkApi('https://example.org',person,'A',async(url,options)=>{
    calls.push({url,options});return json({});
  }).drones;
  await api.frameAnalyses('case_1','request_1');
  await api.queueFrameAnalysis('case_1','request_1','evidence_1',{revision:4,confirmed:true,stage:'detect',request_key:'one'});
  await api.reminderStatus('case_1','request_1');
  await api.retryReminder('case_1','request_1',{revision:5,confirmed:true,notification_id:'a'.repeat(64)});
  const base='https://example.org/network/cases/case_1/drone-requests/request_1';
  assert.deepEqual(calls.map(c=>[c.url,c.options.method]),[[base+'/analysis','GET'],
    [base+'/evidence/evidence_1/analysis','POST'],[base+'/reminders','GET'],[base+'/reminders/retry','POST']]);
  for(const {options} of calls){
    assert.equal(options.headers.Authorization,'Bearer fictional-managed-token');
    assert.equal(options.headers['X-LifeJacket-Organization'],'A');
    assert.equal(options.cache,'no-store');
  }
  assert.equal(JSON.parse(calls[1].options.body).confirmed,true);
  assert.throws(()=>api.queueFrameAnalysis('case_1','request_1','../other',{}));
});
