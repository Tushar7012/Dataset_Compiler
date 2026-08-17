import sys

import pytest

from tuneforge.settings import _default_data_dir


def test_default_data_dir_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    assert str(_default_data_dir()).endswith("TuneForge")
    assert "AppData" in str(_default_data_dir())


def test_default_data_dir_on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", "/Users/test")
    result = _default_data_dir()
    assert "Library" in str(result)
    assert result.name == "TuneForge"


def test_default_data_dir_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/test")
    result = _default_data_dir()
    assert ".local/share" in str(result).replace("\\", "/")
    assert result.name == "TuneForge"


def test_default_data_dir_on_linux_respects_xdg_data_home(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/test/.customdata")
    result = _default_data_dir()
    assert str(result) == str(__import__("pathlib").Path("/home/test/.customdata/TuneForge"))
