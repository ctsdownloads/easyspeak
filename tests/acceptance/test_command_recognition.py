"""Step definitions binding command_recognition.feature to EasySpeak.

The misunderstanding flow lives in route_command: a soft apology on the first
miss, an escalation to the command list on the next, then no more help until a
command succeeds. These steps drive route_command with stub plugins and read
the spoken replies back off the stubbed speech pipeline.
"""

import re
from contextlib import ExitStack
from unittest import mock
from unittest.mock import Mock, patch

import pytest
from easyspeak.core.config import FOLLOWUP_IDLE_ROUNDS, MISUNDERSTAND_GRACE
from easyspeak.core.main import EasySpeak
from easyspeak.core.tray import STATE_MUTED
from easyspeak.plugins import sleep
from pytest_bdd import given, parsers, scenarios, then, when

scenarios(
    "features/command_recognition.feature",
    "features/follow_up_listening.feature",
)


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
        self.handled = []

    def handle(self, cmd, core):
        if cmd == "open files":
            self.handled.append(cmd)
            core.speak("Opening files.")
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
    # The real tray controller, with its channels stubbed: nothing is clicked
    # in the menu, and the indicator is there, so a sleep can engage.
    ctx["easy"].tray.take_command = Mock(return_value=None)
    ctx["easy"].tray.set_state = Mock(return_value=True)


@given("the sleep plugin is loaded as well")
def with_sleep_plugin(ctx):
    ctx["easy"].plugins.append(sleep)


def _route(ctx, phrase):
    """Route one deliberate utterance straight through route_command."""
    ctx["easy"].route_command(phrase)


@when(parsers.parse('I say "{phrase}"'))
def say_phrase(ctx, phrase):
    ctx["clock"][0] += MISUNDERSTAND_GRACE + 1  # a deliberate, spaced-out utterance
    _route(ctx, phrase)


@when(parsers.parse('the mic mishears "{phrase}" a moment later'))
def mic_mishears(ctx, phrase):
    ctx["clock"][0] += 1.0  # an immediate echo, inside the grace window
    _route(ctx, phrase)


def _run_session(ctx, transcripts):
    """Drive the real run() loop through one wake and the scripted utterances.

    The model/audio layer is stubbed so the loop exercises its own
    orchestration: the wake word fires once, each transcript in `transcripts`
    is heard in turn (None is a silent listen), then a KeyboardInterrupt on the
    next wake-word read ends the run. route_command and the session loop stay
    real, so replies, misses and drains happen exactly as in production. A
    session that ends early leaves utterances unheard, and one that never ends
    runs out of script, so either failure shows.
    """
    easy = ctx["easy"]
    # One parent records the speech and stream calls in order, so a step can
    # tell what was drained or released before what. speak becomes a no-op.
    ctx["boundary"] = boundary = Mock()
    easy.speech = boundary.speech

    # Keep the scenario's plugins (skip the real plugin scan) and short-circuit
    # the audio helpers so nothing touches a real mic.
    easy.load_plugins = Mock()
    # Startup samples the room to set the silence threshold, which would eat the
    # scripted stream reads below before the wake word ever fires.
    easy.calibrate_silence = Mock()
    heard = [None if text is None else b"heard-something" for text in transcripts]
    easy.wait_for_speech = Mock(side_effect=heard)
    easy.record_until_silence = Mock(return_value=b"")
    easy.transcribe = Mock(
        side_effect=[text for text in transcripts if text is not None]
    )
    easy.flush_stream = Mock()  # don't consume the scripted stream reads

    stream = boundary.stream
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


@when("the wake word fires and EasySpeak hears one unrecognised command")
def run_one_unrecognised_command(ctx):
    _run_session(ctx, ["flibbertigibbet", None, None])


@when(parsers.re(r"the wake word fires and I say (?P<said>.+), then fall silent"))
def run_scripted_session(ctx, said):
    """Each quoted utterance is heard in turn, then the mic hears nothing until
    the session gives up, however long that takes."""
    utterances = re.findall(r'"([^"]*)"', said)
    _run_session(ctx, [*utterances, *([None] * FOLLOWUP_IDLE_ROUNDS)])


@when(
    parsers.parse(
        'the wake word fires and I say "{phrase}", then EasySpeak is reactivated '
        "from the tray"
    )
)
def run_then_reactivate(ctx, phrase):
    """The phrase is heard once; the tray's idle loop then finds the reactivation
    on its first read. A session that kept listening after the phrase would run
    out of script instead."""
    tray = ctx["easy"].tray
    tray.take_command = Mock(
        side_effect=lambda: (
            "unmute"
            if mock.call(STATE_MUTED) in tray.set_state.call_args_list
            else None
        )
    )
    _run_session(ctx, [phrase])


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


@then("EasySpeak drains its speech before listening again")
def drains_before_listening(ctx):
    # Drained twice: once right after the misunderstanding (so its still-playing
    # apology can't be misheard into the next escalation), once on shutdown.
    # Without the fix only the shutdown drain happens (call_count == 1).
    assert ctx["easy"].speech.drain.call_count == 2


@then("both commands are carried out on the one wake word")
def both_commands_carried_out(ctx):
    assert ctx["plugin"].handled == ["open files", "open files"]


@then('"open files" is carried out on the one wake word')
def open_files_carried_out(ctx):
    assert ctx["plugin"].handled == ["open files"]


@then("each reply is drained before the next listen")
def each_reply_drained(ctx):
    # One drain per reply, plus the one on shutdown.
    assert ctx["easy"].speech.drain.call_count == len(ctx["plugin"].handled) + 1


@then("the apology is drained before the next listen")
def apology_drained(ctx):
    # The apology, the reply to "open files", and the shutdown drain.
    assert ctx["easy"].speech.drain.call_count == 3


@then("EasySpeak listens twice more, then waits for the wake word again")
def listens_twice_more(ctx):
    # The command, then FOLLOWUP_IDLE_ROUNDS silent listens; the run ended on the
    # wake-word read that followed, so the session did give the mic back.
    assert ctx["easy"].wait_for_speech.call_count == 1 + FOLLOWUP_IDLE_ROUNDS


@then("the mic is released before EasySpeak listens again")
def mic_released_before_next_listen(ctx):
    easy = ctx["easy"]
    assert easy.wait_for_speech.call_count == 1
    easy.tray.set_state.assert_any_call(STATE_MUTED)
    # Released for the sleep and reopened on reactivation, then closed on exit.
    assert ctx["boundary"].stream.close.call_count == 2


@then("the confirmation is drained before the mic is released")
def confirmation_drained_before_release(ctx):
    boundary = ctx["boundary"]
    assert (
        mock.call("Voice control turned off.") in boundary.speech.speak.call_args_list
    )
    lifecycle = [
        c for c in boundary.mock_calls if c[0] in ("speech.drain", "stream.close")
    ]
    assert lifecycle[:2] == [mock.call.speech.drain(), mock.call.stream.close()]
