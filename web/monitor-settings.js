(()=>{
 const el=id=>document.getElementById(id);
 let pending=false,dirty=false;
 const toggle=el('daywatch-enabled'),form=el('daywatch-settings-form');
 async function save(config){
  if(pending)return;pending=true;toggle.disabled=true;
  try{await request('daywatch_config',JSON.stringify(config));dirty=false;}
  finally{pending=false;toggle.disabled=false;update();}
 }
 toggle.addEventListener('change',()=>save({enabled:toggle.checked}));
 form.addEventListener('input',()=>{dirty=true});
 form.addEventListener('submit',e=>{e.preventDefault();save({triggerSeconds:Number(el('daywatch-trigger-seconds').value),responseSeconds:Number(el('daywatch-response-seconds').value)})});
 function update(){
  if(typeof state==='undefined'||!state?.daywatch)return;
  const d=state.daywatch;
  if(!pending)toggle.checked=d.enabled;
  el('daywatch-enabled-state').textContent=!d.enabled?'꺼짐 · 마빗 감지와 자동 모의 신고를 멈춥니다. 보드가 휴식 모드로 전환됩니다.':state.activity?.mode!=='checking'?'켜짐 · 체조·낮잠이 끝나면 마빗 감지를 재개합니다.':'켜짐 · 무응답 감지를 사용합니다.';
  if(!dirty){el('daywatch-trigger-seconds').value=d.triggerSeconds;el('daywatch-response-seconds').value=d.responseSeconds;}
 }
 setInterval(update,300);
})();
