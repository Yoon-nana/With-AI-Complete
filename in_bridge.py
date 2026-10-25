"""HTML entry-point helper. Existing main.py remains available for Thonny."""
import logging
from pathlib import Path
from robot_controller import RobotWorker, MockRobotController
from web_kiosk import LocalKioskServer

def main():
    logging.basicConfig(level=logging.INFO)
    worker=RobotWorker(MockRobotController())
    server=None
    try:
        server=LocalKioskServer(worker,base=Path(__file__).resolve().parent,port=8766)
        server.start()
        while not server.model.shutdown_requested.wait(.25):pass
    except KeyboardInterrupt:pass
    finally:
        worker.stop();worker.thread.join(timeout=5)
        if server is not None:server.close()
if __name__=='__main__':main()
