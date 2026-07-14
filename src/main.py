import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from src.ui.app import PipManagerApp


def main():
    root = tk.Tk()
    PipManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
