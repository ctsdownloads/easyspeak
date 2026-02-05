"""Tests for the browser plugin module."""

from unittest.mock import patch

import pytest
from easyspeak.plugins import browser

# Tests for parse_hint_numbers function.


@pytest.mark.parametrize(
    ["input_cmd", "expected"],
    [
        ("zero two", "02"),
        ("one", "1"),
        ("nine", "9"),
        ("zero one two three", "0123"),
        ("oh five", "05"),
        ("won tu", "12"),
        ("tree for", "34"),
        ("eight ate", "88"),
        ("sex seven", "67"),
        ("nein", "9"),
        ("0 1 2", "012"),
        ("test zero test", "0"),
        ("no numbers here", ""),
    ],
)
def test_parse_hint_numbers(input_cmd, expected):
    """Test parsing various hint number formats."""
    result = browser.parse_hint_numbers(input_cmd)

    assert result == expected


@pytest.mark.parametrize(
    ["input_cmd", "expected"],
    [
        ("zero, two!", "02"),
        ("one-two-three", "123"),
        ("four...five", "45"),
        ("six? seven.", "67"),
    ],
)
def test_parse_hint_numbers_with_punctuation(input_cmd, expected):
    """Test parsing hint numbers with punctuation."""
    result = browser.parse_hint_numbers(input_cmd)

    assert result == expected


# Tests for looks_like_hint function.


@pytest.mark.parametrize(
    ["input_cmd", "expected"],
    [
        ("02", True),
        ("92", True),
        ("o2", True),
        ("zero two", False),  # Two words are not considered hints
        ("one", True),
        ("nine", True),
        ("zero one two", False),  # Multiple words are not considered hints
        ("123456789", False),  # Too long
        ("this is a sentence", False),
        ("open youtube", False),
        ("back", False),
        ("", True),  # Empty string returns True
    ],
)
def test_looks_like_hint(input_cmd, expected):
    """Test checking if command looks like a hint number."""
    result = browser.looks_like_hint(input_cmd)

    assert result == expected


# Tests for parse_hint_number function.


@pytest.mark.parametrize(
    ["input_cmd", "expected"],
    [
        ("zero two", "02"),
        ("ninety three", "93"),
        ("twenty one", "21"),
        ("thirty five", "35"),
        ("forty two", "42"),
        ("fifty", "5"),
        ("sixty seven", "67"),
        ("seventy eight", "78"),
        ("eighty nine", "89"),
        ("ten", "10"),
        ("eleven", "11"),
        ("twelve", "12"),
        ("thirteen", "13"),
        ("fourteen", "14"),
        ("fifteen", "15"),
        ("sixteen", "16"),
        ("seventeen", "17"),
        ("eighteen", "18"),
        ("nineteen", "19"),
        ("one two three", "123"),
        ("5", "5"),
        ("92", "92"),
    ],
)
def test_parse_hint_number(input_cmd, expected):
    """Test parsing spoken numbers into hint strings."""
    result = browser.parse_hint_number(input_cmd)

    assert result == expected


@pytest.mark.parametrize(
    ["input_cmd", "expected"],
    [
        ("zero, two!", "02"),
        ("one-two-three", "123"),
        ("four...five", "45"),
    ],
)
def test_parse_hint_number_with_punctuation(input_cmd, expected):
    """Test parsing hint numbers with punctuation."""
    result = browser.parse_hint_number(input_cmd)

    assert result == expected


def test_parse_hint_number_no_numbers():
    """Test parsing command with no numbers."""
    result = browser.parse_hint_number("hello world")

    assert result == ""


# Tests for parse_spoken_url function.


@pytest.mark.parametrize(
    ["spoken_url", "expected"],
    [
        ("claude dot ai", "https://claude.ai"),
        ("github dot com", "https://github.com"),
        ("example dot com slash page", "https://example.com/page"),
        ("test dash site dot com", "https://test-site.com"),
        ("my underscore page dot com", "https://my_page.com"),
        ("site dot co dot uk", "https://site.co.uk"),
        ("localhost colon 3000", "https://localhost:3000"),
    ],
)
def test_parse_spoken_url(spoken_url, expected):
    """Test converting spoken URLs to actual URLs."""
    result = browser.parse_spoken_url(spoken_url)

    assert result == expected


@pytest.mark.parametrize(
    ["spoken_url", "expected"],
    [
        ("CLAUDE DOT AI", "https://claude.ai"),
        ("GitHub Dot Com", "https://github.com"),
    ],
)
def test_parse_spoken_url_case_insensitive(spoken_url, expected):
    """Test URL parsing is case insensitive."""
    result = browser.parse_spoken_url(spoken_url)

    assert result == expected


def test_parse_spoken_url_with_existing_protocol():
    """Test URL parsing preserves existing protocol."""
    result = browser.parse_spoken_url("https://example.com")

    assert result == "https://example.com"


# Tests for qutebrowser command functions.


@patch.object(browser, "core")
def test_qb(mock_core, capsys):
    """Test sending command to qutebrowser."""
    command = "reload"

    browser.qb(command)

    assert mock_core.host_run.call_count == 1
    assert mock_core.host_run.call_args.args[0] == ["qutebrowser", ":reload"]
    captured = capsys.readouterr()
    assert "🌐 qutebrowser :reload" in captured.out


@patch.object(browser, "core")
def test_qb_open(mock_core):
    """Test opening URL in qutebrowser."""
    url = "https://example.com"

    browser.qb_open(url)

    assert mock_core.host_run.call_count == 1
    assert mock_core.host_run.call_args.args[0] == ["qutebrowser", url]


# Tests for handle_browser_command function.


@pytest.mark.parametrize(
    "command",
    [
        "numbers",
        "number",
        "hints",
        "hint",
        "show numbers",
        "show hints",
        "links",
        "link",
        "blanks",
        "blinks",
    ],
)
@patch.object(browser, "qb")
@patch.object(browser, "listen_for_hint")
def test_handle_browser_command_hints(mock_listen, mock_qb, command, mock_core):
    """Test handling hint commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "hint"
    assert mock_listen.called
    assert mock_listen.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    "command",
    [
        "numbers new",
        "number new",
        "hints new",
        "new numbers",
        "links new",
        "link new",
    ],
)
@patch.object(browser, "qb")
@patch.object(browser, "listen_for_hint")
def test_handle_browser_command_hints_new_tab(mock_listen, mock_qb, command, mock_core):
    """Test handling hint commands for new tab."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "hint links tab"
    assert mock_listen.called
    assert mock_listen.call_args.args[0] == mock_core


@pytest.mark.parametrize(
    ["command", "qb_command"],
    [
        ["back", "back"],
        ["go back", "back"],
        ["previous page", "back"],
        ["forward", "forward"],
        ["go forward", "forward"],
        ["next page", "forward"],
        ["reload", "reload"],
        ["refresh", "reload"],
        ["reload page", "reload"],
        ["stop", "stop"],
        ["stop loading", "stop"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_navigation(mock_qb, command, qb_command, mock_core):
    """Test handling navigation commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == qb_command


@pytest.mark.parametrize(
    ["command", "js_constant"],
    [
        ["scroll down", "SCROLL_DOWN_JS"],
        ["down", "SCROLL_DOWN_JS"],
        ["scroll up", "SCROLL_UP_JS"],
        ["up", "SCROLL_UP_JS"],
        ["top", "SCROLL_TOP_JS"],
        ["go to top", "SCROLL_TOP_JS"],
        ["scroll to top", "SCROLL_TOP_JS"],
        ["bottom", "SCROLL_BOTTOM_JS"],
        ["go to bottom", "SCROLL_BOTTOM_JS"],
        ["scroll to bottom", "SCROLL_BOTTOM_JS"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_scrolling(mock_qb, command, js_constant, mock_core):
    """Test handling scrolling commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    # Verify qb was called with jseval and the appropriate JS constant
    call_args = mock_qb.call_args.args[0]
    assert call_args.startswith("jseval -q")
    assert getattr(browser, js_constant) in call_args


@pytest.mark.parametrize(
    ["command", "expected_js"],
    [
        ["page down", "PAGE_DOWN_JS"],
        ["page up", "PAGE_UP_JS"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_page_scroll(mock_qb, command, expected_js, mock_core):
    """Test handling page scroll commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    call_args = mock_qb.call_args.args[0]
    assert getattr(browser, expected_js) in call_args


@pytest.mark.parametrize(
    ["command", "qb_command"],
    [
        ["new tab", "open -t about:blank"],
        ["open tab", "open -t about:blank"],
        ["close tab", "tab-close"],
        ["close this tab", "tab-close"],
        ["next tab", "tab-next"],
        ["tab right", "tab-next"],
        ["last tab", "tab-prev"],
        ["previous tab", "tab-prev"],
        ["tab left", "tab-prev"],
        ["undo tab", "undo"],
        ["restore tab", "undo"],
        ["reopen tab", "undo"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_tabs(mock_qb, command, qb_command, mock_core):
    """Test handling tab commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == qb_command


@pytest.mark.parametrize(
    ["command", "expected_tab"],
    [
        ["tab one", "1"],
        ["tab two", "2"],
        ["tab five", "5"],
        ["tab 3", "3"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_tab_switch(mock_qb, command, expected_tab, mock_core):
    """Test switching to specific tab by number."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == f"tab-focus {expected_tab}"


@pytest.mark.parametrize(
    ["command", "query"],
    [
        ["find test", "test"],
        ["find hello world", "hello world"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_find(mock_qb, command, query, mock_core):
    """Test handling find commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == f"search {query}"


@pytest.mark.parametrize(
    ["command", "query"],
    [
        ["find next", "next"],  # "find next" is treated as search for "next"
        [
            "find previous",
            "previous",
        ],  # "find previous" is treated as search for "previous"
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_find_treated_as_search(
    mock_qb, command, query, mock_core
):
    """Test that find next/previous are treated as search queries due to code logic."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == f"search {query}"


@pytest.mark.parametrize(
    ["command", "qb_command"],
    [
        ["next match", "search-next"],
        ["previous match", "search-prev"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_find_navigation(
    mock_qb, command, qb_command, mock_core
):
    """Test handling find navigation commands that don't start with 'find'."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == qb_command


@pytest.mark.parametrize(
    "command",
    [
        "escape",
        "cancel",
        "nevermind",
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_escape(mock_qb, command, mock_core):
    """Test handling escape commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"


@pytest.mark.parametrize(
    ["command", "site", "url"],
    [
        ["go to youtube", "youtube", "https://youtube.com"],
        ["go to google", "google", "https://google.com"],
        ["go to github", "github", "https://github.com"],
        ["go to reddit", "reddit", "https://reddit.com"],
        ["go to duck", "duck", "https://duckduckgo.com"],
    ],
)
@patch.object(browser, "qb_open")
def test_handle_browser_command_bookmarks(mock_qb_open, command, site, url, mock_core):
    """Test handling bookmark navigation commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb_open.called
    assert mock_qb_open.call_args.args[0] == url
    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args[0] == f"Opening {site}."


@pytest.mark.parametrize(
    ["command", "expected_url"],
    [
        ["go to claude dot ai", "https://claude.ai"],
        ["go to example dot com", "https://example.com"],
        ["open test dot org", "https://test.org"],
    ],
)
@patch.object(browser, "qb_open")
def test_handle_browser_command_spoken_url(
    mock_qb_open, command, expected_url, mock_core
):
    """Test handling spoken URL commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb_open.called
    assert mock_qb_open.call_args.args[0] == expected_url
    assert mock_core.speak.call_count == 1


@pytest.mark.parametrize(
    ["command", "query"],
    [
        ["search test", "test"],
        ["search for python tutorial", "python tutorial"],
        ["search linux tips", "linux tips"],
    ],
)
@patch.object(browser, "qb_open")
def test_handle_browser_command_search(mock_qb_open, command, query, mock_core):
    """Test handling search commands."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    expected_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
    assert mock_qb_open.called
    assert mock_qb_open.call_args.args[0] == expected_url
    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args[0] == f"Searching for {query}."


@patch.object(browser, "qb")
def test_handle_browser_command_bookmark_save(mock_qb, mock_core):
    """Test saving bookmark command."""
    result = browser.handle_browser_command("bookmark this as mysite", mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "quickmark-save mysite"
    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args[0] == "Saved as mysite."


@pytest.mark.parametrize(
    ["command", "hint"],
    [
        ["02", "02"],
        ["92", "92"],
        ["o2", "02"],
    ],
)
@patch.object(browser, "qb")
def test_handle_browser_command_direct_hint(mock_qb, command, hint, mock_core, capsys):
    """Test handling direct hint number input."""
    result = browser.handle_browser_command(command, mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == f"hint-follow {hint}"
    captured = capsys.readouterr()
    assert "Direct digits" in captured.out


def test_handle_browser_command_unknown(mock_core):
    """Test handling unknown command returns None."""
    result = browser.handle_browser_command("unknown command", mock_core)

    assert result is None


# Tests for setup function.


def test_setup(mock_core):
    """Test setup function sets core reference."""
    browser.setup(mock_core)

    assert browser.core == mock_core


# Tests for handle function.


@pytest.mark.parametrize(
    "command",
    [
        "browser",
        "browser mode",
        "open browser",
        "launch browser",
    ],
)
@patch.object(browser, "browser_mode")
def test_handle_browser_mode(mock_browser_mode, command, mock_core):
    """Test handle function for entering browser mode."""
    result = browser.handle(command, mock_core)

    assert result is True
    assert mock_core.host_run.call_count == 1
    call_args = mock_core.host_run.call_args
    assert call_args.args[0] == ["qutebrowser"]
    assert call_args.kwargs["background"] is True
    assert mock_browser_mode.called
    assert mock_browser_mode.call_args.args[0] == mock_core


@patch.object(browser, "handle_browser_command")
@patch.object(browser, "browser_mode")
def test_handle_browser_command_enters_mode(
    mock_browser_mode, mock_handle_cmd, mock_core
):
    """Test handle function enters browser mode after single command."""
    mock_handle_cmd.return_value = True

    result = browser.handle("back", mock_core)

    assert result is True
    assert mock_handle_cmd.called
    assert mock_handle_cmd.call_args.args == ("back", mock_core)
    assert mock_browser_mode.called
    assert mock_browser_mode.call_args.args[0] == mock_core


@patch.object(browser, "handle_browser_command")
def test_handle_unmatched_command(mock_handle_cmd, mock_core):
    """Test handle function with unmatched command."""
    mock_handle_cmd.return_value = None

    result = browser.handle("unrelated command", mock_core)

    assert result is None


@patch.object(browser, "handle_browser_command")
@patch.object(browser, "browser_mode")
def test_handle_browser_command_exception(
    mock_browser_mode, mock_handle_cmd, mock_core, capsys
):
    """Test handle function handles exceptions gracefully."""
    mock_handle_cmd.side_effect = Exception("Test error")

    result = browser.handle("back", mock_core)

    assert result is True
    captured = capsys.readouterr()
    assert "Browser error:" in captured.out


# Tests for listen_for_hint function.


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_timeout(mock_qb, mock_sleep, mock_core_factory, capsys):
    """When no speech is detected, hints are cancelled and mode-leave is called."""
    mock_core = mock_core_factory(wait_for_speech_values=[None])

    browser.listen_for_hint(mock_core)

    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"
    captured = capsys.readouterr()
    assert "Timeout - hints cancelled" in captured.out


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_no_transcription_timeout(
    mock_qb, mock_sleep, mock_core_factory, capsys
):
    """When transcription fails twice, hints are cancelled."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", None], transcribe_values=[None]
    )

    browser.listen_for_hint(mock_core)

    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"
    captured = capsys.readouterr()
    assert "no transcription" in captured.out


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_no_transcription_retry_success(
    mock_qb, mock_sleep, mock_core_factory, capsys
):
    """When first transcription fails but second succeeds, hint is followed."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=[None, "zero two"],
    )

    browser.listen_for_hint(mock_core)

    assert mock_qb.call_count == 2
    assert mock_qb.call_args_list[0].args[0] == "hint-follow 02"
    assert mock_qb.call_args_list[1].args[0] == "fake-key <Escape>"


@pytest.mark.parametrize(
    "cancel_command",
    [
        "exit links",
        "exit link",
        "cancel",
        "nevermind",
        "stop",
        "close",
        "exit",
    ],
)
@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_cancel(
    mock_qb, mock_sleep, cancel_command, mock_core_factory, capsys
):
    """When cancel command is spoken, hints are cancelled."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1"], transcribe_values=[cancel_command]
    )

    browser.listen_for_hint(mock_core)

    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"
    captured = capsys.readouterr()
    assert "Hints cancelled" in captured.out


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_successful_hint(
    mock_qb, mock_sleep, mock_core_factory, capsys
):
    """When a valid hint number is spoken, it is followed."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1"], transcribe_values=["zero two"]
    )

    browser.listen_for_hint(mock_core)

    assert mock_qb.call_count == 2
    assert mock_qb.call_args_list[0].args[0] == "hint-follow 02"
    assert mock_qb.call_args_list[1].args[0] == "fake-key <Escape>"
    captured = capsys.readouterr()
    assert "Hint:" in captured.out


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_phonetic_fallback(
    mock_qb, mock_sleep, mock_core_factory, capsys
):
    """When parse_hint_number returns empty but parse_hint_numbers succeeds (defensive coding)."""
    # Note: In practice, since NUM_WORDS is a superset of HINT_NUMBERS,
    # if parse_hint_number returns empty, parse_hint_numbers will too.
    # This tests the code path even if it's rarely/never reached.
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1"], transcribe_values=["zero"]
    )

    # Mock parse_hint_number to return empty to force phonetic fallback
    with patch.object(browser, "parse_hint_number", return_value=""):
        browser.listen_for_hint(mock_core)

    assert mock_qb.call_count == 2
    assert mock_qb.call_args_list[0].args[0] == "hint-follow 0"
    assert mock_qb.call_args_list[1].args[0] == "fake-key <Escape>"
    captured = capsys.readouterr()
    assert "Phonetic:" in captured.out


@patch("time.sleep")
@patch.object(browser, "qb")
def test_listen_for_hint_audio_buffer_exception(
    mock_qb, mock_sleep, mock_core_factory, capsys
):
    """When clearing audio buffer raises exception, it is caught and ignored."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[None], transcribe_values=["exit browser"]
    )
    # Make stream.read raise an exception
    mock_core.stream.read.side_effect = Exception("Audio buffer error")

    browser.listen_for_hint(mock_core)

    # Should still work despite the exception
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"
    captured = capsys.readouterr()
    assert "Timeout - hints cancelled" in captured.out


@patch("time.sleep")
@patch.object(browser, "handle_browser_command")
@patch.object(browser, "qb")
def test_listen_for_hint_not_a_hint_pass_through(
    mock_qb, mock_handle_cmd, mock_sleep, mock_core_factory, capsys
):
    """When command is not a hint, it is passed to handle_browser_command."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1"], transcribe_values=["go back"]
    )

    browser.listen_for_hint(mock_core)

    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "mode-leave"
    assert mock_handle_cmd.called
    assert mock_handle_cmd.call_args.args == ("go back", mock_core)
    captured = capsys.readouterr()
    assert "Not a hint, trying as command" in captured.out


# Tests for browser_mode function.


@patch.object(browser, "handle_browser_command")
def test_browser_mode_timeout_continue(mock_handle_cmd, mock_core_factory, capsys):
    """When wait_for_speech times out, browser_mode continues listening."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[None, b"audio"], transcribe_values=["exit browser"]
    )

    browser.browser_mode(mock_core)

    assert mock_core.speak.call_count == 1
    assert mock_core.speak.call_args.args[0] == "Browser"
    captured = capsys.readouterr()
    assert "BROWSER MODE ACTIVE" in captured.out
    assert "BROWSER MODE EXIT" in captured.out


@patch.object(browser, "handle_browser_command")
def test_browser_mode_no_transcription_continue(
    mock_handle_cmd, mock_core_factory, capsys
):
    """When transcribe returns None, browser_mode continues listening."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=[None, "exit browser"],
    )

    browser.browser_mode(mock_core)

    captured = capsys.readouterr()
    assert "BROWSER MODE EXIT" in captured.out


@pytest.mark.parametrize(
    "exit_command",
    [
        "exit browser",
        "leave browser",
        "stop browser",
        "quit browser",
        "close browser",
    ],
)
@patch.object(browser, "handle_browser_command")
def test_browser_mode_exit(mock_handle_cmd, exit_command, mock_core_factory, capsys):
    """When exit browser command is spoken, browser_mode exits."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=[exit_command]
    )

    browser.browser_mode(mock_core)

    captured = capsys.readouterr()
    assert "BROWSER MODE EXIT" in captured.out
    assert exit_command in captured.out


@pytest.mark.parametrize(
    "grid_trigger",
    [
        "grid",
        "grit on screen",  # Phonetic variation of grid
        "show grip",  # Phonetic variation of grid
        "mouse click",
        "pointer move",
        "cursor here",
    ],
)
@patch.object(browser, "handle_browser_command")
def test_browser_mode_grid_trigger(
    mock_handle_cmd, grid_trigger, mock_core_factory, capsys
):
    """When grid trigger word is detected, browser_mode exits to grid mode."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=[grid_trigger]
    )

    browser.browser_mode(mock_core)

    assert mock_core.route_command.call_count == 1
    assert mock_core.route_command.call_args.args[0] == grid_trigger
    captured = capsys.readouterr()
    assert "BROWSER MODE EXIT → GRID" in captured.out


@patch.object(browser, "handle_browser_command", return_value=False)
def test_browser_mode_unknown_command(mock_handle_cmd, mock_core_factory, capsys):
    """When an unknown command is spoken, browser_mode prints unknown message."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio1", b"audio2"],
        transcribe_values=["unknown command", "exit browser"],
    )

    browser.browser_mode(mock_core)

    captured = capsys.readouterr()
    assert "? Unknown: unknown command" in captured.out


@patch.object(browser, "handle_browser_command")
def test_browser_mode_audio_buffer_exception(
    mock_handle_cmd, mock_core_factory, capsys
):
    """When clearing audio buffer raises exception, it is caught and ignored."""
    mock_core = mock_core_factory(
        wait_for_speech_values=[b"audio"], transcribe_values=["exit browser"]
    )
    # Make stream.read raise an exception
    mock_core.stream.read.side_effect = Exception("Audio buffer error")

    browser.browser_mode(mock_core)

    # Should still work despite the exception
    captured = capsys.readouterr()
    assert "BROWSER MODE EXIT" in captured.out


# Additional tests for handle_browser_command coverage.


@patch.object(browser, "qb")
def test_handle_browser_command_quickmark_load(mock_qb, mock_core):
    """When 'go to' with unknown bookmark, quickmark-load is used."""
    result = browser.handle_browser_command("go to mysite", mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "quickmark-load mysite"


@patch.object(browser, "qb_open")
def test_handle_browser_command_open_returns_none(mock_qb_open, mock_core):
    """When 'open' without 'go to' prefix, returns None to let other plugins handle."""
    result = browser.handle_browser_command("open myapp", mock_core)

    assert result is None
    assert not mock_qb_open.called


@patch.object(browser, "qb")
def test_handle_browser_command_phonetic_hint_not_digit(mock_qb, mock_core, capsys):
    """When looks_like_hint but phonetic parsing fails, returns None."""
    result = browser.handle_browser_command("xy", mock_core)

    assert result is None
    assert not mock_qb.called


@patch.object(browser, "qb")
def test_handle_browser_command_phonetic_hint_parsing(mock_qb, mock_core, capsys):
    """When looks_like_hint and phonetic parsing succeeds, hint is followed."""
    # Use a short command with number words that looks like a hint
    result = browser.handle_browser_command("one", mock_core)

    assert result is True
    assert mock_qb.called
    assert mock_qb.call_args.args[0] == "hint-follow 1"
    captured = capsys.readouterr()
    assert "Phonetic parsed:" in captured.out
