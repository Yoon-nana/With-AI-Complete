import sys,unittest,json,time,tempfile,shutil
from pathlib import Path
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from robot_controller import RobotWorker,MockRobotController
from web_kiosk import LocalKioskServer
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args):return None
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
  for folder in ['data','models','web']:(base/folder).mkdir()
  shutil.copyfile(root/'data/guidance.json',base/'data/guidance.json')
  shutil.copyfile(root/'models/unified.hex',base/'models/unified.hex')
  shutil.copyfile(root/'web/index.html',base/'web/index.html')
  self.worker=RobotWorker(MockRobotController());self.server=LocalKioskServer(self.worker,base=base,port=0);self.server.start()
  self.worker.activity=None;self.worker.daywatch=None;self.worker.medication=None
  self.base='http://'+self.server.host
 def tearDown(self):self.worker.stop();self.worker.thread.join(2);self.server.close();self.temp.cleanup()
 def req(self,path,data=None,auth=True,origin=None):
  headers={}
  if auth:headers['X-Kiosk-Token']=self.server.token
  if data is not None:headers['Content-Type']='application/json'
  if origin:headers['Origin']=origin
  try:
   with urlopen(Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=3) as r:return r.status,r.read(),r.headers
  except HTTPError as r:return r.code,r.read(),r.headers
 def test_html_buttons_and_download(self):
  code,body,_=self.req('/');self.assertEqual(code,200);self.assertIn('마이크로비트 연결하기'.encode(),body);self.assertIn('로보독 연결하기'.encode(),body)
  code,body,headers=self.req('/firmware/unified.hex',auth=False);self.assertEqual(code,200);self.assertEqual(body,(root/'models/unified.hex').read_bytes());self.assertIn('attachment',headers['Content-Disposition'])
 def test_bootstrap_and_token_security(self):
  code,body,headers=self.req('/bridge-info',auth=False);self.assertEqual(json.loads(body)['bridge'],'aigo-in-v1');self.assertEqual(headers['Access-Control-Allow-Origin'],'*')
  self.assertEqual(self.req('/api/state',auth=False)[0],403)
  self.assertEqual(self.req('/api/connect-robot',{'port':'COM24'},origin='https://foreign.example')[0],403)
  self.assertEqual(self.req('/api/ports',auth=False)[0],403)
  self.assertEqual(self.req('/api/ports')[0],200)
  try:build_opener(NoRedirect).open(self.base+'/start?robot_port=COM24')
  except HTTPError as r:self.assertEqual(r.code,302);self.assertIn('?robot_port=COM24#'+self.server.token,r.headers['Location'])
 def test_connect_uses_worker_and_invalid_port_rejected(self):
  calls=[]
  with patch.object(self.worker,'request_connection',side_effect=lambda p:calls.append(p)):
   self.assertEqual(self.req('/api/connect-robot',{'port':'COM24'})[0],202)
   self.assertEqual(self.req('/api/disconnect-robot',{})[0],202)
  self.assertEqual(calls,['COM24',None])
  self.assertEqual(self.req('/api/connect-robot',{'port':'bad port'})[0],400)
 def test_worker_opens_and_closes_only_on_request(self):
  class Fake:
   mode='real';sound_enabled=False;gestures_enabled=False
   def __init__(self,port):self.port=port
   def initialize(self):return True
   def close(self):pass
  self.assertFalse(self.worker.available)
  with patch('robot_controller.RobotController',Fake):
   self.worker.request_connection('COM24')
   until=time.monotonic()+2
   while not self.worker.available and time.monotonic()<until:time.sleep(.01)
   self.assertTrue(self.worker.available)
   self.assertEqual(self.worker.controller.port,'COM24')
   with self.assertRaises(ValueError):self.worker.request_connection('COM13')
   self.worker.request_connection(None)
   until=time.monotonic()+2
   while self.worker.available and time.monotonic()<until:time.sleep(.01)
   self.assertFalse(self.worker.available)
if __name__=='__main__':unittest.main(verbosity=2)
