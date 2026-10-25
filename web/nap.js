(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  const card=document.createElement('button');card.id='app-choice-nap';
  card.dataset.action='open_app';card.dataset.value='nap';
  card.innerHTML='<span aria-hidden="true">☾</span><strong>낮잠 자기</strong><small>쉬는 시간을 정하면 깨워드려요</small>';
  document.querySelector('.app-choices').insertBefore(card,document.getElementById('app-choice-daywatch'));
  let lastRing=null,lastSoundAt=0,audio=null;
  const tones=new Set();
  function stopWakeSound(){
    if('speechSynthesis'in window)speechSynthesis.cancel();
    for(const tone of tones){try{tone.stop();}catch(error){/* 이미 종료 */}}
    tones.clear();if(audio)audio.suspend().catch(()=>{});
  }
  function prepareAudio(){
    try{const Audio=window.AudioContext||window.webkitAudioContext;if(Audio){audio=audio||new Audio();audio.resume().catch(()=>{});}}catch(error){/* 화면 알림은 유지 */}
  }
  function wakeSound(){
    const voices='speechSynthesis'in window?speechSynthesis.getVoices():[];
    const ko=voices.find(v=>/^ko(?:-|_)/i.test(v.lang));
    if(ko){speechSynthesis.cancel();const u=new SpeechSynthesisUtterance('낮잠 시간이 끝났어요. 천천히 일어나세요.');u.lang='ko-KR';u.voice=ko;u.rate=.85;speechSynthesis.speak(u);}
    else if(audio&&audio.state==='running'){
      for(let i=0;i<3;i++){const tone=audio.createOscillator(),gain=audio.createGain(),at=audio.currentTime+i*.4;tones.add(tone);tone.onended=()=>{tones.delete(tone);tone.disconnect();gain.disconnect();};tone.frequency.value=i===1?660:880;gain.gain.setValueAtTime(0,at);gain.gain.linearRampToValueAtTime(.12,at+.03);gain.gain.linearRampToValueAtTime(0,at+.28);tone.connect(gain).connect(audio.destination);tone.start(at);tone.stop(at+.3);}
    }
  }
  el('nap-form').addEventListener('submit',event=>{event.preventDefault();prepareAudio();request('nap_start',JSON.stringify(Number(el('nap-minutes').value)));});
  el('nap-end').addEventListener('click',()=>{stopWakeSound();request('nap_end');});
  el('sensor-config-form').addEventListener('submit',event=>{event.preventDefault();request('sensor_config',JSON.stringify({port:el('sensor-port').value,drive:el('sensor-drive').value}));});
  function render(){
    if(typeof state==='undefined'||!state?.activity)return;
    const a=state.activity,nap=a.nap;
    el('nap-form').hidden=nap.active;
    el('nap-status-card').hidden=!nap.active;
    el('nap-status-card').classList.toggle('ringing',nap.ringing);
    el('nap-status').textContent=nap.ringing?'일어날 시간이에요!':'편안히 쉬세요';
    el('nap-end').textContent=nap.ringing?'일어났어요 · 알람 끄기':'낮잠 마치기';
    el('nap-due').textContent=nap.due?'깨워드릴 시각: '+new Date(nap.due).toLocaleTimeString('ko-KR'):'';
    const seconds=nap.due?Math.max(0,Math.ceil((new Date(nap.due)-Date.now())/1000)):0;
    el('nap-remaining').textContent=nap.ringing?'알람이 울리고 있어요':`${Math.floor(seconds/60)}분 ${seconds%60}초 남았어요`;
    el('sensor-switch-state').textContent=a.sensor.message;
    if(document.activeElement!==el('sensor-port'))el('sensor-port').value=a.sensor.port;
    if(document.activeElement!==el('sensor-drive'))el('sensor-drive').value=a.sensor.drive;
    if(nap.ringing&&(lastRing!==nap.id||performance.now()-lastSoundAt>=5000)){
      lastRing=nap.id;lastSoundAt=performance.now();
      if(!state.robot.available||!state.robot.sound)wakeSound();
    }
    if(!nap.ringing&&lastRing!==null){stopWakeSound();lastRing=null;}
  }
  setInterval(render,200);
})();
