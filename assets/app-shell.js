/* FotoMag smartphone UI — no third-party scripts or data collection. */
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
    '#prices':'prices','#help':'help','#faq':'help'
  });
  const get = id => document.getElementById(id);
  let active = 'home';
  let messageTimer;
  let openTimer;
  let selectedFormat = '35x45';
  const formatOptions = Object.freeze({
    '35x45': {label:'35×45 мм',count:8},
    '3x4': {label:'3×4 см',count:6},
    '4x6': {label:'4×6 см',count:4}
  });
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
    active = section;
    sheetKicker.textContent = config.kicker;
    sheetTitle.textContent = config.title;
    sheetBody.replaceChildren(template.content.cloneNode(true));
    if(section==='id450') updateFormatUI();
    if(section==='personal') updatePersonalContext(options.orderFormat);
    if(section==='upload'){
      const select=sheetBody.querySelector('#upload-kind');
      if(select && ['photos','documents','id450'].includes(options.uploadKind))
        select.value=options.uploadKind;
      if(options.uploadKind==='id450'){
        const note=sheetBody.querySelector('#upload-comment');
        if(note){
          const chosen=formatOptions[selectedFormat];
          note.value='Фото на документы '+chosen.label+', '+chosen.count+' шт. — 450 ₽';
        }
      }
      window.FotoMagDirectUpload?.onView();
    }
    const sourceIcon = document.querySelector(`[data-action="${config.icon}"] .tile-icon svg`) ||
      document.querySelector(`[data-action="${config.icon}"] .dock-icon svg`);
    sheetIcon.replaceChildren();
    if (sourceIcon) sheetIcon.appendChild(sourceIcon.cloneNode(true));
    else sheetIcon.textContent = section === 'location' ? '⌖' : section === 'help' ? '?' : '✦';
    if (!sheet.open) {
      sheet.showModal();
      sheet.dataset.returnAction = previous && previous.getAttribute('data-action') || 'home';
    }
    sheetBody.scrollTop = 0;
    selectedDock(section);
    if (options.setHash !== false && window.location.hash !== config.route) {
      try { history.pushState({ view: section }, '', config.route); }
      catch (_) { location.hash = config.route; }
    }
    const closeBtn = get('sheet-close');
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }
  function closeView(options = {}) {
    clearTimeout(openTimer);
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
  function navigate(section, orderFormat, uploadKind) {
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
    const format=event.target.closest('[data-format]');
    if(format && format.closest('#sheet-body') && formatOptions[format.dataset.format]){
      selectedFormat=format.dataset.format;
      updateFormatUI();
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
      const btn = event.target.closest('button.app-tile,button.tip-banner,button.dock-btn,button.utility-action,button.sheet-main-cta,button.format-option,a.quick-bot');
      if (btn) btn.classList.add('pressed');
    }
  });
  document.addEventListener('keyup', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.target.closest('button.pressed')?.classList.remove('pressed');
    }
  });
  document.addEventListener('pointerdown', event => {
    const btn = event.target.closest('button.app-tile,button.tip-banner,button.dock-btn,button.utility-action,button.sheet-main-cta,button.format-option,a.quick-bot');
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
    active='home';selectedDock('home');
    if(window.location.hash && hashRoutes[window.location.hash]){
      try {history.replaceState({view:'home'},'',location.pathname+location.search);}catch(_){/* static fallback */}
    }
  });
  window.addEventListener('popstate', () => {
    const section = hashRoutes[location.hash];
    if (section) openView(section, { setHash: false });
    else closeView();
  });
  window.addEventListener('hashchange', () => {
    const section = hashRoutes[location.hash];
    if (section && section !== active) openView(section, { setHash: false });
  });
  if (hashRoutes[location.hash]) openView(hashRoutes[location.hash], { setHash: false });
  else selectedDock('home');
})();
