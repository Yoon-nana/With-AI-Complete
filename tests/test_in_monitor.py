import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from daywatch_bridge import DaywatchService
from activity import ActivityCoordinator
sys.path.insert(0,str(root/'daywatch'))
from device_workflow import DeviceWorkflow,Settings
class Tests(unittest.TestCase):
 def test_settings_persist_validate_and_toggle(self):
  with tempfile.TemporaryDirectory() as folder:
   d=DaywatchService(folder);d.configure({'enabled':False,'triggerSeconds':8,'responseSeconds':5});d.select(True)
   self.assertFalse(d.requested)
   loaded=DaywatchService(folder);self.assertFalse(loaded.enabled);self.assertEqual(loaded.response_seconds,5)
   loaded.configure({'enabled':True});loaded.select(True);self.assertTrue(loaded.requested)
   for v in [0,3601,True,2.5]:
    with self.assertRaises(ValueError):loaded.configure({'responseSeconds':v})
 def test_reward_once_and_busy_retry(self):
  with tempfile.TemporaryDirectory() as folder:
   d=DaywatchService(folder);med=SimpleNamespace(snapshot=lambda:{'active':False,'schedules':[]})
   a=ActivityCoordinator(folder,med,d,clock=lambda:0);a.link.tick=lambda enabled:None;a.start_exercise()
   m=a.mission;idx=m['classId']-2;counts=[0,0,0];a.feed_counts(tuple(counts),'boot');counts[idx]=m['goal'];a.feed_counts(tuple(counts),'boot')
   a.feed_counts(tuple(counts),'boot');self.assertEqual(a.total_completed,1)
   w=SimpleNamespace(controller=SimpleNamespace(mode='mock'),available=False,submit=Mock(side_effect=[False,True]))
   a.tick(w);self.assertTrue(a.reward_pending);a.tick(w);a.tick(w)
   self.assertEqual(w.submit.call_count,2);w.submit.assert_called_with('SUCCESS')
   d.configure({'enabled':False});a.end_exercise();a.tick(w);self.assertFalse(d.requested)
 def test_report_wait_threshold_and_no_duplicate(self):
  now=[0];reports=[];robot=Mock();robot.ai_alive.return_value=True;robot.read_class.return_value=2
  f=DeviceWorkflow(robot,Settings(trigger_seconds=4,response_seconds=3,class_confirm_seconds=1),clock=lambda:now[0],report=reports.append)
  f.start();f.feed('STILL',3);f.tick();self.assertEqual(f.state,'MONITOR')
  now[0]=1;f.feed('STILL',4);f.tick();self.assertEqual(f.state,'PATROL')
  now[0]=2;f.feed('STILL',5);f.tick();now[0]=3;f.feed('STILL',6);f.tick();self.assertEqual(f.state,'ALERT')
  now[0]=4;f.feed('STILL',7);f.tick();now[0]=6;f.feed('STILL',9);f.tick();self.assertEqual(len(reports),0)
  now[0]=7;f.feed('STILL',10);f.tick();f.tick();self.assertEqual(len(reports),1)
if __name__=='__main__':unittest.main(verbosity=2)
