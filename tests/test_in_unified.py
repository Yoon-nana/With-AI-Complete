import sys, unittest, types
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from microbit_link import MicrobitLink
from activity import ActivityCoordinator
class Serial:
 def __init__(self,*a,**k):self.buffer=bytearray();self.writes=[];self.closed=False
 @property
 def in_waiting(self):return len(self.buffer)
 def read(self,n):result=bytes(self.buffer[:n]);del self.buffer[:n];return result
 def write(self,b):self.writes.append(b)
 def close(self):self.closed=True
class Med:
 def snapshot(self):return {'active':False,'schedules':[]}
class Day:
 requested=False
 def select(self,value):self.requested=value
class Tests(unittest.TestCase):
 def test_capability_and_command_switch_without_flashing(self):
  clock=[0];counts=[];link=MicrobitLink(root,lambda *x:counts.append(x),clock=lambda:clock[0]);serial=Serial();link.serial=serial;link.port="COM31"
  serial.buffer.extend(b'BOOT,UNIFIED\nCAPS,UNIFIED,1\nMODEL,CHECK\nML,MOVING,0\n')
  with patch('microbit_link.board_drive',side_effect=AssertionError('must not flash')):link.tick(True)
  self.assertTrue(link.unified);self.assertEqual(link.status,'READY');self.assertIn(b'MODE,CHECK\n',serial.writes)
  link.select('exercise');link.tick(True);self.assertIn(b'MODE,EXERCISE\n',serial.writes)
  serial.buffer.extend(b'MODEL,EXERCISE\nEX,1,2,3\n');clock[0]=1;link.tick(True)
  self.assertEqual(link.status,'READY');self.assertEqual(counts[-1][0],(1,2,3));self.assertFalse(serial.closed)
 def test_old_firmware_is_never_overwritten(self):
  link=MicrobitLink(root,lambda *x:None,clock=lambda:4);link.serial=Serial();link.port="COM31";link.serial.buffer.extend(b'MODEL,CHECK\n')
  with patch('microbit_link.board_drive',side_effect=AssertionError('must not flash')):link.tick(True)
  self.assertEqual(link.status,'NEEDS_FIRMWARE');self.assertIn('unified.hex',link.message)
 def test_nap_ack_and_disconnect_reprobe(self):
  link=MicrobitLink(root,lambda *x:None,clock=lambda:0);serial=Serial();link.serial=serial;link.port="COM31"
  link._line(b'CAPS,UNIFIED,1');link.select('nap');serial.buffer.extend(b'MODEL,NAP\n');link.tick(True)
  self.assertEqual(link.status,'NAP');self.assertIn(b'MODE,NAP\n',serial.writes)
  link.close();self.assertFalse(link.unified);self.assertIsNone(link.current)
 def test_buttons_sync_activity_and_missions(self):
  activity=ActivityCoordinator(root,Med(),Day());link=activity.link
  link._line(b'BUTTON,EXERCISE');self.assertEqual(activity.mode,'exercise');self.assertIsNotNone(activity.mission);self.assertEqual(link.desired,'exercise')
  link._line(b'BUTTON,CHECK');self.assertEqual(activity.mode,'checking');self.assertIsNone(activity.mission)
  link._line(b'BUTTON,NAP');self.assertEqual(activity.mode,'nap');self.assertEqual(link.desired,'nap')
 def test_medication_takes_priority(self):
  med=Med();activity=ActivityCoordinator(root,med,Day());med.snapshot=lambda:{'active':True,'schedules':[]}
  activity.link._line(b'BUTTON,EXERCISE');self.assertEqual(activity.mode,'checking')
 def test_still_buffer_gated_until_check_mode(self):
  link=MicrobitLink(root,lambda *x:None,clock=lambda:0);link._line(b'CAPS,UNIFIED,1');link._line(b'ML,STILL,10')
  self.assertIn(b'ML,STILL,10',link.monitor);link.select('exercise');link._line(b'ML,STILL,50');self.assertEqual(link.monitor,bytearray())
if __name__=='__main__':unittest.main(verbosity=2)
