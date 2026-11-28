
(() => {
'use strict';
const sheet = document.getElementById('sheet');
const sheetBody = document.getElementById('sheet-body');
const sheetTitle = document.getElementById('sheet-title');
const sheetKicker = document.getElementById('sheet-kicker');
const sheetIcon = document.getElementById('sheet-icon');
const scroll = document.getElementById('screen-scroll');
const toast = document.getElementById('toast');
const navButtons = [...document.querySelectorAll('.dock-btn')];
if (!sheet || !sheetBody || !sheetTitle || !sheetKicker || !sheetIcon || !scroll) return;

const sections = Object.freeze({
photos: { title: 'Печать фотографий', kicker: 'Фотоуслуги', icon: 'photos', route: '#photo-print' },
id450: { title: 'Фото на документы', kicker: 'Ваше фото на любом фоне · 450 ₽', icon: 'id450', route: '#order450' },
documents: { title: 'Документы и PDF', kicker: 'Печать с телефона', icon: 'documents', route: '#documents' },
upload: { title: 'Отправить файлы', kicker: 'Без мессенджеров · прямо с телефона', icon: 'documents', route: '#send-files' },
wifi: { title: 'Бесплатный Wi‑Fi', kicker: 'Для гостей FotoMag', icon: 'wifi', route: '#wifi' },
studio: { title: 'Фото на паспорт', kicker: 'Новая съёмка в FotoMag', icon: 'studio', route: '#id-photo' },
shop: { title: 'Мини-магазин', kicker: 'Будущий раздел', icon: 'shop', route: '#shop' },
personal: { title: 'Отправить лично', kicker: 'Без бота · напрямую', icon: 'personal', route: '#personal-contacts' },
bots: { title: 'Выберите бота', kicker: 'Автоматические заказы', icon: 'bots', route: '#bots' },
location: { title: 'Где мы находимся', kicker: 'FotoMag · Ижевск', icon: 'location', route: '#location' },
prices: { title: 'Услуги и цены', kicker: 'Прайс FotoMag', icon: 'prices', route: '#prices' },
help: { title: 'Вопросы и ответы', kicker: 'Помощь клиенту', icon: 'help', route: '#help' }
});
const hashRoutes = Object.freeze({
'#photo-print':'photos','#photos':'photos','#order450':'id450','#promo450':'id450',
'#id-photo':'studio','#documents':'documents','#docs':'documents','#shop':'shop','#send-files':'upload',
'#personal-contacts':'personal','#direct':'personal','#bots':'bots','#location':'location',
'#prices':'prices','#help':'help','#faq':'help','#wifi':'wifi'
});
const get = id => document.getElementById(id);
let active = 'home';
let returnFocus = null;
let uploadScriptPromise;
let uploadViewSequence = 0;
function initUploadView() {
const sequence = ++uploadViewSequence;
if (!uploadScriptPromise && !window.FotoMagDirectUpload) {
uploadScriptPromise = new Promise((resolve, reject) => {
const script = document.createElement('script');
script.src = 'assets/direct-upload.js';
script.async = true;
script.onload = () => window.FotoMagDirectUpload ? resolve() : reject(new Error('Upload unavailable'));
script.onerror = () => reject(new Error('Upload script unavailable'));
document.head.appendChild(script);
});
}
Promise.resolve(uploadScriptPromise).then(() => {
if (sequence === uploadViewSequence && active === 'upload' && sheet.open)
window.FotoMagDirectUpload?.onView();
}).catch(() => {
const note = sheetBody.querySelector('#upload-availability');
if (sequence === uploadViewSequence && note)
note.textContent = 'Загрузка раздела временно недоступна. Используйте VK, MAX или Telegram.';
});
}
let messageTimer;
let openTimer;
let selectedFormat = '35x45';
const formatOptions = Object.freeze({
'35x45': {label:'35×45 мм',count:8},
'3x4': {label:'3×4 см',count:6},
'4x6': {label:'4×6 см',count:4}
});
const isValidFormat = value => Object.hasOwn(formatOptions, value);
const incoming = new URLSearchParams(location.search);
if (isValidFormat(incoming.get('format'))) selectedFormat = incoming.get('format');
function uploadContext(options = {}) {
const saved = window.FotoMagDirectUpload?.getState();
if (saved?.hasDraft || saved?.pending || saved?.sending || saved?.receipt) return;
const kind = options.uploadKind || incoming.get('kind');
const select = sheetBody.querySelector('#upload-kind');
if (select && ['photos','documents','id450'].includes(kind)) select.value = kind;
const format = sheetBody.querySelector('#upload-format');
if (format) format.value = selectedFormat;
if (kind === 'id450') {
const note = sheetBody.querySelector('#upload-comment');
const chosen = formatOptions[selectedFormat];
if (note) note.value = 'Фото на документы '+chosen.label+', '+chosen.count+' шт. — 450 ₽';
}
}
function leaveUpload() {
if (active === 'upload') window.FotoMagDirectUpload?.onLeave();
}
function makeOrderText(option){
return `Здравствуйте! Фото на документы с моей фотографии на любом фоне. Формат ${option.label}, ${option.count} шт. на листе 10×15 см. Услуга 450 ₽. Фото прикрепляю. Подтвердите, пожалуйста, подходит ли снимок и когда будет готово.`;
}
function updateFormatUI(){
const option=formatOptions[selectedFormat];
for(const b of sheetBody.querySelectorAll('[data-format]')){
const selected=b.dataset.format===selectedFormat;
b.classList.toggle('is-selected',selected);
b.setAttribute('aria-pressed',String(selected));
}
const summary=sheetBody.querySelector('#id-format-summary');
if(summary) summary.textContent=`Выбрано: ${option.label} — ${option.count} фото на листе 10×15 см.`;
const copy=sheetBody.querySelector('#copy-order450');
if(copy) copy.dataset.copy=`Фото на документы ${option.label}, ${option.count} шт. — 450 ₽`;
}
function updatePersonalContext(option){
const note=sheetBody.querySelector('#personal-service-context');
const email=sheetBody.querySelector('#direct-email');
const text=sheetBody.querySelector('#personal-order-text');
const copy=sheetBody.querySelector('#copy-personal-order');
if(text){text.hidden=!option;text.value=option?makeOrderText(option):'';}
if(copy){copy.hidden=!option;copy.dataset.copy=option?makeOrderText(option):'';}
if(option){
if(note) note.textContent=`Фото на документы за 450 ₽. ${option.label} — ${option.count} шт. на 10×15. Прикрепите снимок с любого фона в чате и дождитесь подтверждения.`;
if(email) email.href='mailto:kodakprint@yandex.ru?subject='+encodeURIComponent('FotoMag — фото на документы 450 ₽')+'&body='+encodeURIComponent(makeOrderText(option));
} else {
if(note) note.textContent='Выберите способ связи и прикрепите фотографию или документ в открывшемся приложении.';
}
}


function announce(message) {
if (!toast) return;
toast.textContent = message;
toast.classList.add('show');
clearTimeout(messageTimer);
messageTimer = setTimeout(() => toast.classList.remove('show'), 2200);
}
function selectedDock(section) {
const key = section === 'personal' ? 'personal' : section === 'location' ? 'location'
: section === 'home' ? 'home' : section === 'bots' ? 'bots' : 'home';
for (const node of navButtons) {
const isSelected = node.dataset.action === key;
node.classList.toggle('is-active', isSelected);
if (isSelected) node.setAttribute('aria-current', 'page');
else node.removeAttribute('aria-current');
}
}
function openView(section, options = {}) {
const config = sections[section];
const template = get('screen-' + section);
if (!config || !template) return;
clearTimeout(openTimer);
const previous = document.activeElement;
leaveUpload();
active = section;
sheetKicker.textContent = config.kicker;
sheetTitle.textContent = config.title;
sheetBody.replaceChildren(template.content.cloneNode(true));
if(section==='id450') updateFormatUI();
if(section==='personal') updatePersonalContext(options.orderFormat);
if(section==='upload'){
uploadContext(options);
initUploadView();
}
const sourceIcon = document.querySelector(`[data-action="${config.icon}"] .tile-icon svg`) ||
document.querySelector(`[data-action="${config.icon}"] .dock-icon svg`) ||
(section === 'wifi' ? document.querySelector('.wifi-quick svg') : null);
sheetIcon.replaceChildren();
if (sourceIcon) sheetIcon.appendChild(sourceIcon.cloneNode(true));
else sheetIcon.textContent = section === 'location' ? '⌖' : section === 'help' ? '?' : '✦';
if (!sheet.open) {
returnFocus = previous;
sheet.showModal();
sheet.dataset.returnAction = previous && previous.getAttribute('data-action') || 'home';
}
sheetBody.scrollTop = 0;
selectedDock(section);
if (options.setHash !== false && window.location.hash !== config.route) {
try { history.pushState({ view: section, orderFormat: options.orderFormat,
uploadKind: options.uploadKind, format: selectedFormat }, '', config.route); }
catch (_) { location.hash = config.route; }
}
const closeBtn = get('sheet-close');
if (closeBtn) closeBtn.focus({ preventScroll: true });
}
function closeView(options = {}) {
clearTimeout(openTimer);
leaveUpload();
if (sheet.open) sheet.close();
active = 'home';
selectedDock('home');
if (options.resetHash && window.location.hash) {
try { history.pushState({ view: 'home' }, '', location.pathname + location.search); }
catch (_) { location.hash = ''; }
}
}
function showHome() {
closeView({ resetHash: true });
scroll.scrollTo({ top: 0, behavior: 'smooth' });
}
function openUploadOnLocalFotoMag(section, clicked = false, options = {}) {
if (section !== 'upload' || location.hostname !== 'screamble123h.github.io') return false;
const saved = window.FotoMagDirectUpload?.getState();
const retained = saved?.hasDraft || saved?.pending || saved?.sending || saved?.receipt;
openView('upload', { ...options, setHash: clicked });
if (clicked) {
if (retained) {
announce('Открыта текущая заявка. Данные сохранены в этой вкладке.');
return true;
}
const destination = new URL('https://fotomag-izhevsk.dynv6.net:8443/#send-files');
const kind = options.uploadKind || incoming.get('kind') || 'photos';
destination.searchParams.set('kind', ['photos','documents','id450'].includes(kind) ? kind : 'photos');
if (kind === 'id450') destination.searchParams.set('format', selectedFormat);
window.open(destination.href, '_blank', 'noopener,noreferrer');
announce('Форма открывается в новой вкладке. Для отправки подключитесь к Wi-Fi AGFA.');
}
return true;
}
function navigate(section, orderFormat, uploadKind) {
if (section === 'souvenirs') { window.location.assign('souvenirs.html'); return; }
if (openUploadOnLocalFotoMag(section, true, {orderFormat, uploadKind})) return;
if (section === 'home') return showHome();
if (sections[section]) {
clearTimeout(openTimer);
openTimer = setTimeout(() => openView(section, { orderFormat, uploadKind }), 95);
}
}
document.addEventListener('click', event => {
const trigger = event.target.closest('[data-action]');
if (trigger && (!trigger.closest('#sheet-body') || trigger.hasAttribute('data-sheet-nav'))) {
event.preventDefault();
const orderFormat = trigger.id === 'id450-personal' ? formatOptions[selectedFormat] : undefined;
navigate(trigger.dataset.action, orderFormat, trigger.dataset.uploadKind);
return;
}
const wifiConnect = event.target.closest('#wifi-connect');
if (wifiConnect && wifiConnect.closest('#sheet-body')) {
  const hint = sheetBody.querySelector('#wifi-connect-help');
  if (!hint) return;
  hint.hidden = false;
  const explain = 'Откройте настройки Wi-Fi этого телефона, выберите AGFA и введите пароль 00001111. С другого телефона можно отсканировать QR-код выше и подтвердить подключение.';
  const pass = '00001111';
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(pass).then(() => {
      hint.textContent = 'Пароль скопирован. Откройте настройки Wi-Fi этого телефона, выберите AGFA и вставьте пароль. Дождитесь отметки о подключении в настройках телефона.';
      announce('Пароль AGFA скопирован');
    }).catch(() => { hint.textContent = explain; });
  } else {
    hint.textContent = explain;
  }
  return;
}
const format=event.target.closest('[data-format]');
if(format && format.closest('#sheet-body') && isValidFormat(format.dataset.format)){
selectedFormat=format.dataset.format;
updateFormatUI();
try {history.replaceState({...history.state, format:selectedFormat},'',location.href);}catch(_){}
return;
}
const copy = event.target.closest('[data-copy]');
if (copy) {
const value = copy.dataset.copy;
const original = copy.textContent;
const fallback = () => {
copy.textContent = 'Скопируйте подпись вручную: ' + value;
announce('Подпись: ' + value);
};
if (!navigator.clipboard?.writeText) return fallback();
navigator.clipboard.writeText(value).then(() => {
copy.textContent = 'Скопировано ✓';
announce('Добавьте подпись к отправляемой фотографии');
}).catch(fallback);
return;
}
});
document.addEventListener('keydown', event => {
if (event.key === 'Enter' || event.key === ' ') {
const btn = event.target.closest('button.app-tile,button.tip-banner,button.dock-btn,button.utility-action,button.sheet-main-cta,button.format-option,button.wifi-quick,button.wifi-copy,a.quick-bot');
if (btn) btn.classList.add('pressed');
}
});
document.addEventListener('keyup', event => {
if (event.key === 'Enter' || event.key === ' ') {
event.target.closest('button.pressed')?.classList.remove('pressed');
}
});
document.addEventListener('pointerdown', event => {
const btn = event.target.closest('button.app-tile,button.tip-banner,button.dock-btn,button.utility-action,button.sheet-main-cta,button.format-option,button.wifi-quick,button.wifi-copy,a.quick-bot');
if (btn) btn.classList.add('pressed');
});
const removePress = () => {
for (const btn of document.querySelectorAll('.pressed')) {
setTimeout(() => btn.classList.remove('pressed'), 120);
}
};
document.addEventListener('pointerup', removePress);
document.addEventListener('pointercancel', removePress);
window.addEventListener('blur', removePress);
document.getElementById('sheet-close')?.addEventListener('click', () => closeView({ resetHash: true }));
sheet.addEventListener('click', event => {
if (event.target === sheet) closeView({ resetHash: true });
});
sheet.addEventListener('close', () => {
// Ignore a stale close.
if (sheet.open) return;
leaveUpload();
active='home';selectedDock('home');
if(window.location.hash && hashRoutes[window.location.hash]){
try {history.replaceState({view:'home'},'',location.pathname+location.search);}catch(_){}
}
if (returnFocus?.isConnected) returnFocus.focus({preventScroll:true});
});
sheet.addEventListener('cancel', () => leaveUpload());
window.addEventListener('popstate', () => {
const section = hashRoutes[location.hash];
if(isValidFormat(history.state?.format)) selectedFormat=history.state.format;
if (section && !openUploadOnLocalFotoMag(section, false, history.state || {}))
openView(section, { ...history.state, setHash: false });
else if (!section) closeView();
});
window.addEventListener('hashchange', () => {
const section = hashRoutes[location.hash];
if (section && section !== active && !openUploadOnLocalFotoMag(section)) openView(section, { setHash: false });
});
if (!openUploadOnLocalFotoMag(hashRoutes[location.hash])) {
if (hashRoutes[location.hash]) openView(hashRoutes[location.hash], { setHash: false });
else selectedDock('home');
}
})();
