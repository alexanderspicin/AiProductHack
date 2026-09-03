# AiProductHack — локальный голосовой ассистент с 3D-аватаром

A local voice + 3D avatar assistant, inspired by [ykshv/rula](https://github.com/ykshv/rula), built on
[Pipecat](https://pipecat.ai) with local (on-device) turn detection.

- **Transport**: local WebSocket (no LiveKit/Daily required)
- **Turn detection**: local — Silero VAD (turn start) + Pipecat's Smart Turn v3 ONNX model (turn end)
- **STT**: local — faster-whisper via Pipecat's `WhisperSTTService`
- **LLM**: OpenAI API
- **TTS**: Inworld API
- **Avatar**: any glTF (`.glb`) avatar with Oculus viseme blendshapes, animated in the browser with
  plain Three.js (no VRM layer) — driven by small JSON "avatar events" pushed alongside the TTS audio
  (see `backend/app/avatar/protocol.py` / `frontend/src/protocol/avatarProtocol.ts`). Lip sync is
  **fully local** and **text-driven** (primary source, `backend/app/avatar/viseme_text.py`): Inworld TTS
  provides word-level timing, which pipecat delivers as `TTSTextFrame`s interleaved in playback order
  with the audio — so instead of guessing mouth shape from the audio spectrum, we know which word is
  actually being spoken and schedule visemes letter-by-letter across it (Russian orthography is close
  enough to phonetic for a simple per-letter viseme table, vowels held longer than consonants). Falls
  back to spectral audio classification (`viseme_analysis.py`, a Python port of
  [wawa-lipsync](https://github.com/wass08/wawa-lipsync)'s Oculus-LipSync-based algorithm, MIT) for any
  chunk that arrives before word timing is available — e.g. right at utterance start, or if a future TTS
  swap doesn't provide word timestamps. Same 15-viseme Oculus set either way
  (`sil`/`PP`/`FF`/`TH`/`DD`/`kk`/`CH`/`SS`/`nn`/`RR`/`aa`/`E`/`I`/`O`/`U`). No external model/service, no
  network round trip. This replaced an earlier NVIDIA Audio2Face-3D integration (real ARKit blendshapes,
  but a self-hosted gRPC service added per-utterance connect latency and Docker/NGC/GPU infra hassle)
  and, before that, spectral-analysis-only lip sync that looked like a fish mouth opening/closing with no
  real articulation — the text-driven timing is what actually fixed that.

Pipecat already handles barge-in/interruption internally (VAD + Smart Turn drive its built-in
`InterruptionFrame` machinery), so this project does not reimplement rula's `turn_id`/`generation_id`/
`branch_state` state machine — only a small `utterance_id` counter is used so the frontend can discard
stale avatar events after an interrupt.

## Backend

```
pip install -e .
cp .env.example backend/.env   # then fill in OPENAI_API_KEY / INWORLD_API_KEY
cd backend
python app/bot.py
```

(`.env` must live in `backend/`, next to where `bot.py` is run from — both `python-dotenv` and
`pydantic-settings` resolve it relative to the working directory.)

Starts a local dev server at `http://localhost:7860` (the `/start` endpoint bootstraps a session, then
upgrades to a WebSocket). On Windows, if you see a `UnicodeEncodeError` from the startup banner, run with
`PYTHONIOENCODING=utf-8` set (a PowerShell console codepage issue, not a bug in this project).

## Frontend

```
cd frontend
npm install
cp .env.example .env   # defaults to http://localhost:7860, edit if needed
npm run dev
```

Open http://localhost:5173, click **Connect**, and talk.

### Avatar asset

Place a `.glb` at `frontend/public/models/avatar.glb`. It needs the **Oculus Visemes** morph target set
(`viseme_sil`, `viseme_PP`, `viseme_aa`, ... — matched case-insensitively) for the lip sync to drive it;
ARKit shapes are optional (only used by the synthetic "still talking, event was late" fallback in
`visemeDriver.ts`, keyed on `jawOpen`).

**Ready Player Me shut down** (Netflix acquired it, then discontinued the public avatar creator/API on
2026-01-31) — it's no longer a source for this. Currently in place: `avatars/brunette.glb` from
[met4citizen/TalkingHead](https://github.com/met4citizen/TalkingHead) (MIT-licensed repo; the demo
avatar itself predates the shutdown and was originally made with Ready Player Me — fine for a local
prototype, don't assume it's clear for commercial redistribution). That repo's `avatars/` folder has a
few other ready-to-use options (`avaturn.glb`, `vroid.glb`, `avatarsdk.glb`, `mpfb.glb`), all pre-rigged
with both Oculus visemes and ARKit shapes:
```
https://raw.githubusercontent.com/met4citizen/TalkingHead/main/avatars/<name>.glb
```
To make your own from a live service instead: [Avaturn](https://avaturn.me) is Ready Player Me's
closest surviving equivalent (free tier, photo-to-avatar, explicitly ships ARKit + Oculus viseme
blendshapes) but requires a free account at developer.avaturn.me; [VRoid Studio](https://vroid.com/en/studio)
is a free desktop app for anime-style characters but only exports the smaller VRM 0.x preset set
(no `viseme_*` names) — would need re-rigging to work with this project's lip sync as-is.

Without a matching `.glb` in place, the scene still runs (voice pipeline works), just with no visible
avatar mesh.

## Docker

```
cp .env.example .env     # fill in OPENAI_API_KEY / INWORLD_API_KEY
docker compose up --build
```

Then open http://localhost:5173. Backend is on http://localhost:7860.

Runs as-is on **linux/amd64 and on Apple Silicon** — the CPU image pulls only
prebuilt manylinux wheels (`ctranslate2`, `onnxruntime`, `av`), all of which
publish `aarch64` builds, and there is no torch and no compiler in the image.
To publish a multi-arch image from one machine:

```
docker buildx build --platform linux/amd64,linux/arm64 \
  -f backend/Dockerfile --target cpu -t <registry>/rula-backend:latest --push .
```

### GPU

```
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

amd64 only (CUDA 12.6 + cuDNN base image), needs the NVIDIA Container Toolkit on
the host. It switches Whisper to `cuda`/`float16`/`medium`.

### Things worth knowing

- **`WHISPER_DEVICE` and `WHISPER_COMPUTE_TYPE` from `.env` are ignored in
  Docker** — compose pins them per target (`environment` overrides `env_file`).
  The repo's `.env` is written for the host machine (`cuda`/`float16`), which is
  wrong in a CPU container and fatal on a Mac. API keys still come from `.env`.
- The CPU stack defaults to `WHISPER_MODEL=small`; `medium` is slower than real
  time on most laptop CPUs. Override with
  `WHISPER_MODEL_OVERRIDE=base docker compose up` — a distinct variable name on
  purpose, since compose substitutes `${WHISPER_MODEL}` from the very `.env`
  whose host-tuned value we're trying not to inherit.
- `docker compose config` prints resolved values, API keys included. Redirect it
  somewhere private, or use `--quiet` when you only want validation.
- Model weights (Whisper, Smart Turn v3) download on first use into the
  `model-cache` volume, so only the first start pays for it. `docker compose down
  -v` throws them away.
- The frontend bakes the backend URL in at build time (Vite inlines
  `import.meta.env`), so changing `VITE_PIPECAT_BASE_URL` needs `--build`, not
  just a restart.
- Ports are overridable: `BACKEND_PORT`, `FRONTEND_PORT`.
- The browser needs a secure context for microphone access. `http://localhost`
  counts as one; reaching the container from *another* machine by IP does not —
  that needs TLS in front.
- Pipecat's runner builds the client's WebSocket URL from its own `--host`,
  which inside a container has to be `0.0.0.0` — an address the browser can't
  dial. `resolveWsUrl()` in `frontend/src/main.ts` detects that and rebuilds the
  URL from `VITE_PIPECAT_BASE_URL`; without it the containerised backend would
  hand out `wss://0.0.0.0:7860/ws-client`.

## Tests

```
cd backend
pip install -e ".[dev]"
pytest tests/
```
