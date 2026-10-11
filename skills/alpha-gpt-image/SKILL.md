---
name: alpha-gpt-image
description: Generate or edit images with AlphaTech API using GPT Image 2 or Image2.5. Use for text-to-image, reference editing, and prompt refinement when the requested model is image2 or image2.5.
metadata:
  version: 1.2.0
---

# Alpha GPT Image

Use AlphaTech API's OpenAI-compatible image endpoints. Choose the model from the user's request: use `image2.5` when the user asks for Image2.5, Image 2.5, or equivalent; use `gpt-image-2` for Image2, GPT Image 2, or when no version is specified. An explicit `--model` always overrides automatic selection.

## Configuration

The included client resolves the AlphaTech key in this order: this Skill's own `config.json`, then `~/.config/alphatech/config.json`, then `ALPHATECH_API_KEY` / `ALPHATECH_BASE_URL`, then an AlphaTech relay already configured for [CC] via `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` (what CC Switch and the /keys page write). The package itself never contains a key — install it and reuse the credentials this machine already has, or set `ALPHATECH_API_KEY` (create one at https://alphatech.net.cn/keys). The default endpoint is https://alphatech.net.cn/v1.

Never print, summarize, transmit elsewhere, or commit the token. Users create and manage tokens at `https://alphatech.net.cn/console/token`.

## Prompt workflow

When drafting or improving a visual prompt, consult [the Chinese prompt guide](references/seedance2.5-prompting-guide-zh.md). Preserve the user's subject, composition, reference roles, requested edit, style, and exclusions. Convert motion language into one visible captured moment instead of inventing a timeline.

A prompt draft or diagnosis is not permission to generate. Submit a paid generation or edit only when the user explicitly asks, and submit it exactly once. Do not automatically retry a timeout or ambiguous result.

## Execution

Use the dependency-free client:

```bash
python3 scripts/alpha_image.py generate --prompt "..." --output /absolute/path/result.png
python3 scripts/alpha_image.py edit --prompt "..." --image /absolute/path/reference.png --output /absolute/path/result.png
python3 scripts/alpha_image.py models
```

Generation calls `POST /v1/images/generations` with JSON. Editing calls `POST /v1/images/edits` with multipart form data and supports one to six PNG, JPEG, or WebP local files or public HTTPS image URLs.

The client defaults to `--model auto` and resolves the requested model from the prompt. Use `--model image2.5` or `--model gpt-image-2` when the model must be fixed. AlphaTech's current Image2.5 aliases include `image2.5`, `image2.5-flare`, and `image2.5-sunburst`; use `models` to inspect currently enabled models.

Supported options include `--size`, `--quality`, `--background`, `--format`, and `--n`. Keep the requested output extension consistent with the selected format.

## Results and failures

The client saves Base64, data-URL, or public HTTPS results and reports absolute paths. Treat a request as successful only when every requested result is saved. If the API completed but saving failed, do not submit a replacement request automatically. Report the returned error code and whether request completion is known.
