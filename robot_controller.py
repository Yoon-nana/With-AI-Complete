"""첨부된 공개 API만 사용하는 어댑터. 이 파일에서만 장치를 제어한다."""
import importlib
import inspect
import logging
import queue
import threading
import time
from reactions import REACTIONS, ReactionPicker, gesture_value, supported_reactions

COLORS = {
    "WELCOME": (0, 80, 160), "INTRO": (0, 80, 160),
    "HINT": (160, 100, 0), "STEP_GUIDE": (100, 0, 160),
    "SUCCESS": (0, 160, 0), "PRAISE": (0, 160, 0), "COMPLETE": (0, 160, 0), "NEUTRAL": (0, 0, 0),
    "SOUND_TEST": (0, 80, 160), "GESTURE_TEST": (0, 160, 0),
    "MED_ALERT": (160, 100, 0), "MED_REPEAT": (160, 100, 0), "MED_CONFIRM": (0, 160, 0),
}

ROBOT_SOUND_SECONDS = 4.5  # 제공 API에 재생 완료 조회가 없어 효과음 종료 여유를 둔다.
REACTION_ACTIONS = frozenset({"PRAISE", "SUCCESS", "GESTURE_TEST"})
EXCLUSIVE_EFFECT_ACTIONS = REACTION_ACTIONS | {"SOUND_TEST", "MED_ALERT", "MED_REPEAT", "MED_CONFIRM"}


class MockRobotController:
    mode = "mock"

    def __init__(self, sound_enabled=True, gestures_enabled=True):
        self.picker = ReactionPicker()
        self.last_reaction = None
        self.body_reactions = [item["name"] for item in REACTIONS]
        self.sound_enabled = sound_enabled
        self.gestures_enabled = gestures_enabled

    def initialize(self):
        return False  # 모의 모드는 실제 연결로 표시하지 않는다.

    def execute_action(self, action):
        logging.info("[모의 로보독] %s", action)
        if self.gestures_enabled and action in ("PRAISE", "SUCCESS", "GESTURE_TEST"):
            self.last_reaction = self.picker.pick([item["id"] for item in REACTIONS])["name"]

    def close(self):
        pass

    def take_warnings(self):
        return []


class RobotController:
    mode = "real"

    def __init__(self, port=None, sound_enabled=True, gestures_enabled=True, sleeper=None):
        self.port = port
        self.dog = None
        self.api = None
        self.sound_enabled = sound_enabled
        self.gestures_enabled = gestures_enabled
        self.sleep = sleeper or time.sleep
        self.warnings = []
        self.picker = ReactionPicker()
        self.last_reaction = None
        self.body_reactions = []
        self.sound_until = 0.0

    def initialize(self):
        api = importlib.import_module("kocoafab_robodog")
        self.api = api
        self.dog = api.RoboDog()
        if not self.dog.Open(self.port or "None"):
            raise ConnectionError("로보독 시리얼 연결에 실패했습니다.")
        self.body_reactions = [item["name"] for item in supported_reactions(self.api, self.dog)]
        return True

    def execute_action(self, action):
        self.dog.bodyLED(*COLORS[action])
        if action in ("MED_ALERT", "MED_REPEAT", "MED_CONFIRM"):
            if action == "MED_ALERT":
                self._optional_expression("초롱초롱")
            if action != "MED_CONFIRM" and self.sound_enabled:
                self._optional_sound("멍멍")  # 한 번 짖고 종료 대기를 마쳐야 다음 짖음을 허용한다.
            if action != "MED_REPEAT" and self.gestures_enabled:
                self._optional_gesture({"name": "복약 확인" if action == "MED_CONFIRM" else "복약 알림",
                                        "sequence": ("READY",) if action == "MED_CONFIRM" else ("STRETCH", "STANDUP")})
            if action == "MED_CONFIRM":
                try:
                    self.dog.headLEDDraw(bytearray(8), bytearray(8))
                except Exception as error:
                    self._warn(f"복약 알림 눈 끄기 실패: {error}")
            return
        if action in ("PRAISE", "SUCCESS", "GESTURE_TEST"):
            supported = supported_reactions(self.api, self.dog) if self.gestures_enabled else []
            reaction = self.picker.pick([item["id"] for item in (supported or REACTIONS)])
            self._optional_expression(reaction["expression"])
            if self.sound_enabled and reaction.get("sound") is not None:
                self._optional_sound(reaction["sound"])
            if self.gestures_enabled:
                self._optional_gesture(reaction)
            return
        # 문장 안내가 있는 시작·힌트·다시 듣기에는 효과음을 겹쳐 재생하지 않는다.
        if self.sound_enabled and action == "SOUND_TEST":
            self._optional_sound("멍멍")

    def _optional_expression(self, name):
        try:
            self.dog.headLEDExp(getattr(self.api, name))
        except Exception as error:
            self._warn(f"눈 표정 표시 실패: {error}")

    def _warn(self, text):
        logging.warning(text)
        self.warnings.append(text)

    def _optional_sound(self, track_name):
        """문서의 2인자/3인자 호출을 실행 전 시그니처로 구분한다.

        호출 후 TypeError를 보고 재시도하면 소리가 두 번 날 수 있으므로 재시도하지 않는다.
        theme 값은 문서 예시의 '개소리' 상수만 사용하며 숫자를 추측하지 않는다.
        """
        try:
            sound = self.dog.sound
            track = getattr(self.api, track_name)
            volume = getattr(self.api, "중간")
            signature = inspect.signature(sound)
            try:
                signature.bind(track, volume)
                args = (track, volume)
            except TypeError:
                theme = getattr(self.api, "개소리")
                signature.bind(theme, track, volume)
                args = (theme, track, volume)
            sound(*args)
            self.sound_until = time.monotonic() + ROBOT_SOUND_SECONDS
        except Exception as error:
            self._warn(f"로봇 소리 재생 실패: {error}. 설치 라이브러리의 sound()와 사운드 모듈을 확인하세요.")

    def _optional_gesture(self, reaction=None):
        motion_started = False
        try:
            standing = gesture_value(self.api, "STANDUP")
            supported = supported_reactions(self.api, self.dog)
            self.body_reactions = [item["name"] for item in supported]
            reaction = reaction or self.picker.pick([item["id"] for item in supported])
            # 전체 순서를 먼저 검사해 지원되지 않는 동작을 도중에 만나지 않는다.
            sequence = [gesture_value(self.api, name) for name in reaction["sequence"]]
            self.last_reaction = reaction["name"]
            for gesture in sequence:
                try:
                    motion_started = True
                    self.dog.gesture(gesture)
                finally:
                    self.sleep(2.0)
            # 정상 종료는 마지막 자세와 눈 표정을 유지한다.
        except Exception as error:
            self._warn(f"애교 동작 실행 실패: {error}")
            # 전송 오류로 순서가 끊겼을 때만 기본 자세 복귀를 시도한다.
            if motion_started:
                try:
                    self.dog.gesture(standing)
                except Exception as error:
                    self._warn(f"기본 자세 복귀 실패: {error}")
                finally:
                    self.sleep(2.0)

    def take_warnings(self):
        messages, self.warnings = self.warnings, []
        return messages

    def close(self):
        if self.dog is not None:
            try:
                self.dog.Close()
            finally:
                self.dog = None


class RobotWorker:
    """연결부터 종료까지 한 워커가 처리. GUI 스레드는 장치를 기다리지 않는다."""

    def __init__(self, controller):
        self.controller = controller
        self.commands = queue.Queue(maxsize=8)
        self.events = queue.Queue()
        self.lock = threading.Lock()
        self.pending = set()
        self.stopping = threading.Event()
        self.available = False
        self.last_praise = 0.0
        self.audio_until = 0.0
        self.medication = None  # KioskModel이 로컬 설정 저장소와 함께 연결한다.
        self.daywatch = None  # 기존 연결에 추가한 안부 확인 서비스
        self.activity = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, action):
        if (self.daywatch is not None and self.daywatch.requested and not action.startswith('MED_')
                and self.daywatch.snapshot()['state'] in ('PATROL','VERIFY','ALERT','PREPARING')):
            return False
        if action not in COLORS or self.stopping.is_set():
            return False
        with self.lock:
            # 소리 시험도 같은 실행 슬롯을 쓴다. 실행/대기 중에는 새 효과를
            # 큐에 넣지 않고 거절한다. 예약 순번을 쌓는 방식이 아니다.
            if action in EXCLUSIVE_EFFECT_ACTIONS and (
                    self.pending.intersection(EXCLUSIVE_EFFECT_ACTIONS)
                    or time.monotonic() < self.audio_until):
                return False
            if action in REACTION_ACTIONS and time.monotonic() - self.last_praise < 3.0:
                return False
            if action in self.pending:
                return False
            self.pending.add(action)
            try:
                self.commands.put_nowait(action)
            except queue.Full:
                self.pending.discard(action)
                return False
            if action in ("PRAISE", "SUCCESS", "GESTURE_TEST"):
                self.last_praise = time.monotonic()
            if (self.available or self.controller.mode == "real") and getattr(self.controller, "sound_enabled", False) and action in EXCLUSIVE_EFFECT_ACTIONS and action != "MED_CONFIRM":
                self.audio_until = max(self.audio_until, time.monotonic() + ROBOT_SOUND_SECONDS)
        return True

    def _fallback(self, error):
        logging.error("로보독 오류: %s", error)
        try:
            self.controller.close()
        except Exception:
            logging.exception("연결 정리 실패")
        self.controller = MockRobotController()
        self.available = False
        self.events.put(("status", f"연결 오류 · 모의 모드: {error}"))

    def _run(self):
        try:
            try:
                self.available = self.controller.initialize()
                message = "시리얼 포트 연결됨 · 장치 반응은 직접 확인해 주세요" if self.available else "모의 모드 · 실제 로봇 미연결"
                self.events.put(("status", message))
            except Exception as error:
                self._fallback(error)
            while not self.stopping.is_set():
                if self.activity is not None:
                    self.activity.tick(self)
                if self.medication is not None and not self.pending and time.monotonic() >= self.audio_until:
                    try:
                        self.medication.tick(self)
                    except Exception as error:
                        self.events.put(("warning", f"복약 알림 처리 확인 필요: {error}"))
                if self.daywatch is not None and self.daywatch.tick(self):
                    self.stopping.wait(.05)
                    continue
                try:
                    action = self.commands.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if not self.stopping.is_set():
                        try:
                            if action.startswith("MED_") and (self.medication is None or not self.medication.action_allowed(action)):
                                continue  # 취소/변경된 예약을 뒤늦게 실행하지 않는다.
                            if (self.available or self.controller.mode == "real") and getattr(self.controller, "sound_enabled", False) and action in EXCLUSIVE_EFFECT_ACTIONS and action != "MED_CONFIRM":
                                self.audio_until = max(self.audio_until, time.monotonic() + ROBOT_SOUND_SECONDS)
                            self.controller.execute_action(action)
                            # 짧은 앉기/기지개는 2초 만에 끝나도 효과음은 남을 수 있다.
                            # pending을 유지해 PC 안내와 다음 로봇 소리를 함께 기다리게 한다.
                            sound_until = getattr(self.controller, "sound_until", 0.0)
                            self.audio_until = max(self.audio_until, sound_until)
                            while not self.stopping.is_set() and time.monotonic() < sound_until:
                                if action in ("MED_ALERT", "MED_REPEAT") and self.medication is not None:
                                    self.medication.poll_during_bark(self)
                                self.stopping.wait(min(.1, max(0.0, sound_until - time.monotonic())))
                            if action.startswith("MED_") and self.medication is not None:
                                self.medication.action_finished(action)
                            for warning in self.controller.take_warnings():
                                self.events.put(("warning", warning))
                            self.events.put(("action", action))
                        except Exception as error:
                            self._fallback(error)
                finally:
                    with self.lock:
                        self.pending.discard(action)
                    self.commands.task_done()
        finally:
            if self.activity is not None:
                self.activity.close()
            if self.daywatch is not None:
                try:
                    self.daywatch.close()
                except Exception:
                    logging.exception('안부 확인 종료 실패')
            try:
                self.controller.close()
            except Exception:
                logging.exception("로보독 종료 실패")

    def stop(self):
        self.stopping.set()
