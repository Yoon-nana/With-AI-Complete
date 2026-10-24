"""제조사 내장 동작을 서로 다른 순서와 끝자세로 조합한 몸 애교."""
import random

def _reaction(identifier, name, sequence, expression, sound):
    return {"id": identifier, "name": name, "kind": "gesture",
            "sequence": sequence, "expression": expression, "sound": sound}


# 각 항목은 실제 명령 순서가 다르다. 눈/소리만 바꾼 중복 항목은 없다.
# 모든 동작 뒤 최소 2초 대기하며, 정상 종료 때 끝자세를 그대로 유지한다.
# ‘감사’ 표정 구간에서 소리 겹침이 보고되어 해당 조합의 추가 효과음은 끈다.
# sound=None은 눈 표정과 몸 애교는 유지하고 sound()만 호출하지 않는다는 뜻이다.
REACTIONS = (
    _reaction("greeting", "인사하고 일어서기", ("GREETING", "STANDUP"), "초롱초롱", "멍멍"),
    _reaction("sit", "얌전히 앉아 반기기", ("SITDOWN",), "ILOVEU", "안녕"),
    _reaction("stretch", "쭉 기지개 켜기", ("STRETCH",), "감사", None),
    _reaction("greet_sit", "인사한 뒤 착석", ("GREETING", "SITDOWN"), "ILOVEU", "멍멍"),
    _reaction("greet_stretch", "인사한 뒤 쭉 펴기", ("GREETING", "STRETCH"), "초롱초롱", "안녕"),
    _reaction("sit_greet", "앉았다가 인사", ("SITDOWN", "GREETING"), "감사", None),
    _reaction("stretch_greet", "기지개 뒤 인사", ("STRETCH", "GREETING"), "ILOVEU", "멍멍"),
    _reaction("sit_stand", "앉았다가 벌떡", ("SITDOWN", "STANDUP"), "초롱초롱", "안녕"),
    _reaction("stretch_stand", "기지개 뒤 당당하게 서기", ("STRETCH", "STANDUP"), "감사", None),
    _reaction("sit_stretch", "앉기에서 기지개로", ("SITDOWN", "STANDUP", "STRETCH"), "ILOVEU", "안녕"),
    _reaction("stretch_sit", "기지개 켜고 쉬기", ("STRETCH", "STANDUP", "SITDOWN"), "초롱초롱", "멍멍"),
    _reaction("greet_stand_sit", "인사하고 일어나 앉기", ("GREETING", "STANDUP", "SITDOWN"), "감사", None),
    _reaction("greet_stand_stretch", "인사하고 일어나 기지개", ("GREETING", "STANDUP", "STRETCH"), "ILOVEU", "멍멍"),
    _reaction("sit_stand_greet", "앉아 기다리다 일어나 인사", ("SITDOWN", "STANDUP", "GREETING"), "초롱초롱", "멍멍"),
    _reaction("stretch_stand_greet", "기지개 켜고 일어나 인사", ("STRETCH", "STANDUP", "GREETING"), "감사", None),
)

GESTURE_ALIASES = {"GREETING": ("GREETING", "인사하기"),
                   "READY": ("준비", "STANDUP"),
                   "STRETCH": ("STRETCH", "기지개켜기"),
                   "SITDOWN": ("SITDOWN", "앉기자세"),
                   "STANDUP": ("STANDUP", "준비")}


def gesture_value(api, name):
    for alias in GESTURE_ALIASES[name]:
        if hasattr(api, alias):
            return getattr(api, alias)
    raise AttributeError(f"몸동작 상수가 없어요: {name}")


def supported_reactions(api, dog):
    if not callable(getattr(dog, "gesture", None)):
        return []
    try:
        gesture_value(api, "STANDUP")
    except AttributeError:
        return []
    supported = []
    for item in REACTIONS:
        try:
            for gesture in item["sequence"]:
                gesture_value(api, gesture)
        except AttributeError:
            continue
        supported.append(item)
    return supported


class ReactionPicker:
    """지원되는 반응을 한 번씩 섞어 사용하고, 묶음 경계에서도 연속 중복을 피한다."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.bag = []
        self.last = None

    def pick(self, supported_ids):
        supported = set(supported_ids)
        self.bag = [item for item in self.bag if item in supported]
        if not self.bag:
            self.bag = sorted(supported)
            if not self.bag:
                raise ValueError("실행 가능한 애교가 없어요.")
            self.rng.shuffle(self.bag)
            if len(self.bag) > 1 and self.bag[-1] == self.last:
                self.bag[-1], self.bag[0] = self.bag[0], self.bag[-1]
        # 가능한 경우 첫 몸동작도 직전과 달라지게 골라 체감 반복을 줄인다.
        previous = next((item for item in REACTIONS if item["id"] == self.last), None)
        if previous:
            by_id = {item["id"]: item for item in REACTIONS}
            candidates = [i for i, identifier in enumerate(self.bag)
                          if by_id[identifier]["sequence"][0] != previous["sequence"][0]]
            if candidates:
                index = self.rng.choice(candidates)
                self.bag[index], self.bag[-1] = self.bag[-1], self.bag[index]
        self.last = self.bag.pop()
        return next(item for item in REACTIONS if item["id"] == self.last)


def guidance_voice_capability():
    # 제공 API에는 임의 문장 TTS/음성 파일 업로드 함수가 없다.
    # 내장 ‘안녕’ 효과음을 주문 안내 문장을 말하는 기능으로 오인하지 않는다.
    return {"route": "pc", "robotTextSpeech": False,
            "reason": "제공된 공개 API에서 문장 안내 기능은 확인되지 않아 PC 한국어 음성으로 안내합니다."}
