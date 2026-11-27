(() => {
'use strict';
const $=id=>document.getElementById(id),root=$('catalog');
const steps={title:$('stepTitle'),sub:$('stepSub'),label:$('stepLabel'),meta:$('metaLeft'),page:$('metaRight'),back:$('backBtn'),next:$('forwardBtn'),num:$('stepNum')};
const zoom=$('photoDialog'),zoomImg=$('photoImage'),zoomName=$('photoCaption'),zoomTitle=$('photoTitle');
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const channels={
 direct:[['vk','VK','https://vk.com/write103477713'],['max','MAX','https://max.ru/u/f9LHodD0cOJ4xQH5eXwmG7FE-sm42CyZd4DzqF_2BbIDG9GFNtKI4fbc5LU'],['tg','Telegram','https://t.me/Gug18aa'],['mail','Почта','mailto:kodakprint@yandex.ru']],
 bots:[['vk','VK-бот','https://vk.com/write-20848548'],['max','MAX-бот','https://max.ru/id180904019369_bot'],['tg','Telegram-бот','https://t.me/fotomag_orders_bot']]
};
let data=null,series=[],state={step:1,series:null,sku:null,seriesPage:0,itemPage:0,search:'',filter:new URLSearchParams(location.search).get('group')||'Все',mode:'direct',channel:null,qty:1,note:''};
const PAGE=8;
const getItem=()=>data?.items.find(p=>(p.sku||'classic')===state.sku);
const getSeries=()=>series.find(s=>s.name===state.series);
const variants=()=>data.items.filter(p=>p.series===state.series);
const getGroup=name=>{const n=name.toLowerCase();if(n.includes('хамелеон'))return 'Хамелеоны';if(n.includes('термо'))return 'Термокружки';if(n.includes('молочник'))return 'Молочники';if(n.includes('ложк'))return 'С ложкой';if(n.includes('конус'))return 'Конусные';if(n.includes('ручк'))return 'Особые ручки';if(n.includes('stackable')||n.includes('белая классическая'))return 'Классические и цветные';return 'Другие серии';};
const retail=p=>typeof p?.price==='number'?p.price.toLocaleString('ru-RU')+' ₽':'Цена уточняется';
const color=p=>{if(!p.sku)return 'белая';const t=p.name.toLowerCase(),m=t.match(/белая\s*[/]\s*(белая|голубая|красная|розовая|черная|чёрная|желтая|жёлтая|зелёная|зеленая)/i);if(m)return 'белая / '+m[1];if(p.color)return p.color;return 'Цвет указан в названии';};
const safeImg=p=>p?.image?'<img loading="lazy" decoding="async" src="'+esc(p.image)+'" alt="'+esc(p.name)+'">':'<span class="image-pending" aria-label="Фотография готовится">☕</span>';
function pageControls(n,total,kind){
 const pages=Math.ceil(total/PAGE);if(pages<=1)return'';
 return '<div class="pager"><button type="button" data-page="'+esc(kind)+'" data-delta="-1" '+(n===0?'disabled':'')+' aria-label="Предыдущая страница">←</button><span>'+(n+1)+' / '+pages+'</span><button type="button" data-page="'+esc(kind)+'" data-delta="1" '+(n>=pages-1?'disabled':'')+' aria-label="Следующая страница">→</button></div>';
}
function renderSeries(){
 let list=series.filter(s=>(state.filter==='Все'||s.group===state.filter));
 const q=state.search.toLowerCase().trim();
 if(q)list=list.filter(s=>s.name.toLowerCase().includes(q)||data.items.some(p=>p.series===s.name&&(p.name.toLowerCase().includes(q)||(p.sku||'').includes(q))));
 state.seriesPage=Math.min(state.seriesPage,Math.max(0,Math.ceil(list.length/PAGE)-1));
 const view=list.slice(state.seriesPage*PAGE,(state.seriesPage+1)*PAGE);
 steps.page.textContent='Серии '+(view.length?state.seriesPage*PAGE+1:0)+'–'+Math.min(list.length,(state.seriesPage+1)*PAGE)+' из '+list.length;
 const gs=['Все',...new Set(series.map(x=>x.group))];
 root.innerHTML='<div class="chips" aria-label="Категории кружек">'+gs.map(g=>'<button type="button" class="chip" data-filter="'+esc(g)+'" aria-pressed="'+(g===state.filter)+'">'+esc(g)+'</button>').join('')+'</div>'+
 '<div class="search"><input id="searchInput" type="search" placeholder="Серия, цвет или артикул…" aria-label="Поиск серии" value="'+esc(state.search)+'"></div>'+
 '<div class="tile-grid">'+view.map(s=>{const p=data.items.find(p=>p.series===s.name);return '<article class="tile"><div class="tile-image">'+safeImg(p)+'</div><div class="tile-name">'+esc(s.name)+'</div><div class="tile-caption">'+s.count+' '+(s.count===1?'вариант':'вариантов')+' · '+esc(s.group)+'</div><button class="tile-action" type="button" data-series="'+esc(s.name)+'">Цвета и артикулы →</button></article>'}).join('')+'</div>'+
 pageControls(state.seriesPage,list.length,'series')+'<p class="help">Названия серий сохранены из каталога «Сублимагии». Белая классическая кружка FotoMag — отдельная позиция за 650 ₽.</p>';
}
function renderVariants(){
 const s=getSeries();if(!s)return setStep(1);
 const list=variants();state.itemPage=Math.min(state.itemPage,Math.max(0,Math.ceil(list.length/PAGE)-1));
 const view=list.slice(state.itemPage*PAGE,(state.itemPage+1)*PAGE);
 steps.page.textContent='Модели '+(view.length?state.itemPage*PAGE+1:0)+'–'+Math.min(list.length,(state.itemPage+1)*PAGE)+' из '+list.length;
 root.innerHTML='<p class="help"><b>Серия: '+esc(s.name)+'</b><br>Нажмите «Выбрать» у нужного цвета. По фотографии можно открыть полноэкранный просмотр.</p>'+
 '<div class="tile-grid">'+view.map(p=>'<article class="tile"><button class="tile-image" type="button" data-zoom="'+esc(p.sku||'classic')+'" aria-label="Посмотреть фото '+esc(p.name)+'">'+safeImg(p)+'</button><div class="sku">'+(p.sku?'АРТ. '+esc(p.sku):'Фотоцентр FotoMag')+'</div><div class="tile-name">'+esc(color(p))+'</div><div class="tile-caption">'+esc(p.name)+'</div><div class="price">'+esc(retail(p))+'</div><button class="tile-action" type="button" data-item="'+esc(p.sku||'classic')+'">Выбрать вариант →</button></article>').join('')+'</div>'+pageControls(state.itemPage,list.length,'items');
}
function renderDetail(){
 const p=getItem();if(!p)return setStep(2);steps.page.textContent=p.sku?'АРТ. '+p.sku:'Классическая белая';
 root.innerHTML='<button class="detail-photo" type="button" data-zoom="'+esc(p.sku||'classic')+'" aria-label="Увеличить фото">'+safeImg(p)+'</button><div class="detail-panel"><span class="sku">'+(p.sku?'АРТ. '+esc(p.sku):'FotoMag · отдельная модель')+'</span><strong>'+esc(p.name)+'</strong><p><b>Серия:</b> '+esc(p.series)+'</p><p><b>Цвет:</b> '+esc(color(p))+'</p><p class="price">'+esc(retail(p))+'</p><p>Наличие и сроки изготовления подтверждает сотрудник.</p></div>'+
 (p.image?'<button class="detail-zoom" type="button" data-zoom="'+esc(p.sku)+'">⛶ Открыть на весь экран</button>':'<p class="help">Изображение белой классической модели добавим после подтверждения эталона — фото другой кружки не подставляем.</p>');
}
function compose(){
 const p=getItem();if(!p)return'';
 const a=['Здравствуйте! Хочу заказать кружку с фотографией в FotoMag.','Серия: '+p.series,'Товар: '+p.name,'Цвет / вариант: '+color(p),'Артикул: '+(p.sku||'для классической белой уточняется'),'Количество: '+state.qty+' шт.'];
 if(p.price!=null)a.push('Розничная цена за штуку: '+p.price+' ₽');else a.push('Розничную цену уточните, пожалуйста.');
 if(state.note.trim())a.push('Пожелания: '+state.note.trim());
 a.push('Прикреплю свою фотографию. Подтвердите стоимость, наличие и срок изготовления.');
 return a.join('\n');
}
function renderSend(){
 const p=getItem();if(!p)return setStep(2);
 steps.page.textContent='Напрямую или через бота';
 const active=channels[state.mode];
 root.innerHTML='<div class="summary">'+(p.image?'<img loading="lazy" src="'+esc(p.image)+'" alt="">':'<span class="image-pending">☕</span>')+'<div><strong>'+esc(p.name)+'</strong><small>'+(p.sku?'Артикул '+esc(p.sku):'Белая классическая')+' · '+esc(retail(p))+'</small></div></div>'+
 '<label class="request-label" for="quantity">Количество, шт.</label><input class="request-control" id="quantity" type="number" min="1" max="100" value="'+state.qty+'">'+
 '<label class="request-label" for="comment">Пожелания</label><textarea class="request-control" id="comment" rows="2" maxlength="350" placeholder="Печать фото, подарок…">'+esc(state.note)+'</textarea>'+
 '<label class="request-label">Способ заказа</label><div class="mode-tabs"><button type="button" data-mode="direct" class="'+(state.mode==='direct'?'active':'')+'">Написать напрямую</button><button type="button" data-mode="bots" class="'+(state.mode==='bots'?'active':'')+'">Через бота</button></div>'+
 '<div class="channels">'+active.map(c=>'<button type="button" class="channel '+esc(c[0])+'" data-channel="'+esc(c[0])+'" aria-pressed="'+(state.channel===c[0])+'">'+esc(c[1])+'</button>').join('')+'</div>'+
 '<label class="request-label" for="requestText">Текст запроса</label><textarea class="request-control" id="requestText" readonly rows="8">'+esc(compose())+'</textarea>'+
 '<button type="button" class="copy" data-copy>📋 Скопировать текст заказа</button><p id="sendStatus" class="status" role="status" aria-live="polite"></p>'+
 '<p class="help">Перед отправкой прикрепите фотографию в выбранном приложении. Открытие мессенджера не означает, что заказ принят: подтверждение даёт сотрудник.</p>';
}
function setStep(step){state.step=Math.max(1,Math.min(4,step));render();window.scrollTo({top:0,behavior:'instant'});}
function render(){
 if(!data)return;
 const n=state.step;steps.label.textContent='ШАГ '+n+' ИЗ 4';steps.num.textContent=n+' / 4';
 const titles=['Кружки с вашим фото','Выберите цвет и артикул','Выбранная кружка','Отправить запрос'];
 const descriptions=['Сначала выберите серию кружек, как в каталоге поставщика.','Теперь выберите точную модель, цвет и артикул.','Посмотрите фото на весь экран и проверьте название.','Выберите личный контакт FotoMag либо бота.'];
 steps.title.textContent=titles[n-1];steps.sub.textContent=descriptions[n-1];
 steps.meta.textContent=n===1?series.length+' серия · 139 вариантов':n===2?(state.series||'Выбор серии'):n===3?(getItem()?.name||'Товар'):'Подготовка заявки';
 steps.back.textContent=n===1?'← Фотосувениры':'← Назад';
 steps.next.textContent=n===4?(state.channel?'Открыть чат →':'Выберите канал'):'Далее →';
 steps.next.disabled=n===1?!state.series:n===2?!state.sku:n===4?!state.channel:false;
 if(n===1)renderSeries();else if(n===2)renderVariants();else if(n===3)renderDetail();else renderSend();
}
async function copyRequest(){
 const box=$('requestText'),status=$('sendStatus');
 try{await navigator.clipboard.writeText(compose());if(status)status.textContent='Текст скопирован. Вставьте его в чат и прикрепите фото.';return true}
 catch(e){if(box){box.focus();box.select()}if(status)status.textContent='Текст выделен. Скопируйте вручную и отправьте в чат.';return false}
}
function sendChannel(){
 const c=channels[state.mode].find(c=>c[0]===state.channel);if(!c)return;
 if(c[0]==='mail'&&state.mode==='direct'){location.href='mailto:kodakprint@yandex.ru?subject='+encodeURIComponent('FotoMag — заказ кружки '+(getItem()?.sku||''))+'&body='+encodeURIComponent(compose());return}
 const tab=window.open(c[2],'_blank','noopener,noreferrer');
 copyRequest();
 if(!tab){const status=$('sendStatus');if(status)status.textContent='Если приложение не открылось, разрешите всплывающее окно либо скопируйте текст запроса.'}
}
function next(){
 if(state.step===1){if(state.series)setStep(2)}
 else if(state.step===2){if(state.sku)setStep(3)}
 else if(state.step===3)setStep(4);
 else sendChannel();
}
steps.next.addEventListener('click',next);
steps.back.addEventListener('click',()=>{if(state.step===1)location.href='souvenirs.html';else setStep(state.step-1)});
root.addEventListener('click',e=>{
 const t=e.target.closest('[data-filter],[data-series],[data-item],[data-zoom],[data-page],[data-mode],[data-channel],[data-copy]');
 if(!t)return;
 if(t.dataset.filter){state.filter=t.dataset.filter;state.seriesPage=0;render();return}
 if(t.dataset.series){state.series=t.dataset.series;state.sku=null;state.itemPage=0;setStep(2);return}
 if(t.dataset.item){state.sku=t.dataset.item;setStep(3);return}
 if(t.dataset.zoom){showZoom(t.dataset.zoom);return}
 if(t.dataset.page){if(t.dataset.page==='series')state.seriesPage+=Number(t.dataset.delta);else state.itemPage+=Number(t.dataset.delta);render();return}
 if(t.dataset.mode){state.mode=t.dataset.mode;state.channel=null;render();return}
 if(t.dataset.channel){state.channel=t.dataset.channel;render();return}
 if(t.hasAttribute('data-copy'))copyRequest();
});
root.addEventListener('input',e=>{
 if(e.target.id==='searchInput'){
 const pos=e.target.selectionStart??0;state.search=e.target.value;state.seriesPage=0;render();const i=$('searchInput');if(i){i.focus();i.setSelectionRange(pos,pos)}return;
 }
 if(e.target.id==='quantity'){state.qty=Math.min(100,Math.max(1,Number(e.target.value)||1));const i=$('requestText');if(i)i.value=compose()}
 if(e.target.id==='comment'){state.note=e.target.value;const i=$('requestText');if(i)i.value=compose()}
});
let gallery=[],gpos=0;
function showZoom(sku){
 const p=data.items.find(x=>(x.sku||'classic')===sku);if(!p?.image)return;
 gallery=variants().filter(x=>x.image);gpos=Math.max(0,gallery.findIndex(x=>x.sku===sku));zoomView();zoom.showModal();
}
function zoomView(){
 const p=gallery[gpos];if(!p)return;
 zoomImg.src=p.image;zoomImg.alt=p.name;zoomName.textContent=p.name;
 zoomTitle.textContent='Артикул '+(p.sku||'—')+' · '+(gpos+1)+'/'+gallery.length;
 $('photoPrev').disabled=gpos===0;$('photoNext').disabled=gpos===gallery.length-1;
}
$('photoClose').addEventListener('click',()=>zoom.close());
$('photoPrev').addEventListener('click',()=>{gpos=Math.max(0,gpos-1);zoomView()});
$('photoNext').addEventListener('click',()=>{gpos=Math.min(gallery.length-1,gpos+1);zoomView()});
zoom.addEventListener('click',e=>{if(e.target===zoom)zoom.close()});
window.addEventListener('keydown',e=>{if(zoom.open&&e.key==='ArrowRight')$('photoNext').click();if(zoom.open&&e.key==='ArrowLeft')$('photoPrev').click()});
fetch('assets/mug-catalog.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}).then(j=>{
 if(!j.items||j.items.length!==139)throw Error('Неверный формат каталога');
 data=j;const groups=new Map();
 for(const p of j.items){const value=groups.get(p.series)||{name:p.series,count:0,group:getGroup(p.series)};value.count++;groups.set(p.series,value)}
 series=[...groups.values()].sort((a,b)=>(a.name.startsWith('Белая классическая')?-1:b.name.startsWith('Белая классическая')?1:a.name.localeCompare(b.name,'ru')));
 if(state.filter!=='Все'&&!series.some(s=>s.group===state.filter))state.filter='Все';
 render();
}).catch(()=>{root.innerHTML='<p class="help">Не удалось загрузить каталог кружек. Проверьте интернет и обновите страницу. Если ошибка повторяется, напишите сотруднику FotoMag.</p>';steps.next.disabled=true});
})();