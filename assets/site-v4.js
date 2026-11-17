(function(){
  const bar=document.getElementById("floating"),bots=document.getElementById("bots");
  if(!bar||!bots)return;
  let scheduled=false;
  function update(){scheduled=false; const r=bots.getBoundingClientRect();bar.classList.toggle("is-visible",r.bottom<40 && window.scrollY>150);}
  function schedule(){if(!scheduled){scheduled=true;requestAnimationFrame(update);}}
  window.addEventListener("scroll",schedule,{passive:true});window.addEventListener("resize",schedule,{passive:true});update();
})();
