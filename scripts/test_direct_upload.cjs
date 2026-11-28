#!/usr/bin/env node
'use strict';
/* Contract tests for the browser upload module: no browser, network or customer data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../assets/direct-upload.js'), 'utf8');
const response = (body, status = 200) => ({ok:status >= 200 && status < 300, status, json:async () => body});
const flush = async () => { for (let i = 0; i < 100; i++) await Promise.resolve(); };
const HANG = Symbol('pending response');

function fixture(options = {}) {
  const events = new Map(), windowEvents = new Map(), requests = [], puts = [], tabs = [], timers = new Map();
  let nodes, choices, time = 0, timerId = 0, createCount = 0, submitCount = 0, statusCount = 0;
  class Element {
    constructor(id = '') { this.id = id; this.value = ''; this.checked = false; this.files = []; this.dataset = {}; this.disabled = false; this.hidden = false; this.textContent = ''; this.children = []; this.attributes = {}; this.classList = {toggle:() => {}}; }
    setAttribute(name, value) { this.attributes[name] = value; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); }
    replaceChildren(...children) { this.children = children; }
    closest(selector) {
      if (selector === '#sheet-body') return nodes.get('sheet-body');
      if (selector === '#direct-upload-form') return nodes.get('direct-upload-form');
      if (selector.includes('[data-upload-choice]') && this.dataset.uploadChoice) return this;
      return selector.split(',').some(part => part.trim() === '#' + this.id) ? this : null;
    }
  }
  function mount() {
    nodes = new Map(['sheet-body','direct-upload-form','upload-kind','upload-format','upload-phone','upload-name','upload-comment','upload-consent','upload-files','upload-submit','upload-cancel','upload-new','upload-status','upload-availability','upload-recheck','upload-progress','upload-files-summary','upload-file-list'].map(id => [id, new Element(id)]));
    nodes.get('upload-kind').value = 'photos';
    nodes.get('upload-consent').dataset.consentVersion = '2026-11-26';
    nodes.get('upload-recheck').dataset.formUrl = 'https://fotomag-izhevsk.dynv6.net:8443/#send-files';
    nodes.get('direct-upload-form').reportValidity = () => true;
    nodes.get('direct-upload-form').reset = () => {
      for (const key of ['kind','format','phone','name','comment']) nodes.get('upload-' + key).value = key === 'kind' ? 'photos' : '';
      nodes.get('upload-consent').checked = false; nodes.get('upload-files').files = [];
    };
    choices = ['photos','documents','id450'].map(kind => { const el = new Element(); el.dataset.uploadChoice = kind; return el; });
  }
  mount();
  const document = {
    getElementById:id => nodes.get(id),
    querySelector:selector => selector.startsWith('meta') ? {content:options.endpoint === undefined ? 'https://receiver.test/' : options.endpoint} : null,
    querySelectorAll:selector => selector.includes('input,') ? [...['kind','format','phone','name','comment','consent','files'].map(key => nodes.get('upload-' + key)), ...choices] : choices,
    createElement:() => new Element(),
    addEventListener:(type, handler) => events.set(type, [...events.get(type) || [], handler])
  };
  const created = body => ({order_id:'order-1', receipt:'FM-TEST-1', upload_token:'test-only-token', files:body.files.map((file, i) => ({file_id:'file-' + i}))});
  async function fetch(url, init) {
    const requestPath = new URL(url).pathname, data = init.body ? JSON.parse(init.body) : undefined;
    const call = {path:requestPath, method:init.method, data, aborted:false}; requests.push(call);
    if (requestPath === '/api/orders') createCount++;
    if (requestPath.endsWith('/submit')) submitCount++;
    if (requestPath.endsWith('/status')) statusCount++;
    return new Promise((resolve, reject) => {
      const abort = () => { call.aborted = true; const error = new Error('Aborted'); error.name = 'AbortError'; reject(error); };
      init.signal.addEventListener('abort', abort, {once:true});
      if (init.signal.aborted) return abort();
      let body;
      try {
        body = options.fetch?.({path:requestPath, data, createCount, submitCount, statusCount, created});
        if (body === HANG) return;
        if (body instanceof Error) throw body;
        if (body === undefined) {
          if (requestPath === '/api/health') body = {accepting_uploads:true};
          else if (requestPath === '/api/orders') body = created(data);
          else if (requestPath.endsWith('/submit')) body = {received:true, receipt:'FM-TEST-1'};
          else if (requestPath.endsWith('/status')) body = {receipt:'FM-TEST-1', status:'queued', downloaded_to_pc:false};
          else throw new Error('Unexpected request: ' + requestPath);
        }
        Promise.resolve().then(() => resolve(response(body)));
      } catch (error) { reject(error); }
    });
  }
  class XHR {
    constructor() { this.upload = {}; this.status = 200; this.aborted = false; }
    open(method, url) { this.path = new URL(url).pathname; }
    setRequestHeader() {}
    send(file) {
      const record = {path:this.path, file, xhr:this}; puts.push(record);
      const action = options.put?.(record, puts.length);
      if (action === HANG) return;
      queueMicrotask(() => {
        if (this.aborted) return;
        if (action === 'error') return this.onerror();
        this.upload.onprogress?.({lengthComputable:true, loaded:file.size}); this.onload();
      });
    }
    abort() { this.aborted = true; this.onabort?.(); }
  }
  const window = {open:(...args) => { tabs.push(args); return null; }, addEventListener:(type, handler) => windowEvents.set(type, handler)};
  const context = vm.createContext({document, window, fetch, XMLHttpRequest:XHR, URL, AbortController, crypto:webcrypto, Uint8Array,
    setTimeout:(fn, delay) => { const id = ++timerId; timers.set(id, {at:time + delay, fn}); return id; }, clearTimeout:id => timers.delete(id)});
  vm.runInContext(source, context, {filename:'direct-upload.js'});
  const emit = (type, target) => { const event = {target:typeof target === 'string' ? nodes.get(target) : target, preventDefault:() => {}}; for (const handler of events.get(type) || []) handler(event); };
  return {
    api:window.FotoMagDirectUpload, requests, puts, tabs, timers,
    node:id => nodes.get(id),
    click:id => emit('click', id),
    fill:(key, value) => { const el = nodes.get('upload-' + key); if (key === 'consent') el.checked = value; else el.value = value; emit('input', el); },
    files:files => { nodes.get('upload-files').files = files; emit('change', 'upload-files'); },
    submit:() => emit('submit', 'direct-upload-form'),
    beforeUnload:() => { let prevented = false; windowEvents.get('beforeunload')({preventDefault:() => { prevented = true; }}); return prevented; },
    reopen:() => { window.FotoMagDirectUpload.onLeave(); mount(); window.FotoMagDirectUpload.onView(); },
    tick:async delta => {
      const end = time + delta; let iterations = 0;
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= end).sort((a,b) => a[1].at - b[1].at)[0];
        if (!next) break;
        assert.ok(++iterations < 100, 'Timer loop did not settle');
        time = next[1].at; timers.delete(next[0]); next[1].fn(); await flush();
      }
      time = end; await flush();
    }
  };
}
const file = (name, size = 1024) => ({name, size});
async function prepare(f, files = [file('нейтральный.jpg'), file('документ.pdf')]) {
  await flush(); f.files(files); f.fill('consent', true); await flush();
}

(async () => {
  for (const [format, label] of [['35x45','35×45 мм, 8 шт.'], ['3x4','3×4 см, 6 шт.'], ['4x6','4×6 см, 4 шт.']]) {
    for (const note of ['', 'Сделайте срочно', 'Фото на документы 35×45 мм, 8 шт. — 450 ₽\nБез ретуши', 'Фото на документы 35×45 мм, 8 шт. — 450 ₽ Без ретуши']) {
      const f = fixture(); await prepare(f);
      f.fill('kind', 'id450'); f.fill('format', format); f.fill('comment', note);
      f.submit(); await flush();
      const body = f.requests.find(r => r.path === '/api/orders').data;
      const expectedNote = note.startsWith('Фото на документы') ? 'Без ретуши' : note;
      assert.equal(body.kind, 'id450');
      assert.equal(body.comment, 'Фото на документы ' + label + ' — 450 ₽' + (expectedNote ? '\n' + expectedNote : ''));
      assert.equal(f.node('upload-format').disabled, true);
    }
  }
  {
    const f = fixture(); await prepare(f);
    f.fill('kind', 'id450'); f.fill('format', 'constructor'); f.submit(); await flush();
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 0);
    f.fill('format', '4x6'); f.fill('comment', 'я'.repeat(500)); f.submit(); await flush();
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 0);
    assert.equal(f.node('upload-comment').value.length, 500, 'Never truncate client instructions');
    f.fill('comment', 'я'.repeat(500 - 'Фото на документы 4×6 см, 4 шт. — 450 ₽'.length - 1));
    f.submit(); await flush();
    assert.equal(f.requests.find(r => r.path === '/api/orders').data.comment.length, 500);
  }
  console.log('PASS all ID formats survive empty/edited comments; stale heading replaced; API length enforced without truncation');
  {
    let delivered = false, accepting = true, offline = false;
    const f = fixture({fetch:({path}) => path === '/api/health' ? {accepting_uploads:accepting} : path.endsWith('/status') ? offline ? new Error('Temporary network failure') : {receipt:'FM-TEST-1', status:delivered?'received':'pending', downloaded_to_pc:delivered} : undefined});
    await prepare(f); f.submit(); await flush(); await f.tick(40000);
    assert.doesNotMatch(f.api.getState().status, /доставлена на компьютер/);
    delivered = true; accepting = false; f.click('upload-recheck'); await flush(); await f.tick(5000);
    assert.match(f.api.getState().status, /доставлена на компьютер/);
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 1);
    offline = true; f.click('upload-recheck'); await flush(); await f.tick(40000);
    assert.match(f.api.getState().status, /доставлена на компьютер/);
    f.reopen(); await flush(); await f.tick(40000);
    assert.match(f.api.getState().status, /доставлена на компьютер/);
    console.log('PASS late delivery recheck while intake closed; confirmed delivery survives errors/reopen; no duplicate order');
  }
  {
    const f = fixture({endpoint:''}); await flush();
    f.fill('kind', 'id450'); f.fill('format', '4x6');
    f.files([file('client_<img onerror=alert(1)>.pdf')]);
    assert.equal(f.node('upload-file-list').children[0].children[0].textContent, 'client_<img onerror=alert(1)>.pdf');
    f.click('upload-recheck'); const url = new URL(f.tabs[0][0]);
    assert.equal(url.searchParams.get('kind'), 'id450'); assert.equal(url.searchParams.get('format'), '4x6');
    assert.equal(url.hash, '#send-files'); assert.equal(f.requests.length, 0); assert.equal(f.node('upload-submit').disabled, true);
    f.node('upload-recheck').dataset.formUrl = 'https://attacker.test/#send-files'; f.click('upload-recheck'); assert.equal(f.tabs.length, 1);
    console.log('PASS public API disabled, safe filenames, allowlisted LAN context');
  }
  {
    const f = fixture({fetch:({path}) => path.endsWith('/status') ? {receipt:'FM-TEST-1', status:'received', downloaded_to_pc:true} : undefined});
    await prepare(f, [file('нейтральный.jpg'), file('документ.pdf'), file('large.jpg', 25 * 1024 * 1024)]);
    f.submit(); f.submit(); await flush();
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 1); assert.equal(f.puts.length, 3);
    assert.equal(f.api.getState().received, true); assert.match(f.api.getState().status, /принята сервером/);
    assert.doesNotMatch(f.api.getState().status, /доставлена на компьютер/);
    f.reopen(); await flush(); assert.equal(f.api.getState().receipt, 'FM-TEST-1'); assert.equal(f.node('upload-file-list').children.length, 3);
    assert.equal(f.node('upload-submit').disabled, true);
    await f.tick(5000); assert.match(f.api.getState().status, /доставлена на компьютер/);
    assert.equal(f.api.newOrder(), true); assert.equal(f.api.getState().received, false); assert.equal(f.node('upload-file-list').children.length, 0);
    console.log('PASS duplicate click blocked, 25 MiB accepted, receipt restored, delivery separately confirmed');
  }
  {
    const f = fixture({put:(record, count) => count === 2 ? HANG : undefined}); await prepare(f);
    f.submit(); await flush(); assert.equal(f.puts.length, 2); assert.equal(f.beforeUnload(), true);
    f.reopen(); await flush(); assert.equal(f.node('upload-files').disabled, true); assert.equal(f.api.getState().sending, true);
    f.api.cancel(); await flush(); assert.equal(f.puts[1].xhr.aborted, true); assert.equal(f.api.getState().received, false); assert.equal(f.beforeUnload(), false);
    f.submit(); await flush();
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 1);
    assert.equal(f.puts.filter(r => r.path.endsWith('/file-0')).length, 1); assert.equal(f.puts.filter(r => r.path.endsWith('/file-1')).length, 2);
    assert.equal(f.api.getState().received, true); f.api.newOrder();
    console.log('PASS cancellation aborts XHR, preserves draft and resumes only unfinished files');
  }
  {
    const f = fixture({fetch:({path, createCount}) => path === '/api/orders' && createCount === 1 ? HANG : undefined}); await prepare(f);
    f.submit(); await flush(); f.api.cancel(); await flush(); assert.equal(f.requests.find(r => r.path === '/api/orders').aborted, true);
    assert.equal(f.api.getState().received, false); f.submit(); await flush();
    const creates = f.requests.filter(r => r.path === '/api/orders'); assert.equal(creates.length, 2); assert.equal(creates[0].data.request_key, creates[1].data.request_key);
    assert.equal(f.api.getState().received, true); f.api.newOrder();
    console.log('PASS ambiguous create retries the same idempotency key');
  }
  {
    const f = fixture({fetch:({path}) => path.endsWith('/submit') ? new Error('Response lost after server acceptance') : path.endsWith('/status') ? {receipt:'FM-TEST-1', status:'pending', downloaded_to_pc:false} : undefined}); await prepare(f);
    f.submit(); await flush(); assert.equal(f.api.getState().pending, true); assert.equal(f.api.getState().received, false);
    assert.equal(f.api.newOrder(), false); assert.equal(f.node('upload-files').disabled, true);
    f.submit(); await flush(); assert.equal(f.api.getState().received, true); assert.doesNotMatch(f.api.getState().status, /доставлена на компьютер/);
    assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 1); assert.equal(f.requests.filter(r => r.path.endsWith('/submit')).length, 1); assert.equal(f.puts.length, 2);
    f.api.newOrder(); assert.equal(f.timers.size, 0);
    console.log('PASS actual pending status resolves ambiguous submit as server receipt, never PC delivery');
  }
  {
    const f = fixture({fetch:({path}) => path.endsWith('/submit') ? new Error('Submit result unknown') : path.endsWith('/status') ? {receipt:'FM-WRONG-RECEIPT', status:'pending', downloaded_to_pc:false} : undefined}); await prepare(f);
    f.submit(); await flush(); await f.tick(5000);
    assert.equal(f.api.getState().received, false); assert.equal(f.api.getState().receipt, 'FM-TEST-1');
    assert.equal(f.api.newOrder(), false); assert.doesNotMatch(f.api.getState().status, /принята сервером/);
    console.log('PASS pending status with another receipt cannot confirm the current order');
  }
  {
    const f = fixture({fetch:({path, submitCount}) => path.endsWith('/submit') && submitCount === 1 ? HANG : undefined}); await prepare(f);
    f.submit(); await flush(); f.api.cancel(); await flush();
    assert.equal(f.requests.find(r => r.path.endsWith('/submit')).aborted, true);
    assert.match(f.api.getState().status, /сервер уже мог принять/); assert.equal(f.api.newOrder(), false);
    f.submit(); await flush(); assert.equal(f.api.getState().received, true); assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 1); assert.equal(f.puts.length, 2);
    f.api.newOrder();
    console.log('PASS cancellation during submit never claims server deletion and retries same order');
  }
  {
    const f = fixture({fetch:({path}) => path.endsWith('/status') ? HANG : undefined}); await prepare(f);
    f.submit(); await flush(); await f.tick(5000);
    const statusRequest = f.requests.find(r => r.path.endsWith('/status')); assert.ok(statusRequest);
    assert.equal(f.api.newOrder(), true); await flush();
    assert.equal(statusRequest.aborted, true); assert.equal(f.timers.size, 0);
    assert.equal(f.api.getState().received, false); assert.match(f.api.getState().status, /Выберите файлы для новой/);
    console.log('PASS new draft cancels old polling without stale timers or receipt overwrites');
  }
  {
    const f = fixture(); await prepare(f, [file('too-large.jpg', 25 * 1024 * 1024 + 1)]);
    f.submit(); await flush(); assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 0); assert.match(f.api.getState().status, /не больше 25 МБ/);
    f.files([file('file.exe')]); f.submit(); await flush(); assert.match(f.api.getState().status, /Неподдерживаемый формат/);
    f.files(Array.from({length:11}, (_, i) => file(i + '.pdf'))); f.submit(); await flush(); assert.match(f.api.getState().status, /Не более 10/);
    f.files(Array.from({length:5}, (_, i) => file(i + '.jpg', 25 * 1024 * 1024))); f.submit(); await flush(); assert.match(f.api.getState().status, /100 МБ/);
    console.log('PASS file type, count, per-file and aggregate size limits');
  }
  {
    const f = fixture({fetch:({path}) => path === '/api/health' ? {accepting_uploads:false} : undefined}); await prepare(f);
    f.submit(); await flush(); assert.equal(f.requests.filter(r => r.path === '/api/orders').length, 0);
    f.click('upload-recheck'); await flush(); assert.equal(f.tabs.length, 0); assert.equal(f.requests.filter(r => r.path === '/api/health').length, 2);
    assert.equal(f.node('upload-submit').disabled, true);
    console.log('PASS closed receiver never enables upload; recheck uses the configured API');
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
