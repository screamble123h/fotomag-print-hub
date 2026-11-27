(() => {
'use strict';
const choices=[...document.querySelectorAll('input[name="gift"]')];
const chosen=document.getElementById('gift-chosen');
const comment=document.getElementById('gift-note');
const preview=document.getElementById('gift-request-text');
const email=document.getElementById('gift-email');
const feedback=document.getElementById('gift-feedback');
const copy=document.getElementById('gift-copy');
if(!choices.length||!chosen||!comment||!preview||!email||!feedback||!copy)return;
function compose(){
const selected=choices.filter(x=>x.checked).map(x=>x.value);
const lines=['Здравствуйте! Интересуют фотосувениры FotoMag:'];
if(selected.length) selected.forEach(x=>lines.push('• '+x));
else lines.push('Подскажите, какие фотосувениры можно заказать.');
const note=comment.value.trim();
if(note)lines.push('Пожелания: '+note);
lines.push('Уточните, пожалуйста, стоимость, сроки и возможность изготовления.');
return {selected,text:lines.join('\n')};
}
function update(){
const state=compose();
chosen.textContent=state.selected.length?'Выбрано: '+state.selected.length+' — '+state.selected.join(', '):'Пока ничего не выбрано';
preview.value=state.text;
email.href='mailto:kodakprint@yandex.ru?subject='+encodeURIComponent('FotoMag — фотосувениры')+'&body='+encodeURIComponent(state.text);
feedback.textContent='';
}
choices.forEach(x=>x.addEventListener('change',update));
comment.addEventListener('input',update);
copy.addEventListener('click',async()=>{
try {
if(!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
await navigator.clipboard.writeText(preview.value);
feedback.textContent='Запрос скопирован. Откройте VK, MAX или Telegram, вставьте текст и прикрепите фото.';
}catch(_){
preview.focus();preview.select();
feedback.textContent='Автоматическое копирование недоступно. Текст выделен — скопируйте его вручную.';
}
});
update();
})();