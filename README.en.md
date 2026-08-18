# live-interpreter

Cloud simultaneous interpretation for YouTube / Twitch livestreams (speech-to-speech).

It captures live audio, translates it in real time via Alibaba Cloud Bailian's Qwen3.5-LiveTranslate model, and plays the translated speech back — with terminal subtitles, an OBS subtitle overlay, and an OBS video source for the original stream.

## Features

- Speech-to-speech realtime translation over streaming WebSocket (measured ~0.5s first-audio latency)
- YouTube / Twitch live streams, direct HLS (`.m3u8`) URLs, and local audio files
- 60 input languages, 29 output languages with voice (incl. Chinese/English/Japanese/Korean/etc.)
- 53 official voices, server-side voice cloning, hotwords glossary, source-language hints, adjustable VAD
- OBS integration: subtitle overlay (browser source), live video source (`--obs-video`), translated-audio mixing (virtual audio cable)
- Latency statistics (`--stats`), no-key capture self-test (`--mock`), connectivity check tool

## Quick Start

1. Install Python 3.10+, [ffmpeg](https://ffmpeg.org/), and yt-dlp (`pip install yt-dlp`)
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in `DASHSCOPE_API_KEY` and `QWEN_WORKSPACE_ID` (from the Alibaba Cloud Bailian console)
4. Run:

```powershell
python main.py "https://www.youtube.com/watch?v=<LIVE_ID>" --lang zh
```

Press `Ctrl+C` to exit.

## Documentation

Full documentation (in Chinese) is under [`docs/`](docs/README.md):

- Deployment guide ([docs/deployment.md](docs/deployment.md))
- Architecture ([docs/architecture.md](docs/architecture.md))
- Development guide ([docs/development.md](docs/development.md))
- OBS integration ([docs/obs.md](docs/obs.md))
- Troubleshooting ([docs/troubleshooting.md](docs/troubleshooting.md))

## Notes

- Your API key lives in `.env` (gitignored) — never commit it. See [SECURITY.md](SECURITY.md).
- Inside mainland China, access to YouTube/Twitch usually needs a proxy (`--proxy http://127.0.0.1:7890`); the Bailian API itself is reachable directly.
- Billing is token-based on Bailian (see the console for current prices; new users get a free quota).

## License

[MIT](LICENSE)
