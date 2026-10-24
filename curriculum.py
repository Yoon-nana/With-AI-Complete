"""기본 주문부터 옵션 조합과 완전 무작위 주문까지, 전체 주문 미션."""
from dataclasses import dataclass
from core import DEFAULT_OPTIONS, MENUS, OPTION_SPECS, FIELD_LABELS

CURRICULUM_VERSION = 3
FULL_FLOW = ("service_mode", "menu", "options", "confirm")

@dataclass(frozen=True)
class Stage:
    id: int
    title: str
    description: str
    target: dict
    band: str = "기본 주문"
    focus: str = ""
    randomized: bool = False
    screens: tuple = FULL_FLOW
    start: str = "service_mode"
    support: int = 3

    def summary(self, completed=False):
        return {"id": self.id, "title": self.title, "description": self.description,
                "screens": self.screens, "support": self.support, "completed": completed,
                "band": self.band, "focus": self.focus, "randomized": self.randomized}


def recipe(menu, **options):
    return {"service": "가져가기", "menu": menu, "temperature": "차갑게",
            **DEFAULT_OPTIONS, **options}

STAGES = (
    Stage(1, "첫 커피 한 잔", "기본 아이스 커피를 주문해요.", recipe("americano"), focus="기본 주문 전체 흐름"),
    Stage(2, "커피 말고 딸기", "다른 카테고리의 우유 음료를 찾아요.", recipe("strawberry_latte"), focus="카테고리 이동"),
    Stage(3, "매장에서 따뜻하게", "따뜻한 카페라떼를 매장에서 마셔요.", recipe("latte", service="매장에서 먹기", temperature="따뜻하게"), focus="매장 이용과 HOT 선택"),
    Stage(4, "따뜻한 차 한 잔", "티 카테고리에서 따뜻한 차를 찾아요.", recipe("tea", service="매장에서 먹기", temperature="따뜻하게"), focus="티 카테고리와 온도 구분"),
    Stage(5, "주스는 크게", "딸기주스의 크기를 바꿔 주문해요.", recipe("juice", size="라지"), "단일 옵션", "주스 카테고리와 크기 변경"),
    Stage(6, "단맛은 조금만", "꿀아메리카노를 덜 달게 주문해요.", recipe("honey", sweetness="덜 달게"), "단일 옵션", "당도 낮추기"),
    Stage(7, "나만의 아샷추", "복숭아 아이스티에 샷을 추가해요.", recipe("peach_tea", shot="샷 추가"), "단일 옵션", "베이스 음료와 샷 조합"),
    Stage(8, "진한 바닐라 커피", "따뜻한 바닐라라떼에 샷을 두 번 추가해요.", recipe("vanilla", service="매장에서 먹기", temperature="따뜻하게", shot="샷 2번 추가"), "단일 옵션", "온도와 샷 수량 구분"),
    Stage(9, "딸기 위에 휘핑", "딸기라떼를 크게, 휘핑크림과 함께 주문해요.", recipe("strawberry_latte", size="라지", whipped="추가"), "옵션 조합", "크기와 휘핑크림 조합"),
    Stage(10, "달지 않은 초코 라떼", "큰 카페라떼에 초코칩을 올리고 당도를 낮춰요.", recipe("latte", size="벤티", chocochip="추가", sweetness="덜 달게"), "옵션 조합", "토핑과 당도·크기 조합"),
    Stage(11, "차와 버터 쿠키", "따뜻한 차와 버터 쿠키를 매장에서 즐겨요.", recipe("tea", service="매장에서 먹기", temperature="따뜻하게", side="버터 쿠키"), "음료와 사이드", "사이드 종류 구분"),
    Stage(12, "주스와 초코칩 쿠키", "딸기주스와 초코칩 쿠키를 포장해요.", recipe("juice", side="초코칩 쿠키"), "음료와 사이드", "음료·사이드 주문 확인"),
    Stage(13, "덜 단 아샷추 세트", "큰 아샷추와 초코 머핀을 조합해요.", recipe("peach_tea", size="라지", shot="샷 추가", sweetness="덜 달게", side="초코 머핀"), "복합 주문", "샷·크기·당도·사이드 조합"),
    Stage(14, "달콤한 토핑 세트", "바닐라라떼에 여러 토핑과 쿠키를 더해요.", recipe("vanilla", service="매장에서 먹기", size="벤티", whipped="추가", chocochip="추가", sweetness="달게", side="버터 쿠키"), "복합 주문", "여러 옵션을 빠짐없이 확인"),
    Stage(15, "풀 옵션 주문", "아메리카노에 모든 추가 옵션과 머핀을 담아요.", recipe("americano", size="벤티", shot="샷 2번 추가", whipped="추가", chocochip="추가", sweetness="달게", side="초코 머핀"), "복합 주문", "전체 옵션과 사이드 종합"),
    Stage(16, "완전 랜덤 실전", "음료·이용 방식·온도·모든 옵션·사이드를 매번 새로 뽑아요.", {}, "최고 난이도", "모든 주문 조건 무작위", randomized=True),
)


def random_recipe(rng, previous=None):
    """유효한 모든 조합에서 뽑는다. 직전 주문과 같은 경우에도 반드시 달라진다."""
    menu = rng.choice(tuple(MENUS))
    result = {"service": rng.choice(("매장에서 먹기", "가져가기")),
              "menu": menu, "temperature": rng.choice(MENUS[menu][2]),
              **{key: rng.choice(spec[1]) for key, spec in OPTION_SPECS.items()}}
    if result == previous:
        # 재추첨 반복에 의존하지 않고 온전한 무작위 조합 하나를 확실히 바꾼다.
        result["service"] = "가져가기" if result["service"] == "매장에서 먹기" else "매장에서 먹기"
    return result


def describe_order(order):
    """화면·음성 모두 같은 목표를 읽도록 모든 필드를 명시한다."""
    temperature = "아이스" if order["temperature"] == "차갑게" else "따뜻한"
    options = ", ".join(f"{FIELD_LABELS[key]}: {order.get(key, DEFAULT_OPTIONS[key])}" for key in OPTION_SPECS)
    side_count = "" if order.get("side", "없음") == "없음" else " 1개"
    return f"{temperature} {MENUS[order['menu']][0]} 1잔, {order['service']}. {options}{side_count}."


def get_stage(stage_id):
    for stage in STAGES:
        if str(stage.id) == stage_id:
            return stage
    raise ValueError(f"1~{len(STAGES)} 중 학습 스테이지를 선택해 주세요.")
