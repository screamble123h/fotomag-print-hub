(function(){
  const bar=document.getElementById("floating"),bots=document.getElementById("bots");
  if(!bar||!bots)return;
  let scheduled=false;
  function update(){scheduled=false; const r=bots.getBoundingClientRect();bar.classList.toggle("is-visible",r.bottom<40 && window.scrollY>150);}
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
  window.addEventListener("scroll",schedule,{passive:true});window.addEventListener("resize",schedule,{passive:true});update();
  const selected=document.getElementById("order-selection");
  const selectedText=document.getElementById("order-selection-text");
  const copy=document.getElementById("copy-service");
  const options=Object.freeze({
    photo:{label:"Печать фотографий",message:"Здравствуйте! Хочу заказать печать фотографий. Размер: ___. Количество: ___. Бумага: ___. Файлы прикрепляю."},
    docs:{label:"Печать документов",message:"Здравствуйте! Хочу распечатать документы. Формат: ___. Цветная или чёрно-белая: ___. Экземпляров: ___. Файл прикрепляю."},
    photo10x15:{label:"Печать фотографий 10×15",message:"Здравствуйте! Хочу заказать печать фотографий 10×15. Количество: ___. Бумага и способ печати: ___. Файлы прикрепляю."},
    docsA4bw:{label:"Печать документов А4, чёрно-белая",message:"Здравствуйте! Хочу распечатать документы А4. Печать: чёрно-белая. Количество страниц: ___. Экземпляров: ___. Файл прикрепляю."}
  });
  let active=null;
  for(const a of document.querySelectorAll("a[data-service]")){
    a.addEventListener("click",()=>{
      const item=options[a.dataset.service];
      if(!item||!selected||!selectedText||!copy)return;
      active=a.dataset.service;
      selectedText.textContent="Выбрано: "+item.label+". Откройте мессенджер ниже и укажите услугу внутри бота.";
      selected.hidden=false;
      copy.textContent="Скопировать текст для сообщения";
    });
  }
  if(copy){
    copy.addEventListener("click",async()=>{
      const item=options[active];
      if(!item)return;
      try{
        if(!navigator.clipboard||!navigator.clipboard.writeText)throw new Error("clipboard unavailable");
        await navigator.clipboard.writeText(item.message);
        copy.textContent="Текст скопирован ✓";
      }catch(_){
        copy.textContent="Не удалось скопировать — напишите своими словами";
      }
    });
  }
})();
