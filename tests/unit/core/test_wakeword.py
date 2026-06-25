"""Tests for the pyopen-wakeword adapter."""

from unittest.mock import patch

from easyspeak.core.wakeword import WakeWordModel


@patch("easyspeak.core.wakeword.OpenWakeWord")
@patch("easyspeak.core.wakeword.OpenWakeWordFeatures")
@patch("easyspeak.core.wakeword.Model")
class TestWakeWordModel:
    """Tests for the WakeWordModel two-stage adapter."""

    def test_init_loads_shared_features_and_named_model(
        self, mock_model, mock_features, mock_oww
    ):
        """Construction loads the shared extractor and the model for the wake word."""
        wakeword = WakeWordModel("hey_jarvis")

        mock_features.from_builtin.assert_called_once_with()
        mock_model.assert_called_once_with("hey_jarvis")
        mock_oww.from_builtin.assert_called_once_with(mock_model.return_value)
        assert wakeword._features is mock_features.from_builtin.return_value
        assert wakeword._model is mock_oww.from_builtin.return_value

    def test_predict_returns_strongest_probability(
        self, mock_model, mock_features, mock_oww
    ):
        """predict feeds each feature window through the model and keeps the max."""
        features = mock_features.from_builtin.return_value
        model = mock_oww.from_builtin.return_value
        features.process_streaming.return_value = ["emb1", "emb2"]
        model.process_streaming.side_effect = [[0.1, 0.7], [0.3]]

        score = WakeWordModel().predict(b"\x00\x00")

        assert score == 0.7
        features.process_streaming.assert_called_once_with(b"\x00\x00")

    def test_predict_returns_zero_without_detections(
        self, mock_model, mock_features, mock_oww
    ):
        """predict reports 0.0 while the streaming buffers are still filling."""
        mock_features.from_builtin.return_value.process_streaming.return_value = []

        assert WakeWordModel().predict(b"") == 0.0

    def test_reset_clears_both_stages(self, mock_model, mock_features, mock_oww):
        """reset drops buffered state in both the extractor and the model."""
        features = mock_features.from_builtin.return_value
        model = mock_oww.from_builtin.return_value

        WakeWordModel().reset()

        features.reset.assert_called_once_with()
        model.reset.assert_called_once_with()
