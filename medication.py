"""로컬 복약 시간 설정과 STOP QR 확인. 장치 호출은 RobotWorker에서만 한다."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import threading
import time
import uuid

ACTIVE_STATES = {"preparing", "alerting", "waiting", "stopping", "confirming"}
BARK_INTERVAL_SECONDS = 5.0  # 4.5초 효과음 대기 뒤 다음 짖음. 동시에 재생하지 않는다.


class MedicationReminder:
    def __init__(self, path, now=None, clock=None):
        self.path = Path(path)
        self.now = now or datetime.now
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self.status = "idle"
        self.time_text = "08:30"
        self.due = None
        self.message = "복약 시간을 설정해 주세요."
        self.qr_status = "확인 QR의 내용은 영문 대문자 STOP입니다."
        self.revision = 0
        self.alert_count = 0
        self.last_alert = 0.0
        self.next_ai_try = 0.0
        self.qr_ready = False
        self.next_poll = 0.0
        self.ready_at = 0.0
        self.pending_alert = "MED_ALERT"
        self.schedules = []
        self.active_ids = []
        self.require_qr_clear = False
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            status = data["status"]
            if status not in {"idle", "armed", "done"} | ACTIVE_STATES:
                raise ValueError("잘못된 알림 상태")
            entries = data.get("schedules")
            if data.get("version") != 2:
                # 이전 한 개짜리 예약을 약 이름 미설정 항목으로 이관한다.
                self._validate_time(data["time"])
                entries = [] if status == "idle" else [{"id": uuid.uuid4().hex, "time": data["time"],
                    "medicine": "약 이름 미설정", "due": data["due"], "status": "done" if status == "done" else "armed"}]
            if not isinstance(entries, list) or len(entries) > 50:
                raise ValueError("잘못된 예약 목록")
            loaded = []
            for item in entries:
                self._validate_time(item["time"])
                medicine = self._validate_medicine(item["medicine"])
                due = datetime.fromisoformat(item["due"])
                if due.tzinfo is not None or item["status"] not in {"armed", "active", "done", "cancelled"}:
                    raise ValueError("잘못된 예약 상태")
                identifier = item["id"]
                if not isinstance(identifier, str) or not identifier or identifier in {e["id"] for e in loaded}:
                    raise ValueError("잘못된 예약 번호")
                loaded.append({"id": identifier, "time": item["time"], "medicine": medicine, "due": due,
                               "status": "armed" if item["status"] == "active" else item["status"]})
                if item.get('kind') == 'nap': loaded[-1]['kind'] = 'nap'
            self.schedules = loaded
            self.status = "armed" if any(e["status"] == "armed" for e in loaded) else "done" if status == "done" else "idle"
            self._update_summary()
            self.message = {"armed": "저장된 복약 알림을 불러왔어요.", "done": "이번 복약 알림은 STOP QR 확인을 마쳤어요.", "idle": "복약 시간을 설정해 주세요."}[self.status]
        except (OSError, ValueError, KeyError, TypeError):
            self.status, self.due = "idle", None
            self.schedules, self.active_ids = [], []
            self.message = "저장된 설정을 읽지 못했어요. 시간을 다시 설정해 주세요."

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 2, "status": self.status,
                                        "schedules": self._schedule_rows()},
                                       ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _validate_time(value):
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("시간을 08:30처럼 입력해 주세요.")

    @staticmethod
    def _validate_medicine(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
            raise ValueError("복용할 약 이름을 1~80자로 입력해 주세요.")
        return value.strip()

    def _schedule_rows(self):
        return [{**e, "due": e["due"].isoformat()} for e in sorted(self.schedules, key=lambda e: e["due"])]

    def _update_summary(self):
        active = [e for e in self.schedules if e["id"] in self.active_ids]
        upcoming = sorted((e for e in self.schedules if e["status"] == "armed"), key=lambda e: e["due"])
        entries = active or upcoming
        if entries:
            self.time_text, self.due = entries[0]["time"], entries[0]["due"]

    def configure(self, value):
        """이전 단일 시간 API와의 호환. HTML은 add()로 여러 예약을 추가한다."""
        self._validate_time(value)
        with self.lock:
            if self.status in ACTIVE_STATES:
                raise ValueError("진행 중인 알림을 확인하거나 취소한 뒤 시간을 바꿔 주세요.")
            self.schedules, self.active_ids = [], []
            self.add(value, "약 이름 미설정")

    def add(self, value, medicine):
        self._validate_time(value)
        medicine = self._validate_medicine(medicine)
        with self.lock:
            if len(self.schedules) >= 50:
                raise ValueError("예약은 최대 50개예요. 완료된 항목을 삭제한 뒤 추가해 주세요.")
            now = self.now()
            hour, minute = map(int, value.split(":"))
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if due + timedelta(minutes=1) <= now:
                due += timedelta(days=1)
            if any(e["due"] == due and e["medicine"] == medicine and e["status"] in ("armed", "active") for e in self.schedules):
                raise ValueError("같은 시간에 같은 약이 이미 등록되어 있어요.")
            self.schedules.append({"id": uuid.uuid4().hex, "time": value, "medicine": medicine, "due": due, "status": "armed"})
            if self.status not in ACTIVE_STATES:
                self.status = "armed"
                self.message = "복약 시간을 추가했어요. PC와 프로그램을 켜 두세요."
            self._update_summary()
            self._save()
            self.revision += 1

    def add_after(self, minutes, label, kind='nap'):
        if type(minutes) is not int or not 1 <= minutes <= 180:
            raise ValueError('1~180분으로 입력하세요.')
        with self.lock:
            if len(self.schedules) >= 50: raise ValueError('예약은 최대 50개입니다.')
            due = self.now()+timedelta(minutes=minutes)
            row = {'id':uuid.uuid4().hex,'time':due.strftime('%H:%M'),'medicine':label,
                   'due':due,'status':'armed','kind':kind}
            self.schedules.append(row)
            if self.status not in ACTIVE_STATES: self.status = 'armed'
            self._update_summary(); self._save(); self.revision += 1
            return {**row,'due':due.isoformat()}

    def end_nap(self, identifier):
        with self.lock:
            entry = next((e for e in self.schedules if e['id']==identifier and e.get('kind')=='nap'),None)
            if entry is None: return
            entry['status'] = 'done'
            was_active = identifier in self.active_ids
            self.active_ids = [i for i in self.active_ids if i != identifier]
            if was_active and not self.active_ids:
                self.status = 'stopping'; self.qr_ready = False
            elif self.status not in ACTIVE_STATES:
                self.status = 'armed' if any(e['status']=='armed' for e in self.schedules) else 'done'
            self._save(); self.revision += 1

    def remove(self, identifier):
        with self.lock:
            entry = next((e for e in self.schedules if e["id"] == identifier), None)
            if entry is None:
                raise ValueError("삭제할 예약을 찾을 수 없어요.")
            if identifier in self.active_ids:
                raise ValueError("진행 중인 알림은 먼저 취소하거나 STOP으로 확인해 주세요.")
            self.schedules.remove(entry)
            if self.status not in ACTIVE_STATES:
                self.status = "armed" if any(e["status"] == "armed" for e in self.schedules) else "idle"
                self.message = "선택한 복약 시간을 삭제했어요."
            self._update_summary()
            self._save()
            self.revision += 1

    def cancel(self):
        with self.lock:
            self.schedules.clear()
            self.active_ids = []
            self.status = "idle"
            self.message = "등록한 복약 항목을 모두 삭제하고 반복 알림을 종료했어요. 이미 시작한 소리·몸동작은 마친 뒤 멈춥니다."
            self.qr_ready = False
            self.qr_status = "예약이 모두 종료되었어요. 필요하면 새 시간을 추가해 주세요."
            self.due = None
            self.ready_at = 0.0
            self._save()
            self.revision += 1

    def snapshot(self):
        with self.lock:
            return {"status": self.status, "time": self.time_text, "localTime": self.now().strftime("%H:%M"),
                    "due": self.due.isoformat() if self.due else None,
                    "message": self.message, "qrStatus": self.qr_status,
                    "qrValue": "STOP", "revision": self.revision,
                    "alertCount": self.alert_count,
                    "active": self.status in ACTIVE_STATES, "schedules": self._schedule_rows(),
                    "activeMedicines": [e["medicine"] for e in self.schedules if e["id"] in self.active_ids],
                    "activeKinds": sorted(set(e.get('kind','medication') for e in self.schedules if e['id'] in self.active_ids)),
                    "pendingCount": sum(e["status"] == "armed" for e in self.schedules),
                    "barkIntervalSeconds": BARK_INTERVAL_SECONDS}

    def _qr_message(self, text):
        if text != self.qr_status:
            self.qr_status = text
            self.revision += 1

    def action_allowed(self, action):
        with self.lock:
            return self.status == ("confirming" if action == "MED_CONFIRM" else "alerting")

    def action_finished(self, action):
        with self.lock:
            if action == "MED_CONFIRM" and self.status == "confirming":
                for entry in self.schedules:
                    if entry["id"] in self.active_ids:
                        entry["status"] = "done"
                self.active_ids = []
                self.status = "done"
                self.message = "STOP QR 확인이 완료되었어요. 이번 알림을 종료합니다."
                self._update_summary()
            elif action in ("MED_ALERT", "MED_REPEAT") and self.status == "alerting":
                self.status = "waiting"
                self.message = "약을 드셨으면 로보독 카메라에 STOP QR을 보여주세요."
            else:
                return
            self._save()
            self.revision += 1

    def confirm(self, worker, simulated=False):
        with self.lock:
            if simulated and worker.controller.mode != "mock":
                raise ValueError("실제 연결에서는 로보독 카메라로 STOP QR을 확인해 주세요.")
            if self.status not in ("waiting", "alerting"):
                raise ValueError("복약 알림이 울리고 QR 확인을 기다릴 때 사용할 수 있어요.")
            self.require_qr_clear = True
            if worker.submit("MED_CONFIRM"):
                self.status = "confirming"
                self.message = "STOP QR을 인식했어요. 이번 알림을 마무리합니다."
            else:
                self.status = "stopping"
                self.message = "STOP QR을 인식했어요. 현재 소리를 마친 뒤 준비 자세로 돌아갑니다."
            self.revision += 1

    def tick(self, worker):
        """워커의 빈 실행 슬롯에서만 호출한다. HTTP 스레드에서 장치를 읽지 않는다."""
        with self.lock:
            stamp = self.clock()
            if self.status not in ACTIVE_STATES:
                due = sorted((e for e in self.schedules if e["status"] == "armed" and e["due"] <= self.now()), key=lambda e: e["due"])
                if due:
                    group = [e for e in due if e["due"] == due[0]["due"]]
                    self.active_ids = [e["id"] for e in group]
                    for entry in group:
                        entry["status"] = "active"
                    self._update_summary()
                    self.qr_ready = False
                    self.next_ai_try = self.next_poll = 0.0
                    self.alert_count = 0
                    self._prepare("MED_ALERT", stamp)
                return
            if self.status == "stopping":
                if worker.submit("MED_CONFIRM"):
                    self.status = "confirming"
                    self.revision += 1
                return
            if self.status == "preparing" and stamp >= self.ready_at:
                self._alert(worker, self.pending_alert, stamp)
                return
            if self.status != "waiting":
                return
            if not worker.available or worker.controller.mode != "real":
                self._qr_message("모의 모드: 실제 QR 인식 대신 아래 모의 확인 버튼을 사용하세요.")
            elif stamp >= self.next_poll:
                self.next_poll = stamp + .3
                self._read_qr(worker, stamp)
            if self.status == "waiting" and stamp - self.last_alert >= BARK_INTERVAL_SECONDS:
                self._alert(worker, "MED_REPEAT", stamp)

    def poll_during_bark(self, worker):
        """소리 종료 대기 중에도 같은 워커에서 STOP을 읽고 다음 짖음을 막는다."""
        with self.lock:
            stamp = self.clock()
            if self.status in ("waiting", "alerting") and worker.available and worker.controller.mode == "real" and stamp >= self.next_poll:
                self.next_poll = stamp + .3
                self._read_qr(worker, stamp)

    def _prepare(self, action, stamp):
        self.status = "preparing"
        self.pending_alert = action
        self.message = "약을 먹을 시간입니다. 복약 알림을 시작합니다." if action == "MED_ALERT" else "복용하셨으면 STOP QR로 확인해 주세요. 다시 알려드릴게요."
        self.ready_at = stamp + 2.0  # 화면에서 기존 PC 안내를 취소할 여유
        self._save()
        self.revision += 1

    def _alert(self, worker, action, stamp):
        if worker.submit(action):
            self.status = "alerting"
            self.last_alert = stamp
            self.alert_count += 1
            medicines = ", ".join(e["medicine"] for e in self.schedules if e["id"] in self.active_ids)
            self.message = f"{medicines or '약'} 복용 시간이에요. 복용 후 STOP QR로 확인해 주세요."
            self._save()
            self.revision += 1

    def _read_qr(self, worker, stamp):
        dog, api = worker.controller.dog, worker.controller.api
        try:
            if not dog.is_ai_alive():
                self.qr_ready = False
                self._qr_message("AI 카메라 연결을 기다리고 있어요. 연결되면 다시 시도합니다.")
                return
            if not self.qr_ready:
                if stamp < self.next_ai_try:
                    return
                self.next_ai_try = stamp + 15
                response = dog.ai_mode(api.QRCODE_READ, timeout=1.0)
                if response is None:
                    self._qr_message("QR 모드 응답이 없어요. 15초 후 다시 시도합니다.")
                    return
                self.qr_ready = True
                self.next_poll = stamp + 1.0
                self._qr_message("카메라에 영문 대문자 STOP QR을 보여주세요.")
                return
            value = dog.get_qrcode()
            if self.require_qr_clear:
                if value == "STOP":
                    self._qr_message("이전 확인 QR을 내린 뒤, 이번 약을 복용하고 STOP QR을 다시 보여주세요.")
                else:
                    self.require_qr_clear = False
                return
            if value == "STOP":
                self.confirm(worker)
            elif value:
                self._qr_message("다른 QR이에요. 내용이 정확히 STOP인 QR을 보여주세요.")
        except UnicodeDecodeError:
            self._qr_message("QR 문자를 읽지 못했어요. 영문 대문자 STOP으로 만든 QR을 사용하세요.")
        except (AttributeError, OSError, ValueError, TypeError) as error:
            self.qr_ready = False
            self.next_ai_try = stamp + 15
            self._qr_message(f"QR 연결 확인 필요: {error}. 15초 후 다시 시도합니다.")
