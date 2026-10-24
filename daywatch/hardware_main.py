"""실제 장치 버전: Thonny의 PC Python으로 이 파일을 실행하세요.

필요 패키지: pyserial, 사용 중인 로보독의 kocoafab_robodog.
신고는 로컬 파일과 화면에만 기록합니다.
"""
import importlib
import inspect
import json
import math
import queue
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from device_workflow import DeviceWorkflow, Settings, parse_packet

ROOT = Path(__file__).resolve().parent

# 처음 시험할 때 이 두 COM 포트를 실제 장치에 맞추세요. 화면에서도 변경 가능합니다.
MICROBIT_PORT = 'COM6'
ROBODOG_PORT = 'COM4'  # 로보독 동글 포트

# 모형 공간에서 보정할 주행 설정. 회전 시간이 실제 90도가 되는지 먼저 맞추세요.
STRAIGHT_SECONDS = 1.2
CORNER_SECONDS = 8.0  # 오래 걸리는 회전의 안내 주기. 이 시간 때문에 종료하지 않습니다.
FORWARD_SPEED = 6
TURN_SPEED = 35
CLASS_CONFIRM_SECONDS = 0.2
RESPONSE_SECONDS = 15.0  # class2 + 움직임 없음이 연속 유지되는 시연용 시간
BARK_INTERVAL_SECONDS = 5.0  # 내장 소리 길이에 맞춰 늘릴 수 있음. 완료 조회 API는 없음.


class FaceReceiver:
    """신규 로보독 수신 패킷에서 공개 API로 학습 클래스 결과를 읽습니다."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.votes = deque(maxlen=40)
        self.last_rx = self.last_valid = None
        self.raw = self.mode = 0
        self.alive = False
        self.error = None

    def receive(self, dog, packet):
        # Manual mode-change replies are not normal 24-byte sensor reports.
        if len(packet) != 24:
            return
        try:
            raw = dog.get_face_recognition_class()
            ai = dog.get_ai_data()
            alive = bool(dog.is_ai_alive())
            now = self.clock()
            mode = ai[0] if ai else 0
            with self.lock:
                self.last_rx, self.raw, self.mode, self.alive = now, raw, mode, alive
                self.error = None
                while self.votes and now-self.votes[0][0] > 1:
                    self.votes.popleft()
                if mode != 1 or not alive:
                    self.votes.clear()
                    self.last_valid = None
                elif type(raw) is int and raw in (1, 2):
                    if self.votes and self.votes[-1][1] != raw:
                        self.votes.clear()
                    self.votes.append((now, raw))
                    self.last_valid = now
        except Exception as error:
            # Never kill the manufacturer's RX thread from a callback.
            with self.lock:
                self.error = str(error)
                self.votes.clear()
                self.last_valid = None

    def snapshot(self):
        now = self.clock()
        with self.lock:
            age = None if self.last_rx is None else max(0, now-self.last_rx)
            recent = [(stamp, cls) for stamp, cls in self.votes if now-stamp <= 1]
            cls = 0
            if (age is not None and age <= .7 and self.last_valid is not None
                    and now-self.last_valid <= .7 and len(recent) >= 2
                    and recent[-1][0]-recent[0][0] >= .08):
                cls = recent[-1][1]
            return {'raw': self.raw, 'class': cls, 'mode': self.mode, 'age': age,
                    'alive': self.alive and age is not None and age <= 2,
                    'error': self.error}


class Robot:
    def __init__(self, api, dog, faces=None):
        self.api, self.dog = api, dog
        self.faces = faces
        self.last_motion = None
        self.corner_heading = None
        self.rotation_thread = None
        self.rotation_error = None
        self.rotation_cancelled = threading.Event()
        self.sound_until = 0
        track, medium, loud = api.멍멍, api.중간, api.크게
        sig = inspect.signature(dog.sound)
        try:
            sig.bind(track, medium)
            self.sound_args = lambda strong: (track, loud if strong else medium)
        except TypeError:
            theme = api.개소리
            sig.bind(theme, track, medium)
            self.sound_args = lambda strong: (theme, track, loud if strong else medium)

    def stop(self):
        # stop calls are deliberately repeated to override persistent SDK state.
        self.dog.move(self.api.STOP)
        self.dog.spin(self.api.STOP)
        self.last_motion = None
        if self.rotation_thread and self.rotation_thread.is_alive():
            self.rotation_cancelled.set()

    def motion_busy(self):
        return self.rotation_thread is not None and self.rotation_thread.is_alive()

    def enforce_cancelled_rotation(self):
        if self.rotation_cancelled.is_set() and self.motion_busy():
            self.dog.move(self.api.STOP)
            self.dog.spin(self.api.STOP)

    def check_rotation_error(self):
        if self.rotation_error is not None:
            error, self.rotation_error = self.rotation_error, None
            raise RuntimeError('로보독 rotate 명령 오류: '+str(error)) from error

    def forward(self, speed):
        self.check_rotation_error()
        # A cancelled SDK rotate() may still be returning. Do not let its final
        # stop command interrupt a new straight segment.
        if self.motion_busy():
            return False
        self.corner_heading = None
        if self.last_motion != 'forward':
            self.dog.spin(self.api.STOP)
            self.dog.move(self.api.FORWARD, speed)
            self.last_motion = 'forward'
        return True

    def corner(self, speed):
        self.check_rotation_error()
        if self.motion_busy():
            return
        if self.corner_heading is None:
            self.corner_heading = self.heading()
        change = (self.heading()-self.corner_heading+180) % 360-180
        remaining = 90-change
        if abs(remaining) <= 5:
            return
        self.dog.move(self.api.STOP)
        self.rotation_cancelled.clear()
        def rotate_once():
            try:
                # Blocking rotate disarms the SDK's sleep-bound turn hook.
                # Only this motion thread may issue a blocking rotation.
                if not self.rotation_cancelled.is_set():
                    if remaining > 0:
                        self.dog.rotate(self.api.CW, remaining, speed)
                    else:
                        self.dog.rotate(self.api.CCW, -remaining, speed)
            except Exception as error:
                self.rotation_error = error
        self.rotation_thread = threading.Thread(target=rotate_once, daemon=True,
                                                name='RoboDog-right-angle')
        self.rotation_thread.start()
        self.last_motion = 'corner'

    def heading(self):
        value = self.dog.get_rotation()
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('자이로 회전값을 읽지 못했습니다: '+repr(value))
        return value

    def corner_complete(self):
        self.check_rotation_error()
        if self.motion_busy():
            return False
        if self.corner_heading is None:
            return False
        change = (self.heading()-self.corner_heading+180) % 360-180
        return abs(change-90) <= 5

    def finish_motion(self):
        self.stop()
        if self.rotation_thread:
            # Give the SDK a bounded interval to return; Close() then tears
            # down RX/TX if it is still waiting.
            deadline = time.monotonic()+3
            while self.rotation_thread.is_alive() and time.monotonic() < deadline:
                self.enforce_cancelled_rotation()
                self.rotation_thread.join(.1)

    def ai_alive(self):
        if self.faces is not None:
            return self.faces.snapshot()['alive']
        return bool(self.dog.is_ai_alive())

    def read_class(self):
        if self.faces is not None:
            return self.faces.snapshot()['class']
        raw = self.dog.get_face_recognition_class()
        if type(raw) is int:
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None

    def bark(self, loud=False):
        if time.monotonic() < self.sound_until:
            return False
        # Determine overload before calling. Never retry after a sound call.
        self.dog.sound(*self.sound_args(loud))
        self.sound_until = time.monotonic() + BARK_INTERVAL_SECONDS
        return True

    def indicate(self, state):
        colors = {'ALERT': (255, 0, 0), 'OK': (0, 180, 0),
                  'PATROL': (0, 100, 200), 'REPORTED': (180, 0, 120)}
        self.dog.bodyLED(*colors.get(state, (120, 90, 0)))
        eye = bytearray([0, 0x3c, 0x7e, 0x66, 0x66, 0x7e, 0x3c, 0])
        if state in ('WAITING', 'STOPPED', 'NIGHT'):
            eye = bytearray(8)
        self.dog.headLEDDraw(eye, eye)


class HardwareWorker:
    def __init__(self, microbit_port, robot_port, actual_time, events):
        self.microbit_port, self.robot_port = microbit_port, robot_port
        self.actual_time, self.events = actual_time, events
        self.commands = queue.Queue()
        self.exit = threading.Event()
        self.emergency = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def log(self, text):
        self.events.put(('log', text))

    def report(self, data):
        record = {'time': datetime.now().isoformat(timespec='seconds'), 'simulated': True, **data}
        self.events.put(('report', record))
        try:
            (ROOT/'data').mkdir(exist_ok=True)
            with (ROOT/'data/hardware_mock_reports.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False)+'\n')
        except OSError as error:
            self.log('모의 신고 파일 저장 실패: '+str(error))

    def submit(self, command):
        if command == 'stop':
            self.emergency.set()
        else:
            self.commands.put(command)

    def run(self):
        dog = microbit = robot = flow = None
        try:
            if self.microbit_port.casefold() == self.robot_port.casefold():
                raise ValueError('마이크로비트와 로보독은 서로 다른 COM 포트를 지정하세요.')
            serial = importlib.import_module('serial')
            api = importlib.import_module('kocoafab_robodog')
            microbit = serial.Serial(self.microbit_port, 115200, timeout=0)
            faces = FaceReceiver()
            dog = api.RoboDog(receiveCallback=faces.receive)
            if not dog.Open(self.robot_port):
                raise ConnectionError('로보독 연결 실패. 동글 COM 포트를 확인하세요.')
            robot = Robot(api, dog, faces=faces)
            robot.stop()
            self.log('포트 연결 완료. 준비 자세와 AI 연결을 확인합니다.')
            dog.gesture(api.STANDUP)
            if self.exit.wait(2):
                return
            dog.leg_bend(api.ALL_LEG, 60)
            started = time.monotonic()
            while not dog.is_ai_alive():
                if self.exit.wait(.1):
                    return
                if time.monotonic()-started > 10:
                    raise ConnectionError('AI 모듈 응답 없음. 전원과 연결을 확인하세요.')
            mode = dog.ai_mode(api.FACE_RECOGNITION, timeout=3.0)
            self.log(f'라이브러리 {getattr(api, "__version__", "버전 정보 없음")} / 얼굴 인식 모드 응답: {mode!r}')
            if mode is None:
                raise ConnectionError('얼굴 인식 모드 전환 응답이 없습니다.')
            microbit.reset_input_buffer()
            cfg = Settings(class_confirm_seconds=CLASS_CONFIRM_SECONDS,
                           response_seconds=RESPONSE_SECONDS, straight_seconds=STRAIGHT_SECONDS,
                           corner_seconds=CORNER_SECONDS, forward_speed=FORWARD_SPEED,
                           turn_speed=TURN_SPEED, bark_seconds=BARK_INTERVAL_SECONDS,
                           angle_turns=True)
            flow = DeviceWorkflow(robot, cfg, log=self.log, report=self.report)
            flow.start()
            self.events.put(('connected', True))
            self.log('연결 완료 → 자동 감시 시작. class1=정상 / class2=쓰러짐. X 신호를 받으면 출발합니다.')
            buffer = bytearray()
            last_update = 0
            last_rx_log = last_rx_time = time.monotonic()
            last_wait_log = last_rx_time
            received_any = False
            last_x = None
            last_face = None
            while not self.exit.is_set():
                if self.emergency.is_set():
                    self.emergency.clear()
                    # Clear queued start/reset so an emergency stop cannot be undone later.
                    while True:
                        try:
                            self.commands.get_nowait()
                        except queue.Empty:
                            break
                    flow.stop()
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if command == 'start':
                            flow.start()
                        elif command == 'reset':
                            flow.reset()
                            flow.start()
                        elif command == 'ack':
                            flow.acknowledge()
                    except ValueError as error:
                        self.log(str(error))
                count = min(microbit.in_waiting, 4096)
                if count:
                    chunk = microbit.read(count)
                    buffer.extend(chunk)
                    now = time.monotonic()
                    last_rx_time = now
                    if not received_any or now-last_rx_log >= 5:
                        self.log('마빗 수신 원문: '+repr(bytes(chunk[:120])))
                        last_rx_log = now
                    received_any = True
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)
                    packet = parse_packet(line) if len(line) <= 80 else None
                    if packet:
                        flow.feed(*packet)
                        is_x = packet[0] == 'STILL' and packet[1] > 20
                        if is_x != last_x:
                            self.log(f'마빗 해석: {packet[0]}, {packet[1]}초 / X 조건: {"충족" if is_x else "미충족"}')
                            last_x = is_x
                    elif time.monotonic()-last_rx_log >= 1:
                        self.log('수신 형식 불일치: '+repr(bytes(line[:120]))+' / 필요한 형식: ML,STILL,21')
                        last_rx_log = time.monotonic()
                if len(buffer) > 4096:
                    buffer.clear()
                    flow.hold('SIGNAL_LOST', '시리얼 입력이 비정상입니다. 정지했습니다.')
                day = not self.actual_time or 7 <= datetime.now().hour < 20
                flow.tick(daytime=day)
                robot.enforce_cancelled_rotation()
                now = time.monotonic()
                if now-last_wait_log >= 5:
                    if now-last_rx_time >= 5:
                        self.log('마빗 USB 데이터 수신 없음: USB COM 포트와 MakeCode 송신 코드 다운로드 여부를 확인하세요.')
                    elif flow.last_packet is None:
                        self.log('데이터는 들어오지만 ML 패킷을 해석하지 못했습니다. 수신 원문을 확인하세요.')
                    elif not flow.active:
                        self.log(f'현재 결과: {flow.state} / {flow.message}')
                    elif not day:
                        self.log('출발 대기: 실제 시각 기준 밤 시간입니다. 시연하려면 연결 해제 후 실제 시각 사용을 해제하세요.')
                    elif flow.state == 'MONITOR':
                        self.log(f'출발 대기: {flow.movement},{flow.seconds}초 / 재출발 허용={flow.armed}. STILL,21 이상이 필요합니다.')
                    last_wait_log = now
                if now-last_update >= .25:
                    # Diagnostic getter also runs while stopped; it never triggers movement.
                    raw_class = robot.read_class()
                    face_info = faces.snapshot()
                    face_key = (face_info['mode'], face_info['raw'], face_info['class'], face_info['error'])
                    if face_key != last_face:
                        self.log(f"AI 수신: 모드={face_info['mode']} / 원본 클래스={face_info['raw']} / 확인 클래스={face_info['class']}"
                                 +(f" / 오류={face_info['error']}" if face_info['error'] else ''))
                        last_face = face_key
                    self.events.put(('status', {'state': flow.state, 'class': raw_class,
                                               'face_raw': face_info['raw'], 'face_mode': face_info['mode'],
                                               'face_age': face_info['age'],
                                               'decision': flow.decision,
                                               'reason': flow.message,
                                               'movement': flow.movement, 'seconds': flow.seconds,
                                               'laps': flow.laps, 'phase': flow.phase,
                                               'sample_age': None if flow.last_packet is None else round(now-flow.last_packet, 1)}))
                    last_update = now
                # SDK documentation describes sleep hooks. Event.wait avoids those hooks.
                self.exit.wait(.05)
        except Exception as error:
            self.events.put(('error', str(error)))
            self.log(traceback.format_exc())
        finally:
            try:
                if dog is not None:
                    try:
                        if robot is not None:
                            robot.finish_motion()
                        dog.move(0)
                        dog.spin(0)
                    finally:
                        dog.Close()
            except Exception as error:
                self.log('로보독 종료 확인: '+str(error))
            if microbit is not None:
                microbit.close()
            self.events.put(('connected', False))
            self.events.put(('finished', None))


class Window:
    def __init__(self, root):
        self.root, self.worker, self.events = root, None, queue.Queue()
        root.title('로보독 안부 확인 · 실제 연결 / 신고는 모의')
        root.geometry('920x820')
        root.minsize(790, 700)
        root.option_add('*Font', ('맑은 고딕', 12))
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='로보독 · 마이크로비트 실제 연결', font=('맑은 고딕', 21, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='X 상태에서 출발 → class1/2 감지 전까지 사각형 반복 → 확인 → 경고·모의 신고').pack(anchor='w', pady=(8, 16))
        ports = ttk.Frame(frame)
        ports.pack(fill='x')
        self.microbit = tk.StringVar(value=MICROBIT_PORT)
        self.robodog = tk.StringVar(value=ROBODOG_PORT)
        for label, var in [('마이크로비트 COM', self.microbit), ('로보독 동글 COM', self.robodog)]:
            ttk.Label(ports, text=label).pack(side='left', padx=(0, 8))
            ttk.Entry(ports, textvariable=var, width=12).pack(side='left', padx=(0, 18))
        self.actual_time = tk.BooleanVar(value=False)
        self.connection = ttk.Button(frame, text='시작', command=self.connect)
        self.connection.pack(fill='x', pady=15)
        self.control_buttons = []
        self.state = tk.StringVar(value='미연결')
        self.diagnostic = tk.StringVar(value='클래스 진단: 연결 후 원본 / 쓰러진 사진 / 얼굴 없는 화면을 번갈아 보여주세요.')
        ttk.Label(frame, textvariable=self.state, font=('맑은 고딕', 18, 'bold')).pack(anchor='w', pady=8)
        ttk.Label(frame, textvariable=self.diagnostic, wraplength=850).pack(anchor='w', pady=8)
        ttk.Label(frame, text=f'사각형 순찰: 속도 {FORWARD_SPEED}로 {STRAIGHT_SECONDS}초 직진 → 오른쪽 90도 × 4회\n거리 센서로 정지하지 않습니다. 신고는 모의 기록입니다.', wraplength=850).pack(anchor='w', pady=8)
        self.logbox = tk.Text(frame, height=16, wrap='word', state='disabled')
        self.logbox.pack(fill='both', expand=True, pady=10)
        self.console = tk.Toplevel(root)
        self.console.title('로보독 결과 콘솔 · 정지 이유 / 정상 확인 / 모의 신고')
        self.console.geometry('760x620')
        self.console.protocol('WM_DELETE_WINDOW', self.console.iconify)
        pane = ttk.Frame(self.console, padding=18)
        pane.pack(fill='both', expand=True)
        self.console_status = tk.StringVar(value='장치 연결 대기')
        self.console_reason = tk.StringVar(value='장치 연결 후 자동으로 감시합니다.')
        self.console_result = tk.StringVar(value='최근 결과: 아직 없음')
        ttk.Label(pane, textvariable=self.console_status, font=('맑은 고딕', 23, 'bold')).pack(anchor='w', pady=8)
        ttk.Label(pane, textvariable=self.console_reason, wraplength=700).pack(anchor='w', pady=8)
        ttk.Label(pane, textvariable=self.console_result, wraplength=700,
                  font=('맑은 고딕', 15, 'bold')).pack(anchor='w', pady=12)
        ttk.Label(pane, text='신고는 모의 기록입니다. 실제 전화·문자는 보내지 않습니다.').pack(anchor='w')
        self.console_log = tk.Text(pane, wrap='word', state='disabled', height=15)
        self.console_log.pack(fill='both', expand=True, pady=10)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def log(self, text):
        entry = datetime.now().strftime('%H:%M:%S')+'  '+text+'\n'
        for box in (self.logbox, self.console_log):
            box.configure(state='normal')
            box.insert('end', entry)
            if int(box.index('end-1c').split('.')[0]) > 1200:
                box.delete('1.0', '200.0')
            box.see('end')
            box.configure(state='disabled')

    def show_console(self):
        self.console.deiconify()
        self.console.lift()

    def connect(self):
        if self.worker and self.worker.thread.is_alive():
            self.worker.emergency.set()
            self.worker.exit.set()
            self.connection.configure(state='disabled', text='종료 중')
            self.console_status.set('사용자 종료 · 정지 중')
            return
        a, b = self.microbit.get().strip(), self.robodog.get().strip()
        if not a or not b or a.casefold() == b.casefold():
            messagebox.showerror('포트 확인', '장치별로 서로 다른 COM 포트를 입력하세요.')
            return
        self.worker = HardwareWorker(a, b, self.actual_time.get(), self.events)
        self.show_console()
        self.console_result.set('최근 결과: 아직 없음')
        self.connection.configure(state='disabled')
        self.state.set('연결 준비 중')
        self.worker.thread.start()

    def send(self, command):
        if self.worker:
            self.worker.submit(command)

    def poll(self):
        while True:
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                self.log(data)
            elif kind == 'status':
                self.state.set(data['state'])
                labels = {'MONITOR': '자동 감시 중 · X 신호 대기', 'PATROL': '사각형 순찰 중',
                          'VERIFY': '정지 · 얼굴 클래스 연속 확인 중', 'OK': '확인 완료',
                          'MOTION_RESUMED': '움직임 재감지 · 순찰 중지',
                          'ALERT': '쓰러짐 인식 · 반복 짖기로 반응 확인 중',
                          'REPORTED': '모의 신고 완료',
                          'SIGNAL_LOST': '마빗 신호 없음 · 정지', 'AI_LOST': 'AI 연결 끊김 · 정지',
                          'NIGHT': '밤 시간 · 정지', 'STOPPED': '사용자 중지', 'REVIEW': '사람 확인 필요 · 정지'}
                self.console_status.set(labels.get(data['state'], data['state']))
                self.console_reason.set(data['reason'])
                if data['state'] in ('OK', 'ALERT', 'MOTION_RESUMED', 'REPORTED'):
                    self.console_result.set('최근 결과: '+data['reason'])
                decision = {1: '정상 확정', 2: '쓰러짐 확정 · 유지'}.get(data.get('decision'), '아직 미확정')
                self.diagnostic.set(f"사건 판정: {decision}\nAI 모드: {data.get('face_mode', '?')} / 모델 원본: {data.get('face_raw', '?')} / 현재 필터값: {data['class']!r}\n마빗: {data['movement']},{data['seconds']}초 / 마지막 패킷: {data['sample_age']}초 전 / 순찰 {data['laps']}바퀴 · {data['phase']}")
            elif kind == 'report':
                self.console_result.set('최근 결과: 모의 신고 완료 · 실제 전송 없음')
                self.log('【모의 신고】 '+json.dumps(data, ensure_ascii=False))
            elif kind == 'error':
                self.state.set('오류 · 정지')
                self.console_status.set('오류 · 정지')
                self.console_reason.set(data)
                self.log('오류: '+data)
            elif kind == 'connected':
                if data:
                    self.connection.configure(state='normal', text='종료')
            elif kind == 'finished':
                self.connection.configure(state='normal', text='시작')
                self.console_status.set('연결 종료 · 정지')
        self.root.after(100, self.poll)

    def close(self):
        if self.worker:
            self.worker.exit.set()
            self.worker.emergency.set()
            if self.worker.thread.is_alive():
                self.state.set('로봇 정지·연결 해제 중')
                self.root.after(100, self.close)
                return
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    Window(root)
    root.mainloop()
