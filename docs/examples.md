# Examples: 12-video demo (April 2026)

Pipeline output across mixed sources. All runs used the default `--tier=lite` (Gemini Flash Lite, free-tier). Wall times exclude the yt-dlp download.

| # | Source | Length | Path taken | Blocks | Wall | Classification |
|---|---|---|---|---|---|---|
| 1 | YT `ybSWI2cZzIU` | ~13 min | visual (single-pass) | 9 | 71 s | **skill**: Claude + Ghidra MCP reverse engineering tutorial |
| 2 | YT `W4EwfEU8CGA` | 2h 39min | visual (10-window sliding) | 25 | 105 s vision | **skill**: 1M req/sec load-testing |
| 3 | YT `iX8g4LqF8p8` | 21 min | visual (single-pass) | 11 | 85 s | **skill**: 7 authentication concepts |
| 4 | YT `C842vFY5kRo` | ~2h | visual (9-window sliding) | 15 | ~4 min | **skill**: system design + API |
| 5 | YT Short `Yj9qOWnipTQ` | 1.0 min | short-path (File API) | 1 | 60 s | note: data pipeline overview |
| 6 | YT Short `b4TpO9pYpqk` | 1.0 min | short-path (File API) | 1 | 55 s | **skill**: 5 API performance tips |
| 7 | TikTok `7593…462` | 1.6 min | visual (captions missing → whisper) | 3 | 130 s | **rule**: keep abstraction levels consistent |
| 8 | TikTok `7617…054` | 1.5 min | visual | 4 | 100 s | **rule**: highest-level function at top |
| 9 | TikTok `7617…470` | 1.3 min | visual | 5 | 95 s | **rule**: vertical whitespace for readability |
| 10 | TikTok `7618…422` | 1.6 min | visual | 4 | 100 s | **rule**: declare vars close to usage |
| 11 | TikTok `7620…534` | 1.9 min | visual | 5 | 115 s | **rule**: expose behavior, not data |
| 12 | TikTok `7594…998` | 1.1 min | visual | 4 | 75 s | **skill**: replace switches with polymorphism |

**Distribution**: 7 skills / 5 rules / 1 note / 0 discard.

## What the sliding window looked like on video 2

`W4EwfEU8CGA`: 2h 39min, 360p download (picked automatically because duration > 90 min).

```
[3/6 TARGETING] google_genai:gemini-flash-lite-latest windowed read: 11 × 15-min passes
[3/6 TARGETING] window 1/11: 0s → 900s
[3/6 TARGETING] window 2/11: 900s → 1800s
...
[3/6 TARGETING] window 11/11: 9000s → 9558s
[3/6 TARGETING] kept 25 targets (after filtering)
[4/6 KEYFRAMES] extracting 25 frames via ffmpeg
[5/6 VISION] google_genai:gemini-flash-lite-latest fusing 25 frames (6-way concurrent, rate-limited)
[5/6 VISION] done (105.1s)
```

Rate-limit math: 25 frames × 13 req / 60 s cap = ~115 s theoretical minimum. Actual 105 s because the limiter allows an initial burst of 13 before throttling kicks in.

## What a TikTok extraction looked like

`7617132278875016470`: 1m 20s, no platform captions, whisper kicks in.

```
[1/6 INGEST] downloading 'The simplest formatting rules do the most heavy lifting.' (1.3 min)
[1/6 INGEST] done (5.7s)
[2/6 TRANSCRIBE] no captions: running faster-whisper small.en (CPU int8)
[2/6 TRANSCRIBE] done (38.7s)
[PROBE] → visual (confidence 1.00): The video consists entirely of code snippets and text overlays...
[3/6 TARGETING] kept 5 targets (after filtering)
[5/6 VISION] fusing 5 frames (5-way concurrent, rate-limited)
[5/6 VISION] done (18.7s)
[CLASSIFY] → rule: The video establishes a consistent convention for using vertical whitespace...
[6/6 FUSE] writing timeline → ~/.claude/cache/learn-video/7617132278875016470/fused.md
```

On subsequent TikTok runs the whisper model is already cached locally; only the audio processing time remains (~0.5× realtime on CPU int8).

## Issues encountered and fixed during the batch

| Problem | Patch |
|---|---|
| 3.3 GB 720p download of a 2.5 h talk timed out at 30 min | Duration-aware format selector: 720p/480p/360p tiers + scaled timeout (15 min – 1 h) |
| Sliding-window targeting hit an empty response on a Q&A window | `invoke_structured` now returns `schema()` default on empty content; windowed target loop catches per-window exceptions |
| `httpx.ReadError [WinError 10054]` during vision fan-out killed whole run | Added `httpx.TransportError` + `ServiceUnavailable` to retry set; vision fan-out now logs per-frame failures and continues |
| Gemini File API upload stuck at `FILESTATE.ACTIVE` (enum stringification) | Normalize state via `.rsplit(".", 1)[-1]`; poll budget raised 60 s → 5 min |

All four fixes shipped in the same branch; test suite grew from 63 → 74 green.
