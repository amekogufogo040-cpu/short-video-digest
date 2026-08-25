---
name: short-video-digest
description: 将小红书、抖音、视频号单条作品或微信公众号文章链接/口令整理成 Markdown；用户要求时直接保存到指定 Obsidian vault。包含原内容信息、正文/口播文稿重排、总结、内容价值分析、数据或传播原因分析、可复用结构和选题拓展。Use when the user says 整理这条小红书、整理这条抖音、整理这条视频号、整理这篇公众号、公众号文章整理、转文稿、下载文稿、分析这篇文稿、做选题参考、保存到 OB/Obsidian, or provides a Xiaohongshu/Douyin/WeChat Channels article link and wants readable Markdown plus analysis.
---

# Content Digest

Use this skill to turn one Xiaohongshu post, Douyin post, or WeChat Official Account article into a clean final Markdown digest.

For whole-account Douyin collection, batch download, batch ASR, and account-level analysis, use `douyin-account-analyzer` instead. This skill remains the source of truth for single-work digest quality and transcript polishing rules; the account analyzer may reuse its Volc ASR script and final Markdown section contract.

## Default Outcome

Create one final Markdown file named:

```text
标题_平台_博主或账号名称_整理时间.md
```

Default cleanup: keep only the final Markdown. Delete videos, audio, raw JSON, ASR task files, Jina Reader raw output, and process notes unless the user explicitly asks to keep them.

## Required Credentials

Use existing environment variables:

- Xiaohongshu/Douyin: `REDFOX_API_KEY`
- Video ASR: `VOLC_ASR_APP_ID` + `VOLC_ASR_ACCESS_KEY`, or `VOLC_ASR_API_KEY`
- WeChat/Jina Reader optional: `JINA_API_KEY`

Never print credential values.

## Main Script

Run the unified script:

```bash
python3 /Users/ly/.agents/skills/short-video-digest/scripts/short_video_digest.py \
  --input "<share text or URL>" \
  --output-dir "/Users/ly/Documents/小红书信源/outputs/short-video-digest"
```

Useful flags:

- `--complete-data`: for Xiaohongshu/Douyin, attempt the platform detail API for author, publish time, and metrics.
- `--work-id "<id>" --work-url "<canonical-url>"`: pass a browser-resolved canonical ID/link before calling detail APIs.
- `--keep-process`: keep raw JSON, ASR output, Jina output, and media instead of cleaning.
- `--no-asr`: for videos, collect metadata only.
- `--fresh`: for WeChat/Jina Reader, request fresh content.
- `--workspace <dir>`: set the workspace root for relative output paths.

The script prints JSON with `final_markdown` and key metadata. Always read the final Markdown before delivery. If the script leaves placeholder analysis sections, rewrite/enrich them manually before final delivery.

## Save directly to Obsidian

When the user asks to save the result to Obsidian, do not assume a vault path. Require the user-provided absolute vault path and a note directory relative to that vault. Run:

```bash
python3 /Users/ly/.agents/skills/short-video-digest/scripts/short_video_digest_to_obsidian.py \
  --input "<小红书/抖音/公众号链接或口令>" \
  --vault "<Obsidian vault absolute path>" \
  --notes-dir "<vault 内的笔记目录>"
```

Optional flags are `--attachments-dir` (relative to the vault), `--fresh`, `--complete-data`, `--no-asr`, and `--overwrite`. The wrapper validates that the target is an Obsidian vault, prevents note or attachment paths from escaping it, caches by source URL, and writes notes using the `obsidian-biji`/“OB 同步” source-note contract: standard YAML fields, `<!-- biji-sync:start/end -->` managed markers, a source card, platform-specific body headings, and a user digestion area. The default attachment path follows `00-收件箱/网络采集/_附件/{year}/{month}`. For Xiaohongshu and Douyin it downloads the cover into that attachment directory and embeds it in the note. For WeChat, article images remain as source URLs.

For Obsidian capture mode, save source material only: do not include `文章总结`, `核心观点`, `内容价值`, `传播分析`, `可复用方法`, `选题拓展`, or other analysis/prompt sections. Read the JSON output fields `markdown`, `assets`, and `cached`, then inspect the saved Markdown and all local assets before reporting completion. For Xiaohongshu photo notes, preserve every image returned by the source page in original order under `## 图片素材`.

## Routing

The main script auto-detects:

- `mp.weixin.qq.com` -> WeChat article flow using Jina Reader, with WeChat HTML fallback.
- `xhslink.com` / `xiaohongshu.com` -> Xiaohongshu video/post flow.
- `douyin.com` / `iesdouyin.com` -> Douyin video flow.
- `weixin.qq.com/sph/` / `channels.weixin.qq.com` -> 视频号 video flow.

## Xiaohongshu And Douyin

Follow `references/platform-rules.md` for endpoint fields and fallback order.

Core rules:

- Xiaohongshu:
  - Resolve `xhslink.com` short links in a mobile browser when possible to get the long link and work ID.
  - When resolved, pass them to the script with `--work-id` and `--work-url`.
  - Detail endpoint: `POST https://redfox.hk/story/api/xhsUser/queryWorkDetail`
  - Detail fields: `workId`, `workLink`
  - If detail returns “优质数据库未收录”, do not retry repeatedly. Use browser page data plus `parseWork/parse`.
  - For ASR, submit the `videoUrl` returned by `parseWork/parse`, not temporary signed page stream URLs.
- Douyin:
  - Resolve short links when useful to get `share/video/<id>`.
  - Detail endpoint: `POST https://redfox.hk/story/api/dy/data/workDetail` (广域库，接口 `FK67XDVQ`)
  - Detail field: `videoId`（对应抖音 `aweme_id`）
  - Preserve `content`, `coverUrl`, `authorName`, `publishTime`, `opusUrl`, tags, and engagement counts when returned.
  - Do not use Xiaohongshu's `workLink` field for Douyin.
- 视频号:
  - Recognize `weixin.qq.com/sph/` share links as 视频号, not WeChat articles.
  - Use `POST https://redfox.hk/story/api/parseWork/parse` for the video and cover URLs.
  - For direct metadata, use `POST https://redfox.hk/story/api/sph/ability/workLinkDetail` (接口 `MH5YA9DL`) with JSON `{ "url": "<视频号短链>" }`. This real-time endpoint accepts the share URL directly and returns `title`, `description`, `cover`, `nickname`, `publishTime`, and engagement counts (`likeNum`, `favoriteNum`, `commentNum`, `shareNum`); it does not replace `parseWork/parse` for obtaining `videoUrl`.
  - When a `videoId` is available, use the wide-library detail endpoint `POST https://redfox.hk/story/api/sphAllData/queryWorkDetail` (接口 `OE4KUEUO`) to obtain description, cover, author, publish time, and engagement data.
  - Save the cover under the standard Obsidian attachment directory and transcribe the video with Volcengine ASR.
  - When the interface does not return a title, run local macOS Vision OCR on the downloaded cover; use the OCR title before falling back to the description or ASR first sentence.

Image-based post bodies:

- For Xiaohongshu photo notes and Douyin image collections, download every returned image in source order.
- Run local OCR over all downloaded images and write the recognized text under `## 图片正文 OCR`; keep the original images under `## 图片素材`.
- Before writing OCR, remove only obvious platform UI noise (for example `详情`, author lines, and relative timestamps), merge line-wrap fragments, and restore paragraph breaks from punctuation/discourse transitions. Do not summarize or paraphrase the recognized text.
- macOS uses Vision. Windows/Linux use `rapidocr_onnxruntime` when installed (`py -m pip install rapidocr_onnxruntime`). If no OCR engine is available, keep the images and state that OCR was unavailable; never replace the source images with guessed text.

For Xiaohongshu and Douyin short links, do not rely only on command-line redirects or the detail API. Before final delivery, resolve the share link in a real browser/mobile-like context whenever possible and merge page data into the Markdown.

For Xiaohongshu page enrichment, capture:

- `og:url` -> canonical work URL
- URL path -> work ID
- `og:title` / visible title -> title
- visible author name -> author, preserving uncertainty if truncated
- `og:xhs:note_like` -> likes
- `og:xhs:note_collect` -> collects
- `og:xhs:note_comment` -> comments
- `og:videotime` -> duration
- `keywords` / `description` -> tags/description
- visible relative publish time such as `7天前`; convert to an approximate absolute date using the current date and state that it is approximate

If the RedFox detail API says the premium database has not collected the item, do not leave metadata as “接口未返回” when the browser page provides it. Use the browser page values and note the source.

## WeChat Articles

Read `references/jina-reader.md` when troubleshooting WeChat/Jina Reader behavior.

Rules:

- Use Jina Reader first: `https://r.jina.ai/https://mp.weixin.qq.com/s/...`.
- If Jina returns “环境异常” or CAPTCHA warnings, use the bundled WeChat HTML fallback parser.
- Preserve title, account name, publish time when available, source URL, body, and image URLs.
- The final article document must include `正文重排版` followed immediately by a completed `文章总结`.
- `文章总结` must summarize the main argument, key reasoning, reader takeaway, and conversion/intent design when relevant.

## Cost Discipline

For video transcription, use the Volcengine ASR path by default. Do not call the paid RedFox “视频提文案” async endpoints unless the user explicitly requests that route or Volcengine ASR has failed and the user approves the fallback cost. The Obsidian wrapper `short_video_digest_to_obsidian.py` uses the default Volcengine path; `redfox_video_to_obsidian.py` is an explicit, opt-in test/fallback script only.

Default low-cost video path:

1. Check local final Markdown cache.
2. Call RedFox `parseWork/parse` once.
3. Use returned `videoUrl` directly with Volcengine ASR.
4. Resolve short links in browser and merge page meta/visible data when available.
5. Call the Douyin wide-library detail API by default; call the Xiaohongshu detail API only when requested or when required fields are still missing.
6. Create and manually polish final Markdown.
7. Clean process files.

Default low-cost WeChat path:

1. Check local final Markdown cache.
2. Call Jina Reader once.
3. If blocked, use WeChat HTML fallback once.
4. Create and manually polish final Markdown.
5. Clean process files.

Avoid search APIs as fallback unless the user explicitly asks. They cost extra and can mismatch.

## Final Markdown Sections

For Xiaohongshu/Douyin videos, include:

```markdown
# 标题

## 原作品信息

## 口播文稿整理版

## 文章总结

## 这篇文稿能让我学到什么

## 这篇内容真正的价值

## 为什么数据会好 / 为什么数据目前不高但值得参考

## 可复用的创作方法

## 选题拓展
```

For WeChat articles, include:

```markdown
# 标题

## 原文信息

## 正文重排版

## 文章总结

## 核心观点

## 这篇文章能让我学到什么

## 这篇文章真正的价值

## 为什么这篇文章值得传播

## 可复用写作结构

## 选题拓展
```

Use ASR transcripts as raw material for videos; rewrite into readable paragraphs with headings. Do not leave raw timestamp segments in the final output unless the user asks.

The `口播文稿整理版` must be reader-friendly, not a raw transcript dump:

- Remove filler words, stutters, repeated particles, and ASR punctuation errors.
- Preserve the creator's core argument and sequence, but rewrite into clean paragraphs.
- Add short subsection headings for each major idea.
- Add a bold `本段总结：...` after each major subsection.
- Fix obvious ASR errors only when the correction is clear from context; do not invent facts.
- Keep long-form reasoning intact, but make it readable enough to review, quote, and reuse.

The analysis sections must be completed, not left as prompts. When interaction data is available from page meta, use it in the data analysis section. If only partial data is available, state exactly which fields were observed and which were unavailable.

## If Something Fails

- If RedFox detail returns `data:null`, continue with parse/page data.
- If RedFox detail says the item is not in the premium database, continue with browser page data plus `parseWork/parse`; do not retry repeatedly.
- If browser page data is available, prefer it over “接口未返回” placeholders in the final Markdown.

For Xiaohongshu, the authenticated/`xsec_token` note-detail data and rendered note body are authoritative for the caption (`desc`/正文), author, tags, and engagement metrics. RedFox `parseWork/parse` may return only `imageUrls` for photo notes; do not conclude that the note has no正文 in that case. Resolve the share link in a browser, read the note-detail body from the page/API response, and write that caption into `## 原笔记正文`; use `imageUrls` only for the image section. OCR is not a substitute for the platform-provided caption.
- If direct ASR URL fails, verify you used the parseWork `videoUrl`. If it still fails, download video only as fallback, extract audio, and submit a public audio URL if available.
- If no video is available, create a metadata-only digest and say what is missing.
- If Jina Reader cannot read a WeChat article, use the bundled WeChat HTML fallback. If both fail, ask the user to paste article text or provide screenshots/export.

## Verified Douyin ASR Fallback

When Douyin direct video URLs fail in Volcengine ASR with empty audio or inaccessible media, use the audio-extraction fallback:

1. Download the RedFox `parseWork` video URL with `curl -L`.
2. Extract audio with ffmpeg:

```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 -b:a 64k output.mp3
```

3. Make the MP3 available at a public HTTPS URL. A temporary file host is acceptable for one-off analysis when the user has requested transcription and credentials are already available.
4. Submit the public MP3 URL to:

```bash
python3 /Users/ly/.agents/skills/short-video-digest/scripts/volc_asr_transcribe.py \
  --audio-url "<public-mp3-url>" \
  --output-dir "<work-output-dir>"
```

5. Read `volc_asr_transcript.txt`, then rewrite it into the `口播文稿整理版`. Do not ship the raw ASR as final prose.

For batch Douyin account work, keep Volc concurrency conservative at first. If Volc returns QPS or quota errors, lower concurrency or add stagger/backoff. A run that succeeds at high concurrency once is not a guarantee for the next account.
