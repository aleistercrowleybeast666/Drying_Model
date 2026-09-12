"""Compatibility import for the final single-page GUI."""
from judge_gui import main


def __getattr__(name):
    if name == "MainWindow":
        from .judge_window import JudgeWindow
        return JudgeWindow
    raise AttributeError(name)
