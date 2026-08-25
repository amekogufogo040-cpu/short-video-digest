# Platform Rules

## RedFox Endpoints

### parseWork/parse

Default first RedFox call:

```text
POST https://redfox.hk/story/api/parseWork/parse
```

Body:

```json
{"url":"作品链接或短链"}
```

Useful response fields:

- `platform`
- `title`
- `cover`
- `videoUrl`
- `imageUrls`
- `awemeType`

Use `videoUrl` for Volcengine ASR. Prefer this over page-scraped signed stream URLs.

### Xiaohongshu Detail

```text
POST https://redfox.hk/story/api/xhsUser/queryWorkDetail
```

Body:

```json
{
  "workId": "6a4259eb0000000006022021",
  "workLink": "https://www.xiaohongshu.com/discovery/item/6a4259eb0000000006022021"
}
```

Important response fields:

- `workId`
- `workPublishTime`
- `workTitle`
- `workDesc`
- `coverUrl`
- `accountNickname`
- `workCommentsCount`
- `workLikedCount`
- `workCollectedCount`
- `workReadedCount`
- `workSharedCount`
- `workUrl`
- `workType`

`code: 3203` with “优质数据库未收录” means the ID is valid but the premium database lacks the row. Continue with page data and parseWork.

### Douyin Detail

```text
POST https://redfox.hk/story/api/dy/data/workDetail
```

Body:

```json
{
  "videoId": "7663047997038644499"
}
```

Important response fields:

- `videoId`
- `title`
- `content`
- `opusUrl`
- `coverUrl`
- `audioUrl`
- `workType`
- `duration`
- `publishTime`
- `commentCount`
- `shareCount`
- `likeCount`
- `collectCount`
- `commentTopKeywords`
- `accountName`
- `authorLink`
- `authorUrl`

This is the Douyin wide-library endpoint (`FK67XDVQ`) and should be used by default so that the work description and cover are preserved when available.

Do not send `workLink` to Douyin. That field is ignored and causes “作品id和作品链接不能同时为空”.

## Browser Resolution

Use a mobile browser context for short links when a canonical URL or ID is needed.

Xiaohongshu short links can resolve to:

```text
https://www.xiaohongshu.com/discovery/item/<workId>?...
```

or:

```text
https://www.xiaohongshu.com/explore/<workId>?...
```

Douyin short links can resolve to:

```text
https://www.iesdouyin.com/share/video/<workId>/?...
```

If command-line `curl` returns 404 for Xiaohongshu short links, try a real mobile browser context before giving up.

### Xiaohongshu Page Data

When a Xiaohongshu page loads in the browser, inspect visible text and meta tags before finalizing the digest. Public metadata can be more complete than RedFox detail for posts that are not in the premium database.

Useful meta fields:

- `og:url`: canonical work URL; extract the work ID from `/explore/<id>` or `/discovery/item/<id>`
- `og:title`: title, usually suffixed with ` - 小红书`
- `og:type`: `video` or other work type
- `og:image`: cover image
- `og:video`: page video URL; do not use this for ASR unless `parseWork videoUrl` fails
- `og:videotime`: video duration
- `og:xhs:note_like`: like count
- `og:xhs:note_collect`: collect count
- `og:xhs:note_comment`: comment count
- `keywords`: tags without hash marks
- `description`: tags/description text

Useful visible text fields:

- author nickname, even if the detail API did not return it
- relative publish time such as `7天前`
- comments and visible AI/page summaries when useful for context
- bottom action counts when meta tags are missing

If only a truncated author name is visible, keep the visible value and indicate uncertainty rather than inventing the full name. If a relative publish time is visible, convert it to an approximate absolute date using the current date and label it as approximate.

Final data precedence for Xiaohongshu:

1. Browser-resolved canonical URL and page meta/visible fields
2. RedFox detail API fields, when available
3. RedFox `parseWork/parse` fields
4. ASR transcript-derived title/content clues

Do not leave `接口未返回` for fields that the browser page provides.

## ASR

Use Volcengine ASR script with:

```bash
python3 scripts/volc_asr_transcribe.py --audio-url "<parseWork videoUrl>" --format mp3 --out-dir "<process-dir>/asr"
```

Even when the URL is an MP4 video, `--format mp3` has worked with the RedFox parseWork video URL in this workflow.

Avoid submitting page-scraped temporary signed URLs with escaped query strings; they often fail with `Invalid audio URI`.
