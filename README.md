# reelhawk

An autonomous video clipping agent. Long-form video in, publish-ready vertical
clips out: it finds the strongest self-contained moments, cuts them at real
sentence boundaries, tracks the speaker for the crop, burns in word-synced
karaoke captions, quality-gates every clip, and exports or posts the winners.

Extracted from a pipeline that has been publishing daily clips from live-show
back-catalogs since mid-2026. The hard-won operational rules are baked into
the code and documented in [docs/lessons.md](docs/lessons.md).

## How it works

```
fetch ──> transcribe ──> mine ──> facetrack ──> render ──> gate ──> post
yt-dlp    faster-whisper  Claude   YuNet/SFace   ffmpeg     rules    export /
or local  word-level      finds    speaker pos,  9:16 crop  + LLM    Instagram
file      timestamps      moments  multi-speaker karaoke    review   Reels
                          + snaps  detection     captions
                          to sentence
                          boundaries
```

Every stage caches its artifact in the workdir, so re-runs are cheap and a
crashed run resumes where it stopped.

What makes the clips good rather than merely automatic:

- **Sentence-boundary cutting.** Clip edges snap to sentence starts and ends
  using word-level timestamps. Overlong clips are rescued by advancing the
  START to the next sentence — the payoff at the end is never cut.
- **Multi-speaker honesty.** If other people are in the conversation (face
  counting, not diarization, decides), the render refuses a single-face crop
  and shows the full frame.
- **A gate that fails closed.** Duration, caption coverage, complete-sentence
  ending, speaker-on-screen percentage, and an optional LLM check that the
  clip delivers the payoff its opening sets up. No PASS, no publish. A day
  with no good clip is a skipped day, never a padded one.
- **Optional identity lock.** Build a face embedding of your speaker from
  reference photos and the tracker follows that person specifically, not
  whoever is largest in frame.

## Quickstart

Requirements: Python 3.11+, `ffmpeg` and `ffprobe` on PATH, an Anthropic API
key.

```bash
pip install reelhawk            # or: pip install -e . from a checkout
export ANTHROPIC_API_KEY=sk-ant-...

# full pipeline on one video, results land in reelhawk-data/export/
reelhawk run "https://www.youtube.com/watch?v=VIDEO_ID"

# look before you cut: print the mined candidates and stop
reelhawk mine talk.mp4
```

Face tracking is optional:

```bash
pip install "reelhawk[face]"
python scripts/download_models.py          # YuNet + SFace from OpenCV Zoo
# optional identity lock:
python scripts/build_face_embedding.py photos/ speaker.npy
```

Then enable it in `reelhawk.yaml` (see `reelhawk.example.yaml` for every
option):

```yaml
face:
  enabled: true
  embedding: speaker.npy   # omit to track the most prominent face
```

## Running it as a daily agent

```bash
reelhawk daily "https://www.youtube.com/@yourchannel"
```

One deep mine of a long video banks several gate-passed clips; most daily runs
just publish the next banked clip at zero pipeline cost, and only mine when
the bank is empty. Put it in cron and it maintains a clip-per-day cadence for
as long as the back-catalog holds out. When it publishes nothing it says
exactly why, derived from actual state — never a canned story.

If you run it on a server, read the supply section of
[docs/lessons.md](docs/lessons.md) first: video platforms bot-wall datacenter
IPs for downloads (cookies will not save you), so pair a server pipeline with
downloads from a residential connection.

## Publishing

`post.mode: export` (default) writes the MP4, a composed caption, and metadata
to `workdir/export/` for human review. `post.mode: instagram` publishes
gate-passed clips as Reels via the Graph API (`IG_ACCESS_TOKEN` and
`IG_USER_ID` in the environment; the API fetches the video from a public URL,
so either provide `post.upload_cmd` or host the file yourself).

Two deliberate defaults: export mode, because the agent's judgment converges
on yours only while you keep rejecting its mistakes; and a `post.disclosure`
config field for a "clipped by an AI agent" caption line, because disclosing
automation costs nothing and buys trust.

## Configuration

Everything lives in `reelhawk.yaml` (all fields optional; the defaults are the
production values). Copy `reelhawk.example.yaml` and edit. Secrets are
environment-only: `ANTHROPIC_API_KEY`, `IG_ACCESS_TOKEN`, `IG_USER_ID`.

## Development

```bash
pip install -e ".[dev,face]"
pytest
black --check src tests scripts && isort --check src tests scripts
```

## License

MIT. Bundled font: Noto Sans Bold, SIL Open Font License 1.1
(`fonts/OFL.txt`). Face models downloaded from OpenCV Zoo are Apache-2.0.
