"""Tests for the dictation plugin module."""

import json
from unittest.mock import Mock, patch

import pytest
from easyspeak.core import mediakeys
from easyspeak.plugins import dictation


@pytest.fixture(autouse=True)
def _reset_atspi_interpreter():
    """Forget the probed AT-SPI interpreter around each test.

    dictation caches it after the first probe, so without this one test's answer
    leaks into the next.
    """
    dictation._atspi_python = None
    yield
    dictation._atspi_python = None


@patch.object(dictation, "ensure_gnome_accessibility")
def test_setup(mock_ensure):
    """Test that setup correctly assigns the core object."""
    mock_core = Mock()

    dictation.setup(mock_core)

    assert dictation.core == mock_core
    mock_ensure.assert_called_once_with()


# Tests for ensure_gnome_accessibility.


@patch("easyspeak.plugins.dictation.shutil.which", return_value=None)
def test_ensure_gnome_accessibility_no_gsettings(mock_which, readlog):
    """No gsettings on PATH (non-GNOME): silent no-op."""
    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert captured.err == ""


@patch("easyspeak.plugins.dictation.subprocess.run")
@patch("easyspeak.plugins.dictation.shutil.which", return_value="/usr/bin/gsettings")
def test_ensure_gnome_accessibility_schema_missing(mock_which, mock_run, readlog):
    """gsettings present but schema lookup fails: silent no-op."""
    mock_run.return_value = Mock(returncode=1, stdout="")

    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert captured.err == ""
    mock_run.assert_called_once()  # only 'get' is attempted, no 'set'


@patch("easyspeak.plugins.dictation.subprocess.run")
@patch("easyspeak.plugins.dictation.shutil.which", return_value="/usr/bin/gsettings")
def test_ensure_gnome_accessibility_already_on(mock_which, mock_run, readlog):
    """Setting is already true: silent no-op, no 'set' call."""
    mock_run.return_value = Mock(returncode=0, stdout="true\n")

    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert captured.err == ""
    mock_run.assert_called_once()


@patch("easyspeak.plugins.dictation.subprocess.run")
@patch("easyspeak.plugins.dictation.shutil.which", return_value="/usr/bin/gsettings")
def test_ensure_gnome_accessibility_enables(mock_which, mock_run, readlog):
    """Setting is false and 'set' succeeds: prints enabled message + re-login hint."""
    mock_run.side_effect = [
        Mock(returncode=0, stdout="false\n"),  # get
        Mock(returncode=0, stdout=""),  # set
    ]

    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert "enabled GNOME toolkit-accessibility" in captured.err
    assert "log out" in captured.err
    assert mock_run.call_count == 2


@patch("easyspeak.plugins.dictation.subprocess.run")
@patch("easyspeak.plugins.dictation.shutil.which", return_value="/usr/bin/gsettings")
def test_ensure_gnome_accessibility_set_fails(mock_which, mock_run, readlog):
    """Setting is false but 'set' fails: prints WARNING."""
    mock_run.side_effect = [
        Mock(returncode=0, stdout="false\n"),  # get
        Mock(returncode=1, stdout=""),  # set fails
    ]

    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert "WARNING" in captured.err
    assert "could not enable" in captured.err


@patch("easyspeak.plugins.dictation.subprocess.run", side_effect=OSError("nope"))
@patch("easyspeak.plugins.dictation.shutil.which", return_value="/usr/bin/gsettings")
def test_ensure_gnome_accessibility_oserror(mock_which, mock_run, readlog):
    """subprocess.run raising OSError is swallowed silently."""
    dictation.ensure_gnome_accessibility()

    captured = readlog()
    assert captured.err == ""


@pytest.mark.parametrize(
    ["input_text", "expected_output"],
    [
        # Basic text should be capitalized
        ("hello world", "Hello world"),
        # Whisper punctuation should be stripped
        ("hello, world.", "Hello world"),
        # Comma command
        ("hello comma world", "Hello, world"),
        ("hello karma world", "Hello, world"),
        ("hello kama world", "Hello, world"),
        # Period command
        ("hello period world", "Hello. World"),
        ("hello full stop world", "Hello. World"),
        # Question mark
        ("hello question mark", "Hello?"),
        # Exclamation mark
        ("hello exclamation mark", "Hello!"),
        ("hello exclamation point", "Hello!"),
        # Colon and semicolon
        ("hello colon world", "Hello: world"),
        ("hello semicolon world", "Hello; world"),
        ("hello semi colon world", "Hello; world"),
        # New sentence should add period and space and capitalize next word
        ("hello new sentence world", "Hello. World"),
        ("hello next sentence world", "Hello. World"),
        # New paragraph
        ("hello new paragraph world", "Hello\n\nworld"),
        ("hello next paragraph world", "Hello\n\nworld"),
        ("hello new para world", "Hello\n\nworld"),
        # New line
        ("hello new line world", "Hello\nworld"),
        ("hello newline world", "Hello\nworld"),
        ("hello you line world", "Hello\nworld"),
        ("hello line break world", "Hello\nworld"),
        ("hello enter world", "Hello enter world"),
        # Backspace is a keystroke command, not text: it must survive as words
        ("hello backspace world", "Hello backspace world"),
        ("hello delete world", "Hello delete world"),
        # Space command
        ("hello space world", "Hello world"),
        # Tab and enter are keystroke commands, not text
        ("hello tab world", "Hello tab world"),
        # Dash and hyphen
        ("hello dash world", "Hello - world"),
        ("hello hyphen world", "Hello-world"),
        # Apostrophe and quotes
        ("hello apostrophe world", "Hello'world"),
        ("hello quote world", 'Hello"world'),
        ("hello open quote world", 'Hello "world'),
        ("hello close quote world", 'Hello" world'),
        # Parentheses
        ("hello open paren world", "Hello (world"),
        ("hello close paren world", "Hello) world"),
        # Symbols
        ("hello at sign world", "Hello@world"),
        ("hello ampersand world", "Hello&world"),
        ("hello dollar sign world", "Hello$world"),
        ("hello percent sign world", "Hello%world"),
        ("hello percent world", "Hello%world"),
        ("hello hashtag world", "Hello#world"),
        ("hello hash world", "Hello#world"),
        ("hello asterisk world", "Hello*world"),
        ("hello star world", "Hello*world"),
        ("hello underscore world", "Hello_world"),
        ("hello slash world", "Hello/world"),
        ("hello backslash world", "Hello\\world"),
        ("it starts here", "It starts here"),
        ("open workspace one", "Open workspace one"),
        ("i deleted the coma", "I deleted the,"),
        ("the periodic table", "The periodic table"),
        ("a hashtag and a hash", "A#and a#"),
        # Multiple spaces should be collapsed
        ("hello    world", "Hello world"),
        # Punctuation already in input gets stripped by Whisper cleanup
        ("hello , world", "Hello world"),
        ("hello. world", "Hello world"),
        ("hello? world", "Hello world"),
        ("hello! world", "Hello world"),
        # Empty string
        ("", ""),
        # Only whitespace
        ("   ", ""),
    ],
)
def test_format_text(input_text, expected_output):
    """Test format_text with various inputs."""
    result = dictation.format_text(input_text)

    assert result == expected_output


@pytest.mark.parametrize(
    ["input_text", "expected_output"],
    [
        # Multiple periods should be collapsed to one
        ("hello period period world", "Hello. World"),
        # Period takes precedence over comma (both get converted, but comma is removed when followed by period)
        ("hello comma period world", "Hello. World"),
        # Test case insensitivity for commands
        ("hello COMMA world", "Hello, world"),
        ("hello Comma world", "Hello, world"),
        # Mixed commands
        ("hello comma world period next sentence goodbye", "Hello, world. Goodbye"),
    ],
)
def test_format_text_edge_cases(input_text, expected_output):
    """Test format_text edge cases and combinations."""
    result = dictation.format_text(input_text)

    assert result == expected_output


@patch("subprocess.run", return_value=Mock(returncode=0, stdout="OK\n", stderr=""))
def test_insert_via_atspi_success(mock_run, monkeypatch):
    """When text insertion succeeds the result should be INSERTED.

    EASYSPEAK_ATSPI_PYTHON is cleared so the default-interpreter fallback is
    what's asserted, regardless of the environment the tests run in (the Nix
    dev shell exports it).
    """
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    result = dictation.insert_via_atspi("Hello world")

    assert result == dictation.INSERTED
    # Two calls now: probing an interpreter, then running the helper in it.
    assert mock_run.call_count == 2
    call_args = mock_run.call_args.args[0]
    assert call_args[0] == "python3"
    assert call_args[1] == dictation.ATSPI_HELPER
    assert call_args[1].endswith("_atspi_insert.py")
    assert call_args[2] == "Hello world"


@patch(
    "subprocess.run", return_value=Mock(returncode=0, stdout="NO_FOCUS\n", stderr="")
)
def test_insert_via_atspi_no_focus(mock_run):
    """When no text field is focused the result should be NO_FOCUS."""
    result = dictation.insert_via_atspi("Hello world")

    assert result == dictation.NO_FOCUS


@patch(
    "subprocess.run",
    return_value=Mock(returncode=0, stdout="NO_BACKEND\n", stderr="No module named gi"),
)
def test_insert_via_atspi_backend_missing(mock_run, readlog):
    """When the helper reports a missing backend the result is BACKEND_ERROR."""
    result = dictation.insert_via_atspi("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "backend unavailable" in readlog().err


@patch.dict("os.environ", {"EASYSPEAK_ATSPI_PYTHON": "/opt/atspi/bin/python3"})
@patch(
    "subprocess.run",
    return_value=Mock(returncode=1, stdout="", stderr="boom"),
)
def test_insert_via_atspi_helper_crash(mock_run, readlog):
    """A non-zero exit from the helper is treated as a backend error."""
    result = dictation.insert_via_atspi("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "boom" in readlog().err


@patch.dict("os.environ", {"EASYSPEAK_ATSPI_PYTHON": "/opt/atspi/bin/python3"})
@patch("subprocess.run", side_effect=OSError("no python3"))
def test_insert_via_atspi_interpreter_missing(mock_run, readlog):
    """When the interpreter can't even launch the result is BACKEND_ERROR."""
    result = dictation.insert_via_atspi("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "could not start" in readlog().err


@patch.dict("os.environ", {"EASYSPEAK_ATSPI_PYTHON": "/opt/atspi/bin/python3"})
@patch("subprocess.run", return_value=Mock(returncode=0, stdout="OK\n", stderr=""))
def test_insert_via_atspi_uses_configured_interpreter(mock_run):
    """EASYSPEAK_ATSPI_PYTHON overrides the interpreter the helper runs in."""
    dictation.insert_via_atspi("Hello world")

    assert mock_run.call_args.args[0][0] == "/opt/atspi/bin/python3"


@patch("subprocess.run", return_value=Mock(returncode=0, stdout="OK\n", stderr=""))
def test_insert_via_atspi_empty_string(mock_run):
    """When inserting an empty string the result should be INSERTED."""
    result = dictation.insert_via_atspi("")

    assert result == dictation.INSERTED
    call_args = mock_run.call_args.args[0]
    assert call_args[2] == ""


@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_non_dictation_command(mock_insert, mock_core):
    """When given a non-dictation command the result should be None."""
    result = dictation.handle("open browser", mock_core)

    assert result is None
    assert not mock_insert.called


@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_stop_notes_command(mock_insert, mock_core):
    """When given a stop notes command the result should be None."""
    result = dictation.handle("stop notes", mock_core)

    assert result is None
    assert not mock_insert.called


@pytest.mark.parametrize(
    "command",
    ["notebook", "noted", "denote", "footnote", "notepad", "take notice"],
)
@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_ignores_words_merely_containing_note(mock_insert, command, mock_core):
    """Words that only contain 'note' must not enter dictation mode.

    Regression: a substring check fired dictation on 'notebook', 'noted', etc.
    """
    assert dictation.handle(command, mock_core) is None
    mock_insert.assert_not_called()
    mock_core.speak.assert_not_called()


@pytest.mark.parametrize(
    "command",
    ["notes", "note", "take notes", "new note", "notes please"],
)
@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_enters_dictation_on_note_word(
    mock_insert, command, mock_core_with_audio
):
    """'note'/'notes' as a whole word still enters dictation mode."""
    mock_core_with_audio.transcribe = Mock(return_value="stop notes")

    assert dictation.handle(command, mock_core_with_audio) is True
    assert ("Dictation",) in [
        call.args for call in mock_core_with_audio.speak.call_args_list
    ]


@patch("easyspeak.plugins.dictation.insert_text", return_value=True)
@patch("easyspeak.plugins.dictation.format_text", return_value=".")
def test_handle_dictation_mode_no_space_before_punctuation(
    mock_format, mock_insert, mock_core_factory
):
    """When formatted text starts with punctuation no space should be added."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        record_until_silence_value=b"audio_rest",
        transcribe_values=["period", "stop notes"],
    )

    result = dictation.handle("notes", mock_core)

    assert result is True
    assert mock_insert.call_count == 1
    assert mock_insert.call_args.args == (".",)


@patch("easyspeak.plugins.dictation.insert_text", return_value=dictation.NO_FOCUS)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_handle_dictation_mode_no_focus(mock_format, mock_insert, mock_core_with_audio):
    """When no text field is focused a warning should be spoken."""
    mock_core_with_audio.transcribe = Mock(return_value="some text")

    result = dictation.handle("notes", mock_core_with_audio)

    assert result is True
    assert ("No text field focused.",) in [
        call.args for call in mock_core_with_audio.speak.call_args_list
    ]


@patch("easyspeak.plugins.dictation.insert_text", return_value=dictation.BACKEND_ERROR)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_handle_dictation_mode_backend_error(
    mock_format, mock_insert, mock_core_with_audio
):
    """When the AT-SPI backend is unavailable a setup hint should be spoken."""
    mock_core_with_audio.transcribe = Mock(return_value="some text")

    result = dictation.handle("notes", mock_core_with_audio)

    assert result is True
    assert ("Dictation isn't set up on this system.",) in [
        call.args for call in mock_core_with_audio.speak.call_args_list
    ]


@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_dictation_mode_empty_transcription(mock_insert, mock_core_factory):
    """When transcription is empty it should be skipped."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        record_until_silence_value=b"audio3",
        transcribe_values=["", "stop notes"],
    )

    result = dictation.handle("notes", mock_core)

    assert result is True
    assert not mock_insert.called


@pytest.mark.parametrize(
    "stop_phrase",
    [
        "stop notes",
        "stop note",
        "end notes",
        "exit notes",
        "stop nurts",
        "stop nots",
        "stop nuts",
        "stopnotes",
        "done notes",
        "finish notes",
        "close notes",
        "closed notes",
    ],
)
@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_dictation_mode_stop_phrases(
    mock_insert, stop_phrase, mock_core_with_audio
):
    """When a stop phrase is recognized dictation should end."""
    mock_core_with_audio.transcribe = Mock(return_value=stop_phrase)

    result = dictation.handle("notes", mock_core_with_audio)

    assert result is True
    assert ("Done",) in [
        call.args for call in mock_core_with_audio.speak.call_args_list
    ]
    assert not mock_insert.called


def _holds(times):
    """Return a should_continue predicate True for ``times`` polls then False."""
    state = {"n": 0}

    def should_continue():
        state["n"] += 1
        return state["n"] <= times

    return should_continue


@patch.object(dictation, "ensure_gnome_accessibility")
def test_setup_registers_push_to_talk(mock_ensure):
    """setup() registers the push-to-talk session with a core that supports it."""
    mock_core = Mock()

    dictation.setup(mock_core)

    mock_core.register_push_to_talk.assert_called_once()
    assert callable(mock_core.register_push_to_talk.call_args.args[0])


@patch.object(dictation, "ensure_gnome_accessibility")
def test_setup_skips_registration_without_support(mock_ensure):
    """A core lacking register_push_to_talk (older/mocked) is tolerated."""
    core = Mock(spec=["speak"])  # no register_push_to_talk attribute

    dictation.setup(core)  # must not raise


@patch("easyspeak.plugins.dictation.insert_text", return_value=dictation.INSERTED)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_run_push_to_talk_inserts_until_released(mock_format, mock_insert):
    """While held, each utterance is formatted and inserted via AT-SPI."""
    core = Mock()
    core.wait_for_speech = Mock(return_value=b"audio1")
    core.record_until_silence = Mock(return_value=b"audio2")
    core.transcribe = Mock(return_value="hello")

    dictation.run_push_to_talk(core, _holds(1))

    assert mock_insert.call_count == 1
    assert mock_insert.call_args.args == (" Hello",)
    # The capture is gated on the held state so a release can cut it short.
    assert core.wait_for_speech.call_args.kwargs["should_continue"] is not None
    assert core.record_until_silence.call_args.kwargs["should_continue"] is not None


@patch("easyspeak.plugins.dictation.insert_text")
def test_run_push_to_talk_skips_silence(mock_insert):
    """A listen that returns no speech loops without inserting."""
    core = Mock()
    core.wait_for_speech = Mock(return_value=None)

    dictation.run_push_to_talk(core, _holds(1))

    mock_insert.assert_not_called()
    core.transcribe.assert_not_called()


@patch("easyspeak.plugins.dictation.insert_text")
def test_run_push_to_talk_skips_empty_transcription(mock_insert):
    """An empty transcription is skipped."""
    core = Mock()
    core.wait_for_speech = Mock(return_value=b"audio1")
    core.record_until_silence = Mock(return_value=b"audio2")
    core.transcribe = Mock(return_value="")

    dictation.run_push_to_talk(core, _holds(1))

    mock_insert.assert_not_called()


@patch("easyspeak.plugins.dictation.insert_text", return_value=dictation.NO_FOCUS)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_run_push_to_talk_no_focus_stops(mock_format, mock_insert):
    """No focused field is spoken once and ends the session."""
    core = Mock()
    core.wait_for_speech = Mock(return_value=b"audio1")
    core.record_until_silence = Mock(return_value=b"audio2")
    core.transcribe = Mock(return_value="hello")

    dictation.run_push_to_talk(core, _holds(5))

    core.speak.assert_called_once_with("No text field focused.")


@patch("easyspeak.plugins.dictation.insert_text", return_value=dictation.BACKEND_ERROR)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_run_push_to_talk_backend_error_stops(mock_format, mock_insert):
    """A backend error gives the setup hint once and ends the session."""
    core = Mock()
    core.wait_for_speech = Mock(return_value=b"audio1")
    core.record_until_silence = Mock(return_value=b"audio2")
    core.transcribe = Mock(return_value="hello")

    dictation.run_push_to_talk(core, _holds(5))

    core.speak.assert_called_once_with("Dictation isn't set up on this system.")


@patch("easyspeak.plugins.dictation.insert_text")
@patch("easyspeak.plugins.dictation.format_text", return_value="")
def test_dictate_utterance_noop_on_empty_format(mock_format, mock_insert):
    """Text that formats to nothing inserts nothing and keeps dictating."""
    core = Mock()

    assert dictation._dictate_utterance(core, "   ") is False
    mock_insert.assert_not_called()


def test_handle_dictation_mode_ends_when_core_stops(mock_core_with_audio):
    """When core ends the mode (timeout or tray) then handle still reports handled."""
    mock_core_with_audio.transcribe = Mock(side_effect=[])

    assert dictation.handle("notes", mock_core_with_audio) is True


def _probe_result(*working):
    """subprocess.run stand-in where only `working` interpreters import AT-SPI."""

    def _run(cmd, **_kwargs):
        return Mock(returncode=0 if cmd[0] in working else 1, stdout="OK\n", stderr="")

    return _run


@patch("subprocess.run", side_effect=_probe_result("/usr/bin/python3"))
def test_atspi_python_skips_a_venv_interpreter(mock_run, monkeypatch):
    """When `python3` is a venv without PyGObject then the distro one is used.

    Running the daemon from an activated virtualenv makes a bare `python3`
    resolve to the venv's own interpreter, which has no PyGObject -- dictation
    then transcribed perfectly and inserted nothing.
    """
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    assert dictation.atspi_python() == "/usr/bin/python3"


@patch("subprocess.run", side_effect=_probe_result("python3", "/usr/bin/python3"))
def test_atspi_python_prefers_the_one_on_path(mock_run, monkeypatch):
    """When `python3` already works then no further candidate is tried."""
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    assert dictation.atspi_python() == "python3"
    assert mock_run.call_count == 1


@patch("subprocess.run", side_effect=_probe_result())
def test_atspi_python_returns_none_when_nothing_works(mock_run, monkeypatch):
    """When no interpreter can import AT-SPI then there is nothing to run."""
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    assert dictation.atspi_python() is None


@patch.dict("os.environ", {"EASYSPEAK_ATSPI_PYTHON": "/nix/store/x/bin/python3"})
@patch("subprocess.run", side_effect=_probe_result())
def test_atspi_python_override_is_not_probed(mock_run):
    """An explicit interpreter is taken as given, the way the Nix flake sets it."""
    assert dictation.atspi_python() == "/nix/store/x/bin/python3"
    assert not mock_run.called


@patch("subprocess.run", side_effect=_probe_result("python3"))
def test_atspi_python_is_probed_only_once(mock_run, monkeypatch):
    """The answer is remembered, so dictation isn't probing per utterance."""
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    dictation.atspi_python()
    dictation.atspi_python()

    assert mock_run.call_count == 1


@patch("subprocess.run", side_effect=OSError("no such interpreter"))
def test_atspi_python_survives_a_missing_candidate(mock_run, monkeypatch):
    """A candidate that isn't installed is skipped, not raised."""
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    assert dictation.atspi_python() is None


@patch.object(dictation, "atspi_python", return_value=None)
def test_insert_via_atspi_without_an_interpreter_says_how_to_fix_it(
    mock_python, readlog
):
    """When nothing can run the helper then the log names the package to install."""
    assert dictation.insert_via_atspi("hello") == dictation.BACKEND_ERROR

    captured = readlog().err
    assert "python3-gobject" in captured
    assert "EASYSPEAK_ATSPI_PYTHON" in captured


def _windows_reply(wm_class, *, focused=True):
    """A gdbus GetWindows reply naming one window."""
    payload = json.dumps(
        [
            {
                "id": 1,
                "title": "a window",
                "wm_class": wm_class,
                "workspace": 0,
                "focused": focused,
            }
        ]
    )
    return Mock(returncode=0, stdout=f"({payload!r},)", stderr="")


@pytest.mark.parametrize(
    ["wm_class", "expected"],
    [("qutebrowser", "qutebrowser"), ("org.gnome.TextEditor", "org.gnome.TextEditor")],
)
def test_focused_wm_class_reads_the_focused_window(wm_class, expected):
    """The extension's window list is parsed out of gdbus' tuple syntax."""
    with patch("subprocess.run", return_value=_windows_reply(wm_class)):
        assert dictation.focused_wm_class() == expected


def test_focused_wm_class_when_nothing_is_focused():
    """When no window holds focus then there is nothing to report."""
    with patch(
        "subprocess.run", return_value=_windows_reply("qutebrowser", focused=False)
    ):
        assert dictation.focused_wm_class() is None


@pytest.mark.parametrize(
    "reply",
    [
        Mock(returncode=1, stdout="", stderr="no such interface"),
        Mock(returncode=0, stdout="not a variant at all", stderr=""),
        Mock(returncode=0, stdout="('not json',)", stderr=""),
    ],
)
def test_focused_wm_class_tolerates_a_bad_reply(reply):
    """A missing or malformed answer leaves insertion on the AT-SPI path."""
    with patch("subprocess.run", return_value=reply):
        assert dictation.focused_wm_class() is None


@pytest.mark.parametrize("failure", [OSError("no gdbus"), TimeoutError])
def test_focused_wm_class_tolerates_a_missing_extension(failure):
    """No gdbus, or a wedged bus, must not stall an utterance."""
    with patch("subprocess.run", side_effect=failure):
        assert dictation.focused_wm_class() is None


# --- Clipboard insertion -----------------------------------------------------


def _wayland_tools(name):
    """shutil.which stand-in for a session with wl-clipboard installed."""
    return f"/usr/bin/{name}" if name.startswith("wl-") else None


@pytest.fixture
def clipboard(monkeypatch):
    """Drive a Wayland clipboard session and capture what it is asked to do."""
    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    calls = []

    def _run(cmd, **kwargs):
        calls.append((cmd[0], kwargs.get("input")))
        if cmd[0] == "wl-paste":
            return Mock(returncode=0, stdout=b"ORIGINAL", stderr=b"")
        if cmd[0] == "gdbus":
            return _windows_reply("org.gnome.TextEditor")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(dictation.subprocess, "run", _run)
    monkeypatch.setattr(dictation.time, "sleep", lambda _s: None)
    return calls


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_pastes_the_dictated_text(mock_chord, mock_focus, clipboard):
    """Text reaches the application by clipboard and paste.

    Accessibility-level insertion is widely stubbed out -- Chromium-based apps
    accept the call, report success and discard the text -- so dictation
    transcribed perfectly and nothing appeared. Every toolkit implements paste.
    """
    assert dictation.insert_text("hello world") == dictation.INSERTED

    copied = [text for tool, text in clipboard if tool == "wl-copy"]
    assert copied[0] == "hello world"
    assert mock_chord.call_args.args[0] == [29, 47]  # ctrl+v


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_puts_the_clipboard_back(mock_chord, mock_focus, clipboard):
    """Dictating must not quietly cost the user whatever they had copied."""
    dictation.insert_text("hello")

    copied = [text for tool, text in clipboard if tool == "wl-copy"]
    assert copied == ["hello", "ORIGINAL"]


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_leaves_an_empty_clipboard_alone(
    mock_chord, mock_focus, monkeypatch
):
    """When there was nothing to save then nothing is restored."""
    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    copied = []

    def _run(cmd, **kwargs):
        if cmd[0] == "wl-paste":
            return Mock(returncode=1, stdout="", stderr="empty")
        if cmd[0] == "wl-copy":
            copied.append(kwargs.get("input"))
        if cmd[0] == "gdbus":
            return _windows_reply("org.gnome.TextEditor")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(dictation.subprocess, "run", _run)
    monkeypatch.setattr(dictation.time, "sleep", lambda _s: None)

    assert dictation.insert_text("hello") == dictation.INSERTED
    assert copied == ["hello"]


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord", side_effect=RuntimeError("no portal"))
def test_insert_text_reports_a_failed_keystroke(
    mock_chord, mock_focus, clipboard, readlog
):
    """When the paste keystroke can't be sent then say so, don't claim success."""
    assert dictation.insert_text("hello") == dictation.BACKEND_ERROR
    assert "RemoteDesktop" in readlog().err


def test_insert_text_reports_a_failed_copy(monkeypatch, readlog):
    """When the text can't reach the clipboard then there is nothing to paste."""
    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(
        dictation.subprocess,
        "run",
        lambda cmd, **kw: Mock(returncode=1, stdout="", stderr="denied"),
    )

    assert dictation.insert_text("hello") == dictation.BACKEND_ERROR
    assert "clipboard" in readlog().err


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch.object(dictation, "insert_via_atspi", return_value=dictation.INSERTED)
def test_insert_text_falls_back_without_a_clipboard_tool(
    mock_atspi, mock_focus, monkeypatch
):
    """With no wl-clipboard, the old accessibility path is all there is."""
    monkeypatch.setattr(dictation.shutil, "which", lambda _name: None)

    assert dictation.insert_text("hello") == dictation.INSERTED
    assert mock_atspi.call_args.args[0] == "hello"


def test_clipboard_tools_prefers_wayland(monkeypatch):
    """wl-clipboard is used when present."""
    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)

    copy_cmd, paste_cmd = dictation.clipboard_tools()

    assert copy_cmd == ["wl-copy"]
    assert paste_cmd[0] == "wl-paste"


def test_clipboard_tools_without_wl_clipboard(monkeypatch):
    """EasySpeak targets Wayland, so wl-clipboard is the only supported tool."""
    monkeypatch.setattr(dictation.shutil, "which", lambda _name: None)

    assert dictation.clipboard_tools() == (None, None)


@pytest.mark.parametrize(
    ["wm_class", "expected"],
    [
        ("org.gnome.TextEditor", [29, 47]),
        ("qutebrowser", [29, 47]),
        ("kitty", [29, 42, 47]),
        ("org.gnome.console", [29, 42, 47]),
    ],
)
def test_paste_chord_matches_the_focused_app(wm_class, expected, monkeypatch):
    """Terminals paste with Ctrl+Shift+V; Ctrl+V is a control character there."""
    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    monkeypatch.setattr(
        dictation.subprocess, "run", lambda *a, **kw: _windows_reply(wm_class)
    )

    assert dictation.paste_chord() == expected


@patch.dict("os.environ", {"EASYSPEAK_PASTE_KEYS": "shift+insert"})
def test_paste_chord_honours_the_override():
    """A user on a keyboard layout or toolkit we guess wrong can say so."""
    assert dictation.paste_chord() == [42, 110]


@patch.dict("os.environ", {"EASYSPEAK_PASTE_KEYS": "ctrl+banana"})
def test_paste_chord_rejects_an_unknown_key(monkeypatch, readlog):
    """A typo must not silently arm a chord that does nothing."""
    monkeypatch.setattr(
        dictation.subprocess,
        "run",
        lambda *a, **kw: _windows_reply("org.gnome.TextEditor"),
    )

    assert dictation.paste_chord() == [29, 47]
    assert "banana" in readlog().err


@pytest.mark.parametrize("failure", [OSError("gone"), TimeoutError])
def test_read_clipboard_survives_a_broken_tool(failure, monkeypatch):
    """An unreadable clipboard means nothing to restore, not a crash."""
    monkeypatch.setattr(dictation.subprocess, "run", Mock(side_effect=failure))

    assert dictation.read_clipboard(["wl-paste"]) is None


@pytest.mark.parametrize("failure", [OSError("gone"), TimeoutError])
def test_write_clipboard_survives_a_broken_tool(failure, monkeypatch):
    """A clipboard tool that hangs or vanishes fails the insertion cleanly."""
    monkeypatch.setattr(dictation.subprocess, "run", Mock(side_effect=failure))

    assert dictation.write_clipboard(["wl-copy"], "hello") is False


def test_write_clipboard_never_gives_the_tool_a_pipe(monkeypatch):
    """wl-copy must not be handed pipes it can pass to its background daemon.

    It forks a process that holds the selection and inherits our pipes, so
    capturing output makes subprocess.run wait on something that never exits
    (CPython bpo-37424). Every copy timed out and no text was ever pasted.
    """
    captured = {}

    def _run(cmd, **kwargs):
        captured.update(kwargs)
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dictation.subprocess, "run", _run)

    assert dictation.write_clipboard(["wl-copy"], "hello") is True
    assert captured["stdout"] is dictation.subprocess.DEVNULL
    assert captured["stderr"] is dictation.subprocess.DEVNULL
    assert "capture_output" not in captured


def test_write_clipboard_reports_a_timeout(monkeypatch, readlog):
    """A clipboard tool that hangs is named, not silently treated as a mystery."""
    monkeypatch.setattr(
        dictation.subprocess,
        "run",
        Mock(side_effect=dictation.subprocess.TimeoutExpired("wl-copy", 2)),
    )

    assert dictation.write_clipboard(["wl-copy"], "hello") is False
    assert "wl-copy did not finish" in readlog().err


def test_write_clipboard_reports_a_bad_exit(monkeypatch, readlog):
    """A non-zero exit says which tool failed and with what code."""
    monkeypatch.setattr(
        dictation.subprocess, "run", Mock(return_value=Mock(returncode=3))
    )

    assert dictation.write_clipboard(["wl-copy"], "hello") is False
    assert "exited with code 3" in readlog().err


@pytest.mark.parametrize(
    "phrase",
    [
        # "close note" is the one that got away: the hand-written list had
        # "close notes" but not the singular, so saying it stayed in dictation and
        # typed the words -- along with every command spoken afterwards.
        "close note",
        "close notes",
        "closed note",
        "stop note",
        "stop notes",
        "end note",
        "end notes",
        "exit note",
        "exit notes",
        "done notes",
        "finish note",
        "quit notes",
        # Whisper's usual mishearings of "notes".
        "stop nuts",
        "stop nots",
        "stop nurts",
        "stop knots",
        # No space at all, which happens on a fast utterance.
        "stopnotes",
    ],
)
def test_is_exit_phrase_accepts_every_way_of_saying_it(phrase):
    """Every verb pairs with every noun, singular and plural."""
    assert dictation.is_exit_phrase(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "search for potato chip recipes",
        "numbers",
        "take note of this",
        "the closing note was lovely",
        "notes are useful",
    ],
)
def test_is_exit_phrase_keeps_dictating_otherwise(phrase):
    """Ordinary speech about notes is text, not a command to stop."""
    assert dictation.is_exit_phrase(phrase) is False


def test_exit_phrases_cover_both_numbers(mock_core_with_audio):
    """Singular and plural are generated together, so neither can be forgotten."""
    for verb in dictation.EXIT_VERBS:
        assert f"{verb} note" in dictation.EXIT_PHRASES
        assert f"{verb} notes" in dictation.EXIT_PHRASES


@patch.object(dictation, "insert_text", return_value=dictation.INSERTED)
def test_handle_leaves_on_the_singular_phrase(mock_insert, mock_core_with_audio):
    """The whole session ends rather than typing the exit phrase as text."""
    mock_core_with_audio.transcribe = Mock(side_effect=["hello there", "close note"])

    assert dictation.handle("notes", mock_core_with_audio) is True

    inserted = [call.args[0] for call in mock_insert.call_args_list]
    assert "Close note" not in inserted


# --- Insertion latency -------------------------------------------------------


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_reads_the_focused_window_once(mock_chord, mock_focus, clipboard):
    """One gdbus round trip per insertion, not three.

    The window was read once to choose the paste chord and twice more for log
    lines, and every one of those sits between the user finishing a sentence and
    seeing it appear.
    """
    dictation.insert_text("hello")

    assert [tool for tool, _text in clipboard].count("gdbus") == 1


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_returns_before_restoring_the_clipboard(
    mock_chord, mock_focus, clipboard
):
    """The restore waits for the paste to land, so it must not block the caller.

    With the thread stubbed out nothing runs the settle, so any sleep seen here
    would have to be on the path the user is waiting on.
    """
    with (
        patch.object(dictation.threading, "Thread") as thread,
        patch.object(dictation.time, "sleep") as sleep,
    ):
        assert dictation.insert_text("hello") == dictation.INSERTED

    assert not sleep.called
    assert thread.return_value.start.called


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_clipboard_is_restored_in_the_background(mock_chord, mock_focus, clipboard):
    """The user's clipboard still comes back, just not in front of them."""
    threads = []

    def _spawn(target, daemon):
        threads.append(target)
        return Mock(start=Mock())

    with patch.object(
        dictation.threading,
        "Thread",
        side_effect=_spawn,
    ):
        dictation.insert_text("hello")

    assert len(threads) == 1
    with patch.object(dictation.time, "sleep"):
        threads[0]()  # run what the thread would have

    copied = [text for tool, text in clipboard if tool == "wl-copy"]
    assert copied == ["hello", "ORIGINAL"]


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_a_later_utterance_wins_over_a_pending_restore(
    mock_chord, mock_focus, clipboard
):
    """A slow restore must not overwrite text a newer utterance just pasted."""
    threads = []

    with patch.object(
        dictation.threading,
        "Thread",
        side_effect=lambda target, daemon: threads.append(target) or Mock(start=Mock()),
    ):
        dictation.insert_text("first")
        dictation.insert_text("second")

    # Run the first restore only after the second insertion has happened.
    with patch.object(dictation.time, "sleep"):
        threads[0]()

    copied = [text for tool, text in clipboard if tool == "wl-copy"]
    assert copied == ["first", "second"]  # the stale restore was skipped


def test_paste_chord_accepts_a_known_window(monkeypatch):
    """A caller that already looked up the window doesn't pay for it twice."""
    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    monkeypatch.setattr(
        dictation.subprocess, "run", Mock(side_effect=AssertionError("looked it up"))
    )

    assert dictation.paste_chord("kitty") == [29, 42, 47]
    assert dictation.paste_chord("org.gnome.TextEditor") == [29, 47]


def test_read_clipboard_survives_a_copied_image(monkeypatch, readlog):
    """A PNG on the clipboard must not take dictation down mid-sentence.

    wl-paste hands back whatever is there, and a copied screenshot arrives as raw
    bytes. Decoding those as UTF-8 raised straight out of the middle of an
    insertion, killing the dictation session.
    """
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    monkeypatch.setattr(
        dictation.subprocess,
        "run",
        Mock(return_value=Mock(returncode=0, stdout=png, stderr=b"")),
    )

    assert dictation.read_clipboard(["wl-paste"]) is None
    assert "non-text data" in readlog().err


def test_read_clipboard_returns_text_unchanged(monkeypatch):
    """Ordinary text still comes back so it can be restored afterwards."""
    monkeypatch.setattr(
        dictation.subprocess,
        "run",
        Mock(return_value=Mock(returncode=0, stdout=b"hello world", stderr=b"")),
    )

    assert dictation.read_clipboard(["wl-paste"]) == "hello world"


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_still_pastes_over_an_image(mock_chord, mock_focus, monkeypatch):
    """An unreadable clipboard doesn't stop the dictated text going in."""
    png = b"\x89PNG\r\n\x1a\n"
    copied = []

    def _run(cmd, **kwargs):
        if cmd[0] == "wl-paste":
            return Mock(returncode=0, stdout=png, stderr=b"")
        if cmd[0] == "wl-copy":
            copied.append(kwargs.get("input"))
        if cmd[0] == "gdbus":
            return _windows_reply("org.gnome.TextEditor")
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(dictation.subprocess, "run", _run)

    assert dictation.insert_text("hello") == dictation.INSERTED
    assert copied == ["hello"]  # pasted, and no attempt to restore the image


# --- Where the keystroke actually lands ---------------------------------------


@patch.object(dictation, "insert_via_atspi", return_value=dictation.NO_FOCUS)
def test_insert_text_refuses_with_nothing_focused(mock_atspi):
    """A paste into a page with no field focused vanishes without a trace.

    The keystroke is sent, the clipboard held the text, and nothing reports a
    problem -- so the user is left wondering. Asking first turns that into
    "No text field focused."
    """
    assert dictation.insert_text("hello") == dictation.NO_FOCUS


@pytest.mark.parametrize("answer", [dictation.INSERTED, dictation.BACKEND_ERROR])
@patch.object(dictation, "insert_via_atspi")
def test_has_focused_text_field_is_permissive(mock_atspi, answer):
    """A probe that can't run is no reason to refuse to paste.

    Only an explicit "nothing is focused" counts against it; blind but willing is
    the better fallback when the probe itself is unavailable.
    """
    mock_atspi.return_value = answer

    assert dictation.has_focused_text_field() is True


@patch.object(dictation, "insert_via_atspi")
def test_the_focus_probe_writes_nothing(mock_atspi):
    """The helper is run purely as a question, so it must insert no text."""
    dictation.has_focused_text_field()

    assert mock_atspi.call_args.args[0] == ""


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_enters_insert_mode_for_qutebrowser(
    mock_chord, mock_focus, monkeypatch
):
    """qutebrowser is modal: in normal mode a keystroke is a command, not text.

    Ctrl+V isn't bound there at all, so the paste went nowhere. Following a hint
    into a field auto-enters insert mode, which is why dictation worked after
    "numbers" and silently did nothing without it.
    """
    sent = []

    def _run(cmd, **kwargs):
        sent.append(cmd)
        if cmd[0] == "wl-paste":
            return Mock(returncode=0, stdout=b"", stderr=b"")
        if cmd[0] == "gdbus":
            return _windows_reply("org.qutebrowser.qutebrowser")
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(dictation.subprocess, "run", _run)

    dictation.insert_text("hello")

    assert ["qutebrowser", ":mode-enter insert"] in sent


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_leaves_other_apps_alone(mock_chord, mock_focus, clipboard):
    """Only qutebrowser is modal; a text editor must not be prodded."""
    dictation.insert_text("hello")

    assert "qutebrowser" not in [tool for tool, _text in clipboard]


@patch.object(dictation, "has_focused_text_field", return_value=True)
@patch("easyspeak.core.mediakeys.tap_chord")
def test_insert_text_survives_an_unreachable_browser(
    mock_chord, mock_focus, monkeypatch, readlog
):
    """A browser that has since closed must not stop the paste being attempted."""

    def _run(cmd, **kwargs):
        if cmd[0] == "qutebrowser":
            raise OSError("gone")
        if cmd[0] == "wl-paste":
            return Mock(returncode=0, stdout=b"", stderr=b"")
        if cmd[0] == "gdbus":
            return _windows_reply("org.qutebrowser.qutebrowser")
        return Mock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.delenv("EASYSPEAK_PASTE_KEYS", raising=False)
    monkeypatch.setattr(dictation.shutil, "which", _wayland_tools)
    monkeypatch.setattr(dictation.subprocess, "run", _run)

    assert dictation.insert_text("hello") == dictation.INSERTED
    assert "mode-enter insert" in readlog().err


@patch.object(dictation, "_qb_command")
def test_dictation_hands_the_browser_back_in_normal_mode(mock_qb, mock_core_with_audio):
    """Insert mode must not outlive the dictation session.

    It is entered so a paste reaches the page, but leaving the browser in it means
    every later keystroke is treated as text -- hinting and scrolling both
    misbehave, which looked like dictation breaking the browser on its way out.
    """
    dictation._left_browser_in_insert_mode = True
    mock_core_with_audio.transcribe = Mock(side_effect=[])

    dictation.handle("notes", mock_core_with_audio)

    assert mock_qb.call_args.args[0] == "mode-leave"
    assert dictation._left_browser_in_insert_mode is False


@patch.object(dictation, "_qb_command")
def test_nothing_to_hand_back_when_no_browser_was_touched(
    mock_qb, mock_core_with_audio
):
    """Dictating into a text editor must not prod qutebrowser at all."""
    dictation._left_browser_in_insert_mode = False
    mock_core_with_audio.transcribe = Mock(side_effect=[])

    dictation.handle("notes", mock_core_with_audio)

    assert not mock_qb.called


@patch.object(dictation, "_qb_command")
def test_the_browser_is_handed_back_even_after_a_failure(mock_qb, mock_core_with_audio):
    """A crash mid-session still leaves the browser usable."""
    dictation._left_browser_in_insert_mode = True
    mock_core_with_audio.listen_modal = Mock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        dictation.handle("notes", mock_core_with_audio)

    assert mock_qb.call_args.args[0] == "mode-leave"


@pytest.mark.parametrize(
    ["spoken", "expected"],
    [
        ("backspace", ("backspace", 1)),
        ("delete", ("backspace", 1)),
        ("backspace five", ("backspace", 5)),
        ("backspace 5", ("backspace", 5)),
        ("delete three", ("backspace", 3)),
        ("backspace 999", ("backspace", mediakeys.MAX_KEY_REPEATS)),
        ("enter", ("enter", 1)),
        ("press enter", ("enter", 1)),
        ("return", ("enter", 1)),
        ("tab", ("tab", 1)),
        ("escape", ("escape", 1)),
        ("page down", ("page down", 1)),
        ("press down five", ("down", 5)),
        ("press left 3", ("left", 3)),
        ("down", None),
        ("right", None),
        ("backspace the file", None),
        ("hello world", None),
        ("enter the room", None),
    ],
)
def test_key_request(spoken, expected):
    """Key commands take an optional press prefix and an optional repeat count."""
    request = mediakeys.parse_key_request(spoken.split(), dictation.BARE_KEYS)
    if expected is None:
        assert request is None
    else:
        assert request == (mediakeys.KEYS[expected[0]], expected[1])


@patch.object(mediakeys, "press_key", return_value=True)
def test_handle_delete_sends_the_requested_count(mock_press, mock_core):
    """ "backspace five" removes five characters."""
    mock_core.dictation_last_length = 13

    assert dictation._handle_keystroke(mock_core, "backspace five") is True
    assert mock_press.call_args.args == (mediakeys.KEYS["backspace"], 5)


@patch.object(mediakeys, "press_key", return_value=True)
def test_scratch_that_removes_the_last_insertion(mock_press, mock_core):
    """The undo phrase removes exactly what the previous utterance inserted."""
    mock_core.dictation_last_length = 13

    assert dictation._handle_keystroke(mock_core, "scratch that") is True
    assert mock_press.call_args.args == (mediakeys.KEYS["backspace"], 13)
    assert mock_core.dictation_last_length == 0


@patch.object(mediakeys, "press_key")
def test_scratch_that_with_nothing_inserted(mock_press, mock_core):
    """With no previous insertion the user is told, and no keys are sent."""
    mock_core.dictation_last_length = 0

    assert dictation._handle_keystroke(mock_core, "scratch that") is True
    assert not mock_press.called
    assert mock_core.speak.call_args.args[0] == "Nothing to scratch"


@patch.object(mediakeys, "press_key")
def test_handle_delete_ignores_ordinary_speech(mock_press, mock_core):
    """Dictated words that are not a delete command fall through to insertion."""
    assert dictation._handle_keystroke(mock_core, "hello world") is False
    assert not mock_press.called


@patch.object(mediakeys, "press_key", return_value=True)
def test_backspace_shortens_what_scratch_that_removes(mock_press, mock_core):
    """Backspacing part of an utterance leaves the rest still scratchable."""
    mock_core.dictation_last_length = 13

    dictation._handle_keystroke(mock_core, "backspace")
    dictation._handle_keystroke(mock_core, "backspace")

    assert mock_core.dictation_last_length == 11

    dictation._handle_keystroke(mock_core, "scratch that")

    assert mock_press.call_args.args == (mediakeys.KEYS["backspace"], 11)
    assert mock_core.dictation_last_length == 0


@patch.object(mediakeys, "press_key", return_value=False)
def test_handle_keystroke_reports_a_missing_backend(mock_press, mock_core):
    """A keystroke that can't be delivered is reported and stops the fall-through."""
    mock_core.dictation_last_length = 5

    assert dictation._handle_keystroke(mock_core, "backspace") is True
    assert mock_core.speak.call_args.args[0] == "Dictation isn't set up on this system."


@patch.object(mediakeys, "press_key", return_value=True)
def test_a_non_delete_key_clears_the_scratch_length(mock_press, mock_core):
    """A key other than backspace inserts nothing, so there is nothing to scratch."""
    mock_core.dictation_last_length = 13

    assert dictation._handle_keystroke(mock_core, "press enter") is True
    assert mock_core.dictation_last_length == 0


@patch.object(mediakeys, "press_key", return_value=True)
def test_a_keystroke_does_not_end_the_dictation_session(mock_press, mock_core):
    """A keystroke command is handled, then dictation keeps listening."""
    mock_core.dictation_last_length = 0
    mock_core.transcribe.side_effect = ["press enter", "stop notes"]

    assert dictation._dictation_session(mock_core) is True
    assert mock_core.speak.call_args.args[0] == "Done"
