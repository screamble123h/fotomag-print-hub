(function(){
  const bar=document.getElementById("floating"),bots=document.getElementById("bots");
  if(!bar||!bots)return;
  let scheduled=false;
  const order450=document.getElementById("order450");
  function update(){
    scheduled=false;
    const r=bots.getBoundingClientRect();
    const o=order450?.getBoundingClientRect();
    const orderingVisible=!!o && o.top<window.innerHeight-50 && o.bottom>55;
    bar.classList.toggle("is-visible",r.bottom<40 && window.scrollY>150 && !orderingVisible);
  }
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
  window.addEventListener("scroll",schedule,{passive:true});window.addEventListener("resize",schedule,{passive:true});update();
  const personalDetails=document.getElementById("personal-contacts");
  if(personalDetails){
    const openPersonal=()=>{
      personalDetails.open=true;
      requestAnimationFrame(()=>personalDetails.scrollIntoView({behavior:"smooth",block:"start"}));
    };
    for(const el of document.querySelectorAll("[data-open-personal]")){
      el.addEventListener("click",openPersonal);
    }
    if((window.location.hash==="#personal-contacts"||window.location.hash==="#direct"))personalDetails.open=true;
    window.addEventListener("hashchange",()=>{
      if((window.location.hash==="#personal-contacts"||window.location.hash==="#direct"))personalDetails.open=true;
    });
  }
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
  const online450Copy=document.getElementById("order450-copy");
  const online450Text=document.getElementById("order450-request-text");
  const online450Status=document.getElementById("order450-copy-status");
  if(online450Copy&&online450Text&&online450Status){
    online450Copy.addEventListener("click",async()=>{
      try{
        if(!navigator.clipboard?.writeText)throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(online450Text.value);
        online450Status.textContent="Текст скопирован. Откройте чат FotoMag, вставьте текст и прикрепите фотографию.";
      }catch(_){
        online450Text.focus();
        online450Text.select();
        online450Status.textContent="Автоматическое копирование недоступно: текст выделен. Скопируйте его вручную, затем откройте чат.";
      }
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
