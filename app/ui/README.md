# Web UI — Tailwind build

## Regenerate `static/tailwind.min.css`

Requires Node.js 18+ (or use Docker):

```bash
cd app/ui
npx tailwindcss@3.4.10 \
    -c tailwind.config.js \
    -i tailwind.input.css \
    -o static/tailwind.min.css \
    --minify
```

Or via Docker:

```bash
docker run --rm -v "$(pwd)":/w -w /w node:20-alpine \
    npx -y tailwindcss@3.4.10 \
    -c tailwind.config.js \
    -i tailwind.input.css \
    -o static/tailwind.min.css \
    --minify
```

The build scans `templates/**/*.html` and emits a template-scoped CSS (~15 KB).
Pin the version to avoid surprise regressions.
