import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash, webcrypto } from 'node:crypto';
import vm from 'node:vm';

// Exercise the browser module's public mount() and actual event handlers. This
// deliberately small DOM adapter tests request/lifecycle behaviour, not layout,
// browser validation or rendering; those still require the browser rehearsal.
const source = readFileSync(new URL('../web/halo-evidence-workflow.js', import.meta.url), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));
const node = (extra = {}) => ({ disabled: false, isConnected: true, dataset: {}, ...extra });

class Host {
  constructor() { this.isConnected = true; this.html = ''; this.controls = []; }
  set innerHTML(html) {
    this.html = html;
    for (const control of this.controls) control.isConnected = false;
    this.select = node(); this.status = node({ textContent: '' });
    this.blocked = node({ disabled: true }); this.field = node();
    this.controls = [this.select, this.blocked, this.field];
    this.forms = {}; this.actions = [];
    for (const match of html.matchAll(/data-reference-action="([^"]+)"/g)) {
      const button = node({ dataset: { referenceAction: match[1] } });
      this.actions.push(button); this.controls.push(button);
    }
    if (html.includes('id="reference-create"')) {
      this.forms['#reference-create'] = node({ id: 'reference-create', values: new Map() });
    }
    if (html.includes('data-reference-import="W1"')) {
      this.forms['[data-reference-import]'] = node({ dataset: { referenceImport: 'W1' }, values: new Map() });
    }
  }
  get innerHTML() { return this.html; }
  querySelector(selector) {
    if (selector === '[data-reference-select]') return this.select;
    if (selector === '[data-reference-status]') return this.status;
    return null;
  }
  querySelectorAll(selector) {
    if (selector === 'button,input,select,textarea') return this.controls;
    if (selector === '[data-reference-action]') return this.actions;
    return this.forms[selector] ? [this.forms[selector]] : [];
  }
}

const record = {
  id: 'CASE1', name: 'Origin', source: 'imported reference',
  temperature_mode: 'oil_only', assessment: {},
};
const metadata = {
  asset_id: 'A1', source_class: 'synthetic', reviewer: 'Reviewer',
  calibration_reference: 'scale', configuration_reference: 'config', note: 'Synthetic source',
};
const work = {
  id: 'W1', title: 'Investigate oil', priority: 'soon', owner: 'Owner',
  asset_id: 'A1', source_class: 'synthetic', revision: 2, status: 'action_recorded',
  acceptance_note: 'Compare later evidence',
  acceptance_rules: {
    stable_minutes: 10, max_oil_c: 90, max_load_percent: 99, min_oil_drop_c: 0,
    max_load_difference_pct: 5, max_ambient_difference_c: 3, max_voltage_difference_pu: .02,
  },
  trail: [
    { kind: 'inspection', observed_at: '2026-01-01T01:31:00Z', note: 'Inspected' },
    { kind: 'action', observed_at: '2026-01-01T01:32:00Z', note: 'Action' },
  ],
  followups: [{ case_id: 'LINKED', note: 'Existing' }],
  verification: { metrics: {}, holds: ['Later evidence required'], eligible: false },
};
const workflow = (orders = [work]) => structuredClone({
  binding: { provenance: metadata, sha256: 'abc', review_scope: 'Declared' },
  work_orders: orders, limitations: ['No physical certification'],
});
const createValues = () => new Map(Object.entries({
  title: 'Review thermal mismatch', owner: 'Reviewer', priority: 'soon',
  acceptance_note: 'Compare stable later samples', stable_minutes: 10,
  max_gap_seconds: 120, max_load_percent: 99, max_oil_c: 90, min_oil_drop_c: 0,
  max_load_difference_pct: 5, max_ambient_difference_c: 3, max_voltage_difference_pu: .02,
}));
const importValues = () => new Map(Object.entries({
  recording: { size: 40, text: async () => 'elapsed_s,oil_c\n0,30' },
  name: 'Later recording', origin: '90', reviewed: 'on',
  recording_started_at: '2026-01-02T05:30:00', note: 'Later synthetic evidence',
}));

function setup(handler, { selected = record, flow = workflow(), cases = [], rawFetch } = {}) {
  const host = new Host(), callbacks = [], calls = [], downloads = [], authCalls = [], objectUrls = new Map();
  class FormDataAdapter {
    constructor(form) {
      // Real FormData omits disabled fields. Fail if the handler captures it
      // only after applying its busy state, which would silently lose data.
      assert.equal(host.field.disabled, false, 'capture form values before disabling controls');
      this.values = new Map(form.values);
    }
    get(key) { return this.values.get(key) ?? null; }
    has(key) { return this.values.has(key); }
  }
  const context = {
    window: { HaloWorkspace: { api: async (path, body) => {
      if (path === '/twin/challenges') return { cases };
      if (path.endsWith('/workflow')) return flow;
      calls.push({ path, body }); return handler(path, body);
    } }, HaloAuth: { fetch: async (path, options) => {
      authCalls.push({ path, options });
      if (!rawFetch) throw Error('Unexpected authenticated raw fetch');
      return rawFetch(path, options);
    } } },
    document: { getElementById: () => host, createElement: tag => {
      assert.equal(tag, 'a');
      return { click() { downloads.push({ name: this.download, blob: objectUrls.get(this.href) }); } };
    } }, crypto: webcrypto,
    FormData: FormDataAdapter, console, Blob,
    setTimeout: fn => { fn(); return 0; },
    URL: { createObjectURL: blob => { const key = 'blob:' + webcrypto.randomUUID(); objectUrls.set(key, blob); return key; }, revokeObjectURL: key => objectUrls.delete(key) },
  };
  vm.runInNewContext(source, context, { filename: 'halo-evidence-workflow.js' });
  return {
    host, callbacks, calls, downloads, authCalls,
    downloadRaw: (...args) => context.window.HaloEvidenceWorkflow.downloadRaw(...args),
    mount: () => context.window.HaloEvidenceWorkflow.mount({ record: selected, onCase: value => callbacks.push(value) }),
  };
}
const submit = form => form.onsubmit({ preventDefault() {} });
const action = (host, name) => host.actions.find(button => button.dataset.referenceAction === name);

test('lost write response retries the same intent and preserves entered metadata', async () => {
  let fail = true;
  const app = setup(async () => { if (fail) { fail = false; throw Error('Lost response'); } return {}; }, { flow: workflow([]) });
  await app.mount();
  const form = app.host.forms['#reference-create']; form.values = createValues();
  submit(form); await settle();
  assert.match(app.host.status.textContent, /Lost response/);
  submit(form); await settle();
  assert.equal(app.calls.length, 2);
  assert.equal(app.calls[0].body.request_id, app.calls[1].body.request_id);
  assert.equal(app.calls[0].body.owner, 'Reviewer');
  assert.equal(app.calls[0].body.acceptance_rules.max_oil_c, 90);
});

test('identical intent survives panel remount while an edited payload gets a new identity', async () => {
  const app = setup(async () => { throw Error('No response'); }, { flow: workflow([]) });
  await app.mount();
  let form = app.host.forms['#reference-create']; form.values = createValues();
  submit(form); await settle();
  await app.mount(); form = app.host.forms['#reference-create']; form.values = createValues();
  submit(form); await settle();
  assert.equal(app.calls[0].body.request_id, app.calls[1].body.request_id);
  form.values.set('owner', 'Another reviewer'); submit(form); await settle();
  assert.notEqual(app.calls[2].body.request_id, app.calls[0].body.request_id);
});

test('busy controls suppress duplicate submissions and restore their previous disabled state', async () => {
  let release;
  const app = setup(() => new Promise(resolve => { release = resolve; }), { flow: workflow([]) });
  await app.mount();
  const form = app.host.forms['#reference-create']; form.values = createValues();
  submit(form);
  assert.ok(app.host.controls.every(control => control.disabled));
  submit(form); assert.equal(app.calls.length, 1);
  release({}); await settle();
  assert.equal(app.host.field.disabled, false);
  assert.equal(app.host.select.disabled, false);
  assert.equal(app.host.blocked.disabled, true);
});

test('failed submission restores controls without enabling an originally blocked action', async () => {
  const app = setup(async () => { throw Error('Write failed'); }, { flow: workflow([]) });
  await app.mount();
  const form = app.host.forms['#reference-create']; form.values = createValues();
  submit(form); await settle();
  assert.equal(app.host.field.disabled, false);
  assert.equal(app.host.select.disabled, false);
  assert.equal(app.host.blocked.disabled, true);
});

test('partial follow-up resumes its created recording and completed assessment with a stable link identity', async () => {
  let imports = 0, assessments = 0, links = 0; const linkIds = [];
  const app = setup(async (path, body) => {
    if (path.endsWith('/import')) { imports++; return { id: 'FOLLOW1' }; }
    if (path.endsWith('/assess')) {
      assessments++; if (assessments === 1) throw Error('Assessment response lost'); return {};
    }
    if (path.endsWith('/followup')) {
      links++; linkIds.push(body.request_id);
      if (links === 1) throw Error('Link response lost'); return {};
    }
    throw Error(path);
  });
  await app.mount();
  const form = app.host.forms['[data-reference-import]']; form.values = importValues();
  for (let attempt = 0; attempt < 3; attempt++) { submit(form); await settle(); }
  assert.equal(imports, 1);
  assert.equal(assessments, 2);
  assert.equal(links, 2);
  assert.equal(linkIds[0], linkIds[1]);
});

test('lost import response reuses the import request ID instead of creating a second recording', async () => {
  const importIds = []; let failed = false;
  const app = setup(async (path, body) => {
    if (path.endsWith('/import')) {
      importIds.push(body.request_id);
      if (!failed) { failed = true; throw Error('Import response lost'); }
      return { id: 'FOLLOW1' };
    }
    return {};
  });
  await app.mount();
  const form = app.host.forms['[data-reference-import]']; form.values = importValues();
  submit(form); await settle(); submit(form); await settle();
  assert.equal(importIds.length, 2);
  assert.equal(importIds[0], importIds[1]);
});

test('follow-up choices exclude linked, concealed, unassessed and mismatched records', async () => {
  const eligible = { id: 'ELIGIBLE', name: 'Later record', source: 'imported reference', assessed: true, asset_id: 'A1', source_class: 'synthetic' };
  const app = setup(async () => ({}), { cases: [
    eligible, { ...eligible, id: 'LINKED' }, { ...eligible, id: 'CASE1' },
    { ...eligible, id: 'CONCEALED', source: 'concealed synthetic' },
    { ...eligible, id: 'UNASSESSED', assessed: false },
    { ...eligible, id: 'OTHER-ASSET', asset_id: 'A2' },
    { ...eligible, id: 'OTHER-SOURCE', source_class: 'recorded_oil_reference' },
  ] });
  await app.mount();
  // Inspect only the follow-up form: the global saved-case picker intentionally
  // permits selecting an originating recording from another asset.
  const followup = app.host.html.match(/<form[^>]*data-reference-followup="W1"[\s\S]*?<\/form>/)?.[0];
  assert.ok(followup);
  assert.ok(followup.includes('<option value="ELIGIBLE">'));
  for (const id of ['LINKED', 'CASE1', 'CONCEALED', 'UNASSESSED', 'OTHER-ASSET', 'OTHER-SOURCE']) {
    assert.ok(!followup.includes(`<option value="${id}">`), id);
  }
});

test('late assessment response cannot restore a recording after navigation', async () => {
  let release;
  const app = setup(() => new Promise(resolve => { release = resolve; }), { selected: { ...record, assessment: null }, flow: workflow([]) });
  await app.mount();
  const pending = action(app.host, 'assess').onclick();
  app.host.isConnected = false; release(record); await pending;
  assert.equal(app.callbacks.length, 0);
});

test('navigation during follow-up import stops assessment and link continuations', async () => {
  let release;
  const app = setup(() => new Promise(resolve => { release = resolve; }));
  await app.mount();
  const form = app.host.forms['[data-reference-import]']; form.values = importValues();
  submit(form); await settle();
  assert.equal(app.calls.length, 1); assert.ok(app.calls[0].path.endsWith('/import'));
  app.host.isConnected = false; release({ id: 'FOLLOW1' }); await settle();
  assert.equal(app.calls.length, 1);
  assert.equal(app.callbacks.length, 0);
});

test('navigation during reveal prevents revealing additional linked records or selecting the old case', async () => {
  let release;
  const app = setup(() => new Promise(resolve => { release = resolve; }));
  await app.mount();
  const pending = action(app.host, 'reveal').onclick();
  app.host.isConnected = false; release({}); await pending;
  assert.equal(app.calls.length, 1);
  assert.ok(app.calls[0].path.endsWith('/CASE1/reveal'));
  assert.equal(app.callbacks.length, 0);
});

test('evidence download preserves exact server bytes, including integer-valued floats, through the auth helper', async () => {
  const canonical = '{"reading":10.0,"reviewer":"Reviewer","scale":1.25}';
  const sha = createHash('sha256').update(canonical).digest('hex');
  const artifact = `{\n  "reading": 10.0,\n  "reviewer": "Reviewer",\n  "scale": 1.25,\n  "sha256": "${sha}"\n}`;
  const app = setup(async () => { throw Error('The parsed API must not handle this download'); }, {
    flow: workflow([]), rawFetch: async () => ({
      ok: true, blob: async () => new Blob([artifact], { type: 'application/json' }),
      json: async () => { throw Error('Do not parse and normalize exported numbers'); },
    }),
  });
  await app.mount(); await action(app.host, 'export').onclick();
  assert.equal(app.authCalls.length, 1);
  assert.equal(app.authCalls[0].path, '/api/halo/twin/challenges/CASE1/workflow/export');
  assert.equal(app.authCalls[0].options.method, 'GET');
  assert.equal(app.authCalls[0].options.cache, 'no-store');
  assert.equal(app.downloads.length, 1);
  assert.equal(app.downloads[0].name, 'halo-recording-maintenance-evidence.json');
  const bytes = Buffer.from(await app.downloads[0].blob.arrayBuffer());
  assert.deepEqual(bytes, Buffer.from(artifact, 'utf8'));
  assert.match(bytes.toString(), /"reading": 10\.0/);
  assert.equal(app.calls.length, 0);
  // Demonstrate why a seemingly equivalent numeric JSON round-trip is invalid.
  const normalized = JSON.parse(canonical);
  assert.notEqual(createHash('sha256').update(JSON.stringify(normalized)).digest('hex'), sha);
});

test('export refusal stays inline and does not create a download', async () => {
  const app = setup(async () => ({}), {
    rawFetch: async () => ({ ok: false, status: 409, json: async () => ({ detail: 'Reveal every linked follow-up first.' }) }),
  });
  await app.mount(); await action(app.host, 'export').onclick();
  assert.match(app.host.status.textContent, /Reveal every linked follow-up first/);
  assert.equal(app.downloads.length, 0);
  assert.equal(app.host.field.disabled, false);
});

test('navigation during authenticated export does not download stale evidence', async () => {
  let release;
  const app = setup(async () => ({}), { rawFetch: () => new Promise(resolve => { release = resolve; }) });
  await app.mount();
  const pending = action(app.host, 'export').onclick(); app.host.isConnected = false;
  release({ ok: true, blob: async () => { throw Error('Stale response must not be consumed'); } });
  await pending; assert.equal(app.downloads.length, 0);
});

test('public raw-download helper handles a case endpoint without parsing its frozen assessment', async () => {
  const artifact = '{"assessment":{"result":{"offset_c":10.0},"sha256":"stored-hash"}}';
  const app = setup(async () => { throw Error('Parsed API is not an export'); }, {
    rawFetch: async () => ({ ok: true, blob: async () => new Blob([artifact]) }),
  });
  await app.downloadRaw('/twin/challenges/CASE1', 'CASE1.json');
  assert.equal(app.authCalls[0].path, '/api/halo/twin/challenges/CASE1');
  assert.equal(app.downloads[0].name, 'CASE1.json');
  assert.equal(await app.downloads[0].blob.text(), artifact);
});
