import json
import logging
from core import SCREENS

DEFAULT = {"intro": "화면의 버튼을 천천히 골라 주세요.",
           "hint": "선택한 뒤 다음 버튼을 눌러 주세요.",
           "steps": ["원하는 항목을 골라 주세요.", "다음을 눌러 주세요."]}


def load_guidance(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("안내 데이터는 객체여야 합니다.")
    except (OSError, ValueError):
        logging.exception("안내 데이터 읽기 실패. 기본 문구를 사용합니다.")
        data = {}
    result = {}
    for screen in SCREENS:
        item = data.get(screen, {})
        if not isinstance(item, dict):
            item = {}
        valid = {}
        for key, fallback in DEFAULT.items():
            value = item.get(key)
            ok = (isinstance(value, list) and bool(value)
                  and all(isinstance(s, str) and s.strip() for s in value)) if key == "steps" else isinstance(value, str) and bool(value.strip())
            if not ok:
                logging.warning("안내 문구 누락/오류: %s.%s", screen, key)
            valid[key] = value if ok else fallback
        result[screen] = valid
    return result
