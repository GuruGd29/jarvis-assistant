"""The notes Jarvis's Hermes plugin (hermes/plugins/jarvis) puts next to a question, loaded without Hermes."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent / "hermes" / "plugins" / "jarvis" / "__init__.py"


def load_plugin():
    hermes_api = types.ModuleType("agent.memory_provider")
    hermes_api.MemoryProvider = object
    hermes_api.RecallStatus = dict
    hermes_api.spawn_context_thread = lambda *args, **kwargs: None
    with mock.patch.dict(sys.modules, {"agent": types.ModuleType("agent"), "agent.memory_provider": hermes_api}):
        spec = importlib.util.spec_from_file_location("jarvis_hermes_plugin", PLUGIN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # the search child process starts only on the first search
    return module


plugin = load_plugin()


class TanglishNote(unittest.TestCase):
    def test_tanglish_gets_plain_english_and_the_word_meanings(self):
        note = plugin.tanglish_note("naalaiku kaalaila 9 manikku water bill kattanum nu remind pannu")
        self.assertIn("Reply in simple, plain English, with no Tamil script", note)
        for meaning in ("naalaiku = tomorrow", "kaalaila = in the morning", "manikku = at (o'clock)",
                        "kattanum = need to pay"):
            self.assertIn(meaning, note)
        self.assertIn("vaaram = week", plugin.tanglish_note("Indha vaaram evlo selavu panniruken?"))

    def test_english_and_tamil_script_get_no_note(self):
        for message in ("How much did I spend this week?", "Remind me to call Enna tomorrow at 9 am",
                        "Show me the sari I bought la week", "என் கார் இன்சூரன்ஸ் எப்போது? evlo selavu", ""):
            self.assertEqual(plugin.tanglish_note(message), "", message)

    def test_one_tamil_word_is_not_enough(self):
        self.assertEqual(plugin.tanglish_note("selavu for this week?"), "")
        self.assertNotEqual(plugin.tanglish_note("selavu evlo?"), "")

    def test_the_note_comes_after_the_blocks(self):
        provider = plugin.JarvisMemoryProvider()
        with mock.patch.object(provider, "_context", return_value="[Jarvis file search: no related passages.]"), \
                mock.patch.object(provider, "_save_attachments", return_value=None):
            block = provider.prefetch("spotify eppo renew aagum?")
        self.assertTrue(block.startswith("[Jarvis file search: no related passages.]\n\n[The user wrote Tamil"))
        self.assertIn("eppo = when; aagum = will become / will happen", block)
        with mock.patch.object(provider, "_context", return_value=""), \
                mock.patch.object(provider, "_save_attachments", return_value=None):
            self.assertTrue(provider.prefetch("inniki enna plan?").startswith("[The user wrote Tamil"))
            self.assertEqual(provider.prefetch("What's the plan today?"), "")


if __name__ == "__main__":
    unittest.main()
