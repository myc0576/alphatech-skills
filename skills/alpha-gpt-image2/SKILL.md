---
name: alpha-gpt-image2
description: Generate or edit raster images with GPT Image 2 through AlphaTech API. Use for text-to-image, reference-image editing, and prompt refinement when the user wants the AlphaTech relay.
metadata:
  version: 1.0.0
---

# Alpha GPT Image2

Use AlphaTech API's OpenAI-compatible image endpoints. The model is `gpt-image-2` unless the user explicitly selects another compatible AlphaTech model.

## Configuration

The included client reads this Skill's `config.json`, then allows `ALPHATECH_API_KEY` and `ALPHATECH_BASE_URL` to override it. The default endpoint is `https://alphatech.net.cn/v1`. A personalized package downloaded while signed in already contains the user's AlphaTech key.

Never print, summarize, transmit elsewhere, or commit the token. Users create and manage tokens at `https://alphatech.net.cn/console/token`.

## Prompt workflow

When drafting or improving a visual prompt, consult [the Chinese prompt guide](references/seedance2.5-prompting-guide-zh.md). Preserve the user's subject, composition, reference roles, requested edit, style, and exclusions. Convert motion language into one visible captured moment instead of inventing a timeline.

A prompt draft or diagnosis is not permission to generate. Submit a paid generation or edit only when the user explicitly asks, and submit it exactly once. Do not automatically retry a timeout or ambiguous result.

## Execution

Use the dependency-free client:

```bash
python3 scripts/alpha_image2.py generate --prompt "..." --output /absolute/path/result.png
python3 scripts/alpha_image2.py edit --prompt "..." --image /absolute/path/reference.png --output /absolute/path/result.png
python3 scripts/alpha_image2.py models
```

Generation calls `POST /v1/images/generations` with JSON. Editing calls `POST /v1/images/edits` with multipart form data and supports one to six PNG, JPEG, or WebP local files or public HTTPS image URLs.

Supported options include `--size`, `--quality`, `--background`, `--format`, and `--n`. Keep the requested output extension consistent with the selected format.

## Results and failures

The client saves Base64, data-URL, or public HTTPS results and reports absolute paths. Treat a request as successful only when every requested result is saved. If the API completed but saving failed, do not submit a replacement request automatically. Report the returned error code and whether request completion is known.

