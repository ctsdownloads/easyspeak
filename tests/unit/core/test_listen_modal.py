"""Tests for the modal-mode listening loop shared by the plugins.

`listen_modal` replaces the private `while` loop each modal plugin (grid, browser,
dictation, head tracking) used to run. The boilerplate those loops duplicated —
flush, wait, record, transcribe — is covered once here, along with the three things
they never did: polling the tray so sleep and quit keep working, ending the mode
after a spell with no recognised command, and discarding Whisper's echo of its own
prompt.
"""

from contextlib import contextmanager
from itertools import chain, count, repeat
from unittest.mock import Mock, patch

import conftest
import numpy as np
import pytest
from easyspeak.core import main
from easyspeak.core.main import EasySpeak
from easyspeak.core.tray import TrayAction


@pytest.fixture
def easy():
    """An EasySpeak whose tray, stream, and speech are stubbed out."""
    daemon = EasySpeak()
    daemon.tray = Mock()
    daemon.tray.poll = Mock(return_value=TrayAction.CONTINUE)
    daemon.speech = Mock()
    daemon.stream = Mock()
    daemon.stream.get_read_available = Mock(return_value=0)
    daemon.record_until_silence = Mock(return_value=b"tail")
    return daemon


def drive(daemon, heard, transcriptions):
    """Point the daemon at canned listens, then an endless quiet room.

    Both sequences are padded so a test never ends the mode by exhausting a mock —
    the clock ends it, the way it does in the field.
    """
    daemon.wait_for_speech = Mock(side_effect=chain(heard, repeat(None)))
    daemon.transcribe = Mock(side_effect=chain(transcriptions, repeat("")))


@contextmanager
def clock(step=5):
    """Run with a monotonic clock that advances `step` seconds per reading."""
    with patch("easyspeak.core.main.time.monotonic", side_effect=count(0, step)):
        yield


class TestYieldedCommands:
    """What the generator hands back to the plugin."""

    def test_yields_normalised_commands(self, easy):
        """Commands arrive stripped of surrounding punctuation, case kept."""
        drive(easy, [b"a", b"b"], ["Close!", "  Grid?  "])

        with clock():
            assert list(easy.listen_modal("grid")) == ["Close", "Grid"]

    def test_skips_empty_transcriptions(self, easy):
        """An unrecognised utterance is dropped without ending the mode."""
        drive(easy, [b"a", b"b"], ["", "click"])

        with clock():
            assert list(easy.listen_modal("grid")) == ["click"]

    def test_passes_prompt_to_transcribe(self, easy):
        """The mode's vocabulary prompt reaches Whisper."""
        drive(easy, [b"a"], ["click"])

        with clock():
            list(easy.listen_modal("grid", prompt="click double"))

        assert easy.transcribe.call_args.kwargs["prompt"] == "click double"

    def test_passes_language_to_transcribe(self, easy):
        """A mode dictating in another language hands its code down."""
        drive(easy, [b"a"], ["hallo"])

        with clock():
            list(easy.listen_modal("dictation", language="de"))

        assert easy.transcribe.call_args.kwargs["language"] == "de"

    def test_records_the_tail_of_each_utterance(self, easy):
        """The first chunk is joined with the rest of the utterance."""
        drive(easy, [b"head"], ["click"])

        with clock():
            list(easy.listen_modal("grid"))

        assert easy.transcribe.call_args.args[0] == b"headtail"


class TestIdleTimeout:
    """The mode ends on its own instead of trapping the session."""

    def test_ends_when_the_deadline_passes(self, easy):
        """Silence past the idle timeout ends the mode."""
        drive(easy, [], [])

        with clock():
            assert list(easy.listen_modal("browser", idle_timeout=30)) == []

    def test_announces_the_timeout(self, easy):
        """The user is told the mode ended, and what that changes.

        Commands that worked a moment ago now need the wake word in front of
        them, and "Leaving browser" on its own doesn't tell anyone that.
        """
        drive(easy, [], [])

        with clock():
            list(easy.listen_modal("browser", idle_timeout=30))

        spoken = easy.speech.speak.call_args.args[0]
        assert "Leaving browser" in spoken
        assert main.WAKE_WORD_SPOKEN in spoken

    def test_noise_does_not_extend_the_deadline(self, easy):
        """Sound that transcribes to nothing is not a command, so time still runs.

        This is what the round-based counter got wrong: ambient noise ends each wait
        early and used to reset the count, so the mode never timed out in a room
        with a fan in it.
        """
        drive(easy, [b"hum", b"hum", b"hum"], ["", "", ""])

        with clock(step=20):
            assert list(easy.listen_modal("grid", idle_timeout=30)) == []

    def test_a_command_pushes_the_deadline_back(self, easy):
        """A recognised command keeps the mode open for another full timeout."""
        drive(easy, [b"a"], ["click"])

        with clock(step=20):
            assert list(easy.listen_modal("grid", idle_timeout=30)) == ["click"]

    def test_never_waits_past_the_deadline(self, easy):
        """The last listen is shortened so the mode ends on time."""
        drive(easy, [], [])

        with patch("easyspeak.core.main.time.monotonic", side_effect=[0, 25, 31]):
            list(easy.listen_modal("grid", timeout=10, idle_timeout=30))

        assert easy.wait_for_speech.call_args.kwargs["timeout"] == 5


class TestTrayStaysLive:
    """The tray keeps working while a mode holds the microphone."""

    def test_polls_the_tray_each_round(self, easy):
        """Sleep and quit requests are seen between utterances."""
        drive(easy, [b"a"], ["click"])

        with clock():
            list(easy.listen_modal("grid"))

        assert easy.tray.poll.call_count > 1
        assert easy.tray.poll.call_args.args == (easy._close_stream, easy._open_stream)

    def test_quit_stops_the_mode_and_is_recorded(self, easy):
        """Tray Quit ends the mode and survives the unwind to the main loop."""
        easy.tray.poll = Mock(return_value=TrayAction.QUIT)
        drive(easy, [b"a"], ["click"])

        assert list(easy.listen_modal("grid")) == []
        assert easy.exit_requested is True

    def test_resume_ends_the_mode(self, easy):
        """Waking from sleep returns to the wake word rather than resuming."""
        easy.tray.poll = Mock(side_effect=[TrayAction.RESUME])
        drive(easy, [b"a"], ["click"])

        assert list(easy.listen_modal("grid")) == []
        assert easy.exit_requested is False

    def test_flushes_the_microphone_each_round(self, easy):
        """Buffered audio from the previous command can't leak into the next."""
        drive(easy, [b"a"], ["click"])

        with clock(), patch.object(easy, "flush_stream") as flush:
            list(easy.listen_modal("grid"))

        assert flush.call_count > 1


class TestExitRequestPropagates:
    """A quit taken inside a mode still exits the daemon."""

    def test_command_session_returns_exit(self, easy, mock_plugin):
        """route_command handled the command, but the tray asked to quit."""
        easy.plugins = [mock_plugin]
        easy.wait_for_speech = Mock(return_value=b"a")
        easy.transcribe = Mock(return_value="grid")
        easy.exit_requested = True

        assert easy._capture_command_session() is True


class TestPromptEcho:
    """Whisper hands its own prompt back when given near-silence."""

    GRID = (
        "one two three four five six seven eight nine click double "
        "right scroll nudge up down left right close cancel mark drag"
    )
    DICTATION = (
        "comma, period, new sentence, new paragraph, new line, question mark, "
        "exclamation mark, colon, semicolon, stop notes, backspace, space, tab, "
        "enter, apostrophe, quote, dash, hyphen, at sign, hashtag, percent"
    )

    @pytest.mark.parametrize(
        "text",
        [
            "six seven eight nine click double right scroll",
            "nudge up down left right close cancel mark drag",
            "One two three four five six seven eight nine click.",
        ],
    )
    def test_detects_echo(self, text):
        """A long verbatim run of the prompt is silence, not a command."""
        assert EasySpeak._is_prompt_echo(text, self.GRID) is True

    def test_detects_dictation_echo(self):
        """The dictation prompt echo would otherwise type itself and exit."""
        echo = "stop notes, backspace, space, tab, enter"
        assert EasySpeak._is_prompt_echo(echo, self.DICTATION) is True

    @pytest.mark.parametrize(
        "text",
        [
            "six",
            "three seven five",
            "right click",
            "scroll down 3",
            "close",
            "double click",
            "one two three four",
            "one two three four five six",
        ],
    )
    def test_keeps_real_commands(self, text):
        """Real commands, including long all-digit zone chains, survive."""
        assert EasySpeak._is_prompt_echo(text, self.GRID) is False

    def test_transcribe_drops_the_echo(self, easy):
        """An echoed prompt reaches the plugin as nothing at all."""
        segment = Mock(text="six seven eight nine click double right scroll")
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([segment], None))

        assert easy.transcribe(b"\x00\x00", prompt=self.GRID) == ""

    def test_transcribe_keeps_a_real_command(self, easy):
        """A genuine command is returned unchanged."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([Mock(text=" close ")], None))

        assert easy.transcribe(b"\x00\x00", prompt=self.GRID) == "close"


class TestSoundPlayback:
    """A missing player or sound file must never take the daemon down."""

    def test_plays_with_the_first_working_player(self, easy, tmp_path):
        """The first player that succeeds is the one used."""
        sound = tmp_path / "chime.oga"
        sound.write_text("")

        with patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            assert easy.play_sound(sound) is True

        assert run.call_args.args[0][0] == "paplay"

    def test_falls_through_to_the_next_player(self, easy, tmp_path):
        """A session with pw-play but no paplay still gets its sounds."""
        sound = tmp_path / "chime.oga"
        sound.write_text("")

        def _run(cmd, **_kwargs):
            if cmd[0] == "paplay":
                raise OSError("not installed")
            return Mock(returncode=0)

        with patch("subprocess.run", side_effect=_run):
            assert easy.play_sound(sound) is True

        assert easy._sound_player == ["pw-play"]

    def test_remembers_the_working_player(self, easy, tmp_path):
        """Later sounds cost one process, not a walk through the list."""
        sound = tmp_path / "chime.oga"
        sound.write_text("")
        easy._sound_player = ["pw-play"]

        with patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            easy.play_sound(sound)

        assert run.call_count == 1
        assert run.call_args.args[0][0] == "pw-play"

    def test_a_player_that_fails_is_not_remembered(self, easy, tmp_path):
        """A non-zero exit means try the rest, and don't cache the loser."""
        sound = tmp_path / "chime.oga"
        sound.write_text("")

        with patch("subprocess.run", return_value=Mock(returncode=1)):
            assert easy.play_sound(sound) is False

        assert easy._sound_player is None

    def test_no_player_at_all_is_not_fatal(self, easy, tmp_path):
        """An unguarded paplay used to kill the daemon on the first wake word."""
        sound = tmp_path / "chime.oga"
        sound.write_text("")

        with patch("subprocess.run", side_effect=OSError("nothing installed")):
            assert easy.play_sound(sound) is False

    def test_missing_sound_file_is_not_fatal(self, easy, tmp_path):
        """A desktop without the freedesktop sound theme simply stays quiet."""
        with patch("subprocess.run") as run:
            assert easy.play_sound(tmp_path / "absent.oga") is False

        assert not run.called

    def test_wake_chime_uses_the_guarded_player(self, easy):
        """The wake chime goes through the same crash-proof path."""
        with patch.object(easy, "play_sound") as sound:
            easy._play_wake_chime()

        assert sound.called


class TestTranscription:
    """How audio reaches Whisper, which is most of the wait after speaking."""

    def test_passes_samples_not_a_file(self, easy):
        """Writing a WAV to /tmp for the model to read back was pure latency."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([Mock(text="hello")], None))

        pcm = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
        assert easy.transcribe(pcm) == "hello"

        sent = easy.whisper.transcribe.call_args.args[0]
        assert isinstance(sent, np.ndarray)
        assert sent.dtype == np.float32
        assert sent.max() <= 1.0 and sent.min() >= -1.0

    def test_asks_for_no_timestamps(self, easy):
        """Nothing reads them, and generating them costs tokens."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([], None))

        easy.transcribe(b"\x00\x00")

        assert easy.whisper.transcribe.call_args.kwargs["without_timestamps"] is True

    def test_each_utterance_stands_alone(self, easy):
        """Carrying context grows latency across a session and feeds hallucination."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([], None))

        easy.transcribe(b"\x00\x00")

        kwargs = easy.whisper.transcribe.call_args.kwargs
        assert kwargs["condition_on_previous_text"] is False
        assert kwargs["language"] == "en"

    def test_default_prompt_follows_the_decoding_language(self, easy, monkeypatch):
        """Decoding English, a mode gets the English prompt, not the German one."""
        monkeypatch.setattr(
            "easyspeak.core.main.COMMAND_PROMPTS",
            {"de": "öffne, schließe", "en": "open, close"},
        )
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([], None))

        easy.transcribe(b"\x00\x00", language="en")
        easy.transcribe(b"\x00\x00", language="de")

        prompts = [
            c.kwargs["initial_prompt"] for c in easy.whisper.transcribe.call_args_list
        ]
        assert prompts == ["open, close", "öffne, schließe"]

    def test_modes_transcribe_in_english_by_default(self, easy):
        """A mode's words are English until its vocabulary is migrated."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([], None))

        easy.transcribe(b"\x00\x00")

        assert easy.whisper.transcribe.call_args.kwargs["language"] == "en"

    def test_transcribes_in_the_language_asked_for(self, easy):
        """Dictation speaks the user's language; commands stay English."""
        easy.whisper = Mock()
        easy.whisper.transcribe = Mock(return_value=([], None))

        easy.transcribe(b"\x00\x00", language="de")

        assert easy.whisper.transcribe.call_args.kwargs["language"] == "de"


class TestSpokenReplyFeedback:
    """A mode must not hear its own voice.

    With a Piper voice installed the open microphone picks up every spoken reply,
    transcribes it, and hands it back as the next command. That turned "Sorry, I
    didn't understand." into an endless conversation with itself.
    """

    def test_drains_after_the_plugin_speaks(self, easy):
        """Playback is waited out and the microphone emptied before listening."""
        drive(easy, [b"a"], ["click"])

        with clock(), patch.object(easy, "_drain_feedback") as drain:
            for _command in easy.listen_modal("grid"):
                easy.speak("Sorry, I didn't understand.")

        assert drain.called

    def test_does_not_drain_when_nothing_was_said(self, easy):
        """A silent command costs no extra teardown of the speech pipeline."""
        drive(easy, [b"a"], ["click"])

        with clock(), patch.object(easy, "_drain_feedback") as drain:
            for _command in easy.listen_modal("grid"):
                pass

        assert not drain.called

    def test_clears_the_spoke_flag_between_rounds(self, easy):
        """One reply must not make every later round drain as well."""
        drive(easy, [b"a", b"b"], ["click", "close"])
        spoken_once = []

        with clock(), patch.object(easy, "_drain_feedback") as drain:
            for command in easy.listen_modal("grid"):
                if not spoken_once:
                    easy.speak("Only now.")
                    spoken_once.append(command)

        assert drain.call_count == 1


class TestModeAnnouncement:
    """A mode's own announcement must not land in the first sentence."""

    def test_drains_before_the_first_listen(self, easy):
        """Plugins say "Dictation"/"Browser"/"Grid" just before calling in.

        Without waiting that out, the announcement was still playing when
        recording began and arrived on the front of the first utterance --
        "Dictation search for potatoes".
        """
        drive(easy, [], [])
        easy.spoke = True

        with clock(), patch.object(easy, "_drain_feedback") as drain:
            list(easy.listen_modal("dictation", idle_timeout=30))

        assert drain.called

    def test_no_drain_when_the_mode_started_quietly(self, easy):
        """A mode nobody announced costs no teardown of the speech pipeline."""
        drive(easy, [], [])
        easy.spoke = False

        with clock(), patch.object(easy, "_drain_feedback") as drain:
            list(easy.listen_modal("grid", idle_timeout=30))

        assert not drain.called


class TestRecordingLimits:
    """A dictated sentence needs different limits from a spoken command."""

    @pytest.fixture(autouse=True)
    def _real_recorder(self, easy):
        """Use the real recorder; the shared fixture stubs it out."""
        del easy.record_until_silence

    @staticmethod
    def _loud():
        return (np.ones(1600, dtype=np.int16) * 5000).tobytes()

    @staticmethod
    def _quiet():
        return np.zeros(1600, dtype=np.int16).tobytes()

    def test_command_default_caps_at_five_seconds(self, easy):
        """Commands are a few words, so the cap keeps the daemon responsive."""
        easy.stream.read = Mock(return_value=self._loud())

        easy.record_until_silence()

        assert easy.stream.read.call_count == 50

    def test_a_longer_cap_can_be_asked_for(self, easy):
        """Dictation runs past five seconds and used to be cut off mid-sentence."""
        easy.stream.read = Mock(return_value=self._loud())

        easy.record_until_silence(max_seconds=20.0)

        assert easy.stream.read.call_count == 200

    def test_command_default_stops_on_a_brief_pause(self, easy):
        """A third of a second of quiet ends a command."""
        easy.stream.read = Mock(side_effect=[self._loud()] * 6 + [self._quiet()] * 40)

        easy.record_until_silence()

        assert easy.stream.read.call_count == 9

    def test_a_longer_pause_can_be_tolerated(self, easy):
        """People pause mid-sentence for longer than a whole command takes."""
        easy.stream.read = Mock(side_effect=[self._loud()] * 6 + [self._quiet()] * 40)

        easy.record_until_silence(silence_duration=1.2)

        assert easy.stream.read.call_count == 18

    def test_modal_modes_pass_their_limits_through(self, easy):
        """A mode's limits reach the recorder, not just the generator."""
        drive(easy, [b"a"], ["hello"])
        easy.record_until_silence = Mock(return_value=b"tail")

        with clock():
            list(
                easy.listen_modal(
                    "dictation", max_record_seconds=20.0, silence_duration=1.2
                )
            )

        assert easy.record_until_silence.call_args.kwargs == {
            "max_seconds": 20.0,
            "silence_duration": 1.2,
        }


class TestWakeWordInsideAMode:
    """Saying the wake word out of habit shouldn't break a mode."""

    def test_strips_the_wake_word(self, easy):
        """A command prefixed with the wake word still reaches the plugin.

        Modes only stripped it at the top level, so "Hey Jarvis, numbers" inside
        browser mode was logged as an unknown command and dropped.
        """
        drive(easy, [b"a"], ["Hey Jarvis, numbers"])

        with clock():
            assert list(easy.listen_modal("browser")) == ["numbers"]

    def test_keeps_the_case_of_what_was_said(self, easy):
        """Dictation inserts the text as spoken, so the mode gets it unlowered.

        Lowercasing here turned "United States" into "united states" in every
        dictated sentence (#183). The modes that match words lowercase for
        themselves.
        """
        drive(easy, [b"a"], ["Hey Jarvis, Dear Sir"])

        with clock():
            assert list(easy.listen_modal("dictation")) == ["Dear Sir"]

    def test_bare_wake_word_is_not_a_command(self, easy):
        """The wake word alone leaves nothing to act on."""
        drive(easy, [b"a", b"b"], ["hey jarvis", "close"])

        with clock():
            assert list(easy.listen_modal("grid")) == ["close"]


class TestSilenceCalibration:
    """The silence threshold is measured from the room, not assumed.

    A fixed threshold assumes a quiet one. Where the ambient level sits above it,
    `is_silence` never returns True and nothing stops recording early -- a
    three-word command took the whole five-second cap and a dictated sentence took
    twenty, which was most of the wait between speaking and seeing text.
    """

    @pytest.fixture(autouse=True)
    def _real_calibration(self, easy, monkeypatch):
        """Use the real method; the shared fixture stubs it out at startup."""
        monkeypatch.setattr(
            type(easy), "calibrate_silence", conftest.REAL_CALIBRATE_SILENCE
        )

    @staticmethod
    def _room(level):
        """A chunk of steady room noise at the given mean amplitude."""
        return (np.ones(1600, dtype=np.int16) * level).tobytes()

    def test_raises_the_threshold_for_a_noisy_room(self, easy, monkeypatch):
        """A fan or a desktop puts the floor above the default."""
        monkeypatch.delenv("EASYSPEAK_SILENCE_THRESHOLD", raising=False)
        easy.stream.read = Mock(return_value=self._room(400))

        easy.calibrate_silence()

        assert easy.silence_threshold == 1000  # 400 x 2.5

    def test_keeps_the_floor_in_a_quiet_room(self, easy, monkeypatch):
        """A quiet room must not lower the threshold below the configured floor."""
        monkeypatch.delenv("EASYSPEAK_SILENCE_THRESHOLD", raising=False)
        easy.stream.read = Mock(return_value=self._room(10))

        easy.calibrate_silence()

        assert easy.silence_threshold == main.SILENCE_THRESHOLD

    def test_never_rises_above_speech(self, easy, monkeypatch):
        """Calibrating during loud noise must not make speech read as silence."""
        monkeypatch.delenv("EASYSPEAK_SILENCE_THRESHOLD", raising=False)
        easy.stream.read = Mock(return_value=self._room(9000))

        easy.calibrate_silence()

        assert easy.silence_threshold == main.SILENCE_THRESHOLD_MAX

    def test_a_stray_noise_does_not_skew_it(self, easy, monkeypatch):
        """The median is used, so one cough during calibration is ignored."""
        monkeypatch.delenv("EASYSPEAK_SILENCE_THRESHOLD", raising=False)
        quiet = [self._room(200)] * 9
        easy.stream.read = Mock(side_effect=[*quiet[:4], self._room(9000), *quiet[4:]])

        easy.calibrate_silence()

        assert easy.silence_threshold == 500  # 200 x 2.5, the cough ignored

    def test_the_environment_can_override_it(self, easy, monkeypatch):
        """Someone who knows their room can say so and skip the sampling."""
        monkeypatch.setenv("EASYSPEAK_SILENCE_THRESHOLD", "1500")
        easy.stream.read = Mock()

        easy.calibrate_silence()

        assert easy.silence_threshold == 1500
        assert not easy.stream.read.called

    def test_a_bad_override_is_ignored(self, easy, monkeypatch):
        """A typo in the environment falls back to measuring the room."""
        monkeypatch.setenv("EASYSPEAK_SILENCE_THRESHOLD", "loud")
        easy.stream.read = Mock(return_value=self._room(400))

        easy.calibrate_silence()

        assert easy.silence_threshold == 1000

    def test_an_unreadable_microphone_leaves_the_floor(self, easy, monkeypatch):
        """No audio to measure means the configured floor stands."""
        monkeypatch.delenv("EASYSPEAK_SILENCE_THRESHOLD", raising=False)
        easy.stream.read = Mock(side_effect=OSError("no mic"))

        easy.calibrate_silence()

        assert easy.silence_threshold == main.SILENCE_THRESHOLD

    def test_is_silence_uses_the_calibrated_value(self, easy):
        """The measured threshold is what recording actually consults."""
        easy.silence_threshold = 1000
        room = np.ones(1600, dtype=np.int16) * 400

        assert easy.is_silence(room) is np.True_


class TestSilentExits:
    """No way out of a mode should leave the user guessing."""

    def test_waking_from_sleep_is_announced(self, easy):
        """Resuming from the tray ends the mode, and used to say nothing at all."""
        easy.tray.poll = Mock(side_effect=[TrayAction.RESUME])
        drive(easy, [b"a"], ["click"])

        list(easy.listen_modal("grid"))

        spoken = easy.speech.speak.call_args.args[0]
        assert "Leaving grid" in spoken
        assert main.WAKE_WORD_SPOKEN in spoken


class TestWakeWordStripping:
    """Only a leading wake word is removed."""

    @pytest.mark.parametrize(
        ["spoken", "expected"],
        [
            ("hey jarvis, numbers", "numbers"),
            ("hey jarvis numbers", "numbers"),
            ("jarvis, back", "back"),
            ("Hey Jarvis", ""),
            ("Hey Jarvis, Open Documents", "Open Documents"),
            ("grid", "grid"),
        ],
    )
    def test_a_leading_wake_word_is_removed(self, spoken, expected):
        """Users say it out of habit inside a mode that is already listening."""
        assert main.strip_wake_words(spoken) == expected

    @pytest.mark.parametrize(
        "spoken",
        [
            "search jarvis",
            "find jarvis on the page",
            "go to jarvis.dot.com",
            "search for hey jarvis",
        ],
    )
    def test_the_word_is_kept_when_it_is_content(self, spoken):
        """Replacing every occurrence ate the word out of the middle of a command.

        "search jarvis" became "search", and a URL containing it lost part of
        itself.
        """
        assert main.strip_wake_words(spoken) == spoken


class TestRequireWakeWord:
    """Modes can be told to wait for the wake word before every command."""

    def test_the_mode_waits_for_the_wake_word(self, easy):
        """With the flag on, nothing is heard until the wake word fires."""
        easy.require_wake_word = True
        misses, hit = [False], [True]
        easy.wait_for_wake = Mock(side_effect=misses + hit + misses * 20)
        drive(easy, [b"a"], ["back"])

        with clock():
            assert list(easy.listen_modal("browser")) == ["back"]

    def test_a_mode_does_not_wait_by_default(self, easy):
        """The flag is off by default, so the wake word is never waited on."""
        easy.wait_for_wake = Mock()
        drive(easy, [b"a"], ["scroll down"])

        with clock():
            list(easy.listen_modal("browser"))

        assert not easy.wait_for_wake.called

    def test_a_wake_gated_mode_is_optional(self, easy):
        """Dictation captures continuous speech, so it is never wake-gated."""
        easy.require_wake_word = True
        easy.wait_for_wake = Mock()
        drive(easy, [b"a"], ["hello there"])

        with clock():
            assert list(easy.listen_modal("dictation", wake_gated=False)) == [
                "hello there"
            ]

        assert not easy.wait_for_wake.called
