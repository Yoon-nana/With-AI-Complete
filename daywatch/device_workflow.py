"""실제 장치 입력용 판단기. 모터/시리얼 호출은 hardware_main.py가 담당합니다."""
from dataclasses import dataclass
import time
import math


def parse_packet(line):
    """MakeCode가 보내는 ML,STILL,21 형식만 허용합니다."""
    try:
        # bytearray.partition() returns bytearray, as used by the serial reader.
        if isinstance(line, (bytes, bytearray, memoryview)):
            text = bytes(line).decode('ascii')
        elif isinstance(line, str):
            text = line
        else:
            return None
        parts = text.strip().split(',')
        if len(parts) != 3 or parts[0] != 'ML' or parts[1] not in ('MOVING', 'STILL', 'UNKNOWN'):
            return None
        seconds = int(parts[2])
        if not 0 <= seconds <= 604800:
            return None
        return parts[1], seconds
    except (ValueError, UnicodeError, AttributeError):
        return None


@dataclass(frozen=True)
class Settings:
    trigger_seconds: int = 20
    class_confirm_seconds: float = 2
    verify_timeout_seconds: float = 5
    response_seconds: float = 15
    signal_timeout_seconds: float = 4
    unclear_timeout_seconds: float = 8
    straight_seconds: float = 1.2
    corner_seconds: float = 1
    bark_seconds: float = 5
    forward_speed: int = 6
    turn_speed: int = 35
    angle_turns: bool = False

    def __post_init__(self):
        if type(self.trigger_seconds) is not int or self.trigger_seconds < 0:
            raise ValueError('무활동 기준은 0 이상의 정수여야 합니다.')
        for name, value in vars(self).items():
            if name.endswith('_seconds'):
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError(name+' 설정은 유한한 양수여야 합니다.')
        for speed in (self.forward_speed, self.turn_speed):
            if type(speed) is not int or not 1 <= speed <= 100:
                raise ValueError('이동·회전 속도는 1~100의 정수여야 합니다.')
        if self.bark_seconds < 1:
            raise ValueError('짖기 호출 간격은 1초 이상이어야 합니다.')


class DeviceWorkflow:
    def __init__(self, robot, settings=None, clock=time.monotonic, log=None, report=None):
        self.robot, self.cfg, self.clock = robot, settings or Settings(), clock
        self.log = log or (lambda text: None)
        self.report = report or (lambda data: None)
        self.state = 'WAITING'
        self.message = '장치 연결 대기'
        self.movement, self.seconds, self.last_packet = 'UNKNOWN', 0, None
        self.armed = True
        self.active = False
        self.entered = self.clock()
        self.phase_started = self.clock()
        self.phase, self.side, self.laps = 'straight', 0, 0
        self.candidate, self.candidate_since = None, None
        self.danger_since = self.unclear_since = None
        self.next_bark = 0
        self.last_class = None
        self.paused_phase_elapsed = 0
        self.resume_search = False
        self.resume_alert = False
        self.decision = None

    def feed(self, movement, seconds):
        if movement not in ('MOVING', 'STILL', 'UNKNOWN') or type(seconds) is not int or seconds < 0:
            raise ValueError('마이크로비트 입력을 확인하세요.')
        now = self.clock()
        if self.active and self.last_packet is not None and now-self.last_packet > self.cfg.signal_timeout_seconds:
            self.hold('SIGNAL_LOST', '마빗 신호 대기: 신호가 돌아오면 자동 재개합니다.')
        self.movement, self.seconds, self.last_packet = movement, seconds, now
        if self.active and movement == 'MOVING' and self.state in ('PATROL', 'VERIFY', 'ALERT'):
            self.transition('MOTION_RESUMED', '마빗 움직임 재감지: 순찰·추가 짖기를 중단하고 감시로 복귀합니다. 정상 얼굴 확인이나 신고 결과는 아닙니다.')
        # 같은 STILL,21 이상 패킷으로 정상 확인 직후 다시 출발하지 않습니다.
        if movement == 'MOVING' or (movement == 'STILL' and seconds <= self.cfg.trigger_seconds):
            self.armed = True
        if self.state == 'REPORTED' and movement == 'MOVING':
            self.active = True
            self.transition('MONITOR', '모의 신고 후 움직임 재감지: 새 무활동 구간을 자동 감시합니다.')

    def transition(self, state, message):
        self.robot.stop()
        self.state, self.entered = state, self.clock()
        self.message = message
        if state == 'ALERT':
            self.decision = 2
        elif state == 'OK':
            self.decision = 1
        self.candidate = self.candidate_since = None
        self.danger_since = self.unclear_since = None
        self.log(message)
        self.robot.indicate(state)

    def hold(self, state, message):
        if state in ('SIGNAL_LOST', 'AI_LOST'):
            if self.state == state:
                self.robot.stop()
                return
            if self.state not in ('SIGNAL_LOST', 'AI_LOST'):
                self.resume_search = self.state in ('PATROL', 'VERIFY', 'ALERT')
                self.resume_alert = self.state == 'ALERT'
                self.paused_phase_elapsed = max(0, self.clock()-self.phase_started)
            self.active = True
        else:
            self.active = False
        self.transition(state, message)

    def start(self):
        if self.state == 'REPORTED':
            raise ValueError('신고 후에는 재설정하세요.')
        self.active = True
        self.transition('MONITOR', f'무응답 감지 중: 움직임 없음 {self.cfg.trigger_seconds}초부터 순찰을 시작합니다.')

    def reset(self):
        self.active = False
        self.armed = True
        self.last_packet = None
        self.movement, self.seconds = 'UNKNOWN', 0
        self.side = self.laps = 0
        self.decision = None
        self.resume_alert = False
        self.transition('WAITING', '재설정 완료.')

    def stop(self):
        self.hold('STOPPED', '사용자 중지: 이동과 추가 짖기를 중단합니다.')

    def acknowledge(self):
        if self.state not in ('PATROL', 'VERIFY', 'ALERT', 'REVIEW'):
            return
        self.armed = False
        self.transition('OK', '사람이 괜찮다고 응답했습니다.')

    def patrol(self):
        self.phase, self.phase_started = 'straight', self.clock()
        self.side = self.laps = 0
        self.decision = None
        self.transition('PATROL', 'class1 또는 class2를 찾을 때까지 사각형 순찰을 반복합니다.')
        self.log('1/4: 직진')

    def bark(self):
        now = self.clock()
        if now >= self.next_bark:
            accepted = self.robot.bark(loud=self.state == 'ALERT')
            self.next_bark = now + (.1 if accepted is False else self.cfg.bark_seconds)

    def sample_class(self):
        value = self.robot.read_class()
        self.last_class = value if type(value) is int else None
        return self.last_class if self.last_class in (1, 2) else None

    def tick(self, daytime=True):
        if not self.active:
            return
        now = self.clock()
        if not daytime:
            if self.state != 'NIGHT':
                self.transition('NIGHT', '밤 시간: 이동과 추가 짖기를 멈춥니다.')
            return
        if self.state == 'NIGHT':
            self.transition('MONITOR', '낮 시간 감시를 재개합니다.')
        if self.last_packet is None:
            self.robot.stop()
            if now-self.entered > self.cfg.signal_timeout_seconds:
                self.hold('SIGNAL_LOST', '마이크로비트의 ML 패킷을 받지 못했습니다.')
            return
        if now-self.last_packet > self.cfg.signal_timeout_seconds:
            self.hold('SIGNAL_LOST', '마이크로비트 신호 끊김: 정지. 연결 확인 후 재설정하세요.')
            return
        if not self.robot.ai_alive():
            self.hold('AI_LOST', 'AI 연결 대기: 연결이 돌아오면 자동 재개합니다.')
            return
        if self.state in ('SIGNAL_LOST', 'AI_LOST'):
            search = self.resume_search and self.movement != 'MOVING'
            recovered = 'ALERT' if self.resume_alert and self.movement != 'MOVING' else ('PATROL' if search else 'MONITOR')
            self.transition(recovered, '연결 회복: 쓰러짐 확정 결과를 유지하고 경고를 재개합니다.' if recovered == 'ALERT'
                            else '일시 정지 원인 해소: 버튼 없이 자동 재개합니다.')
            self.phase_started = now-self.paused_phase_elapsed
            self.resume_search = False
            self.resume_alert = False
        if self.state == 'MONITOR':
            if self.armed and self.movement == 'STILL' and self.seconds >= self.cfg.trigger_seconds:
                self.armed = False
                self.patrol()
            return
        if self.state in ('OK', 'MOTION_RESUMED'):
            if now-self.entered >= 2:
                self.transition('MONITOR', '감시 대기. 새로운 X 조건에서 순찰합니다.')
            return
        if self.state == 'PATROL':
            cls = self.sample_class()
            if cls != self.candidate:
                self.candidate, self.candidate_since = cls, now
                if cls is not None:
                    self.log(f'class{cls} 감지 후보: 이동하며 연속 인식을 확인합니다.')
            if cls is not None and now-self.candidate_since >= self.cfg.class_confirm_seconds:
                if cls == 1:
                    self.armed = False
                    self.transition('OK', 'class1 연속 인식 완료: 정상 확인. 순찰을 종료합니다.')
                else:
                    self.transition('ALERT', 'class2 연속 인식 완료: 쓰러짐 시연. 정지하고 반복 짖기로 반응을 확인합니다.')
                return
            self.bark()
            duration = self.cfg.straight_seconds if self.phase == 'straight' else self.cfg.corner_seconds
            complete = now-self.phase_started >= duration
            if self.phase == 'corner' and self.cfg.angle_turns:
                complete = self.robot.corner_complete()
                if not complete and now-self.phase_started >= duration:
                    self.log('오른쪽 90도 회전 확인 중입니다. 시간 초과로 종료하지 않고 남은 각도를 이어서 회전합니다.')
                    self.phase_started = now
            if complete:
                self.robot.stop()
                if self.phase == 'straight':
                    self.phase = 'corner'
                    self.log(f'{self.side+1}/4: 오른쪽 90도 회전')
                else:
                    self.phase = 'straight'
                    self.side = (self.side+1) % 4
                    if self.side == 0:
                        self.laps += 1
                        self.log(f'사각형 {self.laps}바퀴 완료. 미검출이므로 계속 순찰합니다.')
                    self.log(f'{self.side+1}/4: 직진')
                self.phase_started = now
            if self.phase == 'straight':
                if self.robot.forward(self.cfg.forward_speed) is False:
                    self.phase_started = now
            else:
                self.robot.corner(self.cfg.turn_speed)
        elif self.state == 'VERIFY':
            cls = self.sample_class()
            if cls != self.candidate:
                self.candidate, self.candidate_since = cls, now
            if cls is not None and now-self.candidate_since >= self.cfg.class_confirm_seconds:
                if cls == 1:
                    self.armed = False
                    self.transition('OK', 'class1 연속 확인: 정상. 순찰을 종료합니다.')
                else:
                    self.transition('ALERT', 'class2 연속 확인: 쓰러짐 시연. 반복 짖기로 반응을 확인합니다.')
            elif now-self.entered >= self.cfg.verify_timeout_seconds:
                self.transition('PATROL', '클래스를 연속 확인하지 못했습니다. 멈췄던 순찰을 이어갑니다.')
                self.phase_started = now-self.paused_phase_elapsed
        elif self.state == 'ALERT':
            self.bark()
            self.sample_class()  # 원본/현재 분류는 진단용이며 확정 결과를 뒤집지 않음.
            unchanged = self.movement == 'STILL'
            if unchanged:
                self.unclear_since = None
                if self.danger_since is None:
                    self.danger_since = now
                if now-self.danger_since >= self.cfg.response_seconds:
                    self.hold('REPORTED', '모의 신고 1회 생성. 실제 전화·문자·119 전송은 없습니다.')
                    self.report({'reason': '쓰러짐(class2) 확정 후 움직임 없음이 경고 중 연속 유지', 'laps': self.laps})
            else:
                self.danger_since = None
