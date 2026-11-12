"""The notes Jarvis's Hermes plugin (hermes/plugins/jarvis) puts next to a question, loaded without Hermes."""
import importlib.util
import json
import sys
import tempfile
import threading
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


class FileLookup(unittest.TestCase):
    """The automatic file search runs, lighter, only for questions about the user's own things."""

    def lookup(self, question):
        provider = plugin.JarvisMemoryProvider()
        search = mock.MagicMock()
        search.request.return_value = {"results": None}  # not a medicine, calendar or money question
        search.search.return_value = []
        provider._search = search
        provider._lookup(question)
        return search.search.call_args

    def test_their_own_things_are_searched_with_the_lighter_settings(self):
        for question in ["When does my car insurance end?", "Where is the warranty card for the fridge?",
                         "What is the wifi password?", "When did I buy the washing machine?",
                         "en car insurance eppo mudiyum?", "என் கார் இன்சூரன்ஸ் எப்போது முடியும்?"]:
            call = self.lookup(question)
            self.assertIsNotNone(call, question)
            self.assertEqual((call.kwargs["pool"], call.kwargs["rerank_chars"]), (10, 800))

    def test_general_questions_are_not_searched(self):
        for question in ["Give me one fun fact about the moon", "What is 15% of 2400?", "Good morning Jarvis",
                         "Tell me a joke", "How do I make filter coffee?", "என்ன சமைக்கலாம்?"]:
            self.assertIsNone(self.lookup(question), question)


class ShorterContext(unittest.TestCase):
    """Fewer, shorter things ride along with a question: the model reads each of them before it answers."""

    def recall_request(self, question):
        provider = plugin.JarvisMemoryProvider()
        search = mock.MagicMock()
        search.request.return_value = {"results": None}
        search.search.return_value = []
        provider._search = search
        provider._context(question)
        return next(c.args[0] for c in search.request.call_args_list if c.args[0].get("op") == "recall")

    def test_earlier_chats_only_when_the_question_refers_back(self):
        for question in ["Good morning Jarvis", "When does my car insurance end?", "Plan my weekend"]:
            self.assertEqual(self.recall_request(question)["episodes"], 0, question)
        for question in ["What did we talk about last time?", "What did you suggest earlier?",
                         "Tell me again what I said about the trip", "naan munnadi enna sonnen?",
                         "நான் முன்னாடி என்ன சொன்னேன்?"]:
            self.assertEqual(self.recall_request(question)["episodes"], 2, question)

    def test_a_weak_second_passage_is_left_out_and_passages_are_short(self):
        strong = {"source": "/f/policy.pdf", "score": 0.5, "text": "x" * 2000}
        far = {"source": "/f/other.pdf", "score": -5.7, "text": "far"}
        near = {"source": "/f/near.pdf", "score": -1.5, "text": "near"}
        block, count = plugin.format_passages([strong, far])
        self.assertEqual(count, 1)
        self.assertIn("x" * 600 + "\n", block + "\n")
        self.assertNotIn("x" * 601, block)
        self.assertEqual(plugin.format_passages([strong, near])[1], 2)
        self.assertEqual(plugin.format_passages([{**near, "score": -9.0}])[1], 0)


class ChatPrompt(unittest.TestCase):
    """The pre_api_request hook keeps a new app chat's system message and tools for the keep-warm job."""

    def setUp(self):
        self.file = Path(tempfile.mkdtemp()) / "state" / "chat-prompt.json"
        patch = mock.patch.object(plugin, "CHAT_PROMPT", self.file)
        patch.start()
        self.addCleanup(patch.stop)
        self.system = {"role": "system", "content": "You are Jarvis. " * 2000}  # longer than the hook's own copy keeps
        self.tools = [{"type": "function", "function": {"name": "calendar_agenda", "parameters": {
            "type": "object", "properties": {"days": {"type": "array", "items": {"type": "object", "properties": {
                "date": {"type": "string"}}}}}}}}]

    def send(self, history, platform="api_server", api_call_count=1):
        """Like Hermes: the hook runs on a helper thread while the thread that built the request waits for it."""
        api_kwargs = {"model": "qwen3.5-4b-64k", "messages": [self.system, *history], "tools": self.tools}
        hook = threading.Thread(target=plugin.keep_chat_prompt, kwargs=dict(
            platform=platform, api_call_count=api_call_count, conversation_history=history,
            request_messages=list(api_kwargs["messages"]), request={"body": {"messages": "cut"}}))
        hook.start()
        hook.join(timeout=10)

    def test_first_request_of_a_new_app_chat_is_kept_in_full(self):
        self.send([{"role": "user", "content": "Hi"}])
        kept = json.loads(self.file.read_text())
        self.assertEqual(kept, {"model": "qwen3.5-4b-64k", "system": self.system, "tools": self.tools})
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_other_requests_are_not_kept(self):
        self.send([{"role": "user", "content": "Hi"}], platform="telegram")
        self.send([{"role": "user", "content": "Hi"}], api_call_count=2)  # after a tool call
        self.send([{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"},
                   {"role": "user", "content": "and tomorrow?"}])
        self.assertFalse(self.file.exists())

    def test_a_request_it_cannot_find_is_not_guessed(self):
        plugin.keep_chat_prompt(platform="api_server", api_call_count=1, conversation_history=[{"role": "user"}],
                                request_messages=[dict(self.system), {"role": "user", "content": "Hi"}])
        self.assertFalse(self.file.exists())

    def test_instant_answers_passed_along_are_not_the_users_words(self):
        message = ("and tomorrow?\n\n[Jarvis answered these earlier in this chat straight from the user's data "
                   "(not the model):\nQ: calendar today?\nA: Standup\n[end of earlier answers]")
        self.assertEqual(plugin.own_words(message), "and tomorrow?")


if __name__ == "__main__":
    unittest.main()
