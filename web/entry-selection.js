(()=>{
 const query=new URLSearchParams(location.search),app=query.get('app'),device=query.get('device');
 if(!['hub','kiosk','medication','daywatch','exercise','nap'].includes(app)&&!['robot','microbit'].includes(device))return;
 const timer=setInterval(async()=>{
  if(typeof state==='undefined'||!state||sending)return;
  clearInterval(timer);
  if(app==='exercise')await request('exercise_start');
  else if(['hub','kiosk','medication','daywatch','nap'].includes(app))await request('open_app',app);
  if(['robot','microbit'].includes(device))document.getElementById('in-'+device+'-open').click();
  query.delete('app');query.delete('device');
  history.replaceState(null,'',location.pathname+(query.size?'?'+query:'')+location.hash);
 },200);
})();
