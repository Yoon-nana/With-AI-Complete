(()=>{
 'use strict';
 const el=id=>document.getElementById(id),dialog=el('in-connect-dialog');
 let kind='robot',pending=false,autoPort=new URLSearchParams(location.search).get('robot_port');
 async function api(path,body){
  const response=await fetch(path,{method:body?'POST':'GET',headers:{'X-Kiosk-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(10000)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'연결 요청 실패');return result;
 }
 async function ports(){el('in-connect-message').textContent='포트 목록을 가져오고 있습니다…';try{const data=await api('/api/ports');el('in-device-list').replaceChildren();const first=document.createElement('option');first.value='';first.textContent='연결할 장치를 선택하세요';el('in-device-list').append(first);for(const port of data.ports){const option=document.createElement('option');option.value=port.port;option.textContent=port.port+' · '+port.description;el('in-device-list').append(option)}el('in-connect-message').textContent=data.ports.length+'개 장치를 찾았습니다. 장치에 맞는 포트를 선택하세요.'}catch(error){el('in-connect-message').textContent=error.message}}
 function open(device){kind=device;el('in-connect-title').textContent=device==='robot'?'로보독 연결하기':'마이크로비트 연결하기';el('in-connect-guide').textContent=device==='robot'?'이 PC에 연결한 로보독의 COM 포트를 선택하세요.':'처음 사용하는 마이크로비트 V2라면 아래에서 프로그램을 다운로드하고 그림 안내를 따라 설치하세요. 설치 후 USB 포트를 선택해 연결합니다. 로보독과 다른 포트를 사용하세요.';el('in-dialog-hex').hidden=device!=='microbit';el('in-device-port').value=device==='robot'?(state?.robot?.port||''):(state?.activity?.sensor?.port||'');dialog.showModal();ports()}
 async function connect(){
  if(pending)return;const port=el('in-device-port').value.trim().toUpperCase();if(!/^COM[1-9][0-9]{0,3}$/.test(port)){el('in-connect-message').textContent='장치의 COM 포트를 선택하세요.';return}
  pending=true;el('in-device-connect').disabled=true;el('in-connect-message').textContent='연결 요청 중…';
  try{
   if(kind==='robot'){await api('/api/connect-robot',{port});el('in-connect-message').textContent='로보독 연결 중입니다. 상단에서 실제 연결 결과를 확인하세요.'}
   else {
    if(state?.robot?.available&&state.robot.port?.toUpperCase()===port)throw Error('로보독과 마이크로비트는 서로 다른 포트로 연결하세요.');
    if(!state)throw Error('화면을 불러온 뒤 다시 연결하세요.');
    const result=await api('/api/event',{action:'sensor_config',value:JSON.stringify({port,drive:''}),revision:state.revision,requestId:crypto.randomUUID()});state=result;render();el('in-connect-message').textContent='마이크로비트 연결 설정을 적용했습니다. 상단에서 수신 상태를 확인하세요.';
   }
   await refresh();
  }catch(error){el('in-connect-message').textContent=error.message}finally{pending=false;el('in-device-connect').disabled=false}
 }
 el('in-robot-open').onclick=()=>open('robot');el('in-microbit-open').onclick=()=>open('microbit');
 el('in-connect-close').onclick=()=>dialog.close();el('in-ports-refresh').onclick=ports;
 el('in-device-list').onchange=()=>{el('in-device-port').value=el('in-device-list').value};el('in-device-connect').onclick=connect;
 el('in-robot-disconnect').onclick=async()=>{try{await api('/api/disconnect-robot',{});await refresh()}catch(error){el('in-robot-status').textContent=error.message}};
 function update(){if(!state)return;const robot=state.robot,connecting=robot.connectionPending;
  el('in-robot-open').disabled=!!robot.available||connecting;el('in-robot-disconnect').disabled=!robot.available||connecting;
  el('in-robot-status').textContent=connecting?'로보독 연결 중…':robot.available?'로보독 '+robot.port+' 연결됨':robot.status||'로보독 미연결 · 화면 사용 가능';
  el('in-microbit-status').textContent=state.activity?.sensor?.message||'마이크로비트를 연결하세요.';
  if(autoPort&&!connecting){const selected=autoPort;autoPort=null;history.replaceState(null,'',location.pathname+location.hash);if(!robot.available){kind='robot';el('in-device-port').value=selected;dialog.showModal();connect()}}
 }
 setInterval(update,350);update();
})();
