"""Tests for the core.instance module (one EasySpeak per desktop session)."""

from pathlib import Path

from easyspeak.core import instance
from easyspeak.core.control import COMMAND_PRESENT, COMMAND_PRESENT_VERBOSE


def test_acquire_takes_the_lock_once():
    """The first copy gets the lock; another one asking while it's held doesn't."""
    first = instance.acquire()

    assert first is not None
    assert instance.acquire() is None
    first.close()


def test_acquire_after_the_running_copy_ended():
    """Once the copy holding the lock is gone, the next one gets it."""
    instance.acquire().close()

    second = instance.acquire()

    assert second is not None
    second.close()


def test_acquire_creates_the_lock_directory(tmp_path, monkeypatch):
    """Without a runtime directory the lock goes to a cache directory not made yet."""
    monkeypatch.setattr(instance, "LOCK_FILE", tmp_path / "cache" / "easyspeak.lock")

    lock = instance.acquire()

    assert lock is not None
    lock.close()


def test_present_asks_the_running_copy_to_greet():
    """A plain second launch writes the present command for the running copy."""
    instance.present()

    assert instance.CONTROL_FILE.read_text() == COMMAND_PRESENT


def test_present_never_shows_a_half_written_request(monkeypatch):
    """The request appears under the control file's name only once complete,
    and nothing is left beside it."""
    written = []
    real_write = Path.write_text

    def write_text(path, text):
        written.append(path)
        return real_write(path, text)

    monkeypatch.setattr(Path, "write_text", write_text)

    instance.present()

    assert len(written) == 1
    assert written[0] != instance.CONTROL_FILE
    assert instance.CONTROL_FILE.read_text() == COMMAND_PRESENT
    assert list(instance.CONTROL_FILE.parent.iterdir()) == [instance.CONTROL_FILE]


def test_present_verbose_asks_for_details(tmp_path, monkeypatch):
    """A second launch with `-v` asks for the details, too."""
    monkeypatch.setattr(instance, "CONTROL_FILE", tmp_path / "cache" / "control")

    instance.present(verbose=True)

    assert instance.CONTROL_FILE.read_text() == COMMAND_PRESENT_VERBOSE
