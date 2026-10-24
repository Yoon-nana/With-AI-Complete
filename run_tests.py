"""Thonny에서 이 파일을 열어 F5를 누르면 자동 테스트를 실행합니다."""
from pathlib import Path
import sys
import unittest


def main():
    base = Path(__file__).resolve().parent
    # Thonny의 현재 작업 폴더가 달라도 테스트를 찾는다.
    tests = unittest.defaultTestLoader.discover(str(base / "tests"), top_level_dir=str(base / "tests"))
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(tests)
    print("\n결과:", "통과" if result.wasSuccessful() else "실패")
    print("GUI 테스트 건너뜀:", len(result.skipped))
    return result.wasSuccessful()


if __name__ == "__main__":
    if not main():
        raise SystemExit(1)
