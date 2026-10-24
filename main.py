"""Thonny에서 이 파일을 열고 F5 또는 실행 버튼을 누르세요.

로보독이 없어도 '모의 모드'로 전체 주문 과정을 연습할 수 있습니다.
PC의 일반 Python으로 실행합니다. MicroPython 보드에 업로드하지 않습니다.
"""
import logging
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox

from web_kiosk import BrowserApp as App
from robot_controller import MockRobotController, RobotController, RobotWorker

# 실제 연결할 때 매번 입력하기 번거롭다면 여기만 바꿀 수 있습니다.
DEFAULT_PORT = "COM4"  # 로보독 동글


def make_controller(mode, port="", sound_enabled=True, gestures_enabled=True):
    """설정 화면의 값을 검사하고 컨트롤러를 준비한다. 연결은 워커가 수행한다."""
    if mode == "mock":
        return MockRobotController(sound_enabled=sound_enabled, gestures_enabled=gestures_enabled)
    if mode != "real":
        raise ValueError("모의 모드 또는 실제 로보독 연결을 선택해 주세요.")
    port = port.strip()
    if len(port) > 128 or any(char.isspace() for char in port):
        raise ValueError("시리얼 포트를 확인해 주세요. 예: COM3")
    return RobotController(port or None, sound_enabled=sound_enabled, gestures_enabled=gestures_enabled)


class Launcher:
    """명령줄 인자 대신 시작 화면에서 연결 모드를 고른다."""

    def __init__(self, root):
        self.root = root
        self.worker = None
        self.app = None
        self.root.title("로보독 도우미 · 연결 설정")
        self.root.geometry("780x680")
        self.root.minsize(700, 620)
        self.root.configure(bg="#f3f6fa")
        self.root.option_add("*Font", ("맑은 고딕", 16))
        self.frame = tk.Frame(root, bg="#f3f6fa", padx=28, pady=20)
        self.frame.pack(fill="both", expand=True)
        tk.Label(self.frame, text="로보독 · 주문 연습 / 복약 / 안부 확인", bg="#f3f6fa",
                 font=("맑은 고딕", 24, "bold")).pack(pady=(0, 16))
        tk.Label(self.frame, text="사용할 연결 방식을 선택해 주세요.", bg="#f3f6fa").pack(anchor="w")
        self.mode = tk.StringVar(value="mock")
        self.port = tk.StringVar(value=DEFAULT_PORT)
        for value, text in (("mock", "모의 모드 · 로보독 없이 연습"),
                            ("real", "실제 로보독 연결 · 효과음 / LED / 무작위 애교")):
            tk.Radiobutton(self.frame, text=text, variable=self.mode, value=value,
                           command=self.update_port_state, bg="#f3f6fa",
                           anchor="w", padx=12, pady=10).pack(fill="x")
        tk.Label(self.frame, text="로보독 포트 (COM4 / 빈칸이면 자동 탐색)",
                 bg="#f3f6fa").pack(anchor="w", pady=(12, 4))
        self.port_entry = tk.Entry(self.frame, textvariable=self.port)
        self.port_entry.pack(fill="x", ipady=8)
        self.sound_enabled = tk.BooleanVar(value=True)
        self.gestures_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(self.frame, text="로보독 내장 소리 사용", variable=self.sound_enabled,
                       bg="#f3f6fa").pack(anchor="w", pady=(10, 0))
        tk.Checkbutton(self.frame, text="화면 조건 충족 시 무작위 몸 애교 사용 (한 번에 1종)", variable=self.gestures_enabled,
                       bg="#f3f6fa").pack(anchor="w")
        tk.Label(self.frame, text="연결에 실패해도 모의 모드로 주문 연습을 계속할 수 있어요.",
                 bg="#f3f6fa", wraplength=650, justify="left").pack(anchor="w", pady=14)
        self.start_button = tk.Button(self.frame, text="기능 선택 열기 · 브라우저", command=self.start,
                                      bg="#ffffff", fg="#142c48", padx=20, pady=12)
        self.start_button.pack(fill="x", pady=6)
        self.start_button.bind("<Return>", lambda event: self.start_button.invoke())
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.update_port_state()
        self.start_button.focus_set()

    def update_port_state(self):
        self.port_entry.config(state="normal" if self.mode.get() == "real" else "disabled")

    def start(self):
        if self.worker is not None:
            return  # 연속 클릭으로 워커/연결이 중복 생성되지 않게 한다.
        try:
            controller = make_controller(self.mode.get(), self.port.get(),
                                         self.sound_enabled.get(), self.gestures_enabled.get())
        except ValueError as error:
            messagebox.showerror("연결 설정 확인", str(error), parent=self.root)
            return
        self.start_button.config(state="disabled")
        self.worker = RobotWorker(controller)
        self.frame.destroy()
        try:
            self.app = App(self.root, self.worker)
        except Exception:
            self.worker.stop()
            logging.exception("주문 화면 초기화 실패")
            self.root.destroy()
            raise

    def shutdown(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.thread.join(timeout=3)


def main():
    # Thonny가 전달하는 실행 인자에 의존하지 않는다.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("로보독 도우미 · Thonny 실행 버전")
    print("사용 중인 Python:", sys.executable)
    print("프로젝트 폴더:", Path(__file__).resolve().parent)
    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise SystemExit("주문 창을 열 수 없습니다. PC Python의 Tcl/Tk 설치를 확인하세요.\n" + str(error))
    launcher = Launcher(root)
    try:
        root.mainloop()
    finally:
        launcher.shutdown()


if __name__ == "__main__":
    main()
