"""PC 로컬 HTML 키오스크. Python이 주문/학습 상태를 한 곳에서 관리한다."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
import queue
import random
import secrets
import threading
import time
import tkinter as tk
from urllib.parse import urlsplit, unquote
import webbrowser

from core import MENUS, Session, OPTION_SPECS, OPTION_PRICES, FIELD_LABELS, order_total
from guidance import load_guidance
from curriculum import STAGES, get_stage, CURRICULUM_VERSION, random_recipe, describe_order
from reactions import guidance_voice_capability
from medication import MedicationReminder
from daywatch_bridge import DaywatchService
from activity import ActivityCoordinator

BASE = Path(__file__).resolve().parent
TASKS = (
    {"service": "가져가기", "menu": "americano", "temperature": "차갑게"},
    {"service": "매장에서 먹기", "menu": "latte", "temperature": "따뜻하게"},
    {"service": "가져가기", "menu": "juice", "temperature": "차갑게"},
)
LABELS = {"americano": "아메리카노", "latte": "카페라떼", "tea": "캐모마일 차",
          "juice": "딸기주스", "vanilla": "바닐라라떼", "honey": "꿀아메리카노", "strawberry_latte": "딸기라떼", "peach_tea": "복숭아 아이스티"}


class KioskModel:
    def __init__(self, worker, base=BASE, rng=None):
        self.worker, self.base = worker, Path(base)
        self.session = Session()
        self.guidance = load_guidance(self.base / "data" / "guidance.json")
        self.lock = threading.Lock()
        self.revision = 0
        self.target = dict(TASKS[0])
        self.task_index = 0
        self.rewarded = set()
        self.message = "어서 오세요. 로보독과 함께 주문을 연습해요."
        self.status = "로보독 연결 확인 중"
        self.warnings = []
        self.last_action = ""
        self.seen = OrderedDict()
        self.shutdown_requested = threading.Event()
        self.lesson = None
        self.rng = rng or random.Random()
        self.menu_order = list(MENUS)
        self.learning_mode = "guided"
        self.legacy_progress = None
        self.completed_by_mode = self._load_progress()
        self.help_revealed = False
        self.help_level = 0
        self.review = None
        self.review_return_screen = None
        self.failed_attempts = 0
        self.app_section = "hub"
        self.medication = MedicationReminder(self.base / "data" / "medication.json")
        self.worker.medication = self.medication
        self.daywatch = DaywatchService(self.base)
        self.worker.daywatch = self.daywatch
        self.activity = ActivityCoordinator(self.base, self.medication, self.daywatch)
        self.worker.activity = self.activity

    @property
    def completed_stages(self):
        return self.completed_by_mode[self.learning_mode]

    def _load_progress(self):
        path = self.base / "data" / "progress.json"
        if not path.exists():
            return {"guided": set(), "practice": set()}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("잘못된 학습 진도")
            if data.get("curriculumVersion") != CURRICULUM_VERSION:
                self.legacy_progress = data
                return {"guided": set(), "practice": set()}
            self.legacy_progress = data.get("previousCurriculum")
            modes = data["completedByMode"]
            result = {}
            for mode in ("guided", "practice"):
                values = modes[mode]
                if not isinstance(values, list) or any(type(v) is not int or not 1 <= v <= len(STAGES) for v in values):
                    raise ValueError("잘못된 학습 진도")
                result[mode] = set(values)
            return result
        except (OSError, ValueError, TypeError, KeyError):
            logging.warning("학습 진도를 읽지 못해 기본 진도로 시작합니다.")
            return {"guided": set(), "practice": set()}

    def _save_progress(self):
        path = self.base / "data" / "progress.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"curriculumVersion": CURRICULUM_VERSION, "previousCurriculum": self.legacy_progress, "completedByMode": {key: sorted(value) for key, value in self.completed_by_mode.items()}}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _begin_stage(self, stage, reset_support=True, same_target=False):
        previous_target = self.target
        self.lesson = stage
        self.target = (dict(previous_target) if same_target else random_recipe(self.rng, previous_target)) if stage.randomized else dict(stage.target)
        if reset_support:
            self.session.new_task(self.learning_mode, variant=stage.randomized)
            self.session.support_level = max(2, stage.support) if self.learning_mode == "guided" else 1
        else:
            self.session.new_task(variant=stage.randomized)
            self.session.support_level = max(2, min(self.session.support_level, stage.support)) if self.learning_mode == "guided" else 1
        self.session.navigate(stage.start)
        self.menu_order = list(MENUS)
        if stage.randomized:
            self.rng.shuffle(self.menu_order)
        self.rewarded.clear()
        self.help_revealed = False
        self.review = None
        self.failed_attempts = 0
        self.task_index = stage.id - 1
        self.message = self._guide() if self.learning_mode == "guided" else self._screen_task()
        self.worker.submit("WELCOME")

    def _finish(self):
        s = self.session
        if self.target and any(s.order.get(k) != v for k, v in self.target.items()):
            if self.learning_mode == "guided":
                raise ValueError("주문 내용을 연습 주문과 다시 비교해 주세요.")
            if self.review is not None:
                return
            rows = [{"field": key, "label": label, "actual": LABELS.get(s.order.get(key), s.order.get(key)),
                     "expected": LABELS.get(expected, expected), "correct": s.order.get(key) == expected}
                    for key, expected in self.target.items() for label in [FIELD_LABELS[key]]]
            self.review_return_screen = s.screen
            s.navigate("confirm")
            self.review = {"correct": False, "items": rows}
            self.failed_attempts += 1
            s.unaided_streak = 0
            self.message = "제출한 주문에서 다른 부분을 찾았어요. 결과를 비교하고 다시 수정해 보세요."
            self._write_record({"completed": False, "correct": False, "help_count": s.help_count,
                                "support_level": s.support_level, "variant": s.variant})
            return
        if self.failed_attempts:
            s.unaided_streak = 0
        record = s.complete()
        if record is None:
            return
        if self.failed_attempts:
            s.unaided_streak = 0
        self.message = f"{self.lesson.id}단계를 완료했어요. 참 잘하셨어요!" if self.lesson else "주문 연습을 완료했어요. 참 잘하셨어요!"
        # 안내 모드는 조건 충족 시 이미 보상했다. 완료 클릭으로 다시 움직이지 않는다.
        self.worker.submit("COMPLETE" if self.learning_mode == "guided" else "SUCCESS")
        record["correct"] = True
        record["failed_attempts"] = self.failed_attempts
        self._write_record(record)
        if self.lesson:
            self.completed_stages.add(self.lesson.id)
            try:
                self._save_progress()
            except OSError:
                logging.exception("학습 진도 저장 실패")
                self.message += " 진도 저장은 실패했어요."

    def _write_record(self, record):
        try:
            with (self.base / "data" / "results.jsonl").open("a", encoding="utf-8") as stream:
                record["task"] = self.task_index if self.target else "free"
                record["stage"] = self.lesson.id if self.lesson else None
                record["mode"] = self.learning_mode
                record["order"] = dict(self.session.order)
                record["target"] = self.target
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logging.exception("학습 기록 저장 실패")
            self.message += " 기록 저장은 실패했어요."

    def _drain(self):
        while True:
            try:
                kind, value = self.worker.events.get_nowait()
            except queue.Empty:
                return
            if kind == "status":
                self.status = value
            elif kind == "warning":
                self.warnings = (self.warnings + [value])[-5:]
            elif kind == "action":
                self.last_action = value

    def _guide(self, selected=None):
        s = self.session
        level = self._assistance_level()
        if self.review:
            if level == 3:
                return "1. ‘다시 확인’이라고 표시된 줄을 찾으세요. 2. 내가 고른 것과 연습 주문을 비교하세요. 3. ‘다시 수정하기’를 눌러 다른 항목을 바꾸세요."
            if level == 2:
                return "결과 표에서 ‘다시 확인’이 붙은 항목부터 비교해 보세요."
            return "제출 결과에서 다른 항목을 확인한 뒤 ‘다시 수정하기’를 눌러 주세요."
        # 기본 가이드와 스스로 방식은 유지하고, 가이드 방식의 요청형 도움만 확장한다.
        if self.learning_mode == "guided" and level in (2, 3):
            extra = self._guided_extra_help(level)
            if extra:
                return extra
        if level == 0 and s.screen not in ("start", "complete"):
            return "도움이 필요하면 힌트나 자세한 도움을 요청할 수 있어요."
        if s.screen == "confirm":
            if level == 3:
                return "1. 이용 방식과 음료 이름을 연습 주문과 비교하세요. 2. 온도·크기·샷·토핑·당도·사이드를 차례로 확인하세요. 3. 다르면 ‘메뉴 수정’ 또는 ‘옵션·사이드 수정’을 누르세요. 4. 모두 맞으면 아래 주문 완료 버튼을 누르세요."
            if level == 2:
                return "연습 주문과 확인 표를 한 줄씩 비교해 보세요. 수정할 내용은 ‘메뉴 수정’이나 ‘옵션·사이드 수정’에서 바꿀 수 있어요."
            return "담은 주문을 확인해 볼게요. " + describe_order(s.order) + " 맞으면 주문 완료를 눌러 주세요."
        item = self.guidance[s.screen]
        if self.target:
            keys = self._screen_fields()
            missing = next((key for key in keys if key in self.target and s.order.get(key) != self.target[key]), None)
            if missing:
                expected = LABELS.get(self.target[missing], self.target[missing])
                if missing == "service":
                    if level == 3:
                        icon = "봉투" if expected == "가져가기" else "가게"
                        return f"1. {icon} 그림을 찾으세요. 2. ‘{expected}’ 버튼을 누르세요. 3. 선택 표시를 확인하고 아래 ‘메뉴 고르기’를 누르세요."
                    if level == 2:
                        return "포장 주문은 봉투 그림, 매장 이용은 가게 그림을 찾아보세요. 연습 주문의 이용 방식과 비교해 보세요."
                    return "주문에 맞는 이용 방식을 선택해 주세요."
                if missing == "menu":
                    category = self._category(self.target["menu"])
                    if level == 3:
                        return f"1. 위쪽 ‘{category}’ 분류를 누르세요. 2. ‘{expected}’ 사진 카드를 누르세요. 3. 선택 표시를 확인하고 ‘옵션 선택하기’를 누르세요."
                    if level == 2:
                        return f"위쪽 ‘{category}’ 분류에서 음료 사진과 이름을 살펴보세요."
                    return "주문에 맞는 음료를 선택해 주세요."
                label = FIELD_LABELS[missing]
                if level == 3:
                    return f"1. ‘{label}’ 항목을 찾으세요. 2. ‘{expected}’ 버튼을 누르세요. 3. 선택 표시를 확인하세요. 남은 옵션도 차례로 골라 주세요."
                if level == 2:
                    hints = {"temperature": "HOT은 따뜻하게, ICE는 차갑게예요. 연습 주문의 온도와 비교해 보세요.",
                             "size": "크기는 기본, 라지, 벤티 순으로 커져요. 요청한 크기와 비교해 보세요.",
                             "shot": "기본은 샷을 더하지 않는 선택이에요. 추가할 샷 횟수를 비교해 보세요.",
                             "whipped": "휘핑크림 항목에서 크림을 올릴지 선택해요. 연습 주문에 추가 요청이 있는지 확인해 보세요.",
                             "chocochip": "초코칩 토핑 항목을 살펴보세요. 요청에 토핑 추가가 있는지 확인해 보세요.",
                             "sweetness": "당도 항목에서 단맛의 정도를 고를 수 있어요. 연습 주문의 표현과 비교해 보세요.",
                             "side": "아래쪽 사이드 항목의 사진과 이름을 보세요. 음료와 함께 주문할 간식이 있는지 확인해 보세요."}
                    return hints[missing]
                return f"주문에 맞게 {label}을 선택해 주세요."
            if keys:
                if level == 3:
                    next_button = {"service_mode": "메뉴 고르기", "menu": "옵션 선택하기", "options": "주문 확인하기"}[s.screen]
                    return f"1. 선택 표시를 확인하세요. 2. 화면 아래 ‘{next_button}’ 버튼을 누르세요."
                if level == 2:
                    return "선택 표시와 연습 주문을 비교한 뒤 화면 아래의 다음 버튼을 찾아보세요."
                return "이 화면의 선택을 마쳤어요. 다음으로 진행해 주세요."
        return " ".join(f"{i}. {text}" for i, text in enumerate(item["steps"], 1)) if level == 3 else item["hint"] if level == 2 else item["intro"]

    def _guided_extra_help(self, level):
        s = self.session
        if not self.target or s.screen not in ("service_mode", "menu", "options", "confirm"):
            return None
        if s.screen == "confirm":
            if level == 2:
                return "이 화면은 새로 고르는 곳이 아니라 지금 담은 주문을 검토하는 곳이에요. 연습 주문과 이용 방식·음료·옵션·사이드를 한 줄씩 짝지어 비교해 보세요. 음료가 다르면 ‘메뉴 수정’, 옵션이나 간식이 다르면 ‘옵션·사이드 수정’에서 바꿀 수 있어요."
            return "1. 이용 방식과 음료 이름을 목표와 비교하세요. 2. 온도·크기·샷·휘핑·초코칩·당도·사이드를 위에서 아래로 확인하세요. 3. 다른 줄이 있으면 ‘메뉴 수정’ 또는 ‘옵션·사이드 수정’을 누르고 바꾼 뒤 이 화면으로 돌아오세요. 4. 모든 줄이 맞으면 아래 ‘주문 연습 완료’를 누르세요. 실제 결제는 없어요."
        fields = self._screen_fields()
        missing = next((key for key in fields if key in self.target and s.order.get(key) != self.target[key]), None)
        if not missing:
            next_button = {"service_mode": "메뉴 고르기", "menu": "옵션 선택하기", "options": "주문 확인하기"}[s.screen]
            if level == 2:
                return "이 화면의 선택은 목표와 일치해요. 선택 표시가 붙은 항목이 지금 담긴 값이라는 뜻이에요. 다시 고를 필요 없이 화면 아래의 진행 버튼을 찾아보세요."
            return f"1. 선택 표시가 붙은 내용을 확인하세요. 2. 지금 선택은 그대로 두세요. 3. 화면 아래 ‘{next_button}’를 누르세요. 누르면 다음 화면으로 이동하고 안내가 다시 시작돼요."
        expected = LABELS.get(self.target[missing], self.target[missing])
        actual = LABELS.get(s.order.get(missing), s.order.get(missing))
        current = "아직 선택하지 않은 상태예요." if actual is None else f"현재 ‘{actual}’이 선택되어 있어요."
        if missing == "service":
            if level == 2:
                reason = "포장은 음료를 매장 밖으로 가져가는 뜻이에요." if expected == "가져가기" else "매장 이용은 음료를 가게 안에서 마신다는 뜻이에요."
                return reason + " 봉투 그림은 포장, 가게 그림은 매장 이용을 나타내요. 연습 주문이 어디서 마시는 주문인지 먼저 생각한 뒤 그림을 비교해 보세요. " + current
            icon = "봉투" if expected == "가져가기" else "가게"
            return f"1. {current} 2. 화면의 {icon} 그림 아래 ‘{expected}’ 버튼을 누르세요. 3. 그 버튼에 선택 표시가 생겼는지 확인하세요. 4. 아래 ‘메뉴 고르기’를 누르세요."
        if missing == "menu":
            category = self._category(self.target["menu"])
            if level == 2:
                reason = {"커피": "커피가 들어간 음료를 모아 둔 분류예요.", "음료": "딸기처럼 과일 맛이 들어간 우유 음료를 찾는 분류예요.", "티": "차와 아이스티를 모아 둔 분류예요.", "에이드·주스": "과일 주스와 에이드를 모아 둔 분류예요."}[category]
                return f"위쪽 ‘{category}’는 {reason} 지금 보이는 목록에 없으면 위쪽 분류 탭을 바꾸면 돼요. 분류 안에서는 사진뿐 아니라 이름까지 목표와 비교해 보세요. " + current
            return f"1. 위쪽 ‘{category}’ 분류를 누르세요. 2. 바뀐 목록에서 이름이 ‘{expected}’인 사진 카드를 누르세요. 3. 카드의 선택 표시와 아래 주문 목록을 확인하세요. 4. ‘옵션 선택하기’를 누르세요."
        label = FIELD_LABELS[missing]
        if level == 3:
            return f"1. {current} 2. ‘{label}’ 항목을 찾으세요. 3. 그 항목의 ‘{expected}’ 버튼을 누르세요. 4. 선택 표시가 옮겨졌는지 확인하세요. 선택 뒤 안내가 바뀌면 그다음 항목을 진행하세요."
        explanations = {
            "temperature": ("HOT은 따뜻하게, ICE는 차갑게라는 뜻이에요.", "옵션 위쪽의 온도 항목", "따뜻한 음료인지 얼음이 든 음료인지 목표의 표현을 구분해 보세요."),
            "size": ("기본, 라지, 벤티 순서로 음료의 크기가 커져요.", "크기 항목", "크기 변경 요청이 없으면 기본, 변경 요청이 있으면 그 크기를 찾아야 해요."),
            "shot": ("샷은 커피 원액을 추가하는 옵션이에요. 기본은 추가 없음, 샷 추가는 한 번, 샷 2번 추가는 두 번이에요.", "샷 항목", "음료 이름에 이미 커피가 있어도 추가 횟수는 별도로 선택해요."),
            "whipped": ("휘핑크림은 음료 위에 올리는 크림이에요. 음료 종류를 바꾸는 선택은 아니에요.", "휘핑크림 항목", "올려 달라는 요청이면 추가, 요청이 없으면 없음을 고르는지 비교해 보세요."),
            "chocochip": ("초코칩 토핑은 음료 위에 더하는 것이고, 초코칩 쿠키는 따로 담는 간식이에요.", "초코칩 토핑 항목", "토핑 추가와 사이드 주문을 서로 혼동하지 않았는지 확인해 보세요."),
            "sweetness": ("보통은 기본 단맛, 덜 달게는 단맛을 줄이고 달게는 단맛을 더하는 선택이에요.", "당도 항목", "크기나 토핑을 골랐어도 당도는 따로 확인해야 해요."),
            "side": ("사이드는 음료와 따로 담는 간식이에요. 초코칩 토핑을 골라도 쿠키가 자동으로 담기지는 않아요.", "옵션 아래쪽의 사이드 항목", "쿠키와 머핀의 사진·이름을 비교하고, 간식 요청이 없으면 없음을 유지하는지 확인해 보세요."),
        }
        meaning, location, check = explanations[missing]
        return f"{meaning} 찾을 곳은 {location}이에요. {check} {current}"

    def _assistance_level(self):
        return self.help_level if self.help_revealed else 1 if self.learning_mode == "guided" else 0

    def _screen_task(self):
        """지금 보이는 화면의 목표만 표시한다. 전체 주문은 최종 확인에서만 제시한다."""
        screen = self.session.screen
        if not self.target or screen in ("start", "complete"):
            return self.guidance[screen]["intro"]
        if screen == "service_mode":
            return f"이용 방식: {self.target['service']}."
        if screen == "menu":
            return f"음료: {LABELS[self.target['menu']]} 1잔."
        if screen == "options":
            options = [f"온도: {self.target['temperature']}"]
            options += [f"{spec[0]}: {self.target[key]}" for key, spec in OPTION_SPECS.items()
                        if key in self.target and self.target[key] != spec[1][0]]
            return ", ".join(options) + (". 나머지는 기본값으로 두세요." if self.learning_mode == "guided" else ". 그 외 옵션: 기본값.")
        return describe_order(self.target)

    @staticmethod
    def _category(key):
        return "티" if key in ("tea", "peach_tea") else "음료" if key == "strawberry_latte" else "에이드·주스" if key == "juice" else "커피"

    def _screen_fields(self):
        return {"service_mode": ("service",), "menu": ("menu",),
                "options": ("temperature", *OPTION_SPECS)}.get(self.session.screen, ())

    def _can_continue(self):
        fields = self._screen_fields()
        if not fields or any(self.session.order.get(key) is None for key in fields):
            return False
        return self.learning_mode == "practice" or not self.target or all(
            self.session.order.get(key) == self.target[key] for key in fields if key in self.target)

    def snapshot(self):
        self._drain()
        s = self.session
        controller = self.worker.controller
        medication = self.medication.snapshot()
        activity = self.activity.snapshot()
        if medication["active"]:
            self.app_section = 'nap' if medication.get('activeKinds') == ['nap'] or not medication.get('activeKinds') else "medication"
        elif activity['mode'] == 'exercise':
            self.app_section = 'exercise'
        elif activity['mode'] == 'nap':
            self.app_section = 'nap'
        elif self.daywatch.requested and self.daywatch.snapshot()['state'] in ('PATROL','VERIFY','ALERT','REPORTED'):
            self.app_section = 'daywatch'
        elif self.app_section == 'exercise' or self.app_section == 'nap' and activity['nap']['finished']:
            self.app_section = 'hub'
        return {"app": self.app_section, "medication": medication, "daywatch": self.daywatch.snapshot(), "activity": activity,
                "screen": s.screen, "order": dict(s.order), "support": s.support_level,
                "helpCount": s.help_count, "variant": s.variant,
                "target": self.target, "message": self.message, "revision": self.revision,
                "screenTask": self._screen_task(),
                "taskDescription": describe_order(self.target) if self.lesson else None,
                "curriculum": [stage.summary(stage.id in self.completed_stages) for stage in STAGES],
                "lesson": self.lesson.summary(self.lesson.id in self.completed_stages) if self.lesson else None,
                "voice": guidance_voice_capability(),
                "mode": self.learning_mode,
                "review": self.review,
                "optionSpecs": [{"key": key, "label": spec[0], "values": spec[1], "prices": OPTION_PRICES.get(key, {})} for key, spec in OPTION_SPECS.items()],
                "total": order_total(s.order), "canContinue": self._can_continue(),
                "canSubmit": s.screen == "confirm" and (self.learning_mode == "practice" or not self.target or all(s.order.get(key) == value for key, value in self.target.items())),
                "ui": {"assisted": self.learning_mode == "guided" or self.help_revealed,
                       "speechDelayMs": max(0, int((getattr(self.worker, "audio_until", 0) - time.monotonic()) * 1000)) if self.worker.available or controller.mode == "real" else 0,
                       "assistanceLevel": self._assistance_level(),
                       "baseCoach": self.learning_mode == "guided" and self._assistance_level() == 1,
                       "showGuide": self.learning_mode == "guided" or self.help_revealed or bool(self.review) or s.screen == "complete",
                       "immediateFeedback": self.learning_mode == "guided",
                       "autoSpeak": self.learning_mode == "guided" or self.help_revealed or bool(self.review) or s.screen == "complete"},
                "robot": {"available": self.worker.available, "mode": controller.mode,
                          "status": self.status, "warnings": list(self.warnings),
                          "connectionPending": getattr(self.worker,"connection_pending",False), "port": getattr(controller,"port",None),
                          "busy": bool(self.worker.pending), "lastAction": self.last_action,
                          "sound": getattr(controller, "sound_enabled", False),
                          "gestures": getattr(controller, "gestures_enabled", False),
                          "reaction": getattr(controller, "last_reaction", None),
                          "bodyReactions": list(getattr(controller, "body_reactions", []))},
                "menus": [{"id": key, "name": LABELS[key], "price": value[1],
                           "options": value[2], "category": self._category(key),
                           "image": f"/assets/generated/{key}.png",
                           "coldImage": f"/assets/generated/{key}.png"}
                          for key in self.menu_order for value in [MENUS[key]]]}

    def _expect_screen(self, *screens):
        if self.session.screen not in screens:
            raise ValueError("화면이 변경됐어요. 현재 화면에서 다시 선택해 주세요.")
        if self.lesson and not self.review and self.session.screen not in (*self.lesson.screens, "complete", "start"):
            raise ValueError("이번 학습 단계에 해당하는 화면이 아니에요.")

    def _praise(self, field, value):
        if self.learning_mode == "practice":
            self.message = "선택이 주문에 반영됐어요."
            return None  # 제출 전에는 정답 여부나 칭찬 동작으로 답을 노출하지 않는다.
        correct = self.target is None or field not in self.target or value == self.target[field]
        if correct:
            self.message = "잘 선택했어요! " + self._guide(selected=True)
            # 선택 항목마다가 아니라 현재 화면의 조건을 전부 맞췄을 때 한 번만 보상한다.
            reward_key = self.session.screen
            if self._can_continue() and reward_key not in self.rewarded:
                self.worker.submit("PRAISE")
                self.rewarded.add(reward_key)
        else:
            self.message = "괜찮아요. 연습 주문과 다시 비교해 보세요. " + self._guide()
        return correct

    def apply(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("요청 형식이 올바르지 않아요.")
        request_id = payload.get("requestId")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
            raise ValueError("요청 번호를 확인해 주세요.")
        if request_id in self.seen:
            return self.snapshot()  # 재전송으로 동작/기록이 중복되지 않는다.
        if type(payload.get("revision")) is not int or payload["revision"] != self.revision:
            raise ValueError("다른 화면에서 선택이 바뀌었어요. 현재 화면을 다시 확인해 주세요.")
        action, value = payload.get("action"), payload.get("value")
        if not isinstance(action, str) or (value is not None and not isinstance(value, str)):
            raise ValueError("버튼 값을 확인해 주세요.")
        s = self.session
        global_actions = {"open_app", "daywatch_config", "daywatch_port", "sensor_config", "exercise_start", "exercise_end", "exercise_pause", "nap_start", "nap_end", "med_set", "med_add", "med_remove", "med_cancel", "med_mock_qr", "quit", "clear_warnings"}
        if self.medication.snapshot()["active"] and action not in global_actions:
            raise ValueError("복약 알림이 진행 중이에요. STOP QR로 확인하거나 알림을 취소해 주세요.")
        if self.review and action not in (*global_actions, "resume_review", "home", "repeat", "hint", "help", "sound_test", "gesture_test"):
            raise ValueError("결과를 확인한 뒤 다시 수정하기를 눌러 주세요.")
        if action == "open_app":
            if value not in ("hub", "kiosk", "medication", "daywatch", "nap"):
                raise ValueError("키오스크 또는 복약 알리미를 선택해 주세요.")
            if value == 'daywatch' and self.medication.snapshot()['active']:
                raise ValueError('현재 복약 알림을 먼저 확인해 주세요.')
            if self.activity.mode == 'exercise': self.activity.end_exercise()
            self.daywatch.select(self.activity.mode == 'checking')
            self.app_section = value
            self.message = "복약 시간을 설정해 주세요." if value == "medication" else "사용할 기능을 골라 주세요." if value == "hub" else self._guide()
            if value == 'daywatch':
                self.message = '무응답 감지 설정을 확인해 주세요.'
            elif value == 'nap':
                self.activity.nap_finished = False
                self.message = '몇 분 뒤에 깨워드릴까요?'
        elif action == 'exercise_start':
            self.activity.start_exercise(); self.app_section = 'exercise'
        elif action == 'exercise_end':
            self.activity.end_exercise(); self.app_section = 'hub'
            self.message = '체조를 마쳤어요. 무응답 감지로 돌아갑니다.'
        elif action == 'exercise_pause':
            self.activity.pause_exercise()
        elif action == 'nap_start':
            try: minutes = json.loads(value)
            except ValueError: raise ValueError('낮잠 시간을 확인하세요.')
            self.activity.start_nap(minutes); self.app_section = 'nap'
            self.message = f'{minutes}분 뒤 알람을 등록했어요.'
        elif action == 'nap_end':
            self.activity.end_nap(); self.app_section = 'hub'
            self.message = '낮잠을 마쳤어요. 무응답 감지로 돌아갑니다.'
        elif action == 'sensor_config':
            try: config = json.loads(value)
            except ValueError: raise ValueError('마빗 연결 설정을 확인하세요.')
            self.activity.configure(config)
        elif action == 'daywatch_config':
            try: config = json.loads(value)
            except ValueError: raise ValueError('무응답 감지 설정을 확인하세요.')
            self.daywatch.configure(config)
            self.daywatch.select(self.activity.mode == 'checking')
            self.message = '무응답 감지 설정을 저장했습니다.'
        elif action == 'daywatch_port':
            self.activity.configure({'port':value,'drive':self.activity.link.drive})
            self.daywatch.select(self.daywatch.requested, port=value)
            self.message = '마빗 USB 포트를 저장했습니다.'
        elif action == "med_add":
            try:
                entry = json.loads(value)
                if not isinstance(entry, dict):
                    raise ValueError("시간과 약 이름을 입력해 주세요.")
                self.medication.add(entry.get("time"), entry.get("medicine"))
            except (json.JSONDecodeError, TypeError):
                raise ValueError("시간과 약 이름을 입력해 주세요.")
            self.app_section = "medication"
            self.message = "복약 시간을 추가했어요."
        elif action == "med_remove":
            self.medication.remove(value)
            self.message = "선택한 복약 시간을 삭제했어요."
        elif action == "med_set":
            self.medication.configure(value)
            self.app_section = "medication"
            self.message = self.medication.snapshot()["message"]
        elif action == "med_cancel":
            self.medication.cancel()
            self.message = self.medication.snapshot()["message"]
        elif action == "med_mock_qr":
            self.medication.confirm(self.worker, simulated=True)
            self.message = self.medication.snapshot()["message"]
        elif action == "set_mode":
            self._expect_screen("start")
            if value not in ("guided", "practice"):
                raise ValueError("안내 버전 또는 스스로 버전을 선택해 주세요.")
            self.learning_mode = value
            self.message = "정답 위치와 설명을 보며 함께 연습해요." if value == "guided" else "정답 표시 없이 스스로 주문하고 제출 후 결과를 확인해요."
        elif action == "resume_review":
            if not self.review:
                raise ValueError("먼저 제출 결과를 확인해 주세요.")
            destination = self.review_return_screen
            self.review = None
            self.help_revealed = False
            s.navigate(destination)
            self.message = "원하는 내용을 다시 수정한 뒤 제출해 보세요."
        elif action == "start_stage":
            self._expect_screen("start", "complete")
            self._begin_stage(get_stage(value))
        elif action in ("next_stage", "new_random"):
            self._expect_screen("complete")
            if self.lesson is None:
                raise ValueError("먼저 학습 스테이지를 선택해 주세요.")
            if action == "new_random" and not self.lesson.randomized:
                raise ValueError("완전 랜덤 실전에서 새 주문을 뽑을 수 있어요.")
            self._begin_stage(get_stage(str(min(len(STAGES), self.lesson.id + 1))), reset_support=False)
        elif action in ("retry", "variant") and self.lesson:
            self._expect_screen("complete")
            stage = get_stage(str(min(len(STAGES), self.lesson.id + 1))) if action == "variant" else self.lesson
            self._begin_stage(stage, reset_support=False, same_target=action == "retry" and stage.randomized)
        elif action in ("start", "retry", "variant"):
            if action == "start":
                self._expect_screen("start")
                if value not in ("guided", "practice", "free"):
                    raise ValueError("연습 방식을 골라 주세요.")
                self.lesson = None
                self.learning_mode = "practice" if value == "free" else value
                self.review = None
                self.help_revealed = False
                self.failed_attempts = 0
                self.menu_order = list(MENUS)
                self.task_index = 0
                self.target = None if value == "free" else dict(TASKS[0])
                s.new_task("practice" if value == "free" else value)
            else:
                self._expect_screen("complete")
                if action == "variant" and self.target is not None:
                    self.task_index = (self.task_index + 1) % len(TASKS)
                    self.target = dict(TASKS[self.task_index])
                s.new_task(variant=action == "variant" or s.variant)
            self.rewarded.clear()
            self.message = self._guide()
            self.worker.submit("WELCOME")
        elif action == "home":
            s.screen = "start"
            self.review = None
            self.help_revealed = False
            self.message = "새로운 주문을 연습해 볼까요?"
        elif action == "service":
            self._expect_screen("service_mode")
            s.choose_service(value)
            self._praise("service", value)
        elif action == "menu":
            self._expect_screen("menu")
            s.choose_menu(value)
            if self.lesson and "options" not in self.lesson.screens:
                s.choose_temperature(self.target["temperature"])
            self._praise("menu", value)
        elif action in ("temperature", "default"):
            self._expect_screen("options")
            s.choose_temperature(value if action == "temperature" else None)
            self._praise("temperature", s.order["temperature"])
        elif action in OPTION_SPECS:
            self._expect_screen("options")
            s.choose_option(action, value)
            self._praise(action, value)
        elif action == "next":
            mapping = {"service_mode": ("service", "menu"), "menu": ("menu", "options"),
                       "options": ("temperature", "confirm")}
            self._expect_screen(*mapping)
            field, dest = mapping[s.screen]
            if not s.order.get(field):
                raise ValueError("먼저 항목을 선택해 주세요.")
            if not self._can_continue():
                raise ValueError("화면 위의 연습 주문에 맞게 골라 주세요.")
            if self.lesson:
                index = self.lesson.screens.index(s.screen)
                if index == len(self.lesson.screens) - 1:
                    self._finish()
                else:
                    s.navigate(self.lesson.screens[index + 1])
                    self.help_revealed = False
                    self.message = self._guide()
            else:
                s.navigate(dest)
                self.help_revealed = False
                self.message = self._guide()
        elif action in ("edit_menu", "edit_options"):
            self._expect_screen("confirm")
            if self.lesson and action == "edit_menu" and "menu" not in self.lesson.screens:
                raise ValueError("이번 단계에서는 옵션 수정으로 온도를 바꿔 보세요.")
            s.navigate("menu" if action == "edit_menu" else "options")
            self.help_revealed = False
            self.message = self._guide()
        elif action == "back":
            if self.lesson and s.screen in self.lesson.screens:
                index = self.lesson.screens.index(s.screen)
                s.navigate(self.lesson.screens[index - 1] if index else "start")
            else:
                s.back()
            self.help_revealed = False
            self.message = self._guide()
        elif action in ("hint", "help"):
            if s.screen not in ("start", "complete"):
                s.request_help()
            self.help_revealed = True
            self.help_level = 2 if action == "hint" else 3
            self.message = self._guide()
            self.worker.submit("STEP_GUIDE" if action == "help" else "HINT")
        elif action == "repeat":
            self.message = self._guide()
            self.worker.submit("HINT")
        elif action == "complete":
            self._expect_screen("confirm", "complete")
            self._finish()
        elif action in ("sound_test", "gesture_test"):
            flag = "sound_enabled" if action == "sound_test" else "gestures_enabled"
            if self.worker.available and not getattr(self.worker.controller, flag, False):
                raise ValueError("시작 창에서 해당 기능을 끈 상태예요. 종료 후 소리/애교 사용을 켜고 다시 시작해 주세요.")
            accepted = self.worker.submit("SOUND_TEST" if action == "sound_test" else "GESTURE_TEST")
            self.message = "시험 명령을 보냈어요. 실제 로봇 반응을 확인해 주세요." if accepted else "동작 중이에요. 잠시 후 시험해 주세요."
            if not self.worker.available:
                self.message = "모의 모드예요. 실제 로봇에서는 소리나 동작이 나오지 않아요."
        elif action == "clear_warnings":
            self.warnings.clear()
        elif action == "quit":
            self.shutdown_requested.set()
        else:
            raise ValueError("허용되지 않은 요청이에요.")
        self.revision += 1
        self.seen[request_id] = True
        if len(self.seen) > 256:
            self.seen.popitem(last=False)
        return self.snapshot()


class LocalKioskServer:
    def __init__(self, worker, base=BASE, port=0):
        self.model = KioskModel(worker, base)
        self.token = secrets.token_urlsafe(24)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # 토큰 및 개인 데이터가 접근 로그에 남지 않는다.

            def reply(self, code, data, content_type="application/json; charset=utf-8"):
                body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def trusted(self):
                return self.headers.get("Host") == outer.host

            def authorized(self):
                return self.trusted() and secrets.compare_digest(self.headers.get("X-Kiosk-Token", ""), outer.token)

            def do_GET(self):
                if not self.trusted():
                    return self.reply(403, {"error": "허용되지 않은 호스트"})
                route = urlsplit(self.path).path
                if route == "/bridge-info":
                    body = b'{"bridge":"aigo-in-v1"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if route == "/start":
                    self.send_response(302)
                    self.send_header("Location", "http://" + outer.host + "/" + ("?" + urlsplit(self.path).query if urlsplit(self.path).query else "") + "#" + outer.token)
                    self.end_headers()
                    return
                if route == "/firmware/unified.hex":
                    firmware = Path(base) / "models" / "unified.hex"
                    if not firmware.is_file(): return self.reply(404, {"error":"통합 HEX 파일이 없습니다."})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", 'attachment; filename="AIGO-IN-unified.hex"')
                    body = firmware.read_bytes()
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if route == "/api/ports":
                    if not self.authorized(): return self.reply(403, {"error":"접근 권한 없음"})
                    from serial.tools import list_ports
                    return self.reply(200, {"ports":[{"port":p.device,"description":p.description} for p in list_ports.comports()]})
                if route == "/api/state":
                    if not self.authorized():
                        return self.reply(403, {"error": "접근 권한 없음"})
                    with outer.model.lock:
                        return self.reply(200, outer.model.snapshot())
                path = (Path(base) / "web" / ("index.html" if route == "/" else unquote(route).lstrip("/"))).resolve()
                web_root = (Path(base) / "web").resolve()
                if not path.is_relative_to(web_root) or not path.is_file():
                    return self.reply(404, {"error": "파일 없음"})
                return self.reply(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")

            def do_POST(self):
                origin = self.headers.get("Origin")
                if not self.authorized() or origin not in (None, "http://" + outer.host):
                    return self.reply(403, {"error": "접근 권한 없음"})
                if self.path in ("/api/connect-robot", "/api/disconnect-robot"):
                    try:
                        length = int(self.headers.get("Content-Length","0"))
                        if not 0 < length <= 1024: raise ValueError("요청 크기를 확인하세요.")
                        payload = json.loads(self.rfile.read(length))
                        if not isinstance(payload, dict): raise ValueError("연결 요청을 확인하세요.")
                        outer.model.worker.request_connection(payload.get("port", "") if self.path == "/api/connect-robot" else None)
                        return self.reply(202, {"message":"연결 요청을 전달했습니다."})
                    except (ValueError,TypeError) as error:
                        return self.reply(400, {"error":str(error)})
                if self.path != "/api/event":
                    return self.reply(404, {"error": "허용되지 않은 경로"})
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4096:
                        raise ValueError("요청 크기를 확인해 주세요.")
                    payload = json.loads(self.rfile.read(size))
                    with outer.model.lock:
                        self.reply(200, outer.model.apply(payload))
                except (ValueError, TypeError, KeyError) as error:
                    with outer.model.lock:
                        self.reply(400, {"error": str(error), "state": outer.model.snapshot()})
                except Exception:
                    logging.exception("키오스크 요청 처리 실패")
                    self.reply(500, {"error": "처리 중 문제가 발생했어요. 다시 시도해 주세요."})

        self.http = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.http.daemon_threads = True
        self.host = f"127.0.0.1:{self.http.server_port}"
        self.url = f"http://{self.host}/#{self.token}"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


class BrowserApp:
    def __init__(self, root, worker):
        self.root, self.worker = root, worker
        self.server = LocalKioskServer(worker)
        self.server.start()
        self.closing = False
        self.root.title("로보독 도우미 · 실행 중")
        self.root.geometry("730x440")
        self.root.minsize(650, 420)
        tk.Label(root, text="주문 연습 / 복약 알리미 / 무응답 감지가 브라우저에 열렸어요", bg="#f3f6fa", pady=22).pack()
        tk.Label(root, text="이 창을 닫으면 로보독과 키오스크를 종료합니다.", bg="#f3f6fa").pack(pady=10)
        tk.Button(root, text="키오스크 다시 열기", command=self.open, pady=12).pack(pady=10)
        tk.Button(root, text="종료 및 로보독 연결 닫기", command=self.close, pady=12).pack(pady=10)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        print("브라우저가 열리지 않으면 이 주소를 직접 여세요:", self.server.url)
        self.open()
        self.root.after(200, self.poll)

    def open(self):
        if not webbrowser.open(self.server.url):
            logging.warning("브라우저 자동 열기 실패. Thonny에 표시된 주소를 직접 여세요.")

    def poll(self):
        if self.closing:
            return
        if self.server.model.shutdown_requested.is_set():
            self.close()
        else:
            self.root.after(200, self.poll)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.server.close()
        self.worker.stop()
        self.wait_closed()

    def wait_closed(self):
        if self.worker.thread.is_alive():
            self.root.after(100, self.wait_closed)
        else:
            self.root.destroy()
