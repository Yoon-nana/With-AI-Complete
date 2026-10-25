"""체조 횟수 미션·낮잠·기본 안부 감시의 서버 측 상태."""
from datetime import datetime
import json
from pathlib import Path
import random
import threading
import time
import uuid
from microbit_link import MicrobitLink

ACTIONS = ((2,'cheering','치어링'),(3,'elbow curl','암컬'),(4,'wrist circle','손목 돌리기'))


class ActivityCoordinator:
    def __init__(self, base, medication, daywatch, rng=None, clock=time.monotonic):
        self.base, self.medication, self.daywatch = Path(base), medication, daywatch
        self.lock = threading.RLock()
        self.rng, self.clock = rng or random.Random(), clock
        self.mode, self.mission, self.counters = 'checking', None, None
        self.last_action = None
        self.completed_at = None
        self.reward_pending = False
        self.total_completed = 0
        self.nap_id = None
        self.nap_due = None
        self.nap_finished = False
        self.link = MicrobitLink(self.base, self.feed_counts)
        self.link.on_mode = self.hardware_mode
        self.daywatch.external_input = self.link.channel
        self.daywatch.exercise_gate = self
        self.boot = None
        self._load_settings()
        self.daywatch.microbit_port = self.link.port
        for row in medication.snapshot()['schedules']:
            if row.get('kind') == 'nap' and row['status'] in ('armed','active'):
                self.nap_id, self.nap_due = row['id'], row['due']
                self.mode = 'nap'
                break

    def hardware_mode(self, mode):
        """Keep physical A/B/AB changes in sync with the PC mission state."""
        with self.lock:
            if self.nap_id or self.medication.snapshot()['active']:
                self.link.commanded = None
                return
            if mode == 'exercise':
                if self.mode != 'exercise': self.start_exercise()
            elif mode == 'checking':
                self.end_exercise()
                self.mode = 'checking'
                self.link.select('checking')
            elif mode == 'nap':
                self.mode, self.mission = 'nap', None
                self.link.select('nap')
                self.daywatch.select(False)

    def _load_settings(self):
        try:
            config = json.loads((self.base/'data/microbit_settings.json').read_text())
            self.link.port = config.get('port','')
            self.link.drive = config.get('drive','')
        except (OSError, ValueError, TypeError):
            pass

    def configure(self, value):
        if not isinstance(value, dict): raise ValueError('마빗 연결 설정을 확인하세요.')
        with self.lock:
            port = value.get('port','')
            self.link.configure(port,value.get('drive',''))
            folder = self.base/'data'; folder.mkdir(exist_ok=True)
            temporary = folder/'microbit_settings.tmp'
            temporary.write_text(json.dumps({'port':self.link.port,'drive':self.link.drive},ensure_ascii=False),encoding='utf-8')
            temporary.replace(folder/'microbit_settings.json')
            self.daywatch.microbit_port = self.link.port

    def _new_mission(self):
        choices = [a for a in ACTIONS if a[0] != self.last_action]
        action = self.rng.choice(choices)
        self.last_action = action[0]
        index = [a[0] for a in ACTIONS].index(action[0])
        self.mission = {'id':uuid.uuid4().hex,'classId':action[0],'action':action[1],
                        'title':action[2],'goal':self.rng.randint(3,10),'done':0,
                        'complete':False,'paused':False,
                        'baseline':self.counters[index] if self.counters else None}
        self.completed_at = None

    def start_exercise(self):
        with self.lock:
            if self.nap_id: raise ValueError('낮잠을 먼저 마친 뒤 체조를 시작하세요.')
            if self.medication.snapshot()['active']: raise ValueError('진행 중인 알람을 먼저 확인하세요.')
            self.mode = 'exercise'; self.total_completed = 0
            self.reward_pending = False
            self._new_mission()
            self.link.select('exercise')
            self.daywatch.select(False)

    def end_exercise(self):
        with self.lock:
            if self.mode == 'exercise': self.mode = 'checking'
            self.mission = None
            self.reward_pending = False
            self.link.select(self.mode)

    def pause_exercise(self):
        with self.lock:
            if self.mission and not self.mission['complete']:
                self.mission['paused'] = not self.mission['paused']

    def feed_counts(self, counts, boot):
        with self.lock:
            if counts is None:
                self.counters, self.boot = None, boot
                if self.mission: self.mission['baseline'] = None
                return
            reset = self.counters is not None and any(a < b for a,b in zip(counts,self.counters))
            self.counters, self.boot = counts, boot
            m = self.mission
            if self.mode != 'exercise' or m is None: return
            index = [a[0] for a in ACTIONS].index(m['classId'])
            value, previous = counts[index], m['baseline']
            m['baseline'] = value
            if reset or previous is None or m['paused'] or m['complete'] or self.medication.snapshot()['active']: return
            delta = max(0,value-previous)
            m['done'] = min(m['goal'],m['done']+delta)
            if m['done'] >= m['goal']:
                m['complete'] = True
                self.total_completed += 1
                self.completed_at = self.clock()
                self.reward_pending = True

    def start_nap(self, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 180:
            raise ValueError('낮잠 시간은 1~180분의 정수로 입력하세요.')
        with self.lock:
            if self.medication.snapshot()['active']: raise ValueError('진행 중인 알람을 먼저 확인하세요.')
            if self.nap_id: self.medication.remove(self.nap_id)
            row = self.medication.add_after(minutes,'낮잠 깨우기',kind='nap')
            self.nap_id, self.nap_due = row['id'], row['due']
            self.nap_finished = False
            self.mode, self.mission = 'nap', None
            self.daywatch.select(False)
            self.link.select('nap')

    def end_nap(self):
        with self.lock:
            if self.nap_id: self.medication.end_nap(self.nap_id)
            self.nap_id = self.nap_due = None
            self.nap_finished = True
            self.mode = 'checking'
            self.link.select('checking')

    def snapshot(self):
        with self.lock:
            med = self.medication.snapshot()
            nap_row = next((r for r in med['schedules'] if r['id']==self.nap_id),None)
            return {'mode':self.mode,'sensor':self.link.snapshot(),
                    'exercise':{'mission':dict(self.mission) if self.mission else None,
                                'completed':self.total_completed},
                    'nap':{'active':self.nap_id is not None,'due':self.nap_due,
                           'finished':self.nap_finished,
                           'ringing':nap_row is not None and nap_row['status']=='active',
                           'id':self.nap_id}}

    def tick(self, worker):
        with self.lock:
            if self.nap_id:
                row = next((r for r in self.medication.snapshot()['schedules'] if r['id']==self.nap_id),None)
                if row is None or row['status'] in ('done','cancelled'):
                    self.nap_id = self.nap_due = None; self.mode = 'checking'
                    self.nap_finished = True
            self.link.select(self.mode)
        enabled = self.link.manual_connected or worker.controller.mode == 'real' and worker.available
        self.link.tick(enabled)
        with self.lock:
            if self.reward_pending and self.mode == 'exercise' and not self.medication.snapshot()['active']:
                if worker.submit('SUCCESS'):
                    self.reward_pending = False
            if self.mode == 'exercise' and not self.reward_pending and self.completed_at is not None and self.clock()-self.completed_at >= 1.5:
                self._new_mission()
            monitor = self.mode == 'checking' and self.daywatch.enabled
            if self.daywatch.requested != monitor: self.daywatch.select(monitor)

    def close(self): self.link.close()
