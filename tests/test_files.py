"""Files in the app: a file attached to one chat, and the user's own files. No server, network or database.

  .venv/bin/python -m unittest discover tests
"""
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document

from jarvis import ocr
from jarvis.parse import parse_file
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
        with self.assertRaisesRegex(ValueError, "Jarvis can read PDF"):
            files.attach("photos.zip", b"PK\x03\x04")
        with self.assertRaisesRegex(ValueError, "no text"):
            files.attach("empty.txt", b"   \n ")
        with self.assertRaisesRegex(ValueError, "no longer there"):
            files.message_with("0" * 32, "hi")
        with self.assertRaisesRegex(ValueError, "no longer there"):
            files.message_with("../../etc", "hi")

    def test_a_message_without_a_file_is_unchanged(self):
        self.assertEqual(files.split_message("How much did I spend?"), (None, "How much did I spend?"))


def picture_of(lines: list[str], size=(1400, 900)):
    """A clean picture of some text, like a phone photo of a bill or a scanned page."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", size, 245)
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=48)
    for n, line in enumerate(lines):
        draw.text((80, 80 + n * 90), line, fill=20, font=font)
    return image


@unittest.skipUnless(ocr.available(), "Tesseract isn't installed (docs/files.md)")
class TextRecognition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("ATTACH_DIR", Path(self.tmp.name) / "attachments"), ("_db", mock.MagicMock())):
            patcher = mock.patch.object(files, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(ocr, "CACHE_DIR", Path(self.tmp.name) / "ocr")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_photo_of_a_bill_is_read(self):
        buffer = io.BytesIO()
        picture_of(["SRI KRISHNA SWEETS", "Mysore Pak 500g Rs 420", "TOTAL Rs 960"]).save(buffer, "JPEG")
        sent = files.attach("bill.jpg", buffer.getvalue())
        message, _ = files.message_with(sent["id"], "How much was the bill?")
        self.assertIn("960", message)
        self.assertIn("SWEETS", message)

    def test_a_scanned_pdf_is_read_page_by_page(self):
        path = Path(self.tmp.name) / "scan.pdf"
        first, second = picture_of(["Haemoglobin 13.8 g/dL"]), picture_of(["Vitamin D 21 ng/mL LOW"])
        first.save(path, save_all=True, append_images=[second], resolution=150)
        sections = parse_file(path)
        self.assertEqual([s.page for s in sections], [1, 2])
        self.assertIn("13.8", sections[0].text)
        self.assertIn("Vitamin D", sections[1].text)

    def test_quick_view_of_a_scan(self):
        root = Path(self.tmp.name) / "Jarvis"
        (root / "health").mkdir(parents=True)
        picture_of(["Fasting glucose 92 mg/dL"]).save(root / "health" / "lab.pdf", resolution=150)
        (root / "health" / ".hidden.txt").write_text("not shown")
        with mock.patch.object(files.config, "DATA_ROOT", root):
            seen = files.view("health/lab.pdf")
            self.assertEqual((seen["kind"], seen["pages"], seen["picture"]), ("pdf", 1, True))
            self.assertIn("glucose", seen["sections"][0]["text"])
            self.assertTrue(files.picture("health/lab.pdf", 1).startswith(b"\xff\xd8"))  # a JPEG of the page
            for outside in ("../../etc/passwd", "health/.hidden.txt", "health/missing.pdf"):
                with self.assertRaises(LookupError):
                    files.view(outside)
            with self.assertRaises(LookupError):
                files.picture("health/lab.pdf", 2)


class Names(unittest.TestCase):
    def test_safe_names(self):
        self.assertEqual(files.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(files.safe_name("C:\\Users\\me\\Bill: May?.pdf"), "Bill_ May_.pdf")
        self.assertEqual(files.safe_name("..."), "file")
        self.assertEqual(files.safe_name("ரசீது.pdf"), "ரசீது.pdf")  # Tamil names stay readable


if __name__ == "__main__":
    unittest.main()
