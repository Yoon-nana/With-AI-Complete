/* 서버의 마빗 카운트로 미션을 완료합니다. 시간만으로 넘어가지 않습니다. */
(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  const moves={
    2:{image:'arm-wave.png',instruction:'양손 주먹을 쥐고 양팔을 가볍게 흔들어 보세요.'},
    3:{image:'arm-curl.png',instruction:'주먹을 쥐고 팔을 접었다 펴 보세요.'},
    4:{image:'wrist-circle.png',instruction:'손목을 바깥으로 천천히 돌려 보세요.'}
  };
  let missionId=null, completeSpoken=false, wasPaused=false, speechToken=0;
  const card=document.createElement('button');
  card.id='app-choice-exercise';card.dataset.action='exercise_start';
  card.innerHTML='<span aria-hidden="true">✦</span><strong>가벼운 체조</strong><small>무작위 1~5회 미션에 도전해요</small>';
  document.querySelector('.app-choices').append(card);
  function current(){return typeof state!=='undefined'?state:null;}
  function stopVoice(){speechToken++;if('speechSynthesis'in window)speechSynthesis.cancel();}
  function instruction(m){return `${m.title}${m.classId===4?'를':'을'} ${m.goal}회 해 보세요. ${moves[m.classId].instruction}`;}
  function speak(text){
    stopVoice();if(!el('exercise-voice').checked||!text)return;
    const status=el('exercise-voice-status');
    if(!('speechSynthesis'in window)||!('SpeechSynthesisUtterance'in window)){status.textContent='이 브라우저는 음성을 지원하지 않아요.';return;}
    const ticket=speechToken;
    const play=()=>{
      if(ticket!==speechToken||current()?.app!=='exercise')return;
      const voices=speechSynthesis.getVoices(),ko=voices.filter(v=>/^ko(?:-|_)/i.test(v.lang));
      if(voices.length&&!ko.length){status.textContent='한국어 음성이 없어 화면으로 안내합니다.';return;}
      const u=new SpeechSynthesisUtterance(text);u.lang='ko-KR';u.rate=.85;
      if(ko.length)u.voice=ko.find(v=>v.localService)||ko[0];
      u.onstart=()=>{if(ticket===speechToken)status.textContent='목표 횟수와 동작을 안내하고 있어요.';};
      u.onend=()=>{if(ticket===speechToken)status.textContent='다시 듣기로 목표를 한 번 더 들을 수 있어요.';};
      u.onerror=e=>{if(ticket===speechToken&&!['canceled','interrupted'].includes(e.error))status.textContent='다시 듣기를 눌러 주세요.';};
      speechSynthesis.resume();speechSynthesis.speak(u);
    };
    if(speechSynthesis.getVoices().length)play();else setTimeout(play,500);
  }
  function render(){
    const s=current(),m=s?.activity?.exercise?.mission;
    if(s?.app!=='exercise'||!m){if(missionId!==null){stopVoice();missionId=null;}return;}
    const move=moves[m.classId];if(!move)return;
    if(m.id!==missionId){
      missionId=m.id;completeSpoken=false;wasPaused=m.paused;
      el('exercise-title').textContent=m.title;
      el('exercise-number').textContent='동작 '+String(m.classId).padStart(2,'0');
      el('exercise-instruction').textContent=`${m.title} ${m.goal}회 해 보세요.`;
      el('exercise-detail').textContent=move.instruction;
      el('exercise-image').src='/assets/exercise/'+move.image;
      el('exercise-image').alt=m.title+' 동작을 보여주는 어르신';
      el('exercise-image-caption').textContent=move.instruction;
      document.querySelectorAll('[data-exercise-chip]').forEach(node=>node.classList.toggle('is-current',Number(node.dataset.exerciseChip)===m.classId));
      speak(instruction(m));
    }
    el('exercise-countdown').innerHTML=m.done+'<span>/ '+m.goal+'회</span>';
    el('exercise-progress-bar').style.width=(m.done/m.goal*100)+'%';
    el('exercise-progress').setAttribute('aria-valuemax',String(m.goal));
    el('exercise-progress').setAttribute('aria-valuenow',String(m.done));
    el('exercise-pause').textContent=m.paused?'이어서 하기':'잠시 멈춤';
    el('exercise-run-state').textContent=m.complete?'목표 횟수 달성!':m.paused?'잠시 멈췄어요':'마빗 카운트로 확인하고 있어요';
    el('exercise-mission-state').textContent=m.complete?'잘하셨어요! 다음 미션을 준비해요':`목표까지 ${m.goal-m.done}회 남았어요`;
    el('exercise-session-count').textContent='완료한 미션 '+s.activity.exercise.completed+'개';
    el('exercise-sensor-state').textContent=s.activity.sensor.message;
    if(m.paused&&!wasPaused)stopVoice();
    if(!m.paused&&wasPaused)speak(instruction(m));
    wasPaused=m.paused;
    if(m.complete&&!completeSpoken){completeSpoken=true;speak('잘하셨어요.');}
  }
  el('exercise-close').addEventListener('click',()=>{stopVoice();request('exercise_end');});
  el('exercise-pause').addEventListener('click',()=>request('exercise_pause'));
  el('exercise-repeat').addEventListener('click',()=>{const m=current()?.activity?.exercise?.mission;if(m&&!m.paused)speak(instruction(m));});
  el('exercise-voice').addEventListener('change',()=>{if(!el('exercise-voice').checked)stopVoice();else{const m=current()?.activity?.exercise?.mission;if(m)speak(instruction(m));}});
  window.addEventListener('pagehide',stopVoice);
  setInterval(render,100);
  window.ExerciseGuide=Object.freeze({getState:()=>({active:current()?.app==='exercise',mission:current()?.activity?.exercise?.mission})});
})();
