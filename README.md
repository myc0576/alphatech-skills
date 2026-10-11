# AlphaTech Skills

Agent Skills for the [AlphaTech API](https://alphatech.net.cn) — image, video and
music generation wired to one API key.

## Install

```bash
npx skills add https://alphatech.net.cn
```

That reads the site's
[`/.well-known/agent-skills/index.json`](https://alphatech.net.cn/.well-known/agent-skills/index.json)
and installs every published Skill into the agents it finds. To install one:

```bash
npx skills add https://alphatech.net.cn --skill alpha-video -g -y
```

Keep them current with `npx skills update -g`.

This repository is the same catalogue on GitHub, for people who prefer a git
source:

```bash
npx skills add myc0576/alphatech-skills
```

## Credentials

The packages never contain an API key. Each Skill resolves one at run time, in
this order:

1. the Skill's own `config.json` (or `~/.config/alphatech/config.json`),
2. `ALPHATECH_API_KEY` / `ALPHATECH_BASE_URL`,
3. an AlphaTech relay already configured for [CC] via `ANTHROPIC_BASE_URL` +
   `ANTHROPIC_AUTH_TOKEN` — what CC Switch and the
   [keys page](https://alphatech.net.cn/keys) write.

Create a key at <https://alphatech.net.cn/keys>.

## Skills

| Skill | What it does |
| --- | --- |
| [`alpha-video`](skills/alpha-video) | Cinematic AI video: shot plans, combat choreography, Seedance prompt compilation, task polling and download. |
| [`alpha-gpt-image`](skills/alpha-gpt-image) | Image generation and editing; picks Image 2 or Image 2.5 per request. |
| [`alpha-gpt-image2`](skills/alpha-gpt-image2) | Pinned to GPT Image 2. |
| [`alpha-suno`](skills/alpha-suno) | Songs, instrumentals and lyrics through the Suno-compatible route. |

## License

See each Skill's own files. Third-party notices are preserved in the packages.
