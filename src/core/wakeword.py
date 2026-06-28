"""Wake-word detection backed by pyopen-wakeword.

Wraps rhasspy's pyopen-wakeword (an alternative openWakeWord implementation that
ships a bundled TensorFlow Lite and depends only on numpy). pyopen-wakeword
splits detection into a feature extractor and a per-word model and streams
probabilities; this thin wrapper just feeds one through the other and reports
the strongest score for the chunk. It is glue for that two-stage streaming API,
not a compatibility shim — there is no extra copy or conversion on the hot path.
"""

from pyopen_wakeword import Model, OpenWakeWord, OpenWakeWordFeatures

from .config import WAKE_WORD


class WakeWordModel:
    """Single-wake-word detector: scores 16 kHz PCM chunks for one wake word."""

    def __init__(self, wake_word: str = WAKE_WORD):
        """Load the shared feature extractor and the model for one wake word."""
        self._features = OpenWakeWordFeatures.from_builtin()
        self._model = OpenWakeWord.from_builtin(Model(wake_word))

    def predict(self, pcm: bytes) -> float:
        """Return the wake-word probability for a chunk of 16-bit mono 16 kHz PCM.

        pyopen-wakeword yields zero or more probabilities per chunk as its
        internal buffers fill; the strongest stands in for "latest score for
        this frame", so the caller's threshold check is unchanged.
        """
        score = 0.0
        for embeddings in self._features.process_streaming(pcm):
            for prob in self._model.process_streaming(embeddings):
                score = max(score, prob)
        return score

    def reset(self) -> None:
        """Drop buffered audio and embeddings so stale state can't fire a wake."""
        self._features.reset()
        self._model.reset()
