---
name: alpha-video
description: Design cinematic AI fight videos and submit approved generations through AlphaTech API. Use for combat choreography, shot plans, Seedance prompts, reference-led video creation, task polling, and result downloads.
metadata:
  version: 1.0.3
---

# Alpha Video

Turn plots, characters, weapons, locations, reference media, or existing prompts into readable and executable fight-video plans, then use AlphaTech API when the user explicitly requests generation.

## Configuration and execution boundary

The included client resolves the AlphaTech key in this order: this Skill's own `config.json`, then `~/.config/alphatech/config.json`, then `ALPHATECH_API_KEY` / `ALPHATECH_BASE_URL`, then an AlphaTech relay already configured for [CC] via `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` (what CC Switch and the /keys page write). The package itself never contains a key — install it and reuse the credentials this machine already has, or set `ALPHATECH_API_KEY` (create one at https://alphatech.net.cn/keys). The default endpoint is https://alphatech.net.cn.

Never print or commit a token. Manage AlphaTech tokens at `https://alphatech.net.cn/console/token`.

Prompt design is not permission to submit a paid task. Create a video only after an explicit generation request, submit exactly once, and never automatically replace an ambiguous or failed task. Polling and downloading the same task are safe.

```bash
python3 scripts/alpha_video.py models
python3 scripts/alpha_video.py create --model '64:seedance-2.0@1080p' --prompt "..." --seconds <user_requested_whole_seconds> --wait --download /absolute/path/result.mp4
python3 scripts/alpha_video.py create --model '64:seedance-2.0@1080p' --prompt "..." --reference /absolute/path/frame.png --wait
python3 scripts/alpha_video.py status --task-id TASK_ID
python3 scripts/alpha_video.py wait --task-id TASK_ID --download /absolute/path/result.mp4
```

`create` calls `POST /v1/videos`; status uses `GET /v1/videos/{task_id}`; download uses `GET /v1/videos/{task_id}/content`. AlphaTech video aliases use the `<channel>:<model>@<quality>` form (the legacy `aistarslab/` prefix is also accepted). Use `models` before generation when the current AlphaTech model name is uncertain. Model availability and price are determined by AlphaTech, not by this Skill.

`--seconds` is required and must be selected from the user's concrete duration requirement; this Skill never supplies a default or assumes a fixed duration. It is sent as an integer string because the downstream adapter requires whole seconds. `--size` is optional and, when supplied, must be one of AlphaTech's accepted aspect-ratio enums (`720x1280`, `1280x720`, `1792x1024`, or `1024x1792`). Do not pass arbitrary values such as `1920x1080` or `720P`; omit `--size` when the model alias already includes the desired quality.

## Multi-reference media chain

For multiple references, send JSON arrays using `inputImages`, `inputVideos`, and `inputAudios`. Each item may be a public HTTPS URL, a Data URL, or a local path; the client converts local paths to Data URLs. AlphaTech's AIStarsLab video adapter materializes Data URLs in its temporary asset directory, generates a random HTTPS URL under `/aistarslab-video-assets/`, and sends only those HTTPS URLs to the upstream channel. Single-file OpenAI-compatible multipart uses `input_reference`; use JSON arrays for multiple images, videos, or audio files.

```bash
python3 scripts/alpha_video.py create --model '64:seedance-2.0@1080p' --prompt "人物向前奔跑" --seconds <user_requested_whole_seconds> \
  --image /absolute/path/reference.png --video https://example.com/reference.mp4 --audio 'data:audio/mpeg;base64,...'
```

## Director workflow

1. Identify the real duration, aspect ratio, available assets, target model, and no more than two core audience takeaways.
2. Lock character identity, wardrobe, weapons, injuries, screen direction, and location geometry.
3. Build an attack-response-contact-result chain. Adjacent beats must inherit the previous end state.
4. Give each beat one dominant action, one main camera movement, one visible result, and one transition anchor.
5. Produce a rich director draft, then a reduced model-execution prompt that preserves the main causality.
6. Before delivery, audit identity continuity, spatial reachability, contact readability, model load, and whether the climax follows from accumulated action.

For platform limits and compilation, read [platform profiles](references/platform-prompt-profiles.md), [machine-readable profiles](references/platform-profiles.json), and [the motion contract](references/motion-performance-contract.md). For Seedance 2.5, also read [Seedance prompt engineering](references/seedance-2.5-prompt-engineering.md). The deterministic compiler can audit structured projects:

```bash
python3 scripts/prompt_compiler.py audit --input /absolute/path/project.json
python3 scripts/prompt_compiler.py compile --input /absolute/path/project.json
```

For choreography and camera decisions, consult [combat design](references/combat-design.md) and [shot grammar](references/shot-grammar-and-camera-direction.md). For final packaging and load reduction, consult [prompt output and QA](references/prompt-output-and-qa.md) and [negative constraints](references/negative-constraints.md). Use [acting integration](references/acting-performance-in-combat.md) only when performance changes tactics, and [single-shot execution](references/cinedance-shot-execution.md) only for one already validated beat.

Do not claim frame-accurate timing, guaranteed FPS, exact lens behavior, or execution that has not been observed in an actual result.
