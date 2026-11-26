/* FotoMag direct upload. No third-party libraries or browser storage.
   The API URL is blank until a private backend is deployed and approved. */
(() => {
  "use strict";
  const LIMIT_FILE = 25 * 1024 * 1024;
  const LIMIT_TOTAL = 100 * 1024 * 1024;
  const LIMIT_COUNT = 10;
  const EXTENSIONS = new Set(["jpg","jpeg","png","webp","heic","heif","pdf","docx","xlsx"]);
  const meta = document.querySelector('meta[name="fotomag-upload-api"]');
  const configured = (meta?.content || "").trim().replace(/\/+$/, "");
  let endpoint = "";
  try {
    const url = new URL(configured);
    if (url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash &&
        url.pathname === "/") endpoint = url.origin;
  } catch (_) { /* Deployment has not configured the API. */ }

  const get = id => document.getElementById(id);
  const selectedFiles = () => [...(get("upload-files")?.files || [])];
  const humanSize = bytes => (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") + " МБ";
  let sending = false;
  let pendingAttempt = null;
  let activeReceipt = "";
  let readinessGeneration = 0;
  let gatewayReady = false;

  function status(message, isError = false) {
    const line = get("upload-status");
    if (!line) return;
    line.textContent = message;
    line.classList.toggle("is-error", isError);
  }

  function onView() {
    activeReceipt = "";
    const generation = ++readinessGeneration;
    gatewayReady = false;
    const button = get("upload-submit");
    const note = get("upload-availability");
    if (!button || !note) return;
    button.disabled = true;
    note.textContent = endpoint
      ? "Проверяем защищённое соединение с FotoMag…"
      : "Прямая отправка работает при подключении к Wi-Fi AGFA в фотоцентре. Проверьте связь с приёмником.";
    updateFiles();
    updateKindChoices();
    if (endpoint) void checkReadiness(generation);
  }

  async function checkReadiness(generation) {
    // Only run after the user opens this screen. Never delay the page's first paint.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6500);
    try {
      const response = await fetch(endpoint + "/api/health", {
        method: "GET", credentials: "omit", mode: "cors", cache: "no-store",
        signal: controller.signal
      });
      if (!response.ok) throw new Error("Gateway unavailable");
      const result = await response.json();
      if (generation !== readinessGeneration) return;
      const button = get("upload-submit");
      const note = get("upload-availability");
      if (!button || !note) return;
      gatewayReady = result.accepting_uploads === true;
      button.disabled = !gatewayReady;
      note.textContent = gatewayReady
        ? "Защищённый приём FotoMag работает. Файлы отправятся напрямую и будут проверены перед получением на ПК."
        : "Приём пока закрыт. Убедитесь, что вы в сети AGFA, затем проверьте соединение с FotoMag.";
    } catch (_) {
      if (generation === readinessGeneration) {
        gatewayReady = false;
        const button = get("upload-submit");
        const note = get("upload-availability");
        if (button) button.disabled = true;
        if (note) note.textContent = "Нет связи с приёмником. Файлы не отправлены, воспользуйтесь резервным каналом.";
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  function updateKindChoices() {
    const selected = get("upload-kind")?.value;
    for (const button of document.querySelectorAll("#direct-upload-form [data-upload-choice]")) {
      const active = button.dataset.uploadChoice === selected;
      button.classList.toggle("is-selected", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  function updateFiles() {
    const line = get("upload-files-summary");
    if (!line) return;
    const files = selectedFiles();
    const bytes = files.reduce((n, f) => n + f.size, 0);
    line.textContent = files.length
      ? "Выбрано: " + files.length + " файл(ов) · " + humanSize(bytes)
      : "JPG, PNG, WEBP, HEIC, PDF, DOCX, XLSX · до 25 МБ каждый.";
    const list = get("upload-file-list");
    if (!list) return;
    list.replaceChildren();
    for (const file of files.slice(0, 4)) {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.className = "upload-file-name";
      name.textContent = file.name;
      const size = document.createElement("span");
      size.className = "upload-file-size";
      size.textContent = humanSize(file.size);
      item.append(name, size);
      list.appendChild(item);
    }
    if (files.length > 4) {
      const more = document.createElement("li");
      more.textContent = "И ещё " + (files.length - 4) + " файл(ов)";
      list.appendChild(more);
    }
  }

  function validate(files) {
    if (!files.length) return "Выберите хотя бы один файл.";
    if (files.length > LIMIT_COUNT) return "Не более 10 файлов за одну отправку.";
    let total = 0;
    for (const f of files) {
      const ext = f.name.toLowerCase().split(".").pop();
      if (!EXTENSIONS.has(ext)) return "Неподдерживаемый формат: " + f.name;
      if (!f.size || f.size > LIMIT_FILE) return "Файл " + f.name + " должен быть не больше 25 МБ.";
      total += f.size;
    }
    if (total > LIMIT_TOTAL) return "Общий размер файлов не должен превышать 100 МБ.";
    return "";
  }

  async function post(path, data, token = "") {
    const controller = new AbortController();
    const watchdog = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(endpoint + path, {
        method: "POST", mode: "cors", credentials: "omit", cache: "no-store",
        headers: { "Content-Type": "application/json", ...(token ? {Authorization: "Bearer " + token} : {}) },
        body: JSON.stringify(data), signal: controller.signal
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Сервер не принял запрос.");
      }
      return payload;
    } finally {
      clearTimeout(watchdog);
    }
  }

  function put(path, file, token, index, totalBytes, sentBytes) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", endpoint + path);
      xhr.timeout = 180000;
      xhr.setRequestHeader("Authorization", "Bearer " + token);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = event => {
        if (!event.lengthComputable) return;
        const bar = get("upload-progress");
        if (bar) bar.value = Math.min(100, Math.floor((sentBytes + event.loaded) * 100 / totalBytes));
        status("Отправка файла " + index + ": " + file.name + " · " + humanSize(event.loaded) + " / " + humanSize(file.size));
      };
      xhr.onload = () => xhr.status >= 200 && xhr.status < 300
        ? resolve() : reject(new Error("Сервер не принял файл: " + file.name));
      xhr.onerror = () => reject(new Error("Прервалась связь при отправке файла: " + file.name));
      xhr.ontimeout = () => reject(new Error("Истекло время отправки файла: " + file.name));
      xhr.onabort = () => reject(new Error("Отправка прервана."));
      xhr.send(file);
    });
  }

  async function waitForWorkstation(orderId, token, receipt) {
    // Background checks occur ONLY after a client deliberately submits files.
    // No storage or tracking cookies; the one-order token stays in this tab.
    for (let attempt = 0; attempt < 8; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 5000));
      if (!get("upload-status") || activeReceipt !== receipt) return;
      try {
        const response = await fetch(endpoint + "/api/orders/" + orderId + "/status", {
          method: "GET", mode: "cors", credentials: "omit", cache: "no-store",
          headers: {Authorization: "Bearer " + token},
          signal: AbortSignal.timeout(8000)
        });
        if (!response.ok) continue;
        const result = await response.json();
        if (result.receipt !== receipt) return;
        if (result.downloaded_to_pc === true && result.status === "received" && activeReceipt === receipt) {
          status("✓ Заявка " + receipt + " доставлена на компьютер FotoMag в канал «Напрямую». Сотрудник проверит файлы перед печатью.");
          return;
        }
      } catch (_) { /* The queued order is retained while connectivity is unavailable. */ }
    }
    if (activeReceipt === receipt) status("✓ Заявка " + receipt + " принята сервером. Подтверждение записи на диск ещё не поступило. Сохраните номер заявки.");
  }

  async function send(form) {
    if (sending) return;
    if (!endpoint || !gatewayReady) return status("Защищённый приёмник ещё не готов.", true);
    const files = selectedFiles();
    const problem = validate(files);
    if (problem) return status(problem, true);
    if (!form.reportValidity()) return;
    const kind = get("upload-kind")?.value || "documents";
    const phone = get("upload-phone")?.value.trim() || "";
    const client_name = get("upload-name")?.value.trim() || "";
    const comment = get("upload-comment")?.value.trim() || "";
    const checkbox = get("upload-consent");
    const consent = Boolean(checkbox?.checked);
    if (!consent) return status("Подтвердите согласие на обработку данных.", true);
    const submit = get("upload-submit");
    const progress = get("upload-progress");
    sending = true;
    activeReceipt = "";
    if (submit) submit.disabled = true;
    if (progress) { progress.hidden = false; progress.value = 0; }
    try {
      const details = {
        kind, phone, client_name, comment, consent, consent_version: checkbox.dataset.consentVersion,
        files: files.map(f => ({name: f.name, size: f.size}))
      };
      const signature = JSON.stringify(details);
      if (!pendingAttempt || pendingAttempt.signature !== signature ||
          !files.every((file, i) => file === pendingAttempt.files[i])) {
        const random = crypto.getRandomValues(new Uint8Array(32));
        pendingAttempt = {signature, files, nextFile: 0, created: null,
          key: Array.from(random, byte => byte.toString(16).padStart(2, "0")).join("")};
      }
      const attempt = pendingAttempt;
      if (!attempt.created) {
        status("Оформляем заявку и готовим защищённую загрузку…");
        const reply = await post("/api/orders", {...details, request_key: attempt.key});
        if (!reply.order_id || !reply.receipt || !reply.upload_token || reply.files?.length !== files.length)
          throw new Error("Неверный ответ сервера.");
        attempt.created = reply;
      }
      const created = attempt.created;
      const total = files.reduce((n, f) => n + f.size, 0);
      let sent = files.slice(0, attempt.nextFile).reduce((n, f) => n + f.size, 0);
      for (let i = attempt.nextFile; i < files.length; i++) {
        const f = files[i];
        await put("/api/orders/" + created.order_id + "/files/" + created.files[i].file_id,
                  f, created.upload_token, i + 1, total, sent);
        attempt.nextFile = i + 1;
        sent += f.size;
        if (progress) progress.value = Math.floor(sent * 100 / total);
      }
      const answer = await post("/api/orders/" + created.order_id + "/submit", {},
                                created.upload_token);
      if (answer.received !== true || answer.receipt !== created.receipt)
        throw new Error("Не удалось подтвердить доставку файлов.");
      pendingAttempt = null;
      if (progress) progress.value = 100;
      activeReceipt = answer.receipt;
      status("✓ Заявка " + answer.receipt + " принята сервером. Передача на компьютер FotoMag ожидается; это ещё не подтверждение печати.");
      void waitForWorkstation(created.order_id, created.upload_token, answer.receipt);
      form.reset();
      updateFiles();
      updateKindChoices();
      if (submit) submit.textContent = "Отправить ещё файлы";
    } catch (error) {
      const receipt = pendingAttempt?.created?.receipt;
      status((error?.message || "Ошибка отправки.") +
        (receipt ? " Номер заявки: " + receipt + "." : "") +
        " Оставьте эту вкладку открытой и нажмите кнопку отправки ещё раз.", true);
    } finally {
      sending = false;
      if (submit) submit.disabled = !gatewayReady;
    }
  }

  document.addEventListener("click", event => {
    const health = event.target.closest("#upload-recheck");
    if (health && health.closest("#sheet-body")) {
      const url = health.dataset.healthUrl || "";
      try {
        const dest = new URL(url);
        if (dest.protocol !== "https:" || dest.hostname !== "fotomag-izhevsk.dynv6.net" ||
            dest.port !== "8443" || dest.pathname !== "/api/health") throw new Error("Invalid health target");
        window.open(dest.href, "_blank", "noopener,noreferrer");
        status("Открывается проверка сервера. JSON со статусом ok означает наличие связи, но не разрешение отправки.");
      } catch (_) { status("Не удалось открыть проверку связи.", true); }
      return;
    }
    const choice = event.target.closest("#direct-upload-form [data-upload-choice]");
    if (!choice) return;
    const kind = choice.dataset.uploadChoice;
    if (!["photos", "documents", "id450"].includes(kind)) return;
    const value = get("upload-kind");
    if (value) value.value = kind;
    updateKindChoices();
  });

  document.addEventListener("change", event => {
    if (event.target.id === "upload-files") updateFiles();
  });
  document.addEventListener("submit", event => {
    if (event.target.id !== "direct-upload-form") return;
    event.preventDefault();
    send(event.target);
  });
  window.FotoMagDirectUpload = Object.freeze({onView});
  if (get('direct-upload-form')) onView(); // Deep link opened before deferred script executed.
})();
