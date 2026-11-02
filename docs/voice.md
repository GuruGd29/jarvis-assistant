# Voice messages

Tap the **mic** beside Send in the app, speak, and tap **■** when done. The recording becomes text on your own
computer with [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (free, MIT licence), and the text lands in the
message box so you can check it before sending. English, Tamil and Tanglish work; it picks the language itself.
Nothing leaves your computer.

The app starts whisper.cpp's server when it starts and keeps the model loaded (about 1 GB of memory), so a voice
message turns into text in a second or two. Without the model file the app simply shows no mic button.

## On a Mac (Apple silicon)

```bash
brew install whisper-cpp
mkdir -p ~/jarvis-system/models
curl -L -o ~/jarvis-system/models/ggml-large-v3-turbo-q8_0.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin   # 874 MB
```

Then restart the app (`launchctl kickstart -k gui/$(id -u)/com.jarvis.web`). On an M1 Pro a 20-second message
takes about 1.6 seconds, on the graphics chip.

## On a Linux server

Build whisper.cpp ([its README](https://github.com/ggml-org/whisper.cpp#quick-start)), put `whisper-server` on the
`PATH`, and use a smaller model: large-v3-turbo is too slow without a graphics chip. On a 2-core server
`ggml-small-q8_0.bin` (264 MB) is the sensible choice:

```
JARVIS_WHISPER_MODEL=/home/ubuntu/jarvis-system/models/ggml-small-q8_0.bin
```

## Getting names right

Whisper knows common words but not your names, so "BookMyShow" can come out as "book video". List the apps, banks,
people and places you say often in `.env`, then restart the app:

```
JARVIS_VOICE_WORDS=Jarvis, BookMyShow, Zomato, Swiggy, HDFC, ICICI, Telegram, Velachery
```

Each message is also decoded carefully (5 candidates rather than the first guess). On a test clip with background
noise this turned "Paramburu" and "Vela Cherry" into "Paramaguru" and "Velachery", at the same speed.

To see how well it hears you, set `JARVIS_VOICE_KEEP=10`: the last 10 voice messages and the text each became are
kept in `logs/voice/` (on this computer only; older ones are deleted as new ones arrive).

`JARVIS_WHISPER_PORT` (default 8793) is the local port the app talks to whisper.cpp on. Its log is
`logs/whisper.log`.
