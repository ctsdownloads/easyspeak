"""Tests for the browser plugin module."""

from unittest.mock import patch

import pytest
from easyspeak.plugins import browser


class TestParseHintNumbers:
    """Tests for parse_hint_numbers function."""

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
    def test_parse_hint_numbers(self, input_cmd, expected):
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
    def test_parse_hint_numbers_with_punctuation(self, input_cmd, expected):
        """Test parsing hint numbers with punctuation."""
        result = browser.parse_hint_numbers(input_cmd)

        assert result == expected


class TestLooksLikeHint:
    """Tests for looks_like_hint function."""

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
    def test_looks_like_hint(self, input_cmd, expected):
        """Test checking if command looks like a hint number."""
        result = browser.looks_like_hint(input_cmd)

        assert result == expected


class TestParseHintNumber:
    """Tests for parse_hint_number function."""

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
    def test_parse_hint_number(self, input_cmd, expected):
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
    def test_parse_hint_number_with_punctuation(self, input_cmd, expected):
        """Test parsing hint numbers with punctuation."""
        result = browser.parse_hint_number(input_cmd)

        assert result == expected

    def test_parse_hint_number_no_numbers(self):
        """Test parsing command with no numbers."""
        result = browser.parse_hint_number("hello world")

        assert result == ""


class TestParseSpokenUrl:
    """Tests for parse_spoken_url function."""

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
    def test_parse_spoken_url(self, spoken_url, expected):
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
    def test_parse_spoken_url_case_insensitive(self, spoken_url, expected):
        """Test URL parsing is case insensitive."""
        result = browser.parse_spoken_url(spoken_url)

        assert result == expected

    def test_parse_spoken_url_with_existing_protocol(self):
        """Test URL parsing preserves existing protocol."""
        result = browser.parse_spoken_url("https://example.com")

        assert result == "https://example.com"


class TestQbCommands:
    """Tests for qutebrowser command functions."""

    @patch.object(browser, "core")
    def test_qb(self, mock_core, capsys):
        """Test sending command to qutebrowser."""
        command = "reload"

        browser.qb(command)

        mock_core.host_run.assert_called_once_with(["qutebrowser", ":reload"])
        captured = capsys.readouterr()
        assert "🌐 qutebrowser :reload" in captured.out

    @patch.object(browser, "core")
    def test_qb_open(self, mock_core):
        """Test opening URL in qutebrowser."""
        url = "https://example.com"

        browser.qb_open(url)

        mock_core.host_run.assert_called_once_with(["qutebrowser", url])


class TestHandleBrowserCommand:
    """Tests for handle_browser_command function."""

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
    def test_handle_browser_command_hints(
        self, mock_listen, mock_qb, command, mock_core
    ):
        """Test handling hint commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with("hint")
        mock_listen.assert_called_once_with(mock_core)

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
    def test_handle_browser_command_hints_new_tab(
        self, mock_listen, mock_qb, command, mock_core
    ):
        """Test handling hint commands for new tab."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with("hint links tab")
        mock_listen.assert_called_once_with(mock_core)

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
    def test_handle_browser_command_navigation(
        self, mock_qb, command, qb_command, mock_core
    ):
        """Test handling navigation commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(qb_command)

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
    def test_handle_browser_command_scrolling(
        self, mock_qb, command, js_constant, mock_core
    ):
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
    def test_handle_browser_command_page_scroll(
        self, mock_qb, command, expected_js, mock_core
    ):
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
    def test_handle_browser_command_tabs(self, mock_qb, command, qb_command, mock_core):
        """Test handling tab commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(qb_command)

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
    def test_handle_browser_command_tab_switch(
        self, mock_qb, command, expected_tab, mock_core
    ):
        """Test switching to specific tab by number."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(f"tab-focus {expected_tab}")

    @pytest.mark.parametrize(
        ["command", "query"],
        [
            ["find test", "test"],
            ["find hello world", "hello world"],
        ],
    )
    @patch.object(browser, "qb")
    def test_handle_browser_command_find(self, mock_qb, command, query, mock_core):
        """Test handling find commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(f"search {query}")

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
        self, mock_qb, command, query, mock_core
    ):
        """Test that find next/previous are treated as search queries due to code logic."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(f"search {query}")

    @pytest.mark.parametrize(
        ["command", "qb_command"],
        [
            ["next match", "search-next"],
            ["previous match", "search-prev"],
        ],
    )
    @patch.object(browser, "qb")
    def test_handle_browser_command_find_navigation(
        self, mock_qb, command, qb_command, mock_core
    ):
        """Test handling find navigation commands that don't start with 'find'."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(qb_command)

    @pytest.mark.parametrize(
        "command",
        [
            "escape",
            "cancel",
            "nevermind",
        ],
    )
    @patch.object(browser, "qb")
    def test_handle_browser_command_escape(self, mock_qb, command, mock_core):
        """Test handling escape commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with("mode-leave")

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
    def test_handle_browser_command_bookmarks(
        self, mock_qb_open, command, site, url, mock_core
    ):
        """Test handling bookmark navigation commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb_open.assert_called_once_with(url)
        mock_core.speak.assert_called_once_with(f"Opening {site}.")

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
        self, mock_qb_open, command, expected_url, mock_core
    ):
        """Test handling spoken URL commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb_open.assert_called_once_with(expected_url)
        mock_core.speak.assert_called_once()

    @pytest.mark.parametrize(
        ["command", "query"],
        [
            ["search test", "test"],
            ["search for python tutorial", "python tutorial"],
            ["search linux tips", "linux tips"],
        ],
    )
    @patch.object(browser, "qb_open")
    def test_handle_browser_command_search(
        self, mock_qb_open, command, query, mock_core
    ):
        """Test handling search commands."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        expected_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
        mock_qb_open.assert_called_once_with(expected_url)
        mock_core.speak.assert_called_once_with(f"Searching for {query}.")

    @patch.object(browser, "qb")
    def test_handle_browser_command_bookmark_save(self, mock_qb, mock_core):
        """Test saving bookmark command."""
        result = browser.handle_browser_command("bookmark this as mysite", mock_core)

        assert result is True
        mock_qb.assert_called_once_with("quickmark-save mysite")
        mock_core.speak.assert_called_once_with("Saved as mysite.")

    @pytest.mark.parametrize(
        ["command", "hint"],
        [
            ["02", "02"],
            ["92", "92"],
            ["o2", "02"],
        ],
    )
    @patch.object(browser, "qb")
    def test_handle_browser_command_direct_hint(
        self, mock_qb, command, hint, mock_core, capsys
    ):
        """Test handling direct hint number input."""
        result = browser.handle_browser_command(command, mock_core)

        assert result is True
        mock_qb.assert_called_once_with(f"hint-follow {hint}")
        captured = capsys.readouterr()
        assert "Direct digits" in captured.out

    def test_handle_browser_command_unknown(self, mock_core):
        """Test handling unknown command returns None."""
        result = browser.handle_browser_command("unknown command", mock_core)

        assert result is None


class TestSetup:
    """Tests for setup function."""

    def test_setup(self, mock_core):
        """Test setup function sets core reference."""
        browser.setup(mock_core)

        assert browser.core == mock_core


class TestHandle:
    """Tests for handle function."""

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
    def test_handle_browser_mode(self, mock_browser_mode, command, mock_core):
        """Test handle function for entering browser mode."""
        result = browser.handle(command, mock_core)

        assert result is True
        mock_core.host_run.assert_called_once()
        call_args = mock_core.host_run.call_args
        assert call_args.args[0] == ["qutebrowser"]
        assert call_args.kwargs["background"] is True
        mock_browser_mode.assert_called_once_with(mock_core)

    @patch.object(browser, "handle_browser_command")
    @patch.object(browser, "browser_mode")
    def test_handle_browser_command_enters_mode(
        self, mock_browser_mode, mock_handle_cmd, mock_core
    ):
        """Test handle function enters browser mode after single command."""
        mock_handle_cmd.return_value = True

        result = browser.handle("back", mock_core)

        assert result is True
        mock_handle_cmd.assert_called_once_with("back", mock_core)
        mock_browser_mode.assert_called_once_with(mock_core)

    @patch.object(browser, "handle_browser_command")
    def test_handle_unmatched_command(self, mock_handle_cmd, mock_core):
        """Test handle function with unmatched command."""
        mock_handle_cmd.return_value = None

        result = browser.handle("unrelated command", mock_core)

        assert result is None

    @patch.object(browser, "handle_browser_command")
    @patch.object(browser, "browser_mode")
    def test_handle_browser_command_exception(
        self, mock_browser_mode, mock_handle_cmd, mock_core, capsys
    ):
        """Test handle function handles exceptions gracefully."""
        mock_handle_cmd.side_effect = Exception("Test error")

        result = browser.handle("back", mock_core)

        assert result is True
        captured = capsys.readouterr()
        assert "Browser error:" in captured.out
