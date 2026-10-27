(()=>{
 'use strict';
 const status=document.getElementById('entry-status');
 let pending=false;
 function launch(params){
  if(pending)return;
  pending=true;
  status.textContent='연결 도우미를 여는 중입니다…';
  const query=new URLSearchParams(params);
  location.href='aigo-in://open?port=AUTO'+(query.size?'&'+query:'');
  status.textContent='연결 도우미 실행을 허용해 주세요. 처음 사용하는 PC라면 아래 설치 안내를 펼쳐 주세요.';
  pending=false;
 }
 document.addEventListener('click',event=>{
  const button=event.target.closest('button[data-action="open_app"]');
  if(button)launch({app:button.dataset.value});
 });
 document.getElementById('in-robot-open').onclick=()=>launch({device:'robot'});
 document.getElementById('in-microbit-open').onclick=()=>launch({device:'microbit'});
})();
