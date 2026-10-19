"""Tests for the standalone About dialog's metadata (core.about).

The libadwaita UI itself can only run on a live GNOME session with a display,
so it's excluded from coverage; these cover the gi-free parts: the version
lookup and the credit constants the dialog is built from.
"""

import importlib.metadata
from unittest.mock import patch

from easyspeak.core import about


class TestAppVersion:
    """Tests for resolving the installed package version."""

    @patch("easyspeak.core.about.importlib.metadata.version", return_value="1.2.3")
    def test_returns_installed_version(self, mock_version):
        """The dialog shows whatever version is actually installed."""
        assert about.app_version() == "1.2.3"
        assert mock_version.call_args.args[0] == "easyspeak-linux"

    @patch(
        "easyspeak.core.about.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    )
    def test_returns_empty_without_dist_metadata(self, mock_version):
        """A source checkout with no dist metadata shows no version, not an error."""
        assert about.app_version() == ""


class TestCredits:
    """Sanity checks on the metadata the About dialog advertises."""

    def test_lists_author_and_contributors(self):
        """The author headlines the developers; contributors are listed too."""
        assert about.DEVELOPER_NAME == "Matt Hartley"
        assert any("Matt Hartley" in d for d in about.DEVELOPERS)
        assert about.CONTRIBUTORS
        # No automated/bot accounts in the human credits.
        assert not any("Copilot" in c for c in about.CONTRIBUTORS)

    def test_credits_every_model_with_its_license(self):
        """Each shipped model names its owner and a license the dialog can show."""
        assert len(about.LEGAL) == 13
        for title, owner, license_id in about.LEGAL:
            assert title and owner.startswith("©"), title
            assert license_id in {"MIT", "Apache-2.0", *about.LICENSE_URLS}, title
        assert all(url.startswith("https://") for url in about.LICENSE_URLS.values())

    def test_links_out_to_the_project(self):
        """The repo, docs, issues and discussions links are all real https URLs."""
        for url in (
            about.REPO_URL,
            about.DOCS_URL,
            about.ISSUES_URL,
            about.DISCUSSIONS_URL,
        ):
            assert url.startswith("https://")


def test_about_html_credits_every_model():
    """The rich-text About information names each model with its license."""
    with patch.object(about, "app_version", return_value="1.2.3"):
        text = about.about_html()

    assert "<h3>EasySpeak 1.2.3</h3>" in text
    for title, _holder, license_id in about.LEGAL:
        assert title in text
        assert license_id in text


def test_about_html_escapes_markup():
    """Characters with a meaning in rich text are shown as text."""
    with patch.object(about, "COMMENTS", "Fast <and> local & private"):
        assert "Fast &lt;and&gt; local &amp; private" in about.about_html()
