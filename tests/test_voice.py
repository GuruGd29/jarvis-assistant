"""Voice messages: what reaches the message box, and when the app offers the mic. No model needed.

  .venv/bin/python -m unittest discover tests
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from jarvis.web import voice


class VoiceText(unittest.TestCase):
    def test_sounds_and_silence_are_not_words(self):
        self.assertEqual(voice.clean(" [BLANK_AUDIO]"), "")
        self.assertEqual(voice.clean(" (music) How much did I spend\n today?"), "How much did I spend today?")
        self.assertEqual(voice.clean(" இந்த வாரம் எவ்வளவு செலவு?"), "இந்த வாரம் எவ்வளவு செலவு?")
        self.assertEqual(voice.clean(" ."), "")

    def test_names_hint_ends_with_a_full_stop(self):
        for words, expected in (("Jarvis, Zomato", "Jarvis, Zomato."), ("Jarvis, Zomato.", "Jarvis, Zomato."), (" ", "")):
            with mock.patch.object(voice.config, "VOICE_WORDS", words):
                self.assertEqual(voice.hint(), expected)

    def test_keeps_only_the_newest_messages(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(voice.config, "SYSTEM_DIR", Path(tmp)), \
                mock.patch.object(voice.config, "VOICE_KEEP", 2), mock.patch.object(voice, "datetime") as clock:
            for second in range(3):
                clock.now.return_value = datetime(2026, 11, 2, 18, 0, second)
                voice.keep(b"RIFF", f"message {second}")
            folder = Path(tmp) / "logs" / "voice"
            self.assertEqual(sorted(p.name for p in folder.iterdir()), [
                "2026-11-02_18-00-01.txt", "2026-11-02_18-00-01.wav", "2026-11-02_18-00-02.txt", "2026-11-02_18-00-02.wav"])
            self.assertEqual((folder / "2026-11-02_18-00-02.txt").read_text(), "message 2\n")

    def test_no_mic_without_the_model(self):
        with mock.patch.object(voice.config, "WHISPER_MODEL", Path("/nonexistent/model.bin")):
            self.assertFalse(voice.available())
