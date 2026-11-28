(() => {
'use strict';
const PAGE=8;
const itemKey=p=>p.sku||'classic';
const quantity=value=>Math.min(100,Math.max(1,Math.trunc(Number(value))||1));
const getGroup=name=>{const n=name.toLowerCase();if(n.includes('хамелеон'))return 'Хамелеоны';if(n.includes('термо'))return 'Термокружки';if(n.includes('молочник'))return 'Молочники';if(n.includes('ложк'))return 'С ложкой';if(n.includes('конус')||n.includes('латте'))return 'Конусные';if(n.includes('ручк'))return 'Особые ручки';if(n.includes('stackable')||n.includes('классическая')||n.includes('цветные'))return 'Классические и цветные';return 'Другие серии';};
const retail=p=>typeof p?.price==='number'?p.price.toLocaleString('ru-RU')+' ₽':'Цену уточним';
const color=p=>{if(!p.sku)return 'белая';const m=p.name.toLowerCase().match(/белая\s*[/]\s*(белая|голубая|красная|розовая|черная|чёрная|желтая|жёлтая|зелёная|зеленая)/i);return m?'белая / '+m[1]:(p.color||'Цвет указан в названии');};
function productURL(p,base){const url=new URL('mugs.html',base);url.search='';url.hash='';url.searchParams.set('sku',itemKey(p));return url.href;}
function orderText(p,qty,note,base){
 if(!p)return '';
 const lines=['Здравствуйте! Хочу заказать кружку с фотографией в FotoMag.','Серия: '+p.series,'Товар: '+p.name,'Цвет / вариант: '+color(p),'Артикул: '+(p.sku||'для классической белой уточняется'),'Количество: '+quantity(qty)+' шт.'];
 lines.push(typeof p.price==='number'?'Розничная цена за штуку: '+p.price+' ₽':'Розничная цена: уточним до оформления.');
 lines.push('Ссылка на товар: '+productURL(p,base));
 if(String(note||'').trim())lines.push('Пожелания: '+String(note).trim().slice(0,350));
 lines.push('Прикреплю свою фотографию. Подтвердите стоимость, наличие и срок изготовления.');
 return lines.join('\n');
}
// Node release checks exercise these same functions without a DOM.
if(typeof module==='object'&&module.exports&&typeof document==='undefined'){
 module.exports={PAGE,itemKey,quantity,getGroup,retail,color,productURL,orderText};return;
}
const $=id=>document.getElementById(id),root=$('catalog');
const steps={title:$('stepTitle'),sub:$('stepSub'),label:$('stepLabel'),meta:$('metaLeft'),page:$('metaRight'),back:$('backBtn'),next:$('forwardBtn'),num:$('stepNum')};
const zoom=$('photoDialog'),zoomImg=$('photoImage'),zoomName=$('photoCaption'),zoomTitle=$('photoTitle');
const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const channels={
 direct:[['vk','VK','https://vk.com/write103477713'],['max','MAX','https://max.ru/u/f9LHodD0cOJ4xQH5eXwmG7FE-sm42CyZd4DzqF_2BbIDG9GFNtKI4fbc5LU'],['tg','Telegram','https://t.me/Gug18aa'],['mail','Яндекс.Почта','mailto:kodakprint@yandex.ru']],
 bots:[['vk','VK-бот','https://vk.com/write-20848548'],['max','MAX-бот','https://max.ru/id180904019369_bot'],['tg','Telegram-бот','https://t.me/fotomag_orders_bot']]
};
const initial=()=>({step:1,series:null,sku:null,seriesPage:0,itemPage:0,search:'',filter:'Все',mode:'direct',channel:null,qty:1,note:'',zoomSku:null});
let data=null,series=[],state=initial(),depth=0,routeMessage='';
const drafts=new Map();
function keepDraft(){if(state.sku)drafts.set(state.sku,{qty:state.qty,note:state.note})}
const getItem=()=>data?.items.find(p=>itemKey(p)===state.sku);
const getSeries=()=>series.find(s=>s.name===state.series);
const variants=()=>data.items.filter(p=>p.series===state.series);
const safeImg=p=>p?.image?'<img loading="lazy" decoding="async" src="'+esc(p.image)+'" alt="'+esc(p.name)+'">':'<span class="image-pending" aria-label="Фотография готовится">☕</span>';
function pageControls(n,total,kind){
 const pages=Math.ceil(total/PAGE);if(pages<=1)return'';
 return '<div class="pager"><button type="button" data-page="'+esc(kind)+'" data-delta="-1" '+(n===0?'disabled':'')+' aria-label="Предыдущая страница">Назад</button><span>'+(n+1)+' / '+pages+'</span><button type="button" data-page="'+esc(kind)+'" data-delta="1" '+(n>=pages-1?'disabled':'')+' aria-label="Следующая страница">Вперёд</button></div>';
}
function renderSeries(){
 let list=series.filter(s=>(state.filter==='Все'||s.group===state.filter));
 const q=state.search.toLowerCase().trim();
 if(q)list=list.filter(s=>s.name.toLowerCase().includes(q)||data.items.some(p=>p.series===s.name&&(p.name.toLowerCase().includes(q)||(p.sku||'').includes(q))));
 state.seriesPage=Math.min(state.seriesPage,Math.max(0,Math.ceil(list.length/PAGE)-1));
 const view=list.slice(state.seriesPage*PAGE,(state.seriesPage+1)*PAGE);
 steps.page.textContent='Серии '+(view.length?state.seriesPage*PAGE+1:0)+'–'+Math.min(list.length,(state.seriesPage+1)*PAGE)+' из '+list.length;
 const gs=[...new Set(['Все',...series.map(x=>x.group),state.filter])];
 root.innerHTML=(routeMessage?'<p class="help" role="status">'+esc(routeMessage)+'</p>':'')+'<div class="chips" aria-label="Категории кружек">'+gs.map(g=>'<button type="button" class="chip" data-filter="'+esc(g)+'" aria-pressed="'+(g===state.filter)+'">'+esc(g)+'</button>').join('')+'</div>'+
 '<div class="search"><input id="searchInput" type="search" placeholder="Серия, цвет или артикул…" aria-label="Поиск серии" value="'+esc(state.search)+'"></div>'+
 '<div class="tile-grid">'+view.map(s=>{const p=data.items.find(p=>p.series===s.name);return '<article class="tile"><div class="tile-image">'+safeImg(p)+'</div><div class="tile-name">'+esc(s.name)+'</div><div class="tile-caption">'+s.count+' '+(s.count===1?'вариант':'вариантов')+' · '+esc(s.group)+'</div><button class="tile-action" type="button" data-series="'+esc(s.name)+'">Цвета и артикулы</button></article>'}).join('')+'</div>'+
 (!list.length?'<div class="empty-state"><p role="status">'+esc(q?'По вашему запросу ничего не найдено. Попробуйте другое название или артикул.':'В категории «'+state.filter+'» пока нет подтверждённых моделей. Наличие и варианты можно уточнить у FotoMag.')+'</p><a class="copy" href="./#direct">Уточнить у FotoMag</a><button class="copy" type="button" data-filter="Все" data-reset-search>Все серии</button></div>':'')+pageControls(state.seriesPage,list.length,'series')+'<p class="help">Названия серий сохранены из каталога «Сублимагии». Белая классическая кружка FotoMag — отдельная позиция за 650 ₽.</p>';
}
function renderVariants(){
 const s=getSeries();if(!s)return setStep(1);
 const list=variants();state.itemPage=Math.min(state.itemPage,Math.max(0,Math.ceil(list.length/PAGE)-1));
 const view=list.slice(state.itemPage*PAGE,(state.itemPage+1)*PAGE);
 steps.page.textContent='Модели '+(view.length?state.itemPage*PAGE+1:0)+'–'+Math.min(list.length,(state.itemPage+1)*PAGE)+' из '+list.length;
 root.innerHTML='<p class="help"><b>Серия: '+esc(s.name)+'</b><br>Нажмите «Выбрать» у нужного цвета. По фотографии можно открыть полноэкранный просмотр.</p>'+
 '<div class="tile-grid">'+view.map(p=>'<article class="tile"><button class="tile-image" type="button" data-zoom="'+esc(p.sku||'classic')+'" '+(p.image?'':'disabled ')+'aria-label="'+esc(p.image?'Посмотреть фото '+p.name:'Фотография этой модели готовится')+'">'+safeImg(p)+'</button><div class="sku">'+(p.sku?'АРТ. '+esc(p.sku):'Фотоцентр FotoMag')+'</div><div class="tile-name">'+esc(color(p))+'</div><div class="tile-caption">'+esc(p.name)+'</div><div class="price">'+esc(retail(p))+'</div><button class="tile-action" type="button" data-item="'+esc(p.sku||'classic')+'">Выбрать вариант</button></article>').join('')+'</div>'+pageControls(state.itemPage,list.length,'items');
}
function renderDetail(){
 const p=getItem();if(!p)return setStep(2);steps.page.textContent=p.sku?'АРТ. '+p.sku:'Классическая белая';
 root.innerHTML='<button class="detail-photo" type="button" data-zoom="'+esc(p.sku||'classic')+'" '+(p.image?'':'disabled ')+'aria-label="'+(p.image?'Увеличить фото':'Фотография этой модели готовится')+'">'+safeImg(p)+'</button><div class="detail-panel"><span class="sku">'+(p.sku?'АРТ. '+esc(p.sku):'FotoMag · отдельная модель')+'</span><strong>'+esc(p.name)+'</strong><p><b>Серия:</b> '+esc(p.series)+'</p><p><b>Цвет:</b> '+esc(color(p))+'</p><p class="price">'+esc(retail(p))+'</p><p>Наличие и сроки изготовления подтверждает сотрудник.</p></div>'+
 (p.image?'<button class="detail-zoom" type="button" data-zoom="'+esc(p.sku)+'">⛶ Открыть на весь экран</button>':'<p class="help">Изображение белой классической модели добавим после подтверждения эталона — фото другой кружки не подставляем.</p>');
}
function compose(){return orderText(getItem(),state.qty,state.note,document.querySelector('link[rel="canonical"]')?.href||location.href);}
function renderSend(){
 const p=getItem();if(!p)return setStep(2);
 steps.page.textContent='Личное обращение или бот';
 const active=channels[state.mode];
 root.innerHTML='<div class="summary">'+(p.image?'<img loading="lazy" src="'+esc(p.image)+'" alt="">':'<span class="image-pending">☕</span>')+'<div><strong>'+esc(p.name)+'</strong><small>'+(p.sku?'Артикул '+esc(p.sku):'Белая классическая')+' · '+esc(retail(p))+'</small></div></div>'+
 '<label class="request-label" for="quantity">Количество, шт.</label><input class="request-control" id="quantity" type="number" inputmode="numeric" min="1" max="100" step="1" value="'+state.qty+'">'+
 '<label class="request-label" for="comment">Пожелания</label><textarea class="request-control" id="comment" rows="2" maxlength="350" placeholder="Печать фото, подарок…">'+esc(state.note)+'</textarea>'+
 '<p class="request-label">Способ заказа</p><div class="mode-tabs"><button type="button" data-mode="direct" class="'+(state.mode==='direct'?'active':'')+'">Лично сотруднику</button><button type="button" data-mode="bots" class="'+(state.mode==='bots'?'active':'')+'">Через бота</button></div>'+
 '<div class="channels">'+active.map(c=>'<button type="button" class="channel '+esc(c[0])+'" data-channel="'+esc(c[0])+'" aria-pressed="'+(state.channel===c[0])+'">'+esc(c[1])+'</button>').join('')+'</div>'+
 '<label class="request-label" for="requestText">Текст запроса</label><textarea class="request-control" id="requestText" readonly rows="8">'+esc(compose())+'</textarea>'+
 '<button type="button" class="copy" data-copy>📋 Скопировать текст заказа</button><p id="sendStatus" class="status" role="status" aria-live="polite"></p><a id="manualChannel" class="copy" hidden target="_blank" rel="noopener noreferrer">Открыть выбранный чат</a>'+
 '<p class="help">Скопируйте текст, вставьте его в чат и прикрепите фотографию. Для почты подготовлен текст письма. Нажмите «Отправить» в самом приложении: открытие чата или письма не отправляет заявку.</p>';
}
function readRoute(saved){
 const query=new URLSearchParams(location.search),p=data.items.find(x=>itemKey(x)===query.get('sku'));
 state={...initial(),...(saved||{})};
 if(!saved){
  state.filter=query.get('group')||'Все';state.series=query.get('series');
  if(p){state.sku=itemKey(p);state.series=p.series;state.step=query.get('step')==='4'?4:3;}
  else if(query.has('sku'))routeMessage='Такой артикул не найден. Выберите модель в каталоге или уточните её у сотрудника.';
  else if(series.some(s=>s.name===state.series))state.step=2;
 }
 if(state.sku&&drafts.has(state.sku))Object.assign(state,drafts.get(state.sku));
 state.qty=quantity(state.qty);state.note=String(state.note||'').slice(0,350);
 state.search=String(state.search||'').slice(0,120);state.filter=String(state.filter||'Все').slice(0,80);
 state.seriesPage=Math.max(0,Math.trunc(Number(state.seriesPage))||0);state.itemPage=Math.max(0,Math.trunc(Number(state.itemPage))||0);
 if(!getSeries()){state.series=null;state.sku=null;state.step=1;}
 if(!getItem()&&state.step>2)state.step=state.series?2:1;
 if(!channels[state.mode])state.mode='direct';
 if(!channels[state.mode].some(c=>c[0]===state.channel))state.channel=null;
 state.step=Math.min(4,Math.max(1,Math.trunc(state.step)||1));
 if(!data.items.some(p=>itemKey(p)===state.zoomSku&&p.image))state.zoomSku=null;
}
function viewURL(){
 const url=new URL(location.href);url.search='';url.hash='';
 if(state.filter!=='Все')url.searchParams.set('group',state.filter);
 if(state.step>=2&&state.series)url.searchParams.set('series',state.series);
 if(state.step>=3&&state.sku)url.searchParams.set('sku',state.sku);
 if(state.step===4)url.searchParams.set('step','4');
 return url.href;
}
function remember(mode='replace',scroll=window.scrollY){
 // Quantity/comment remain in this tab's history; shared links carry only product data.
 history[mode==='push'?'pushState':'replaceState']({...history.state,fotomagMugs:{...state},mugsDepth:depth,mugsScroll:scroll},'',viewURL());
}
function navigate(patch,push=true){
 keepDraft();remember();state={...state,...patch,zoomSku:null};routeMessage='';
 if(patch.sku)Object.assign(state,drafts.get(patch.sku)||{qty:1,note:''});
 if(push)depth++;
 render();remember(push?'push':'replace',0);
 window.scrollTo({top:0,behavior:'instant'});steps.title.focus({preventScroll:true});
}
function setStep(step){navigate({step:Math.max(1,Math.min(4,step))});}
function goBack(){
 if(state.step===1){location.href='souvenirs.html';return;}
 if(depth>0)history.back();else navigate({step:state.step-1},false);
}
window.addEventListener('popstate',e=>{
 if(!data)return;
 keepDraft();const previousZoom=state.zoomSku;routeMessage='';readRoute(e.state?.fotomagMugs);depth=Number(e.state?.mugsDepth)||0;
 if(zoom.open)zoom.close();render();
 if(state.zoomSku)openPhoto(state.zoomSku);
 else if(previousZoom){const target=[...root.querySelectorAll('[data-zoom]')].find(b=>b.dataset.zoom===previousZoom);(target||steps.title).focus({preventScroll:true});}
 else steps.title.focus({preventScroll:true});
 window.scrollTo({top:Number(e.state?.mugsScroll)||0,behavior:'instant'});
});
function render(){
 if(!data)return;
 const n=state.step;steps.label.textContent='ШАГ '+n+' ИЗ 4';steps.num.textContent=n+' / 4';
 const titles=['Кружки с вашим фото','Выберите цвет и артикул','Выбранная кружка','Отправить запрос'];
 const descriptions=['Сначала выберите серию кружек, как в каталоге поставщика.','Теперь выберите точную модель, цвет и артикул.','Посмотрите фото на весь экран и проверьте название.','Выберите личный контакт FotoMag либо бота.'];
 steps.title.textContent=titles[n-1];steps.sub.textContent=descriptions[n-1];
 steps.meta.textContent=n===1?series.length+' серия · '+data.items.length+' вариантов':n===2?(state.series||'Выбор серии'):n===3?(getItem()?.name||'Товар'):'Подготовка заявки';
 steps.back.textContent=n===1?'Фотосувениры':'Назад';
 steps.next.textContent=n===4?(state.channel?(state.channel==='mail'?'Открыть письмо':'Открыть чат'):'Выберите канал'):'Далее';
 steps.next.disabled=n===1?!state.series:n===2?!state.sku:n===4?!state.channel:false;
 if(n===1)renderSeries();else if(n===2)renderVariants();else if(n===3)renderDetail();else renderSend();
}
async function copyRequest(){
 const box=$('requestText'),status=$('sendStatus');
 try{await navigator.clipboard.writeText(compose());if(status)status.textContent='Текст скопирован. Вставьте его в чат и прикрепите фото.';return true}
 catch(e){if(box){box.focus();box.select()}if(status)status.textContent='Автоматически скопировать не удалось. Текст выделен: скопируйте вручную, затем откройте чат.';return false}
}
function sendChannel(){
 const c=channels[state.mode].find(c=>c[0]===state.channel);if(!c)return;
 const input=$('quantity');state.qty=quantity(input?.value||state.qty);if(input)input.value=state.qty;remember();
 if(c[0]==='mail'&&state.mode==='direct'){
  location.href='mailto:kodakprint@yandex.ru?subject='+encodeURIComponent('FotoMag — заказ кружки '+(getItem()?.sku||''))+'&body='+encodeURIComponent(compose());
  $('sendStatus').textContent='Текст подготовлен для письма. Прикрепите фото и отправьте письмо в почтовом приложении.';return;
 }
 const manual=$('manualChannel');manual.href=c[2];manual.hidden=false;
 // Begin copying before focus moves. This link remains available if opening is declined.
 void copyRequest();window.open(c[2],'_blank','noopener,noreferrer');
}
function next(){
 if(state.step===1){if(state.series)setStep(2)}
 else if(state.step===2){if(state.sku)setStep(3)}
 else if(state.step===3)setStep(4);
 else sendChannel();
}
steps.next.addEventListener('click',next);
steps.back.addEventListener('click',goBack);
root.addEventListener('click',e=>{
 const t=e.target.closest('[data-filter],[data-series],[data-item],[data-zoom],[data-page],[data-mode],[data-channel],[data-copy]');
 if(!t)return;
 if(t.dataset.filter){state.filter=t.dataset.filter;state.seriesPage=0;state.series=null;state.sku=null;if(t.hasAttribute('data-reset-search'))state.search='';routeMessage='';render();remember();[...root.querySelectorAll('[data-filter]')].find(b=>b.dataset.filter===state.filter)?.focus();return}
 if(t.dataset.series){navigate({series:t.dataset.series,sku:null,itemPage:0,step:2});return}
 if(t.dataset.item){navigate({sku:t.dataset.item,step:3});return}
 if(t.dataset.zoom){showZoom(t.dataset.zoom);return}
 if(t.dataset.page){if(t.dataset.page==='series')state.seriesPage+=Number(t.dataset.delta);else state.itemPage+=Number(t.dataset.delta);render();remember();root.querySelector('[data-series],[data-item]')?.focus();return}
 if(t.dataset.mode){state.mode=t.dataset.mode;state.channel=null;render();remember();root.querySelector('[data-mode="'+state.mode+'"]')?.focus();return}
 if(t.dataset.channel){state.channel=t.dataset.channel;render();remember();root.querySelector('[data-channel="'+state.channel+'"]')?.focus();return}
 if(t.hasAttribute('data-copy'))copyRequest();
});
root.addEventListener('input',e=>{
 if(e.target.id==='searchInput'){
 const pos=e.target.selectionStart??0;state.search=e.target.value;state.seriesPage=0;state.series=null;state.sku=null;render();remember();const i=$('searchInput');if(i){i.focus();i.setSelectionRange(pos,pos)}return;
 }
 if(e.target.id==='quantity'){state.qty=quantity(e.target.value);const i=$('requestText');if(i)i.value=compose();keepDraft();remember()}
 if(e.target.id==='comment'){state.note=e.target.value;const i=$('requestText');if(i)i.value=compose();keepDraft();remember()}
});
root.addEventListener('change',e=>{if(e.target.id==='quantity')e.target.value=state.qty});
let gallery=[],gpos=0;
function openPhoto(sku){
 const p=data.items.find(x=>itemKey(x)===sku);if(!p?.image)return;
 gallery=data.items.filter(x=>x.series===p.series&&x.image);gpos=Math.max(0,gallery.findIndex(x=>itemKey(x)===sku));zoomView();if(!zoom.open)zoom.showModal();$('photoClose').focus();
}
function showZoom(sku){
 if(!data.items.some(p=>itemKey(p)===sku&&p.image))return;
 remember();state.zoomSku=sku;depth++;remember('push');openPhoto(sku);
}
function closeZoom(){
 if(state.zoomSku&&depth>0)history.back();else{state.zoomSku=null;zoom.close();remember();}
}
function zoomView(){
 const p=gallery[gpos];if(!p)return;
 zoomImg.src=p.image;zoomImg.alt=p.name;zoomName.textContent=p.name;
 zoomTitle.textContent='Артикул '+(p.sku||'—')+' · '+(gpos+1)+'/'+gallery.length;
 $('photoPrev').disabled=gpos===0;$('photoNext').disabled=gpos===gallery.length-1;
}
function movePhoto(delta){gpos=Math.min(gallery.length-1,Math.max(0,gpos+delta));state.zoomSku=itemKey(gallery[gpos]);zoomView();remember();}
$('photoClose').addEventListener('click',closeZoom);
$('photoPrev').addEventListener('click',()=>movePhoto(-1));$('photoNext').addEventListener('click',()=>movePhoto(1));
zoom.addEventListener('cancel',e=>{e.preventDefault();closeZoom()});
window.addEventListener('keydown',e=>{if(!zoom.open)return;if(e.key==='ArrowRight'){e.preventDefault();movePhoto(1)}if(e.key==='ArrowLeft'){e.preventDefault();movePhoto(-1)}});
fetch('assets/mug-catalog.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}).then(j=>{
 if(!j.items||j.items.length!==139)throw Error('Неверный формат каталога');
 data=j;const groups=new Map();
 for(const p of j.items){const value=groups.get(p.series)||{name:p.series,count:0,group:getGroup(p.series)};value.count++;groups.set(p.series,value)}
 series=[...groups.values()].sort((a,b)=>(a.name.startsWith('Белая классическая')?-1:b.name.startsWith('Белая классическая')?1:a.name.localeCompare(b.name,'ru')));
 readRoute(history.state?.fotomagMugs);depth=Number(history.state?.mugsDepth)||0;render();remember();if(state.zoomSku)openPhoto(state.zoomSku);
}).catch(()=>{root.innerHTML='<p class="help">Не удалось загрузить каталог кружек. Проверьте интернет и обновите страницу. Если ошибка повторяется, напишите сотруднику FotoMag.</p>';steps.next.disabled=true});
})();