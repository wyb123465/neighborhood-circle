const { test } = require('node:test');
const assert = require('node:assert/strict');
const { AssistantRunController } = require('../assistant-state.js');
const response = (data, ok = true) => ({ ok, json: async () => data });

test('late creation is cancelled after user stops, without rendering', async () => {
  let resolve, updates = [], calls = [];
  const controller = new AssistantRunController(async (url) => { calls.push(url); if (url === '/api/assistant/runs') return new Promise(r => { resolve = r; }); return response({}); }, job => updates.push(job));
  const pending = controller.start({ task: '检查养老' });
  await controller.stop(true);
  resolve(response({ id: 'old', session_id: 's', status: 'complete' }));
  await pending;
  assert.deepEqual(updates, []);
  assert.equal(calls.at(-1), '/api/assistant/runs/old/cancel');
  assert.equal(controller.session, null);
});

test('a stale result cannot overwrite a newer completed run', async () => {
  let resolve, count = 0, updates = [];
  const controller = new AssistantRunController(async (url) => { if (url.endsWith('/cancel')) return response({}); if (++count === 1) return new Promise(r => { resolve = r; }); return response({ id: 'new', session_id: 's2', status: 'complete' }); }, job => updates.push(job.id));
  const older = controller.start({ task: '旧请求' });
  await controller.start({ task: '新请求' });
  resolve(response({ id: 'old', session_id: 's1', status: 'complete' }));
  await older;
  assert.deepEqual(updates, ['new']);
  assert.equal(controller.session, 's2');
});

test('followup includes session and server failure stays visible', async () => {
  let bodies = [], updates = [];
  const controller = new AssistantRunController(async (url, options) => { bodies.push(JSON.parse(options.body)); return bodies.length === 1 ? response({ id: 'one', session_id: 's', status: 'complete' }) : response({ detail: '会话已过期' }, false); }, job => updates.push(job));
  await controller.start({ task: '检查' });
  await controller.start({ task: '为什么' });
  assert.equal(bodies[1].session_id, 's');
  assert.equal(updates.at(-1).error, '会话已过期');
});
