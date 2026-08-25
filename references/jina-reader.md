# Jina Reader Notes

Official Reader endpoint:

```text
https://r.jina.ai/
```

Basic URL form:

```bash
curl "https://r.jina.ai/https://example.com/article"
```

For WeChat article URLs:

```bash
curl "https://r.jina.ai/https://mp.weixin.qq.com/s/..."
```

Optional headers:

```text
Authorization: Bearer $JINA_API_KEY
X-Return-Format: markdown
X-No-Cache: true
```

Use `X-No-Cache: true` only when the user requests fresh content or the cached result is clearly stale.

Reader returns Markdown-like text. Common useful lines:

- `Title: ...`
- `URL Source: ...`
- `Markdown Content:`

Rate behavior from Jina public docs:

- Reader API converts URLs to LLM-friendly text.
- Without an API key it has a lower rate limit.
- With a free key the read endpoint has higher request limits.

Troubleshooting:

- If the page requires login or is blocked, ask the user to paste article text.
- If output is mostly navigation/noise, retry with fresh cache or ask for a cleaned copy.
- If images matter, preserve image URLs from the returned Markdown.
