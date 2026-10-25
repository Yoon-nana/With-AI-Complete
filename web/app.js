"use strict";
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
let state = null, category = "커피", sending = false, quitting = false;
let speechTimer=null, pendingSpeech='', lastSpeech='', lastSpeechAt=0;
let medFormInitialized=false;
function cancelSpeech(){
  clearTimeout(speechTimer);speechTimer=null;pendingSpeech='';
  if('speechSynthesis'in window)speechSynthesis.cancel();
}
const titles = {start:["WELCOME","주문 연습을 시작해 볼까요?"], service_mode:["STEP 01 · 이용 방식","어디에서 드시겠어요?"], menu:["STEP 02 · 메뉴 선택","원하는 음료를 골라 주세요"], options:["STEP 03 · 옵션 선택","음료 옵션과 사이드를 골라 주세요"], confirm:["STEP 04 · 주문 확인","주문 내용을 확인해 주세요"], complete:["WELL DONE!","주문을 완성했어요"]};
const stages = ["service_mode","menu","options","confirm","complete"];
const escapeHtml = text => String(text).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const won = number => Number(number).toLocaleString("ko-KR") + "원";
const imageFor = (menu,order) => order.temperature==='차갑게'?menu.coldImage:menu.image;
const storeIcon = '<svg viewBox="0 0 64 64" width="58" height="58" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M9 26 15 10h34l6 16M13 31v23h38V31M9 26c0 10 12 10 12 0 0 10 11 10 11 0 0 10 11 10 11 0 0 10 12 10 12 0M27 54V39h10v15M17 14h30"/></svg>';
const bagIcon = '<svg viewBox="0 0 64 64" width="58" height="58" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M15 23h34l4 33H11l4-33ZM24 27V16a8 8 0 0 1 16 0v11M25 38c0 9 14 9 14 0"/></svg>';
const button = (text,action,value="",className="") => `<button class="${className}" data-action="${action}" data-value="${escapeHtml(value)}">${text}</button>`;
function say(text,force=false){
  if(['PATROL','VERIFY','ALERT'].includes(state?.daywatch?.state)||['exercise','nap'].includes(state?.activity?.mode))return;
  if(state?.medication?.active)return; // STOP까지 짖음이 반복되므로 PC 안내는 끼워 넣지 않는다.
  if(state?.voice?.route && state.voice.route!=='pc')return;
  if (!$('voice').checked) return;
  if (!('speechSynthesis' in window)) { $('voice-status').textContent="이 브라우저에서는 음성 안내를 사용할 수 없어요."; return; }
  const voices = speechSynthesis.getVoices().filter(v=>v.lang.startsWith('ko') && v.localService);
  if(!voices.length){ $('voice-status').textContent="설치된 한국어 PC 음성이 없어 화면 문구로 안내해요."; return; }
  if(!force&&(pendingSpeech===text||(lastSpeech===text&&Date.now()-lastSpeechAt<1600)))return;
  cancelSpeech();pendingSpeech=text;
  const play=()=>{
    if(pendingSpeech!==text||!$('voice').checked||quitting)return;
    if((state.robot.available||state.robot.mode==='real')&&state.robot.sound&&state.robot.busy){speechTimer=setTimeout(play,250);return;}
    if(Number(state.ui.speechDelayMs)>0){speechTimer=setTimeout(play,Math.min(Number(state.ui.speechDelayMs)+150,1000));return;}
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice=voices[0];utterance.lang="ko-KR";utterance.rate=.85;
    utterance.onerror=event=>{if(!['canceled','interrupted'].includes(event.error))$('voice-status').textContent="음성 안내를 재생하지 못했어요. 화면 문구를 확인해 주세요.";};
    pendingSpeech='';lastSpeech=text;lastSpeechAt=Date.now();
    $('voice-status').textContent="PC의 한국어 음성으로 안내 중이에요.";
    speechSynthesis.speak(utterance);
  };
  const delay=Number(state.ui.speechDelayMs)||0;
  if(delay>0){$('voice-status').textContent='로보독 효과음이 끝나면 안내할게요.';speechTimer=setTimeout(play,delay+150);}else play();
}
async function request(action,value=""){
  if(sending || !state || quitting) return;
  sending=true;
  // 서버는 응답 전에 로봇을 움직일 수 있다. 응답을 받은 뒤 끊으면 늦다.
  cancelSpeech();
  try{
    if((state.robot.available||state.robot.mode==='real')&&state.robot.sound){
      // 브라우저 오디오 장치가 취소를 반영할 짧은 여유 후 요청한다.
      await new Promise(resolve=>setTimeout(resolve,150));
    }
    const response=await fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json','X-Kiosk-Token':token},body:JSON.stringify({action,value,revision:state.revision,requestId:crypto.randomUUID()})});
    const result=await response.json();
    if(!response.ok){ if(result.state){state=result.state;render();} $('guidance').textContent=result.error;$('network-error').textContent=result.error; say(result.error); return; }
    const oldScreen=state.screen;
    if(['start','start_stage','retry','variant','next_stage','new_random'].includes(action))category='커피';
    state=result; render(); $('network-error').textContent='';
    if(['sound_test','gesture_test','quit'].includes(action))cancelSpeech();
    if(oldScreen!==state.screen){cancelSpeech();window.scrollTo({top:0,behavior:'smooth'});}
    if(action==='quit'){quitting=true;$('network-error').textContent='프로그램을 종료했어요. 이 탭을 닫아 주세요.';}
    else if(!['sound_test','gesture_test','clear_warnings'].includes(action) && (state.app!=='kiosk'||state.ui?.autoSpeak||['set_mode','repeat','help','hint'].includes(action))) say(state.message,action==='repeat');
    if(oldScreen!==state.screen){$('heading').setAttribute('tabindex','-1');$('heading').focus({preventScroll:true});}
  }catch(error){$('network-error').textContent='PC 프로그램과 연결이 끊겼어요. 실행 창을 확인하고 화면 새로 연결을 눌러 주세요.';}
  finally{sending=false;}
}
function renderRobot(){
  if(!state)return;
  const robot=state.robot;
  $('robot-status').textContent=robot.status;
  $('robot-dot').classList.toggle('connected',robot.available);
  $('robot-event').textContent=(robot.busy?'몸동작 처리 중 · ':'')+(robot.bodyReactions?.length?`몸동작 후보 ${robot.bodyReactions.length}종 · `:'')+(robot.reaction?`${robot.mode==='mock'?'모의 몸 애교':'최근 몸 애교'} ${robot.reaction}`:robot.lastAction?`최근 요청 ${robot.lastAction}`:'');
  $('robot-warning').textContent=robot.warnings.join(' / ');
}
function render(){
  renderApp();
  const s=state, order=s.order, menu=s.menus.find(m=>m.id===order.menu);
  const lesson=s.screen==='start'?null:s.lesson;
  const assisted=Boolean(s.ui?.assisted), independent=s.mode==='practice';
  const assistanceLevel=s.ui.assistanceLevel;
  const lessonScreens=lesson?lesson.screens:stages;
  const completed=(s.curriculum||[]).filter(stage=>stage.completed).length;
  $('progress-count').textContent=`${completed} / ${(s.curriculum||[]).length} 완료`;
  $('mode-label').textContent=independent?'스스로 버전 · 목표만 보고 직접 주문':'안내 버전 · 할 일 자동 안내와 즉시 피드백';
  document.body.classList.toggle('independent-mode',independent);
  $('lesson-name').textContent=lesson?`${lesson.id}단계 · ${lesson.title}`:'원하는 스테이지를 골라 연습해요.';
  $('mission-index').textContent=lesson?`${lesson.id}단계 미션`:'오늘의 연습';
  $('voice-route').textContent=s.voice?.route==='robot'?'로보독에서 안내를 읽어 드려요.':'안내 목소리: PC · 로보독은 눈 표정·효과음·몸 애교로 반응해요.';
  $('heading').textContent=titles[s.screen][1];$('stage-label').textContent=titles[s.screen][0];
  if(lesson)$('stage-label').textContent=`STAGE ${String(lesson.id).padStart(2,'0')} · ${lesson.title}`;
  $('counter').textContent=s.screen==='start'?'':s.screen==='complete'?'학습 완료':`${Math.max(1,lessonScreens.indexOf(s.screen)+1)} / ${lessonScreens.length}`;
  $('guidance').textContent=s.message;
  $('guidance-level').textContent=['스스로 도전','기본 가이드 · 지금 할 일만','힌트 · 위치와 개념 설명','자세한 도움 · 정답 버튼과 순서'][assistanceLevel];
  if(!independent&&assistanceLevel===2)$('guidance-level').textContent='힌트 · 뜻과 이유, 찾을 단서';
  if(!independent&&assistanceLevel===3){
    $('guidance-level').textContent='자세한 도움 · 한 단계씩 따라 하기';
    $('guidance').textContent=s.message.replace(/ ([2-9]\. )/g,'\n$1');
  }
  document.querySelector('.guidance').hidden=!s.ui.showGuide;
  document.querySelector('[data-action=hint]').setAttribute('aria-pressed',String(assistanceLevel===2));
  document.querySelector('[data-action=help]').setAttribute('aria-pressed',String(assistanceLevel===3));
  if(s.screen==='start'){$('task').textContent='1단계부터 차근차근';$('task-detail').textContent='익숙한 단계는 바로 골라서 연습해도 좋아요.';}
  else if(s.target){$('task').textContent=s.screen==='service_mode'?'이용 방식 선택':s.screen==='menu'?'음료 선택':s.screen==='options'?'옵션·사이드 선택':'전체 주문 확인';$('task-detail').textContent=s.screenTask;}
  else{$('task').textContent='내가 고르는 자유 주문';$('task-detail').textContent='마시고 싶은 음료를 자유롭게 골라 보세요.';}
  const stepNames={service_mode:'이용 방식 고르기',menu:'음료 고르기',options:'옵션·사이드 고르기',confirm:'주문 확인하기',complete:'연습 완료'};
  $('steps').innerHTML=lessonScreens.map((screen,i)=>`<li class="${s.screen===screen?'current':s.screen==='complete'||lessonScreens.indexOf(s.screen)>i?'done':''}">${stepNames[screen]}</li>`).join('');
  $('steps').hidden=s.screen==='start'||(independent&&!assisted);
  $('categories').innerHTML=['커피','음료','티','에이드·주스'].map(c=>`<button data-category="${c}" class="${category===c?'active':''}" aria-pressed="${category===c}">${c}</button>`).join('');
  $('categories').hidden=s.screen!=='menu';
  const selected=(field,value)=>order[field]===value?' selected':'';
  let html='';
  if(s.screen==='start'){
    html=`<div class="learning-hub"><div class="hub-intro"><span class="eyebrow">주문 하나를 완성하는 ${s.curriculum.length}개의 미션</span><h3>기본 주문부터, 완전 랜덤 실전까지.</h3><p>같은 단계도 안내를 보며 배우거나, 스스로 도전할 수 있어요.</p></div><div class="mode-picker">${button('<strong>안내 버전</strong><span>할 일 자동 안내 · 선택 즉시 피드백</span>','set_mode','guided','mode-option'+(!independent?' mode-selected':''))}${button('<strong>스스로 버전</strong><span>자동 안내 없음 · 제출 후 결과 확인</span>','set_mode','practice','mode-option'+(independent?' mode-selected':''))}</div><p class="mode-description">${independent?'스스로 선택해 주문을 제출해요. 중간에 맞았는지는 알려주지 않아요. 도움은 언제든 요청할 수 있어요.':'기본은 현재 할 일만 자동으로 알려드려요. 힌트에서 위치와 개념을, 자세한 도움에서 정확한 버튼과 순서를 확인할 수 있어요.'}</p><div class="stage-grid">${(s.curriculum||[]).map((stage,i)=>(i===0||s.curriculum[i-1].band!==stage.band?`<h4 class="stage-group-heading">${escapeHtml(stage.band)}</h4>`:'')+button(`<span class="stage-number">${String(stage.id).padStart(2,'0')}</span><strong>${escapeHtml(stage.title)}</strong><span class="stage-focus">${escapeHtml(stage.focus)}</span><span class="stage-desc">${escapeHtml(stage.description)}</span><span class="stage-state">${stage.completed?'✓ 이 버전 완료 · 다시 연습':'연습 시작 →'}</span>`,'start_stage',String(stage.id),'stage-card'+(stage.completed?' mastered':''))).join('')}</div><div class="hub-extra">${button('정해진 주문 없이 자유롭게 연습','start','free','text-button')}</div></div>`;
  }else if(s.screen==='service_mode'){
    html=`<div class="choice-grid">${button('<span class="choice-icon">'+storeIcon+'</span>매장에서 먹기<small>매장 안에서 편안하게</small>','service','매장에서 먹기','choice-card'+selected('service','매장에서 먹기'))}${button('<span class="choice-icon">'+bagIcon+'</span>가져가기<small>포장해서 가져갈게요</small>','service','가져가기','choice-card'+selected('service','가져가기'))}</div>`;
  }else if(s.screen==='menu'){
    let items=s.menus.filter(m=>m.category===category);
    html='<div class="menu-grid">'+items.map(m=>button(`<span class="pill">${m.options.length===1?'ICE':'HOT / ICE'}</span>${order.menu===m.id?'<span class="selected-label">✓ 선택됨</span>':''}<img src="${m.image}" alt="${escapeHtml(m.name)}"><span class="menu-name">${escapeHtml(m.name)}</span><span class="price">${won(m.price)}</span>`,'menu',m.id,'menu-card'+selected('menu',m.id))).join('')+'</div>';
  }else if(s.screen==='options'){
    const groups=[{key:'temperature',label:'온도 · 필수 선택',values:menu.options,prices:{}},...s.optionSpecs];
    html=`<div class="options-layout"><div class="option-product"><img src="${imageFor(menu,order)}" alt="${escapeHtml(menu.name)}"><strong>${escapeHtml(menu.name)}</strong><p class="option-note">기본 옵션은 미리 선택되어 있어요.<br>추가 옵션은 연습용 구성입니다.</p></div><div class="customization">${groups.map(g=>`<section class="option-group" id="option-${g.key}"><h3>${escapeHtml(g.label)}</h3><div class="option-choices">${g.values.map(v=>button(`${g.key==='side'&&v!=='없음'?`<img class="side-photo" src="/assets/${({'초코칩 쿠키':'cookie','버터 쿠키':'butter-cookie','초코 머핀':'muffin'})[v]}.svg" alt="${escapeHtml(v)} 그림">`:''}<strong>${escapeHtml(v)}</strong><small>${g.prices[v]?'+'+won(g.prices[v]):'추가 금액 없음'}${order[g.key]===v?' · ✓ 선택됨':''}</small>`,g.key,v,'option-choice'+selected(g.key,v))).join('')}</div></section>`).join('')}</div></div>`;
  }else if(s.review){
    html=`<section class="review-card"><span class="eyebrow">스스로 주문한 결과</span><h3>다른 부분을 함께 살펴볼까요?</h3><p>제출 전에는 정답을 알려드리지 않았어요. 이제 주문을 비교해 보세요.</p><div class="review-head"><span>항목</span><span>내가 고른 것</span><span>연습 주문</span></div>${s.review.items.map(item=>`<div class="review-row ${item.correct?'match':'mismatch'}"><strong>${escapeHtml(item.label)} ${item.correct?'✓':'다시 확인'}</strong><span>${escapeHtml(item.actual)}</span><span>${escapeHtml(item.expected)}</span></div>`).join('')}<p>틀린 부분을 수정해서 다시 제출할 수 있어요.</p>${button('다시 수정하기','resume_review','','review-resume')}</section>`;
  }else if(s.screen==='confirm'){
    html=`<div class="summary"><dl><div><dt>이용 방식</dt><dd>${escapeHtml(order.service)}</dd></div><div><dt>선택한 메뉴</dt><dd>${escapeHtml(menu.name)} 1잔</dd></div><div><dt>온도</dt><dd>${escapeHtml(order.temperature)}</dd></div>${s.optionSpecs.map(spec=>`<div><dt>${escapeHtml(spec.label)}</dt><dd>${escapeHtml(order[spec.key])}${spec.key==='side'&&order.side!=='없음'?' 1개':''}</dd></div>`).join('')}<div class="total"><dt>연습 주문 금액</dt><dd>${won(s.total)}</dd></div></dl></div><div class="edit-buttons">${button('메뉴 수정','edit_menu')}${button('옵션·사이드 수정','edit_options')}</div>`;
  }else{
    html=`<div class="complete-card"><span class="complete-check">✓</span><h3>${lesson?`${lesson.id}단계, 해냈어요!`:'참 잘하셨어요!'}</h3><p class="receipt">${lesson?escapeHtml(lesson.title)+'<br>':''}${escapeHtml(menu.name)} · ${escapeHtml(order.temperature)} · ${escapeHtml(order.service)}<br>${s.optionSpecs.map(spec=>escapeHtml(spec.label)+": "+escapeHtml(order[spec.key])).join(" · ")}<br>합계 ${won(s.total)}<br>이번 연습의 도움 요청 ${s.helpCount}회<br>실제 결제는 진행되지 않았어요.</p><div class="complete-actions">${button(lesson?.randomized?'같은 랜덤 주문 재도전':'이 단계 다시 연습','retry')}${lesson?(lesson.randomized?button('새 랜덤 주문 뽑기','new_random'):button('다음 스테이지 →','next_stage')):button('다른 주문에 도전','variant')}</div></div>`;
  }
  $('content').innerHTML=html;
  if(s.review){$('heading').textContent='제출한 주문을 비교해 보세요';$('counter').textContent='결과 확인';$('steps').hidden=true;}
  $('service-tag').textContent=order.service||'이용 방식 선택 전';
  $('cart').innerHTML=menu?`<img src="${imageFor(menu,order)}" alt=""><div><strong>${escapeHtml(menu.name)}</strong><small>${escapeHtml(order.temperature||'온도 선택 전')} / 1잔</small><small>${s.optionSpecs.filter(spec=>order[spec.key]&&order[spec.key]!==spec.values[0]).map(spec=>escapeHtml(spec.label)+': '+escapeHtml(order[spec.key])).join(' · ')}</small></div><span class="amount">${won(s.total)}</span>`:'<span class="empty-cart">선택한 음료가 여기에 표시됩니다.</span>';
  const field={service_mode:'service',menu:'menu',options:'temperature'}[s.screen];
  const valid=s.canContinue, completeValid=s.canSubmit;
  $('primary').disabled=!(valid||completeValid||s.screen==='complete');
  $('primary').dataset.action=s.screen==='confirm'?'complete':s.screen==='complete'?'home':'next';
  $('primary').innerHTML=s.screen==='confirm'?`주문 연습 완료<small>${won(s.total)} · 실제 결제 없음</small>`:s.screen==='complete'?'처음으로':s.screen==='menu'?'옵션 선택하기 →':s.screen==='options'?'주문 확인하기 →':s.screen==='service_mode'?'메뉴 고르기 →':'연습을 선택해 주세요';
  if(lesson&&lesson.screens.length===1&&s.screen!=='complete')$('primary').textContent='이 단계 완료 ✓';
  if(independent&&s.screen==='confirm'&&!s.review)$('primary').innerHTML=`주문 제출하기<small>제출 후 결과 확인</small>`;
  if(independent&&lesson?.screens.length===1&&s.screen!=='complete'&&!s.review)$('primary').textContent='선택 제출하기';
  if(s.screen==='complete')$('primary').textContent='스테이지 목록으로';
  if(s.review){$('primary').disabled=false;$('primary').dataset.action='resume_review';$('primary').textContent='다시 수정하기';}
  if(assistanceLevel===3&&!s.review&&s.target){
    const actionFor=s.screen==='options'?['temperature',...s.optionSpecs.map(spec=>spec.key)].find(key=>s.target[key]!==undefined&&order[key]!==s.target[key]):{service_mode:'service',menu:'menu'}[s.screen];
    const targetValue=actionFor?s.target[actionFor]:null;
    const targetButton=Array.from($('content').querySelectorAll('button[data-action]')).find(b=>b.dataset.action===actionFor&&b.dataset.value===targetValue);
    if(targetButton){targetButton.classList.add('guided-focus');targetButton.insertAdjacentHTML('beforeend','<span class="guide-cue">여기를 눌러 보세요</span>');}
    if(valid||completeValid)$('primary').classList.add('guided-next');else $('primary').classList.remove('guided-next');
    if(s.screen==='menu'&&!targetButton){const targetMenu=s.menus.find(m=>m.id===s.target.menu);Array.from($('categories').querySelectorAll('button')).find(b=>b.dataset.category===targetMenu.category)?.classList.add('guided-focus');}
  }else $('primary').classList.remove('guided-next');
  if(assistanceLevel===2&&!s.review&&s.target){
    if(s.screen==='menu'){
      const targetMenu=s.menus.find(m=>m.id===s.target.menu);
      Array.from($('categories').querySelectorAll('button')).find(b=>b.dataset.category===targetMenu.category)?.classList.add('hint-focus');
    }else if(s.screen==='options'){
      const key=['temperature',...s.optionSpecs.map(spec=>spec.key)].find(k=>s.target[k]!==undefined&&order[k]!==s.target[k]);
      if(key)$('option-'+key)?.classList.add('hint-focus');
    }else if(s.screen==='service_mode')$('content').querySelector('.choice-grid')?.classList.add('hint-focus');
  }
  $('back').hidden=Boolean(s.review);
  $('back').disabled=['start','complete'].includes(s.screen);
  renderRobot();
}
function renderApp(){
  renderDaywatch();
  const med=state.medication, app=med.active?(med.activeKinds?.length===1&&med.activeKinds[0]==='nap'||!med.activeKinds?.length?'nap':'medication'):state.app;
  document.body.classList.toggle('app-hub-mode',app==='hub');
  document.body.classList.toggle('app-medication-mode',app==='medication');
  document.body.classList.toggle('app-daywatch-mode',app==='daywatch');
  $('daywatch-screen').hidden=app!=='daywatch';
  document.body.classList.toggle('exercise-mode',app==='exercise');
  document.body.classList.toggle('app-nap-mode',app==='nap');
  $('exercise-screen').hidden=app!=='exercise';
  $('nap-screen').hidden=app!=='nap';
  $('app-hub').hidden=app!=='hub';$('medication-screen').hidden=app!=='medication';
  const labels={idle:'알림 설정 전',armed:'복약 시간 예약됨',preparing:'약을 먹을 시간이에요',alerting:'짖는 소리로 알려드려요',waiting:'STOP QR 확인을 기다려요',stopping:'STOP 확인 · 반복 알림 중지',confirming:'준비 자세로 돌아가는 중',done:'이번 복약 알림 완료'};
  $('med-state').textContent=labels[med.status]||med.status;
  $('med-message').textContent=med.message;
  $('med-qr-status').textContent=med.qrStatus;
  $('med-due').textContent=med.due&&med.status!=='idle'?'예약 시각: '+new Date(med.due).toLocaleString('ko-KR',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}):'';
  $('med-status-card').classList.toggle('alerting',med.active);
  $('med-nav-status').textContent=med.active?(med.activeKinds?.includes('nap')?'낮잠 알람이 울리고 있어요':'복약 알림 확인이 필요해요'):med.pendingCount?`알람 ${med.pendingCount}개 · 다음 ${med.time}`:'';
  if(!medFormInitialized){$('med-time').value=med.time;medFormInitialized=true;}
  $('med-active-medicines').textContent=med.activeMedicines?.length?'지금 복용할 약: '+med.activeMedicines.join(' · '):'';
  $('med-schedule-count').textContent=`예약 ${med.pendingCount}개`;
  const entryLabels={armed:'예약됨',active:'알림 중',done:'확인 완료',cancelled:'취소됨'};
  $('med-schedule-list').innerHTML=(med.schedules||[]).map(entry=>`<li class="med-schedule ${entry.status==='active'?'is-active':''}"><div><strong>${escapeHtml(entry.time)}</strong><span>${escapeHtml(entry.medicine)}</span><small>${new Date(entry.due).toLocaleDateString('ko-KR',{month:'long',day:'numeric'})} · ${entryLabels[entry.status]}</small></div><button class="med-remove" data-action="med_remove" data-value="${escapeHtml(entry.id)}" aria-label="${escapeHtml(entry.time+' '+entry.medicine+' 삭제')}" ${entry.status==='active'?'disabled':''}>삭제</button></li>`).join('')||'<li class="med-empty">아직 등록한 시간이 없어요. 시간과 약 이름을 추가해 주세요.</li>';
  document.querySelector('.med-cancel').textContent='예약 전체 종료';
  $('med-mock-qr').hidden=state.robot.mode!=='mock'||!['waiting','alerting'].includes(med.status);
}
function renderDaywatch(){
  const d=state?.daywatch;if(!d)return;
  const labels={IDLE:'무응답 감지 대기',PREPARING:'준비 자세를 잡는 중',WAITING:'연결·동작 대기',MOCK:'모의 연결 · 실제 감시 없음',MONITOR:'자동 감시 중',PATROL:'사각형 순찰 중',VERIFY:'얼굴 확인 중',OK:'정상 확인 완료',ALERT:'쓰러짐 확정 · 반응 확인 중',REPORTED:'모의 신고 완료',MOTION_RESUMED:'움직임 감지 · 순찰 중지',SIGNAL_LOST:'마빗 신호 대기',AI_LOST:'AI 연결 대기',ERROR:'연결 확인 필요',MEDICATION:'복약 알림 우선 진행'};
  $('daywatch-state').textContent=labels[d.state]||d.state;
  $('daywatch-message').textContent=d.message;
  $('daywatch-result').textContent=d.decision===2?'사건 판정: 쓰러짐 확정 · 유지':d.decision===1?'사건 판정: 정상 확인':'아직 확정된 결과가 없습니다.';
  $('daywatch-input').textContent=`마빗: ${d.movement} · ${d.seconds}초`;
  $('daywatch-class').textContent=`모델 원본: ${d.raw} / 현재 필터: ${d.class}`;
  $('daywatch-route').textContent=`순찰 ${d.laps}바퀴 · ${d.phase==='corner'?'오른쪽 90도 회전':'직진'}`;
  const log=$('daywatch-log'),text=(d.logs||[]).join('\n');
  if(log.textContent!==text){log.textContent=text;log.scrollTop=log.scrollHeight;}
  if(document.activeElement!==$('daywatch-port'))$('daywatch-port').value=d.microbitPort||'COM6';
}
async function refresh(){
  if(sending||quitting)return;
  try{
    const response=await fetch('/api/state',{headers:{'X-Kiosk-Token':token}});if(!response.ok)throw Error();const next=await response.json();
    const medChanged=!state||state.medication.revision!==next.medication.revision;
    const wasActive=state?.medication?.active;
    const oldMedStatus=state?.medication?.status;
    const changed=!state||state.revision!==next.revision||state.app!==next.app||medChanged;
    state=next;
    if(state.medication.active&&(!wasActive||(state.medication.status==='preparing'&&oldMedStatus!=='preparing'))){cancelSpeech();window.scrollTo({top:0,behavior:'smooth'});}
    if(changed)render();else renderRobot();renderDaywatch();$('network-error').textContent='';
    if(['PATROL','VERIFY','ALERT'].includes(state.daywatch?.state))cancelSpeech();
    if(oldMedStatus!==state.medication.status&&['waiting','done'].includes(state.medication.status))say(state.medication.message);
  }
  catch(error){$('network-error').textContent='연결을 확인해 주세요. Thonny의 실행 창이 열려 있어야 합니다.';}
}
document.addEventListener('click',event=>{const buttonNode=event.target.closest('button');if(!buttonNode||buttonNode.disabled)return;if(buttonNode.dataset.category){category=buttonNode.dataset.category;render();return;}if(buttonNode.dataset.action)request(buttonNode.dataset.action,buttonNode.dataset.value||'');});
$('refresh').addEventListener('click',refresh);
$('med-form').addEventListener('submit',event=>{event.preventDefault();request('med_add',JSON.stringify({time:$('med-time').value,medicine:$('med-medicine').value}));});
$('daywatch-port-form').addEventListener('submit',event=>{event.preventDefault();request('daywatch_port',$('daywatch-port').value);});
$('fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(error){$('network-error').textContent='전체 화면을 열지 못했어요. 브라우저의 F11 키를 사용할 수 있어요.';}});
$('voice').addEventListener('change',()=>{if(!$('voice').checked)cancelSpeech();});
if(!token)$('network-error').textContent='Thonny에서 main.py를 실행해 열린 주소를 사용해 주세요.';else refresh();
setInterval(refresh,900);
