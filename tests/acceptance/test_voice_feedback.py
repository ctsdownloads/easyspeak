"""Step definitions binding voice_feedback.feature to EasySpeak's behaviour."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.core.main import EasySpeak
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/voice_feedback.feature")


def _live_proc():
    """A subprocess mock that reports itself as still running."""
    proc = Mock()
    proc.poll.return_value = None
    return proc


@pytest.fixture
def speech():
    """Patch the subprocess boundary and carry per-scenario state between steps."""
    with patch("subprocess.Popen") as popen:
        yield {"popen": popen}


@given("a fresh EasySpeak with a stubbed speech pipeline")
def fresh_easyspeak(speech):
    player, piper = _live_proc(), _live_proc()
    speech["popen"].side_effect = [player, piper]
    speech["easy"] = EasySpeak()
    speech["player"], speech["piper"] = player, piper


@given("a fresh EasySpeak whose speech pipeline fails once then recovers")
def flaky_easyspeak(speech):
    player1, broken = _live_proc(), _live_proc()
    broken.stdin.write.side_effect = BrokenPipeError()
    player2, healthy = _live_proc(), _live_proc()
    speech["popen"].side_effect = [player1, broken, player2, healthy]
    speech["easy"] = EasySpeak()
    speech["healthy"] = healthy


@given(parsers.parse('I have spoken "{phrase}"'))
@when(parsers.parse('I speak "{phrase}"'))
def speak_phrase(speech, phrase):
    speech["last_phrase"] = phrase
    speech["easy"].speak(phrase)


@when("the app drains speech on shutdown")
def drain_on_shutdown(speech):
    speech["easy"]._drain_speech()


@then("the voice model is loaded only once")
def model_loaded_once(speech):
    # One pipeline build == one player + one piper spawn; reuse spawns nothing.
    assert speech["popen"].call_count == 2


@then("both phrases are sent to the speech pipeline")
def both_phrases_sent(speech):
    assert speech["piper"].stdin.write.call_count == 2


@then("no speech pipeline is started")
def no_pipeline_started(speech):
    speech["popen"].assert_not_called()


@then("the pending phrase is flushed and played to completion")
def pending_phrase_flushed(speech):
    piper, player = speech["piper"], speech["player"]
    piper.stdin.close.assert_called_once()  # flush the queued phrase to piper
    piper.wait.assert_called_once()  # wait for synthesis to finish
    player.wait.assert_called_once()  # and for playback to drain


@then("the phrase is delivered after the pipeline is rebuilt")
def delivered_after_rebuild(speech):
    expected = (speech["last_phrase"] + "\n").encode()
    speech["healthy"].stdin.write.assert_called_once_with(expected)
