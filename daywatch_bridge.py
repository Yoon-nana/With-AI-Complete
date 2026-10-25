"""기존 워커에 무응답 감지 본체를 연결한다. COM을 중복으로 열지 않는다."""
from collections import deque
from dataclasses import replace
from datetime import datetime
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time


def load_runtime():
    name = '_aigo_daywatch_hardware'
    if name in sys.modules:
        return sys.modules[name]
    folder = Path(__file__).resolve().parent / 'daywatch'
    spec = importlib.util.spec_from_file_location(name, folder / 'hardware_main.py')
    module = importlib.util.module_from_spec(spec)
    flow_name = '_aigo_daywatch_flow'
    flow_spec = importlib.util.spec_from_file_location(flow_name, folder / 'device_workflow.py')
    flow = importlib.util.module_from_spec(flow_spec)
    sys.modules[flow_name] = flow
    previous = sys.modules.get('device_workflow')
    try:
        flow_spec.loader.exec_module(flow)
        sys.modules['device_workflow'] = flow
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop('device_workflow', None)
        else:
            sys.modules['device_workflow'] = previous
    sys.modules[name] = module
    return module


class DaywatchService:
    def __init__(self, base):
        self.base = Path(base)
        self.lock = threading.RLock()
        self.requested = False
        self.enabled = True
        self.trigger_seconds = 20
        self.response_seconds = 15
        try:
            saved = json.loads((self.base/'data/daywatch_settings.json').read_text(encoding='utf-8'))
            if type(saved.get('enabled')) is bool: self.enabled = saved['enabled']
            for name in ('trigger_seconds', 'response_seconds'):
                value = saved.get(name)
                if type(value) is int and 1 <= value <= 3600: setattr(self, name, value)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.microbit_port = 'COM6'
        self.logs = deque(maxlen=120)
        self.status = {'state': 'IDLE', 'message': '무응답 감지를 선택하면 자동으로 시작합니다.',
                       'active': False, 'decision': None, 'raw': 0, 'class': 0,
                       'movement': 'UNKNOWN', 'seconds': 0, 'laps': 0, 'phase': 'straight'}
        self.robot = self.flow = self.microbit = self.faces = None
        self.previous_callback = None
        self.buffer = bytearray()
        self.ready_at = None
        self.last_status = 0
        self.last_face = None
        self.failed = False
        self.external_input = None

    def log(self, text):
        with self.lock:
            self.logs.append(datetime.now().strftime('%H:%M:%S')+' '+text)

    def publish(self, **values):
        with self.lock:
            self.status.update(values)

    def snapshot(self):
        with self.lock:
            return {**self.status, 'requested': self.requested,
                    'microbitPort': self.microbit_port, 'logs': list(self.logs),
                    'enabled': self.enabled, 'triggerSeconds': self.trigger_seconds, 'responseSeconds': self.response_seconds}

    def configure(self, config):
        if not isinstance(config, dict): raise ValueError('무응답 감지 설정을 확인하세요.')
        with self.lock:
            enabled = config.get('enabled', self.enabled)
            trigger = config.get('triggerSeconds', self.trigger_seconds)
            response = config.get('responseSeconds', self.response_seconds)
            if type(enabled) is not bool or any(type(v) is not int or not 1 <= v <= 3600 for v in (trigger, response)):
                raise ValueError('시간은 1~3600초의 정수로 입력하세요.')
            folder = self.base/'data'; folder.mkdir(exist_ok=True)
            temporary = folder/'daywatch_settings.tmp'
            temporary.write_text(json.dumps({'enabled':enabled,'trigger_seconds':trigger,'response_seconds':response}),encoding='utf-8')
            temporary.replace(folder/'daywatch_settings.json')
            self.enabled, self.trigger_seconds, self.response_seconds = enabled, trigger, response
            if not enabled: self.requested = False

    def select(self, enabled, port=None):
        with self.lock:
            if port is not None:
                port = port.strip()
                if not port or len(port) > 128 or any(c.isspace() for c in port):
                    raise ValueError('마빗 USB 포트를 확인하세요. 예: COM6')
                if self.robot is not None and port != self.microbit_port:
                    raise ValueError('다른 기능으로 이동한 뒤 마빗 포트를 바꿔 주세요.')
                self.microbit_port = port
            self.requested = enabled and self.enabled
            if enabled:
                self.failed = False
                self.status['message'] = '자동 연결 준비 중입니다.'

    def report(self, data):
        record = {'time': datetime.now().isoformat(timespec='seconds'), 'simulated': True, **data}
        self.log('【모의 신고】 '+json.dumps(record, ensure_ascii=False))
        try:
            folder = self.base / 'data'
            folder.mkdir(exist_ok=True)
            with (folder / 'daywatch_mock_reports.jsonl').open('a', encoding='utf-8') as output:
                output.write(json.dumps(record, ensure_ascii=False)+'\n')
        except OSError as error:
            self.log('모의 신고 저장 실패: '+str(error))

    def _release(self):
        if self.robot is not None:
            self.robot.stop()
            self.robot.enforce_cancelled_rotation()
            if self.robot.motion_busy():
                return False
            self.robot.dog.receiveCallback = self.previous_callback
        if self.microbit is not None:
            self.microbit.close()
        self.robot = self.flow = self.microbit = self.faces = None
        self.buffer.clear()
        self.ready_at = None
        self.publish(active=False)
        return True

    def _prepare(self, worker):
        runtime = load_runtime()
        controller = worker.controller
        dog, api = controller.dog, controller.api
        robot_port = str(getattr(getattr(dog, 'serial', None), 'port', controller.port) or 'COM4')
        if robot_port.casefold() == self.microbit_port.casefold():
            raise ValueError('마빗 USB와 로보독 COM4는 서로 다른 포트여야 합니다.')
        self.microbit = self.external_input if self.external_input is not None else importlib.import_module('serial').Serial(self.microbit_port, 115200, timeout=0)
        self.faces = runtime.FaceReceiver()
        self.previous_callback = getattr(dog, 'receiveCallback', None)
        self.robot = runtime.Robot(api, dog, faces=self.faces)
        previous, receiver = self.previous_callback, self.faces
        def receive(device, packet):
            receiver.receive(device, packet)
            if previous:
                try:
                    previous(device, packet)
                except Exception as error:
                    self.log('기존 수신 콜백 확인: '+str(error))
        dog.receiveCallback = receive
        self.robot.stop()
        dog.gesture(api.STANDUP)
        self.ready_at = time.monotonic()+2
        self.publish(active=True, state='PREPARING', message='준비 자세를 잡는 중입니다.', decision=None)
        self.log('기존 로보독 연결 공유 · 마빗 '+self.microbit_port+' 연결')

    def tick(self, worker):
        """True이면 무응답 감지가 장치를 사용 중이므로 기존 동작을 섞지 않는다."""
        try:
            med_active = worker.medication is not None and worker.medication.snapshot()['active']
            if self.robot is not None:
                worker.audio_until = max(worker.audio_until, self.robot.sound_until)
            if self.robot is not None and (not self.requested or med_active or self.failed):
                if not self._release():
                    return True
            if not self.requested or self.failed:
                if not self.failed:
                    self.publish(state='IDLE', message='무응답 감지 종료 · 기존 기능을 사용할 수 있습니다.')
                return False
            if med_active:
                self.publish(state='MEDICATION', active=False,
                             message='복약 알림을 먼저 진행합니다. 완료 후 무응답 감지를 자동 재개합니다.')
                return False
            if self.robot is None:
                if worker.pending or time.monotonic() < worker.audio_until:
                    self.publish(state='WAITING', message='현재 로보독 반응이 끝나면 자동 시작합니다.')
                    return False
                if worker.controller.mode != 'real':
                    self.publish(state='MOCK', active=False,
                                 message='모의 연결입니다. 실제 감시는 시작 화면에서 실제 연결을 선택하세요.')
                    return False
                if not worker.available:
                    self.publish(state='WAITING', message='기존 로보독 연결을 기다립니다.')
                    return False
                self._prepare(worker)
                return True
            if self.flow is None:
                if time.monotonic() < self.ready_at:
                    return True
                runtime = load_runtime()
                self.robot.dog.leg_bend(worker.controller.api.ALL_LEG, 60)
                mode = self.robot.dog.ai_mode(worker.controller.api.FACE_RECOGNITION, timeout=3.0)
                if mode is None:
                    raise ConnectionError('얼굴 인식 모드 응답 없음. AI 카메라 연결을 확인하세요.')
                self.log('얼굴 인식 모드 응답: '+repr(mode))
                cfg = runtime.Settings(trigger_seconds=self.trigger_seconds, class_confirm_seconds=runtime.CLASS_CONFIRM_SECONDS,
                    response_seconds=self.response_seconds, straight_seconds=runtime.STRAIGHT_SECONDS,
                    corner_seconds=runtime.CORNER_SECONDS, forward_speed=runtime.FORWARD_SPEED,
                    turn_speed=runtime.TURN_SPEED, bark_seconds=runtime.BARK_INTERVAL_SECONDS, angle_turns=True)
                self.flow = runtime.DeviceWorkflow(self.robot, cfg, log=self.log, report=self.report)
                self.microbit.reset_input_buffer()
                self.flow.start()
            count = min(self.microbit.in_waiting, 4096)
            if count:
                self.buffer.extend(self.microbit.read(count))
            while b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                packet = load_runtime().parse_packet(line) if len(line) <= 80 else None
                if packet:
                    self.flow.feed(*packet)
            if len(self.buffer) > 4096:
                self.buffer.clear()
                self.flow.hold('SIGNAL_LOST', '마빗 수신 형식을 확인하세요.')
            self.flow.cfg = replace(self.flow.cfg, trigger_seconds=self.trigger_seconds, response_seconds=self.response_seconds)
            self.flow.tick(daytime=True)
            self.robot.enforce_cancelled_rotation()
            worker.audio_until = max(worker.audio_until, self.robot.sound_until)
            info = self.faces.snapshot()
            key = (info['raw'], info['class'], info['mode'], info['error'])
            if key != self.last_face:
                self.log(f"AI 모드={info['mode']} / 원본={info['raw']} / 현재 필터={info['class']}")
                self.last_face = key
            self.publish(active=True, state=self.flow.state, message=self.flow.message,
                decision=self.flow.decision, raw=info['raw'], **{'class': info['class']},
                movement=self.flow.movement, seconds=self.flow.seconds,
                laps=self.flow.laps, phase=self.flow.phase)
            return self.robot.motion_busy() or self.flow.state in ('PATROL', 'VERIFY', 'ALERT')
        except Exception as error:
            self.failed = True
            self.publish(state='ERROR', message=str(error), active=False)
            self.log('무응답 감지 오류: '+str(error))
            if self.robot is not None or self.microbit is not None:
                try:
                    return not self._release()
                except Exception as cleanup_error:
                    self.log('무응답 감지 연결 정리 오류: '+str(cleanup_error))
                    if self.microbit is not None:
                        try:
                            self.microbit.close()
                        except Exception:
                            pass
                    self.robot = self.flow = self.microbit = self.faces = None
                    worker._fallback(cleanup_error)
            return False

    def close(self):
        if self.robot:
            self.robot.finish_motion()
        if not self._release():
            if self.microbit:
                self.microbit.close()
            self.robot.dog.receiveCallback = self.previous_callback
