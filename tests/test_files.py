"""Files in the app: a file attached to one chat, and the user's own files. No server, network or database.

  .venv/bin/python -m unittest discover tests
"""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document

from jarvis.web import files

PLUGIN = Path(__file__).resolve().parent.parent / "hermes" / "plugins" / "jarvis" / "__init__.py"


def plugin_own_words():
    """The plugin's own_words(), without loading Hermes: the same pattern, taken from the plugin's source."""
    source = PLUGIN.read_text()
    pattern = re.search(r'_CHAT_FILE = re\.compile\((r".*?")\)\n', source).group(1)
    compiled = re.compile(eval(pattern))
    return lambda text: compiled.sub("", text or "").strip()


class ChatAttachment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(files, "ATTACH_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_attached_text_goes_with_the_message_and_comes_back_as_a_chip(self):
        sent = files.attach("Lease, final (v2).md", b"# Lease\n\nRent is 25,000 a month.\n\nDeposit: 3 months.")
        self.assertEqual((sent["name"], sent["cut"]), ("Lease, final (v2).md", False))
        message, name = files.message_with(sent["id"], "What is the deposit?")
        self.assertIn("Rent is 25,000 a month.", message)
        attached, own = files.split_message(message)
        self.assertEqual(attached, {"name": "Lease, final (v2).md", "info": sent["info"]})
        self.assertEqual(own, "What is the deposit?")
        self.assertEqual(name, "Lease, final (v2).md")
        # the plugin searches, learns and looks for commands in the user's own words only
        self.assertEqual(plugin_own_words()(message), "What is the deposit?")

    def test_word_files_and_long_files(self):
        doc = Document()
        doc.add_paragraph("Insurance policy 42. Renews on 15 December.")
        path = Path(self.tmp.name) / "policy.docx"
        doc.save(path)
        sent = files.attach("policy.docx", path.read_bytes())
        self.assertIn("words", sent["info"])
        long = files.attach("notes.txt", ("word " * 20_000).encode())
        self.assertTrue(long["cut"])

    def test_what_cannot_be_attached(self):
        with self.assertRaisesRegex(ValueError, "Photos"):
            files.attach("photo.jpg", b"\xff\xd8\xff")
        with self.assertRaisesRegex(ValueError, "no text"):
            files.attach("empty.txt", b"   \n ")
        with self.assertRaisesRegex(ValueError, "no longer there"):
            files.message_with("0" * 32, "hi")
        with self.assertRaisesRegex(ValueError, "no longer there"):
            files.message_with("../../etc", "hi")

    def test_a_message_without_a_file_is_unchanged(self):
        self.assertEqual(files.split_message("How much did I spend?"), (None, "How much did I spend?"))


class Names(unittest.TestCase):
    def test_safe_names(self):
        self.assertEqual(files.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(files.safe_name("C:\\Users\\me\\Bill: May?.pdf"), "Bill_ May_.pdf")
        self.assertEqual(files.safe_name("..."), "file")
        self.assertEqual(files.safe_name("ரசீது.pdf"), "ரசீது.pdf")  # Tamil names stay readable


if __name__ == "__main__":
    unittest.main()
