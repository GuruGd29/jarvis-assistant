# Files

Jarvis takes files in two separate ways.

| | 📎 in Chat | More → Your files |
|---|---|---|
| For | Asking about one file in one conversation, like ChatGPT or Claude | Your own documents that Jarvis should know about from now on |
| Where it goes | `state/attachments/`, kept 7 days so the chat can be re-read, then deleted | `~/Jarvis/<documents, finance, health or notes>/` |
| Searchable later | No. It isn't added to your files, searched in other chats or learned from | Yes: any chat can find and quote it, naming the file |

Both read PDF, Word (.docx), text, Markdown, CSV, JSON and HTML, up to 20 MB. A photo or a scanned PDF (a picture of
a page) has no text to read until text recognition is added.

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
