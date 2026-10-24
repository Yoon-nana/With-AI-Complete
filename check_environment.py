"""문제 발생 시 Thonny에서 이 파일을 실행해 현재 환경을 확인하세요.

검사만 수행합니다. 패키지 설치나 실제 로보독 연결은 하지 않습니다.
"""
import importlib.util
import importlib
import inspect
from pathlib import Path
import sys


def main():
    base = Path(__file__).resolve().parent
    print("Python 실행 파일:", sys.executable)
    print("Python 버전:", sys.version)
    print("프로젝트 폴더:", base)
    print("가상환경 사용:", sys.prefix != sys.base_prefix)
    for module in ("tkinter", "kocoafab_robodog"):
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        print(module + ":", "찾음" if present else "찾지 못함")
    for name in ("main.py", "kiosk.py", "core.py", "guidance.py",
                 "robot_controller.py", "curriculum.py", "reactions.py", "data/guidance.json"):
        print(name + ":", "있음" if (base / name).is_file() else "없음")
    print("tkinter '찾음'은 창 생성 성공까지 보장하지는 않습니다.")
    print("로보독 라이브러리가 없어도 모의 모드는 사용할 수 있습니다.")
    if importlib.util.find_spec("kocoafab_robodog") is not None:
        try:
            api = importlib.import_module("kocoafab_robodog")
            print("설치된 로보독 라이브러리:", getattr(api, "__file__", "경로 확인 불가"))
            print("sound 함수 정의:", inspect.signature(api.RoboDog.sound))
            for name in ("멍멍", "안녕", "개소리", "중간", "GREETING", "STRETCH", "STANDUP", "초롱초롱", "ILOVEU"):
                print(name + " 상수:", "있음" if hasattr(api, name) else "없음")
        except Exception as error:
            print("API 검사 오류:", error)
    print("제공된 문서의 sound()는 내장 사운드 재생용이며 임의 문장 TTS 기능은 확인되지 않았습니다.")
    print("주문 안내 멘트는 PC 한국어 음성을 사용하고, 로보독은 효과음과 애교로 반응합니다.")


if __name__ == "__main__":
    main()
