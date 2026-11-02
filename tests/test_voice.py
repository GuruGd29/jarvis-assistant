"""Voice messages: what reaches the message box, and when the app offers the mic. No model needed.

  .venv/bin/python -m unittest discover tests
"""
import unittest
from pathlib import Path
from unittest import mock

from jarvis.web import voice


class VoiceText(unittest.TestCase):
    def test_sounds_and_silence_are_not_words(self):
        self.assertEqual(voice.clean(" [BLANK_AUDIO]"), "")
        self.assertEqual(voice.clean(" (music) How much did I spend\n today?"), "How much did I spend today?")
        self.assertEqual(voice.clean(" இந்த வாரம் எவ்வளவு செலவு?"), "இந்த வாரம் எவ்வளவு செலவு?")

    def test_no_mic_without_the_model(self):
        with mock.patch.object(voice.config, "WHISPER_MODEL", Path("/nonexistent/model.bin")):
            self.assertFalse(voice.available())
