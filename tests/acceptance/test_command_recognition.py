"""Step definitions binding command_recognition.feature to EasySpeak.

The misunderstanding flow lives in route_command: a soft apology on the first
miss, an escalation to the command list on the next, then no more help until a
command succeeds. These steps drive route_command with stub plugins and read
the spoken replies back off the stubbed speech pipeline.
"""

from contextlib import ExitStack
from unittest.mock import Mock, patch

import pytest
from easyspeak.core.config import MISUNDERSTAND_GRACE
from easyspeak.core.main import EasySpeak
from easyspeak.core.tray import TrayAction
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/command_recognition.feature")


def _live_proc():
    """A subprocess mock that reports itself as still running."""
    proc = Mock()
    proc.poll.return_value = None
    return proc


class _StubPlugins:
    """A minimal plugin that understands only "open files" and "help".

    Mirrors the real base plugin: handling "help" displays the command list,
    so a successful "help" both resets the streak and shows help — exactly the
    behaviour the feature pins down. ``show_help`` is the single place the list
    is "shown", whether reached via the help command or core's escalation.
    """

    NAME = "stub"

    def __init__(self):
        self.help_shown_count = 0

    def handle(self, cmd, core):
        if cmd == "open files":
            return True
        if cmd == "help":
            self.show_help(core)
            return True
        return None  # anything else is not understood

    def show_help(self, core):
        self.help_shown_count += 1
        core.speak("Check the terminal for available commands.")


@pytest.fixture
def ctx():
    """Patch the subprocess boundary and a controllable clock, and carry
    per-scenario state between steps. The clock lets a step place an utterance
    inside or outside the misunderstanding grace window deterministically."""
    state = {"clock": [1000.0]}
    with patch("subprocess.Popen") as popen, ExitStack() as stack:
        stack.enter_context(patch("time.time", side_effect=lambda: state["clock"][0]))
        state["popen"] = popen
        state["stack"] = stack
        yield state


@given('a fresh EasySpeak that understands only "help" and "open files"')
def fresh_easyspeak(ctx):
    player, piper = _live_proc(), _live_proc()
    ctx["popen"].side_effect = [player, piper]
    ctx["easy"] = EasySpeak()
    ctx["piper"] = piper
    ctx["plugin"] = _StubPlugins()
    ctx["easy"].plugins = [ctx["plugin"]]


def _route(ctx, phrase):
    """Route one deliberate utterance, mirroring the loop's per-iteration reset
    of keep_listening so each turn's assertion reflects only this command."""
    ctx["easy"].keep_listening = False
    ctx["easy"].route_command(phrase)


@when(parsers.parse('I say "{phrase}"'))
def say_phrase(ctx, phrase):
    ctx["clock"][0] += MISUNDERSTAND_GRACE + 1  # a deliberate, spaced-out utterance
    _route(ctx, phrase)


@when(parsers.parse('the mic mishears "{phrase}" a moment later'))
def mic_mishears(ctx, phrase):
    ctx["clock"][0] += 1.0  # an immediate echo, inside the grace window
    _route(ctx, phrase)


@when("the wake word fires and EasySpeak hears one unrecognised command")
def run_one_unrecognised_command(ctx):
    """Drive the real run() loop through a single wake → unrecognised command.

    The model/audio layer is stubbed so the loop exercises its own
    orchestration: wake fires once, one gibberish transcript is heard, then a
    KeyboardInterrupt ends the loop. route_command stays real, so the soft
    apology and the post-miss drain happen exactly as in production.
    """
    easy = ctx["easy"]
    easy.speech = Mock()  # count drains; speak becomes a no-op
    easy.tray = Mock()
    easy.tray.poll.return_value = TrayAction.CONTINUE

    # Keep only the stub plugin (skip the real plugin scan) and short-circuit
    # the audio helpers so nothing touches a real mic.
    easy.load_plugins = Mock()
    easy.wait_for_speech = Mock(return_value=b"heard-something")
    easy.record_until_silence = Mock(return_value=b"")
    easy.transcribe = Mock(return_value="flibbertigibbet")
    easy.flush_stream = Mock()  # don't consume the scripted stream reads

    stream = Mock()
    pcm = b"\x00\x00" * 1280
    stream.read.side_effect = [pcm, KeyboardInterrupt()]  # wake once, then stop

    stack = ctx["stack"]
    stack.enter_context(patch("easyspeak.core.main.load_whisper_model"))
    stack.enter_context(patch("easyspeak.core.main.ensure_extension"))
    stack.enter_context(patch("subprocess.run"))  # silence the wake beep
    pyaudio = stack.enter_context(patch("easyspeak.core.main.pyaudio"))
    pyaudio.PyAudio.return_value.open.return_value = stream
    wake = stack.enter_context(patch("easyspeak.core.main.WakeWordModel"))
    wake.return_value.predict.return_value = 0.9  # above threshold

    easy.run()


def _spoken(ctx):
    """Every phrase handed to piper this scenario, in order, decoded."""
    return [
        call.args[0].decode().strip()
        for call in ctx["piper"].stdin.write.call_args_list
    ]


@then(parsers.parse('EasySpeak says "{reply}"'))
def easyspeak_says(ctx, reply):
    assert reply in _spoken(ctx)


@then(parsers.parse('EasySpeak\'s last reply is "{reply}"'))
def easyspeak_last_reply(ctx, reply):
    assert _spoken(ctx)[-1] == reply


@then(parsers.parse('EasySpeak said "{reply}" only once'))
def easyspeak_said_only_once(ctx, reply):
    assert _spoken(ctx).count(reply) == 1


@then("the command list is not shown")
def command_list_not_shown(ctx):
    assert ctx["plugin"].help_shown_count == 0


@then("the command list is shown")
def command_list_shown(ctx):
    assert ctx["plugin"].help_shown_count >= 1


@then("the command list is shown exactly once")
def command_list_shown_once(ctx):
    assert ctx["plugin"].help_shown_count == 1


@then("EasySpeak keeps listening for another command")
def easyspeak_keeps_listening(ctx):
    assert ctx["easy"].keep_listening is True


@then("EasySpeak drains its speech before listening again")
def drains_before_listening(ctx):
    # Drained twice: once right after the misunderstanding (so its still-playing
    # apology can't be misheard into the next escalation), once on shutdown.
    # Without the fix only the shutdown drain happens (call_count == 1).
    assert ctx["easy"].speech.drain.call_count == 2
