/* FotoMag direct upload: per-tab state; the public API stays disabled until configured. */
(() => {
  'use strict';
  const LIMIT_FILE = 25 * 1024 * 1024, LIMIT_TOTAL = 100 * 1024 * 1024, LIMIT_COUNT = 10;
  const EXTENSIONS = new Set(['jpg','jpeg','png','webp','heic','heif','pdf','docx','xlsx']);
  const FIELD_IDS = ['kind','format','phone','name','comment','consent'];
  const get = id => document.getElementById(id);
  const humanSize = bytes => (bytes / (1024 * 1024)).toFixed(1).replace('.', ',') + ' МБ';
  let endpoint = '';
  try {
    const url = new URL((document.querySelector('meta[name="fotomag-upload-api"]')?.content || '').trim());
    if (url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/') endpoint = url.origin;
  } catch (_) { /* Public static page: no browser API calls. */ }
  const state = {view:false, files:[], fields:null, dirty:false, sending:false, cancelled:false,
    pending:null, accepted:null, ready:false, message:'', error:false, availability:'', progress:null};
  const requests = {send:new Set(), health:new Set(), poll:new Set()};
  let xhr = null, healthRun = 0, pollRun = 0, pollTimer = null, pollWake = null;

  function snapshot() {
    if (!state.view || !get('direct-upload-form')) return;
    state.fields = Object.fromEntries(FIELD_IDS.map(key => {
      const el = get('upload-' + key);
      return [key, key === 'consent' ? Boolean(el?.checked) : (el?.value || '')];
    }));
    state.fields.consentVersion = get('upload-consent')?.dataset.consentVersion || '';
  }
  const hasDraft = () => Boolean(state.dirty || state.files.length || state.fields?.comment || state.fields?.name || state.fields?.phone);
  function getState() {
    return {sending:state.sending, pending:Boolean(state.pending), hasDraft:hasDraft(),
      received:Boolean(state.accepted), receipt:state.accepted?.receipt || state.pending?.created?.receipt || '',
      status:state.message, configured:Boolean(endpoint)};
  }
  function status(message, error = false) {
    state.message = message; state.error = error;
    if (!state.view) return;
    const line = get('upload-status');
    if (line) { line.textContent = message; line.classList.toggle('is-error', error); }
  }
  function controls() {
    if (!state.view) return;
    const locked = state.sending || Boolean(state.accepted) || Boolean(state.pending?.submitStarted);
    for (const el of document.querySelectorAll('#direct-upload-form input, #direct-upload-form textarea, #direct-upload-form [data-upload-choice]')) el.disabled = locked;
    const submit = get('upload-submit'), cancel = get('upload-cancel'), fresh = get('upload-new');
    if (submit) { submit.disabled = state.sending || !state.ready || Boolean(state.accepted); submit.textContent = state.pending ? 'Повторить отправку этой заявки' : 'Отправить в FotoMag'; }
    if (cancel) { cancel.hidden = !state.sending; cancel.disabled = !state.sending; }
    if (fresh) { fresh.hidden = !hasDraft() && !state.accepted; fresh.disabled = state.sending || Boolean(state.pending?.submitStarted); fresh.textContent = state.accepted ? 'Отправить ещё файлы' : 'Начать новую заявку'; }
    const fileInput = get('upload-files');
    if (fileInput) fileInput.required = !state.files.length;
    const bar = get('upload-progress');
    if (bar) { bar.hidden = state.progress === null; bar.value = state.progress || 0; }
    const note = get('upload-availability');
    if (note) note.textContent = state.availability;
    const recheck = get('upload-recheck');
    if (recheck) recheck.textContent = endpoint ? 'Проверить соединение' : 'Открыть форму FotoMag в Wi-Fi AGFA';
  }
  function updateFiles() {
    if (!state.view) return;
    const files = state.files, summary = get('upload-files-summary'), list = get('upload-file-list');
    if (summary) summary.textContent = files.length ? 'Выбрано: ' + files.length + ' файл(ов) · ' + humanSize(files.reduce((sum, f) => sum + f.size, 0)) : 'До 10 файлов, по 25 МБ каждый; всего до 100 МБ.';
    if (!list) return;
    list.replaceChildren();
    for (const file of files) {
      const item = document.createElement('li'), name = document.createElement('span'), size = document.createElement('span');
      name.className = 'upload-file-name'; name.textContent = file.name;
      size.className = 'upload-file-size'; size.textContent = humanSize(file.size);
      item.append(name, size); list.appendChild(item);
    }
  }
  function updateKindChoices() {
    if (!state.view) return;
    for (const button of document.querySelectorAll('#direct-upload-form [data-upload-choice]')) {
      const selected = button.dataset.uploadChoice === get('upload-kind')?.value;
      button.classList.toggle('is-selected', selected); button.setAttribute('aria-pressed', String(selected));
    }
  }
  function restore() {
    if (state.fields) for (const key of FIELD_IDS) {
      const el = get('upload-' + key);
      if (el) { if (key === 'consent') el.checked = state.fields[key]; else el.value = state.fields[key]; }
    }
    const input = get('upload-files');
    if (input && state.files.length && typeof DataTransfer !== 'undefined') {
      try { const files = new DataTransfer(); state.files.forEach(file => files.items.add(file)); input.files = files.files; } catch (_) { /* The visible file list and File references remain valid. */ }
    }
    updateFiles(); updateKindChoices(); status(state.message, state.error); controls();
  }
  function onView() {
    state.view = true;
    if (!state.fields || (!hasDraft() && !state.pending && !state.accepted && !state.sending)) snapshot();
    restore();
    if (endpoint) void recheck();
    else { state.ready = false; state.availability = 'Прямая отправка работает при подключении к Wi-Fi AGFA в фотоцентре. Откройте форму FotoMag ниже.'; controls(); }
  }
  function onLeave() { snapshot(); state.view = false; return getState(); }
  function abortBucket(bucket) { for (const controller of requests[bucket]) controller.abort(); }
  function stopPolling() {
    pollRun++; clearTimeout(pollTimer); pollTimer = null;
    if (pollWake) { pollWake(false); pollWake = null; }
    abortBucket('poll');
  }
  async function request(path, {method = 'GET', data, token = '', bucket = 'send', timeout = 30000} = {}) {
    const controller = new AbortController(); requests[bucket].add(controller);
    let expired = false;
    const timer = setTimeout(() => { expired = true; controller.abort(); }, timeout);
    try {
      const response = await fetch(endpoint + path, {method, credentials:'omit', mode:'cors', cache:'no-store',
        headers:{...(data !== undefined ? {'Content-Type':'application/json'} : {}), ...(token ? {Authorization:'Bearer ' + token} : {})},
        ...(data !== undefined ? {body:JSON.stringify(data)} : {}), signal:controller.signal});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Сервер не принял запрос. Код ' + response.status + '.');
      return result;
    } catch (error) {
      if (expired) throw new Error('Время ожидания ответа истекло. Результат запроса пока не подтверждён.');
      throw error;
    } finally { clearTimeout(timer); requests[bucket].delete(controller); }
  }
  async function recheck() {
    if (!endpoint) return false;
    abortBucket('health'); const run = ++healthRun;
    state.ready = false; state.availability = 'Проверяем защищённое соединение с FotoMag…'; controls();
    try {
      const result = await request('/api/health', {bucket:'health', timeout:6500});
      if (run !== healthRun) return false;
      state.ready = result.accepting_uploads === true;
      state.availability = state.ready ? 'Защищённый приём FotoMag работает.' : 'Приём пока закрыт. Проверьте соединение или используйте личный канал связи.';
    } catch (_) {
      if (run !== healthRun) return false;
      state.ready = false; state.availability = 'Нет связи с приёмником. Новая передача не начата. Проверьте соединение или используйте личный канал связи.';
    }
    controls(); return state.ready;
  }
  function validate(files) {
    if (!files.length) return 'Выберите хотя бы один файл.';
    if (files.length > LIMIT_COUNT) return 'Не более 10 файлов за одну отправку.';
    let total = 0;
    for (const file of files) {
      if (!EXTENSIONS.has(file.name.toLowerCase().split('.').pop())) return 'Неподдерживаемый формат: ' + file.name;
      if (!file.size || file.size > LIMIT_FILE) return 'Файл ' + file.name + ' должен быть не больше 25 МБ.';
      total += file.size;
    }
    return total > LIMIT_TOTAL ? 'Общий размер файлов не должен превышать 100 МБ.' : '';
  }
  function put(path, file, token, index, total, sent) {
    return new Promise((resolve, reject) => {
      const transfer = new XMLHttpRequest(); xhr = transfer;
      transfer.open('PUT', endpoint + path); transfer.timeout = 180000;
      transfer.setRequestHeader('Authorization', 'Bearer ' + token); transfer.setRequestHeader('Content-Type', 'application/octet-stream');
      const finish = error => { if (xhr === transfer) xhr = null; error ? reject(error) : resolve(); };
      transfer.upload.onprogress = event => {
        if (!event.lengthComputable || state.cancelled) return;
        state.progress = Math.min(100, Math.floor((sent + event.loaded) * 100 / total)); controls();
        status('Отправка файла ' + index + ': ' + file.name + ' · ' + humanSize(event.loaded) + ' / ' + humanSize(file.size));
      };
      transfer.onload = () => finish(transfer.status >= 200 && transfer.status < 300 ? null : new Error('Сервер не принял файл: ' + file.name));
      transfer.onerror = () => finish(new Error('Прервалась связь при отправке файла: ' + file.name));
      transfer.ontimeout = () => finish(new Error('Истекло время отправки файла: ' + file.name));
      transfer.onabort = () => finish(new Error('Передача остановлена.'));
      transfer.send(file);
    });
  }
  function delivered(result) { return result.downloaded_to_pc === true && result.status === 'received'; }
  // The existing receiver stores "pending" only after verified /submit; it is not a PC acknowledgement.
  function confirmsReceipt(result) { return result.received === true || result.status === 'pending' || delivered(result); }
  function accept(attempt, result) {
    state.accepted = {orderId:attempt.created.order_id, token:attempt.created.upload_token, receipt:attempt.created.receipt};
    state.pending = null; state.progress = 100;
    status(delivered(result) ? '✓ Заявка ' + state.accepted.receipt + ' доставлена на компьютер FotoMag в канал «Напрямую». Сотрудник проверит файлы перед печатью.' : '✓ Заявка ' + state.accepted.receipt + ' принята сервером. Подтверждение доставки на компьютер ожидается. Печать подтверждает сотрудник.');
    controls();
  }
  async function pollStatus(attempt) {
    stopPolling(); const run = pollRun, created = attempt.created;
    if (!created) return;
    for (let count = 0; count < 8 && run === pollRun; count++) {
      const continuePolling = await new Promise(resolve => { pollWake = resolve; pollTimer = setTimeout(() => { pollWake = null; resolve(true); }, 5000); });
      if (!continuePolling || run !== pollRun) return;
      try {
        const result = await request('/api/orders/' + created.order_id + '/status', {token:created.upload_token, bucket:'poll', timeout:8000});
        if (run !== pollRun || result.receipt !== created.receipt) return;
        if (confirmsReceipt(result)) { accept(attempt, result); if (delivered(result)) return; }
      } catch (_) { /* Preserve the last confirmed state and receipt. */ }
    }
    if (run !== pollRun) return;
    status(state.accepted ? '✓ Заявка ' + created.receipt + ' принята сервером. Подтверждение записи на диск ещё не поступило. Сохраните номер заявки.' : 'Результат приёма заявки ' + created.receipt + ' пока не подтверждён. Повторите отправку этой же заявки или уточните её статус у сотрудника.');
  }
  async function send(form) {
    if (state.sending || state.accepted) return;
    if (!endpoint || !state.ready) return status('Нет подтверждённого соединения с приёмником. Нажмите «Проверить соединение».', true);
    snapshot(); const files = state.files, fields = state.fields;
    const problem = validate(files); if (problem) return status(problem, true);
    if (!form.reportValidity()) return;
    if (!fields.consent) return status('Подтвердите согласие на обработку данных.', true);
    const details = {kind:fields.kind || 'documents', phone:fields.phone.trim(), client_name:fields.name.trim(), comment:fields.comment.trim(),
      consent:true, consent_version:fields.consentVersion, files:files.map(file => ({name:file.name, size:file.size}))};
    const signature = JSON.stringify(details);
    if (!state.pending || (!state.pending.submitStarted && (state.pending.signature !== signature || !files.every((file, i) => file === state.pending.files[i])))) {
      const random = crypto.getRandomValues(new Uint8Array(32));
      state.pending = {signature, details, files, nextFile:0, created:null, submitStarted:false,
        key:Array.from(random, byte => byte.toString(16).padStart(2, '0')).join('')};
    }
    const attempt = state.pending;
    stopPolling(); state.sending = true; state.cancelled = false; state.progress = 0; controls();
    try {
      if (!attempt.created) {
        status('Оформляем заявку и готовим защищённую загрузку…');
        const reply = await request('/api/orders', {method:'POST', data:{...attempt.details, request_key:attempt.key}});
        if (!reply.order_id || !reply.receipt || !reply.upload_token || reply.files?.length !== attempt.files.length || reply.files.some(file => !file.file_id)) throw new Error('Неверный ответ сервера. Повторите эту же заявку.');
        attempt.created = reply;
      }
      const created = attempt.created;
      if (attempt.submitStarted) {
        try {
          const current = await request('/api/orders/' + created.order_id + '/status', {token:created.upload_token, timeout:8000});
          if (current.receipt === created.receipt && confirmsReceipt(current)) { accept(attempt, current); if (!delivered(current)) void pollStatus(attempt); return; }
        } catch (error) { if (state.cancelled) throw error; }
      }
      const total = attempt.files.reduce((sum, file) => sum + file.size, 0);
      let sent = attempt.files.slice(0, attempt.nextFile).reduce((sum, file) => sum + file.size, 0);
      for (let i = attempt.nextFile; i < attempt.files.length; i++) {
        if (state.cancelled) throw new Error('Передача остановлена.');
        await put('/api/orders/' + created.order_id + '/files/' + created.files[i].file_id, attempt.files[i], created.upload_token, i + 1, total, sent);
        attempt.nextFile = i + 1; sent += attempt.files[i].size;
        state.progress = Math.floor(sent * 100 / total); controls();
      }
      if (state.cancelled) throw new Error('Передача остановлена.');
      attempt.submitStarted = true; status('Файлы загружены. Ожидаем подтверждение приёма заявки сервером…');
      const answer = await request('/api/orders/' + created.order_id + '/submit', {method:'POST', data:{}, token:created.upload_token});
      if (answer.received !== true || answer.receipt !== created.receipt) throw new Error('Приём заявки пока не подтверждён.');
      accept(attempt, answer); void pollStatus(attempt);
    } catch (error) {
      const receipt = attempt.created?.receipt;
      if (state.cancelled) status(attempt.submitStarted ? 'Передача остановлена, но сервер уже мог принять заявку ' + receipt + '. Проверяем её статус; новую заявку не создаём.' : 'Передача остановлена. Уже загруженные файлы могут оставаться на приёмнике. Для продолжения нажмите «Повторить отправку этой заявки».' + (receipt ? ' Номер: ' + receipt + '.' : ''));
      else status((error?.message || 'Ошибка отправки.') + (receipt ? ' Номер заявки: ' + receipt + '.' : '') + ' Оставьте вкладку открытой и повторите эту же заявку.', true);
      if (attempt.submitStarted) void pollStatus(attempt);
    } finally { state.sending = false; controls(); }
  }
  function cancel() {
    if (!state.sending) return false;
    state.cancelled = true; stopPolling(); healthRun++; abortBucket('health'); abortBucket('send');
    if (xhr) xhr.abort();
    return true;
  }
  function newOrder() {
    if (state.sending || state.pending?.submitStarted) return false;
    const previous = state.accepted?.receipt;
    stopPolling(); state.files = []; state.fields = null; state.dirty = false; state.pending = null; state.accepted = null; state.progress = null;
    if (state.view) { get('direct-upload-form')?.reset(); snapshot(); }
    status(previous ? 'Предыдущая заявка ' + previous + ' принята сервером. Выберите файлы для новой заявки.' : 'Новая заявка. Выберите файлы.');
    restore(); return true;
  }
  function openLocalForm(button) {
    try {
      snapshot(); const url = new URL(button.dataset.formUrl || '');
      if (url.protocol !== 'https:' || url.hostname !== 'fotomag-izhevsk.dynv6.net' || url.port !== '8443' || url.pathname !== '/' || url.username || url.password || url.search || url.hash !== '#send-files') throw new Error('Unexpected destination');
      if (['photos','documents','id450'].includes(state.fields?.kind)) url.searchParams.set('kind', state.fields.kind);
      if (['35x45','3x4','4x6'].includes(state.fields?.format)) url.searchParams.set('format', state.fields.format);
      window.open(url.href, '_blank', 'noopener,noreferrer');
      status('Откройте форму FotoMag в новой вкладке, подключившись к AGFA. Файлы нужно выбрать там; в этой вкладке они не отправлены.');
    } catch (_) { status('Не удалось открыть форму FotoMag. Используйте личный канал связи.', true); }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('#upload-recheck, #upload-cancel, #upload-new, #direct-upload-form [data-upload-choice]');
    if (!button || !button.closest('#sheet-body')) return;
    if (button.id === 'upload-recheck') { if (endpoint) void recheck(); else openLocalForm(button); return; }
    if (button.id === 'upload-cancel') { cancel(); return; }
    if (button.id === 'upload-new') { newOrder(); return; }
    if (state.sending || state.accepted || state.pending?.submitStarted) return;
    const kind = button.dataset.uploadChoice;
    if (['photos','documents','id450'].includes(kind) && get('upload-kind')) { get('upload-kind').value = kind; state.dirty = true; snapshot(); updateKindChoices(); controls(); }
  });
  const inputChanged = event => {
    if (!state.view || !event.target.closest('#direct-upload-form') || state.sending || state.accepted || state.pending?.submitStarted) return;
    if (event.target.id === 'upload-files') state.files = [...event.target.files];
    state.dirty = true; snapshot(); updateFiles(); controls();
  };
  document.addEventListener('change', inputChanged); document.addEventListener('input', inputChanged);
  document.addEventListener('submit', event => { if (event.target.id === 'direct-upload-form') { event.preventDefault(); void send(event.target); } });
  window.addEventListener('beforeunload', event => { if (state.sending) { event.preventDefault(); event.returnValue = ''; } });
  window.FotoMagDirectUpload = Object.freeze({onView, onLeave, getState, cancel, recheck, newOrder});
  if (get('direct-upload-form')) onView();
})();
