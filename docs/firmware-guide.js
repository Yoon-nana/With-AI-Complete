(()=>{
 'use strict';
 const script=document.currentScript,assets=script?.dataset.assetRoot||'/assets/microbit-guide/';
 const steps=[
  {title:'다운로드 폴더에서 파일을 찾아요',text:'파일 탐색기(노란 폴더 아이콘)를 열고 왼쪽의 「다운로드」를 선택하세요. 방금 받은 AIGO-IN-unified.hex 파일을 찾으세요.',image:'download-file.png',alt:'다운로드 폴더에서 AIGO-IN-unified HEX 파일을 선택한 실제 탐색기 화면',mark:'file',tip:'파일이 여러 개라면 가장 최근에 받은 파일을 선택하세요. 이름 뒤에 (1), (2) 같은 숫자가 붙어도 괜찮아요.'},
  {title:'파일을 한 번 누르고 복사해요',text:'프로그램 파일을 한 번 클릭한 뒤 키보드의 Ctrl 키를 누른 채 C를 누르세요. 상단의 복사 아이콘을 눌러도 됩니다.',image:'copy-file.png',alt:'HEX 파일이 선택되고 상단 복사 아이콘이 활성화된 탐색기 화면',mark:'copy',tip:'파일을 더블 클릭해 열 필요는 없어요. 선택 → Ctrl + C로 복사하세요.',keys:'Ctrl + C'},
  {title:'MICROBIT 드라이브를 열어요',text:'마이크로비트 V2를 USB 케이블로 PC에 연결하세요. 파일 탐색기 왼쪽 「내 PC」에서 「MICROBIT」를 선택하세요.',image:'microbit-drive.png',alt:'MICROBIT 드라이브를 열어 DETAILS와 MICROBIT 항목이 보이는 실제 탐색기 화면',mark:'drive',tip:'사진의 D:는 예시예요. 내 PC에서 E: 등 다른 문자로 보여도 MICROBIT라는 이름을 찾으면 됩니다.'},
  {title:'빈 곳에서 붙여넣기를 해요',text:'MICROBIT 드라이브 안의 빈 곳을 마우스 오른쪽 버튼으로 누르고 「붙여넣기」를 선택하세요. Ctrl + V를 눌러도 됩니다.',image:'paste-file.png',alt:'MICROBIT 드라이브의 빈 곳을 오른쪽 클릭하여 붙여넣기 메뉴를 연 실제 탐색기 화면',mark:'paste',tip:'다른 폴더 안으로 들어가지 말고, 지금 열린 MICROBIT 드라이브에 바로 붙여넣으세요.',keys:'Ctrl + V'},
  {title:'설치가 끝나면 이 화면으로 돌아와요',text:'복사가 끝나고 마이크로비트의 재시작이 끝날 때까지 USB를 연결한 채 기다리세요. 드라이브가 잠시 사라졌다가 다시 나타날 수 있어요.',tip:'이후 상단 「마이크로비트 연결하기」에서 마이크로비트의 COM 포트를 선택하세요. 로보독과 서로 다른 포트를 사용해요.'}
 ];
 const dialog=document.createElement('dialog');dialog.className='firmware-guide';dialog.id='firmware-guide';dialog.setAttribute('aria-labelledby','firmware-guide-title');
 dialog.innerHTML='<header><div><small>마이크로비트 V2 · 프로그램 설치 안내</small><h2 id="firmware-guide-title"></h2></div><button type="button" class="firmware-guide-close" aria-label="설치 안내 닫기">✕</button></header><p class="firmware-download-note" role="status">다운로드를 시작했어요. 기본 설정에서는 다운로드 폴더에 저장됩니다. 저장 창이 뜨면 「저장」을 눌러 주세요.</p><ol class="firmware-guide-track" aria-label="설치 순서"></ol><section class="firmware-guide-content" aria-live="polite"></section><footer><span class="firmware-guide-page"></span><div><button type="button" class="firmware-guide-back">이전</button><button type="button" class="firmware-guide-next">다음</button></div></footer><details><summary>파일이나 MICROBIT가 보이지 않아요</summary><p>파일은 브라우저 다운로드 목록(Ctrl + J)에서도 찾을 수 있어요. 저장 위치를 바꿨다면 지정한 폴더를 확인하세요. MICROBIT가 보이지 않으면 데이터 전송이 되는 USB 케이블로 다시 연결하세요.</p></details><a class="firmware-guide-redownload" download="AIGO-IN-unified.hex">프로그램 다시 다운로드</a>';
 document.body.append(dialog);let page=0,returnFocus=null;
 const content=dialog.querySelector('section'),track=dialog.querySelector('ol'),next=dialog.querySelector('.firmware-guide-next'),back=dialog.querySelector('.firmware-guide-back');
 function render(){const step=steps[page];dialog.querySelector('.firmware-download-note').hidden=page!==0;dialog.querySelector('h2').textContent=step.title;
  track.innerHTML=steps.map((s,i)=>`<li ${i===page?'aria-current="step"':''} class="${i<=page?'visited':''}">${i+1}</li>`).join('');
  content.replaceChildren();const text=document.createElement('p');text.className='firmware-guide-text';text.textContent=step.text;content.append(text);
  if(step.image){const figure=document.createElement('figure');figure.className='firmware-guide-picture '+step.mark;const img=document.createElement('img');img.src=assets+step.image;img.alt=step.alt;figure.append(img);const mark=document.createElement('span');mark.className='firmware-guide-highlight';mark.setAttribute('aria-hidden','true');figure.append(mark);content.append(figure)}
  else {const done=document.createElement('div');done.className='firmware-guide-finish';done.innerHTML='<strong>복사 → 재시작 기다리기 → COM 포트 연결</strong><p>프로그램은 처음 한 번 설치하면 돼요.<br>A: 무응답 감지 · B: 체조 · A+B: 휴식</p>';content.append(done)}
  if(step.keys){const key=document.createElement('div');key.className='firmware-guide-keys';key.textContent=step.keys;content.append(key)}
  const tip=document.createElement('p');tip.className='firmware-guide-tip';tip.textContent=step.tip;content.append(tip);
  dialog.querySelector('.firmware-guide-page').textContent=`${page+1} / ${steps.length} 단계`;back.disabled=page===0;next.textContent=page===steps.length-1?'안내 닫기':'다음';dialog.scrollTop=0;
 }
 function close(){dialog.close();returnFocus?.focus()}
 dialog.querySelector('.firmware-guide-close').onclick=close;
 back.onclick=()=>{if(page>0){page--;render()}};
 next.onclick=()=>{if(page<steps.length-1){page++;render()}else close()};
 document.addEventListener('click',event=>{const link=event.target.closest('a[download]');if(!link||!link.getAttribute('href')?.includes('unified.hex')||link.classList.contains('firmware-guide-redownload')||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  // Keep the native download action; the dialog explains the following manual steps.
  returnFocus=link;page=0;dialog.querySelector('.firmware-guide-redownload').href=link.href;render();if(!dialog.open)dialog.showModal();
 });
})();
