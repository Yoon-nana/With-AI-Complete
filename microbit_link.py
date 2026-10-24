"""마빗 한 대의 USB 연결과 모드별 HEX 전환. JSON 샘플을 실행 모델로 취급하지 않는다."""
from collections import deque
import importlib
import os
from pathlib import Path
import shutil
import threading
import time


def valid_hex(path):
    if not path.is_file() or not 0 < path.stat().st_size <= 8_000_000:
        return False
    try:
        rows = path.read_text(encoding='ascii').splitlines()
        eof = data_seen = False
        for row in rows:
            if not row.strip():
                continue
            if eof or not row.startswith(':'):
                return False
            data = bytes.fromhex(row[1:])
            if len(data) < 5 or len(data) != data[0]+5 or sum(data) % 256:
                return False
            eof = data[3] == 1
            if data[3] == 0 and data[0] > 0: data_seen = True
        return eof and data_seen
    except (OSError, ValueError, UnicodeError):
        return False


def board_drive(explicit=''):
    if explicit:
        paths = [Path(explicit)]
    elif os.name == 'nt':
        paths = [Path(chr(code)+':/') for code in range(65, 91)]
    else:
        volumes = Path('/Volumes')
        paths = list(volumes.iterdir()) if volumes.is_dir() else []
    matches = []
    for path in paths:
        try:
            details = (path/'DETAILS.TXT').read_text(errors='replace')
            if 'microbit' in details.lower() and 'Unique ID' in details:
                matches.append(path)
        except OSError:
            continue
    if len(matches) != 1:
        raise ValueError('MICROBIT 드라이브 한 개를 연결하거나 설정에서 정확한 드라이브를 지정하세요.')
    return matches[0]


class MonitorChannel:
    """기존 안부 확인 코드에 바이트 수신 인터페이스만 제공한다."""
    def __init__(self, link): self.link = link
    @property
    def in_waiting(self):
        with self.link.lock: return len(self.link.monitor)
    def read(self, count):
        with self.link.lock:
            data = bytes(self.link.monitor[:count]); del self.link.monitor[:count]; return data
    def reset_input_buffer(self):
        with self.link.lock: self.link.monitor.clear()
    def close(self): self.reset_input_buffer()


class MicrobitLink:
    def __init__(self, base, on_counts, clock=time.monotonic):
        self.base, self.on_counts, self.clock = Path(base), on_counts, clock
        self.lock = threading.RLock()
        self.port, self.drive = 'COM6', ''
        self.desired, self.current = 'checking', None
        self.serial = None
        self.buffer, self.monitor = bytearray(), bytearray()
        self.status, self.message = 'WAITING', '마빗 연결 대기'
        self.last_rx = None
        self.next_try = self.probe_until = 0
        self.flash_target = None
        self.flash_deadline = 0
        self.commanded = None
        self.count_boot = 0
        self.checking_warmup = False
        self.channel = MonitorChannel(self)

    def configure(self, port, drive=''):
        if not isinstance(port, str) or not port.strip() or len(port) > 128 or any(c.isspace() for c in port):
            raise ValueError('마빗 USB 포트를 확인하세요.')
        if not isinstance(drive, str) or len(drive) > 512:
            raise ValueError('MICROBIT 드라이브 경로를 확인하세요.')
        if drive:
            board_drive(drive)
        self.close()
        self.port, self.drive = port.strip(), drive
        self.current = self.flash_target = None
        self.next_try = 0

    def select(self, mode):
        if mode not in ('checking', 'exercise', 'nap'):
            raise ValueError('지원하지 않는 마빗 모드')
        with self.lock:
            if self.desired != mode:
                self.checking_warmup = mode == 'checking'
                self.desired, self.commanded = mode, None
                self.monitor.clear()
                self.flash_target = None
                self.flash_deadline = 0

    def snapshot(self):
        with self.lock:
            return {'state': self.status, 'message': self.message, 'requested': self.desired,
                    'loaded': self.current, 'port': self.port, 'drive': self.drive,
                    'fresh': self.last_rx is not None and self.clock()-self.last_rx <= 3,
                    'dataset': '체조-data-samples.json' if self.desired == 'exercise'
                               else 'Checking grandmother-data-samples.json' if self.desired == 'checking' else None}

    def _line(self, line):
        try: parts = line.decode('ascii').strip().split(',')
        except UnicodeError: return
        if parts[:2] == ['BOOT', 'EXERCISE']:
            self.current = 'exercise'; self.count_boot += 1
            self.on_counts(None, self.count_boot)
        elif parts[:2] == ['MODEL', 'EXERCISE']:
            self.current = 'exercise'
        elif parts[:2] == ['MODEL', 'CHECK']:
            self.current = 'checking'
        elif len(parts) == 3 and parts[0] == 'ML' and parts[1] in ('MOVING','STILL','UNKNOWN'):
            try: seconds = int(parts[2])
            except ValueError: return
            if not 0 <= seconds <= 604800: return
            self.current = 'checking'
            if parts[1] == 'MOVING' or parts[1] == 'STILL' and seconds <= 20:
                self.checking_warmup = False
        elif len(parts) == 4 and parts[0] == 'EX':
            try: counts = tuple(int(x) for x in parts[1:])
            except ValueError: return
            if not all(0 <= x <= 2**31-1 for x in counts): return
            self.current = 'exercise'
            if self.desired == 'exercise': self.on_counts(counts, self.count_boot)
        else: return
        self.last_rx = self.clock()
        if parts[:1] == ['ML'] and self.desired == 'checking' and self.current == 'checking' and not self.checking_warmup:
            with self.lock:
                if len(self.monitor) < 4096: self.monitor.extend(line+b'\n')

    def tick(self, enabled):
        if not enabled:
            self.close(); self.status, self.message = 'MOCK', '모의 연결 · 실제 마빗 입력을 기다리지 않습니다.'
            return
        now = self.clock()
        try:
            if self.serial is None:
                if now < self.next_try: return
                self.serial = importlib.import_module('serial').Serial(self.port,115200,timeout=0)
                self.probe_until = now+2
                self.commanded = None
            count = min(self.serial.in_waiting,4096)
            if count: self.buffer.extend(self.serial.read(count))
            while b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n'); self.buffer = bytearray(rest)
                if len(line) <= 100: self._line(bytes(line))
            if len(self.buffer) > 4096: self.buffer.clear()
            target = self.current if self.desired == 'nap' else self.desired
            if target and self.current == target:
                command = 'MODE,'+{'checking':'CHECK','exercise':'EXERCISE','nap':'NAP'}[self.desired]
                if self.commanded != command:
                    self.serial.write((command+'\n').encode('ascii')); self.commanded = command
                    if self.desired == 'checking':
                        self.monitor.clear()
                fresh = self.last_rx is not None and now-self.last_rx <= 3
                self.status = 'READY' if fresh else 'NO_SIGNAL'
                self.message = '낮잠 중 · 위험 판단을 쉬고 있습니다.' if self.desired == 'nap' else '선택한 모델의 마빗 신호 수신 중' if fresh else '마빗 수신이 끊겼습니다.'
                if fresh: self.flash_target = None
                return
            if self.desired == 'nap':
                if self.commanded != 'MODE,NAP':
                    self.serial.write(b'MODE,NAP\n'); self.commanded = 'MODE,NAP'
                self.status, self.message = 'NAP', '낮잠 중 · 마빗 판단을 사용하지 않습니다.'
                return
            if now < self.probe_until: return
            if self.flash_target == self.desired:
                self.status = 'RECONNECTING'
                self.message = '모델을 내려보냈습니다. 마빗 재연결과 모델 응답을 기다립니다.'
                if now > self.flash_deadline:
                    self.status, self.message = 'MODEL_MISMATCH', '내려보낸 모델의 응답이 없습니다. 학습 HEX와 COM 포트를 확인하세요.'
                return
            firmware = self.base/'models'/('exercise.hex' if self.desired == 'exercise' else 'checking.hex')
            if not valid_hex(firmware):
                self.status, self.message = 'NEEDS_FIRMWARE', f'{firmware.name} 학습 HEX가 필요합니다. JSON은 학습 샘플이며 실행 모델이 아닙니다.'
                return
            drive = board_drive(self.drive)
            self.close()
            shutil.copyfile(firmware, drive/'AIGO.hex')
            self.flash_target, self.flash_deadline = self.desired, now+25
            self.current, self.next_try = None, now+3
            self.status, self.message = 'FLASHING', '선택한 학습 모델을 마빗에 자동으로 내려보내고 있습니다.'
        except (OSError, ValueError, ImportError) as error:
            self.close(); self.next_try = now+3
            self.status, self.message = 'ERROR', str(error)

    def close(self):
        if self.serial is not None:
            try: self.serial.close()
            finally: self.serial = None
        self.buffer.clear()
