"""화면과 하드웨어에 의존하지 않는 주문/학습 상태."""
from dataclasses import dataclass, field

MENUS = {
    "americano": ("아메리카노", 3000, ("따뜻하게", "차갑게")),
    "latte": ("카페라떼", 3500, ("따뜻하게", "차갑게")),
    "tea": ("캐모마일 차", 3000, ("따뜻하게", "차갑게")),
    "juice": ("딸기주스", 4000, ("차갑게",)),
    "vanilla": ("바닐라라떼", 3800, ("따뜻하게", "차갑게")),
    "honey": ("꿀아메리카노", 3200, ("차갑게",)),
}
MENUS.update({
    "strawberry_latte": ("딸기라떼", 4000, ("차갑게",)),
    "peach_tea": ("복숭아 아이스티", 3500, ("차갑게",)),
})
OPTION_SPECS = {
    "size": ("크기", ("기본", "라지", "벤티")),
    "shot": ("샷", ("기본", "샷 추가", "샷 2번 추가")),
    "whipped": ("휘핑크림", ("없음", "추가")),
    "chocochip": ("초코칩 토핑", ("없음", "추가")),
    "sweetness": ("당도", ("보통", "덜 달게", "달게")),
    "side": ("사이드", ("없음", "초코칩 쿠키", "버터 쿠키", "초코 머핀")),
}
DEFAULT_OPTIONS = {key: spec[1][0] for key, spec in OPTION_SPECS.items()}
FIELD_LABELS = {"service": "이용 방식", "menu": "음료", "temperature": "온도",
                **{key: spec[0] for key, spec in OPTION_SPECS.items()}}
OPTION_PRICES = {"size": {"라지": 500, "벤티": 1000}, "shot": {"샷 추가": 500, "샷 2번 추가": 1000},
                 "whipped": {"추가": 500}, "chocochip": {"추가": 500},
                 "side": {"초코칩 쿠키": 1500, "버터 쿠키": 1200, "초코 머핀": 2000}}


def order_total(order):
    base = MENUS.get(order.get("menu"), ("", 0))[1]
    return base + sum(prices.get(order.get(key), 0) for key, prices in OPTION_PRICES.items())


SCREENS = ("start", "service_mode", "menu", "options", "confirm", "complete")


@dataclass
class Session:
    screen: str = "start"
    mode: str = "guided"
    support_level: int = 3
    help_count: int = 0
    unaided_streak: int = 0
    order: dict = field(default_factory=dict)
    variant: bool = False
    finished: bool = False

    def new_task(self, mode=None, variant=False):
        if mode is not None:
            if mode not in ("guided", "practice"):
                raise ValueError("올바른 연습 방식을 선택해 주세요.")
            self.mode = mode
            self.support_level = 3 if mode == "guided" else 1
            self.unaided_streak = 0
        self.order.clear()
        self.help_count = 0
        self.variant = variant
        self.finished = False
        self.screen = "service_mode"

    def navigate(self, target):
        if target not in SCREENS:
            raise ValueError("알 수 없는 화면입니다.")
        if target in ("menu", "options", "confirm", "complete"):
            if self.order.get("service") not in ("매장에서 먹기", "가져가기"):
                raise ValueError("이용 방식을 먼저 골라 주세요.")
        if target in ("options", "confirm", "complete"):
            if self.order.get("menu") not in MENUS:
                raise ValueError("음료를 먼저 골라 주세요.")
        if target in ("confirm", "complete"):
            allowed = MENUS[self.order["menu"]][2]
            if self.order.get("temperature") not in allowed:
                raise ValueError("옵션을 먼저 골라 주세요.")
            if any(self.order.get(key) not in spec[1] for key, spec in OPTION_SPECS.items()):
                raise ValueError("추가 옵션을 다시 확인해 주세요.")
        if target == "complete" and not self.finished:
            raise ValueError("완료 버튼을 눌러 주세요.")
        self.screen = target

    def choose_service(self, value):
        if value not in ("매장에서 먹기", "가져가기"):
            raise ValueError("이용 방식을 다시 확인해 주세요.")
        self.order["service"] = value

    def choose_menu(self, value):
        if value not in MENUS:
            raise ValueError("음료를 다시 확인해 주세요.")
        if self.order.get("menu") != value:
            self.order.pop("temperature", None)
            self.order.update(DEFAULT_OPTIONS)
        self.order["menu"] = value

    def choose_temperature(self, value=None):
        if self.order.get("menu") not in MENUS:
            raise ValueError("음료를 먼저 골라 주세요.")
        options = MENUS[self.order["menu"]][2]
        value = value or options[0]
        if value not in options:
            raise ValueError("이 음료에 맞는 옵션을 골라 주세요.")
        self.order["temperature"] = value

    def choose_option(self, key, value):
        if self.order.get("menu") not in MENUS:
            raise ValueError("음료를 먼저 골라 주세요.")
        if key not in OPTION_SPECS or value not in OPTION_SPECS[key][1]:
            raise ValueError("올바른 추가 옵션을 골라 주세요.")
        self.order[key] = value

    def request_help(self):
        self.help_count += 1
        self.support_level = max(self.support_level, 2) if self.help_count == 1 else 3

    def complete(self):
        if self.finished:
            return None
        self.navigate("confirm")  # 필수 선택 검증
        record = {"completed": True, "help_count": self.help_count,
                  "support_level": self.support_level, "variant": self.variant}
        if self.help_count:
            self.unaided_streak = 0
        else:
            self.unaided_streak += 1
            if self.unaided_streak == 2:
                self.support_level = max(1, self.support_level - 1)
                self.unaided_streak = 0
        self.finished = True
        self.navigate("complete")
        return record

    def back(self):
        if self.screen not in ("start", "complete"):
            self.navigate(SCREENS[SCREENS.index(self.screen) - 1])
