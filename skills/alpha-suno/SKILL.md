---
name: alpha-suno
description: Generate songs, instrumentals, or lyrics through AlphaTech API's Suno-compatible route. Use for music creation, lyric generation, continuation, task polling, and result downloads.
metadata:
  version: 1.2.0
---

# Alpha Suno

Use AlphaTech API's Suno-compatible asynchronous endpoints. Do not expose or request an upstream provider key.

## Configuration

The included client resolves the AlphaTech key in this order: this Skill's own `config.json`, then `~/.config/alphatech/config.json`, then `ALPHATECH_API_KEY` / `ALPHATECH_BASE_URL`, then an AlphaTech relay already configured for [CC] via `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` (what CC Switch and the /keys page write). The package itself never contains a key — install it and reuse the credentials this machine already has, or set `ALPHATECH_API_KEY` (create one at https://alphatech.net.cn/keys). The default endpoint is https://alphatech.net.cn.

Never print or commit the token. Manage AlphaTech tokens at `https://alphatech.net.cn/console/token`.

## Execution boundary

A request to draft, improve, or diagnose a music prompt does not authorize generation. Submit only after an explicit request, make the billable submit call exactly once, and never automatically replace an ambiguous or failed task. Polling the same task is safe.

Use `MUSIC` for songs and instrumentals and `LYRICS` for lyric generation. Supported music fields include prompt, title, tags, `mv`, `make_instrumental`, `continue_at`, `continue_clip_id`, and `gpt_description_prompt`.

```bash
python3 scripts/alpha_suno.py generate --prompt "..." --title "..." --tags "..." --poll
python3 scripts/alpha_suno.py generate --prompt "..." --make-instrumental --poll --download-dir /absolute/path/output
python3 scripts/alpha_suno.py lyrics --prompt "..." --poll
python3 scripts/alpha_suno.py status --task-id TASK_ID
python3 scripts/alpha_suno.py models
```

The protocol details are in [the AlphaTech Suno protocol](references/newapi-suno-protocol.md). If AlphaTech has no enabled Suno channel, report that availability failure without switching providers or resubmitting.

On success, return the task ID, status, title, and available audio, video, image, or lyric fields. Report absolute paths for explicitly requested downloads. Never reveal bearer tokens or signed result URL query values.

