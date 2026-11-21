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
  let activeReceipt = "";

  function status(message, isError = false) {
    const line = get("upload-status");
    if (!line) return;
    line.textContent = message;
    line.classList.toggle("is-error", isError);
  }

  function onView() {
    activeReceipt = ""; // Do not update a newly opened screen from an old order poll.
    const button = get("upload-submit");
    const note = get("upload-availability");
    if (!button || !note) return;
    button.disabled = !endpoint;
    note.textContent = endpoint
      ? "Канал «Напрямую»: файлы будут доставлены на компьютер FotoMag, разложены по датам и отдельным папкам клиентов. Печать после проверки сотрудником."
      : "Прямая отправка готовится к запуску. Сейчас воспользуйтесь VK, MAX или Telegram ниже.";
    updateFiles();
  }

  function updateFiles() {
    const line = get("upload-files-summary");
    if (!line) return;
    const files = selectedFiles();
    const bytes = files.reduce((n, f) => n + f.size, 0);
    line.textContent = files.length
      ? "Выбрано файлов: " + files.length + " · " + humanSize(bytes)
      : "Можно выбрать до 10 файлов: JPG, PNG, WEBP, HEIC, PDF, DOCX, XLSX.";
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
        if (result.downloaded_to_pc && activeReceipt === receipt) {
          status("✓ Заявка " + receipt + " доставлена на компьютер FotoMag в канал «Напрямую». Сотрудник проверит файлы перед печатью.");
          return;
        }
      } catch (_) { /* The queued order is retained while connectivity is unavailable. */ }
    }
    if (activeReceipt === receipt) status("✓ Заявка " + receipt + " принята сервером. Ожидает загрузки на компьютер FotoMag — сотрудник свяжется с вами.");
  }

  async function send(form) {
    if (sending) return;
    if (!endpoint) return status("Прямая отправка ещё не включена.", true);
    const files = selectedFiles();
    const problem = validate(files);
    if (problem) return status(problem, true);
    if (!form.reportValidity()) return;
    const kind = get("upload-kind")?.value || "documents";
    const phone = get("upload-phone")?.value.trim() || "";
    const client_name = get("upload-name")?.value.trim() || "";
    const comment = get("upload-comment")?.value.trim() || "";
    const consent = Boolean(get("upload-consent")?.checked);
    if (!consent) return status("Подтвердите согласие на обработку данных.", true);
    const submit = get("upload-submit");
    const progress = get("upload-progress");
    sending = true;
    activeReceipt = "";
    if (submit) submit.disabled = true;
    if (progress) { progress.hidden = false; progress.value = 0; }
    let created;
    try {
      status("Оформляем заявку и готовим защищённую загрузку…");
      created = await post("/api/orders", {
        kind, phone, client_name, comment, consent,
        files: files.map(f => ({name: f.name, size: f.size}))
      });
      if (!created.order_id || !created.upload_token || created.files?.length !== files.length)
        throw new Error("Неверный ответ сервера.");
      const total = files.reduce((n, f) => n + f.size, 0);
      let sent = 0;
      for (let i = 0; i < files.length; i++) {
        const f = files[i];
        await put("/api/orders/" + created.order_id + "/files/" + created.files[i].file_id,
                  f, created.upload_token, i + 1, total, sent);
        sent += f.size;
        if (progress) progress.value = Math.floor(sent * 100 / total);
      }
      const answer = await post("/api/orders/" + created.order_id + "/submit", {},
                                created.upload_token);
      if (!answer.received || answer.receipt !== created.receipt)
        throw new Error("Не удалось подтвердить доставку файлов.");
      if (progress) progress.value = 100;
      activeReceipt = answer.receipt;
      status("✓ Заявка " + answer.receipt + " принята сервером. Передача на компьютер FotoMag ожидается; это ещё не подтверждение печати.");
      void waitForWorkstation(created.order_id, created.upload_token, answer.receipt);
      form.reset();
      updateFiles();
      if (submit) submit.textContent = "Отправить ещё файлы";
    } catch (error) {
      status((error?.message || "Ошибка отправки.") +
        " Если доставка не подтверждена, используйте резервный канал ниже.", true);
    } finally {
      sending = false;
      if (submit) submit.disabled = !endpoint;
    }
  }

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
