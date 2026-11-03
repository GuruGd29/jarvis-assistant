# Files

Jarvis takes files in two separate ways.

| | 📎 in Chat | More → Your files |
|---|---|---|
| For | Asking about one file in one conversation, like ChatGPT or Claude | Your own documents that Jarvis should know about from now on |
| Where it goes | `state/attachments/`, kept 7 days so the chat can be re-read, then deleted | `~/Jarvis/<documents, finance, health or notes>/` |
| Searchable later | No. It isn't added to your files, searched in other chats or learned from | Yes: any chat can find and quote it, naming the file |

Both read PDF, Word (.docx), text, Markdown, CSV, JSON and HTML, and photos (JPG, PNG, WebP, HEIC), up to 20 MB.
Photos and scanned PDFs are read with text recognition (below).

## Attaching a file to a chat

Tap the paperclip next to the message box (on a computer you can also drop the file onto the chat), then ask your
question. A chip above the box shows the file once it has been read; × removes it. Sending with no question asks for
a short summary.

The file's text goes to the AI with your message: up to about 15,000 words, which leaves room for the conversation.
A longer file is cut there, and the chip says so. In the chat the message shows the file as a chip, never its text.
The Jarvis plugin (`hermes/plugins/jarvis`) cuts the file out before it searches your files and memory, looks for
commands like "remember …" or a "yes" to a pending change, or queues the message for learning, so nothing in the
file becomes a fact about you.

## Your files

**More → Your files** lists every file in `~/Jarvis` by folder, with whether Jarvis can search it. Pick a folder,
then **Choose a file** (or drop one on the page on a computer): it is saved and indexed at once, usually in under a
second, and Jarvis can answer from it in any chat. A file with the same name gets " (2)". The bin deletes a file from
the folder and from the index.

Files you put in `~/Jarvis` yourself, or send to the Telegram bot, appear here too. The folder is still read every
15 minutes (`jarvis-ingest`), so adding files in Finder keeps working.

### Quick view

Tap a file to open it in the app: a photo is shown as it is, a PDF page by page (10 at a time, **Show more pages**
for the rest), and under it (beside it on a computer) the text Jarvis read in it, page by page. That text is what
Jarvis searches and quotes, so it is the place to check when an answer looks wrong. **Open** shows the file itself
in the browser (PDFs, photos, text) or downloads it (Word and other files); **Delete** is the same as the bin.

The file and its pages are never kept on the phone; what Jarvis read is, so it can still be read offline.

## Text recognition (photos and scans)

A photo of a bill, a screenshot or a scanned PDF is a picture of words, not text. Jarvis reads it with
[Tesseract](https://github.com/tesseract-ocr/tesseract) (free and open source, Apache 2.0), on your own computer:

- **Photos** (JPG, PNG, WebP; HEIC from an iPhone is converted first with `sips` on a Mac or `heif-convert` on Linux).
  A sideways phone photo is turned upright first.
- **Scanned PDFs**: a page with almost no text in it (under 60 characters, as when a scanner app stamps one line on
  it) is also read as a picture, and the reading with more text is kept. Up to 30 pages of a scan are read.

A photo takes under a second, a scanned page one or two seconds. What was read is kept in `state/ocr/` by the
file's content, so indexing again or opening the file in the quick view doesn't read it twice.

Languages: English, plus the ones in `JARVIS_LANGUAGES` that Tesseract has installed (Tamil, Hindi, Telugu,
Kannada, Malayalam and others), or exactly `JARVIS_OCR_LANGS` (e.g. `eng+tam`). `install.sh` installs Tesseract and
those languages on Linux. On a Mac:

```bash
brew install tesseract
# one more language, e.g. Tamil (about 3 MB; `brew install tesseract-lang` adds all of them, about 650 MB):
curl -fLo "$(brew --prefix)/share/tessdata/tam.traineddata" https://github.com/tesseract-ocr/tessdata_fast/raw/main/tam.traineddata
```

Restart the app afterwards. Homebrew keeps that file inside Tesseract's own folder, so after
`brew upgrade tesseract` run the `curl` line again. Without Tesseract, photos can't be added and a scanned PDF has no text, as before.
Photos in Google Drive aren't copied by "sync drive" (a Drive full of photos would fill the disk); scanned PDFs are.
