import logging
import logging.handlers
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("pip_manager")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(formatter)
logger.addHandler(console)

try:
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pip_manager.log")
    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info("Log file: %s", log_path)
except Exception as e:
    logger.warning("Could not setup file logging: %s", e)

import tkinter as tk
from src.ui.app import PipManagerApp


def main():
    root = tk.Tk()
    PipManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
