"""Thonny에서 실행하면 현재 코드로 배포 ZIP을 다시 만든다. 외부 패키지 불필요."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def build_zip():
    source = Path(__file__).resolve().parent
    output = source.parent / "로보독_키오스크_복약알림_전체파일.zip"
    temporary = output.with_suffix(".zip.tmp")
    excluded_dirs = {"__pycache__", ".venv", ".git", "node_modules", "qa", "tests"}
    required = (
        "main.py", "core.py", "web_kiosk.py", "curriculum.py", "reactions.py",
        "robot_controller.py", "daywatch_bridge.py", "activity.py", "microbit_link.py",
        "web/exercise.js", "web/exercise.css", "web/nap.js", "web/nap.css",
        "models/manifest.json", "models/checking.hex", "models/exercise.hex",
        "microbit/checking_runtime.ts", "microbit/exercise_runtime.ts", "daywatch/hardware_main.py",
        "daywatch/device_workflow.py", "daywatch/microbit_full.ts", "web/daywatch.css",
        "data/guidance.json", "web/index.html",
        "web/app.js", "web/styles.css",
        "web/readable.css",
        "web/assets/robodog.svg",
        "medication.py", "web/assets/medication-stop.svg",
    )
    for name in required:
        if not (source / name).is_file():
            raise FileNotFoundError(f"필수 파일이 없어요: {name}")
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            for file in sorted(source.rglob("*")):
                relative = file.relative_to(source)
                if not file.is_file() or excluded_dirs.intersection(relative.parts):
                    continue
                if any(part.startswith(".") for part in relative.parts):
                    continue
                if file.suffix in (".zip", ".tmp", ".pyc", ".log"):
                    continue
                # 학습 기록·진도 등 사용 중 생긴 데이터는 배포하지 않는다.
                if relative.parts[0] == "data" and relative.as_posix() != "data/guidance.json":
                    continue
                if relative.parts[:2] == ("daywatch", "data"):
                    continue
                archive.write(file, Path(source.name) / relative)
        with ZipFile(temporary) as archive:
            damaged = archive.testzip()
            if damaged:
                raise OSError(f"압축 검증 실패: {damaged}")
            for name in required:
                if archive.read(f"{source.name}/{name}") != (source / name).read_bytes():
                    raise OSError(f"파일 검증 실패: {name}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


if __name__ == "__main__":
    result = build_zip()
    print(f"ZIP을 만들었어요: {result}")
    print(f"파일 크기: {result.stat().st_size:,} 바이트")
