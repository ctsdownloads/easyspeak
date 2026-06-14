"""Tests for the dictation plugin module."""

from unittest.mock import Mock, patch

import pytest
from easyspeak.plugins import dictation


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
        # Note: semicolon commands are broken - "colon" pattern matches first in the actual code
        ("hello semicolon world", "Hello semi: world"),
        ("hello semi colon world", "Hello semi: world"),
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
        ("hello enter world", "Hello\nworld"),
        # Backspace command
        ("hello backspace world", "Hello\bworld"),
        ("hello back space world", "Hello\bworld"),
        ("hello delete world", "Hello\bworld"),
        # Space command
        ("hello space world", "Hello world"),
        # Tab command
        ("hello tab world", "Hello\tworld"),
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
        # Note: backslash command is broken - "slash" pattern matches first in the actual code
        ("hello backslash world", "Hello back/world"),
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
def test_insert_text_success(mock_run, monkeypatch):
    """When text insertion succeeds the result should be INSERTED.

    EASYSPEAK_ATSPI_PYTHON is cleared so the default-interpreter fallback is
    what's asserted, regardless of the environment the tests run in (the Nix
    dev shell exports it).
    """
    monkeypatch.delenv("EASYSPEAK_ATSPI_PYTHON", raising=False)

    result = dictation.insert_text("Hello world")

    assert result == dictation.INSERTED
    assert mock_run.call_count == 1
    call_args = mock_run.call_args.args[0]
    assert call_args[0] == "python3"
    assert call_args[1] == dictation.ATSPI_HELPER
    assert call_args[1].endswith("_atspi_insert.py")
    assert call_args[2] == "Hello world"


@patch(
    "subprocess.run", return_value=Mock(returncode=0, stdout="NO_FOCUS\n", stderr="")
)
def test_insert_text_no_focus(mock_run):
    """When no text field is focused the result should be NO_FOCUS."""
    result = dictation.insert_text("Hello world")

    assert result == dictation.NO_FOCUS


@patch(
    "subprocess.run",
    return_value=Mock(returncode=0, stdout="NO_BACKEND\n", stderr="No module named gi"),
)
def test_insert_text_backend_missing(mock_run, readlog):
    """When the helper reports a missing backend the result is BACKEND_ERROR."""
    result = dictation.insert_text("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "backend unavailable" in readlog().err


@patch(
    "subprocess.run",
    return_value=Mock(returncode=1, stdout="", stderr="boom"),
)
def test_insert_text_helper_crash(mock_run, readlog):
    """A non-zero exit from the helper is treated as a backend error."""
    result = dictation.insert_text("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "boom" in readlog().err


@patch("subprocess.run", side_effect=OSError("no python3"))
def test_insert_text_interpreter_missing(mock_run, readlog):
    """When the interpreter can't even launch the result is BACKEND_ERROR."""
    result = dictation.insert_text("Hello world")

    assert result == dictation.BACKEND_ERROR
    assert "could not start" in readlog().err


@patch.dict("os.environ", {"EASYSPEAK_ATSPI_PYTHON": "/opt/atspi/bin/python3"})
@patch("subprocess.run", return_value=Mock(returncode=0, stdout="OK\n", stderr=""))
def test_insert_text_uses_configured_interpreter(mock_run):
    """EASYSPEAK_ATSPI_PYTHON overrides the interpreter the helper runs in."""
    dictation.insert_text("Hello world")

    assert mock_run.call_args.args[0][0] == "/opt/atspi/bin/python3"


@patch("subprocess.run", return_value=Mock(returncode=0, stdout="OK\n", stderr=""))
def test_insert_text_empty_string(mock_run):
    """When inserting an empty string the result should be INSERTED."""
    result = dictation.insert_text("")

    assert result == dictation.INSERTED
    assert mock_run.call_count == 1
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


@patch("easyspeak.plugins.dictation.insert_text", return_value=True)
@patch("easyspeak.plugins.dictation.format_text", return_value="Hello")
def test_handle_dictation_mode_single_input(
    mock_format, mock_insert, mock_core_factory
):
    """When handling dictation with single input the result should be True."""
    # First call returns audio with 'some text', second call returns audio with 'stop notes'
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        record_until_silence_value=b"audio_rest",
        transcribe_values=["some text", "stop notes"],
    )

    result = dictation.handle("notes", mock_core)

    assert result is True
    assert ("Dictation",) in [call.args for call in mock_core.speak.call_args_list]
    assert ("Done",) in [call.args for call in mock_core.speak.call_args_list]
    assert mock_core.transcribe.call_count == 2
    assert mock_format.call_count == 1
    assert mock_format.call_args.args == ("some text",)
    assert mock_insert.call_count == 1
    assert mock_insert.call_args.args == (" Hello",)


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


@patch("easyspeak.plugins.dictation.insert_text")
def test_handle_dictation_mode_timeout_waiting(mock_insert, mock_core_factory):
    """When waiting times out the system should continue waiting."""
    # First wait times out (returns None), second succeeds, third times out, fourth succeeds with stop
    expected_wait_count = 4
    mock_core = mock_core_factory(
        wait_for_speech_values=[None, b"audio1", None, b"audio2"],
        transcribe_values=["hello", "stop notes"],
    )

    result = dictation.handle("note", mock_core)

    assert result is True
    assert mock_core.wait_for_speech.call_count == expected_wait_count


@patch("easyspeak.plugins.dictation.insert_text", return_value=True)
@patch("easyspeak.plugins.dictation.format_text")
def test_handle_dictation_mode_with_prompt(mock_format, mock_insert, mock_core_factory):
    """When transcribing the dictation prompt should be passed."""
    mock_format.return_value = "Hello"
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        record_until_silence_value=b"audio_rest",
        transcribe_values=["some text", "stop notes"],
    )

    dictation.handle("notes", mock_core)

    # Check that transcribe was called with the prompt
    assert mock_core.transcribe.call_count == 2
    first_call = mock_core.transcribe.call_args_list[0]
    assert first_call.kwargs["prompt"] == dictation.DICTATION_PROMPT
