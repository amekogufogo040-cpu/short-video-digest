#!/usr/bin/env python3
import argparse
import html
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


def safe_filename(text: str) -> str:
    text = (text or "未命名").strip()
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:90] or "未命名"


def extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s，。；、]+", text or "")
    if not m:
        raise SystemExit("No URL found. Provide --url or --input with an article URL.")
    return m.group(0).rstrip("。,.，")


def getenv_from_shell(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists():
        m = re.search(rf"export\s+{re.escape(name)}=[\"']?([^\"'\n]+)", zshrc.read_text(errors="ignore"))
        if m:
            return m.group(1).strip()
    return ""


def read_with_jina(url: str, fresh: bool = False) -> str:
    reader_url = "https://r.jina.ai/" + url
    headers = {
        "User-Agent": "wechat-article-digest/1.0",
        "X-Return-Format": "markdown",
    }
    key = getenv_from_shell("JINA_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if fresh:
        headers["X-No-Cache"] = "true"
    req = urllib.request.Request(reader_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Jina Reader HTTP {exc.code}: {body[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Jina Reader network error: {exc.reason}") from exc


def read_wechat_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")


class WechatContentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.skip += 1
        if self.skip:
            return
        if tag in ("p", "section", "div", "li", "blockquote", "h1", "h2", "h3"):
            self.parts.append("\n")
        if tag == "br":
            self.parts.append("\n")
        if tag == "img":
            attr = dict(attrs)
            src = attr.get("data-src") or attr.get("src")
            if src:
                self.parts.append(f"\n![图片]({src})\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg") and self.skip:
            self.skip -= 1
        if self.skip:
            return
        if tag in ("p", "section", "div", "li", "blockquote", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def first_wechat_match(patterns, text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if match:
            return re.sub(r"<.*?>", "", match.group(1)).strip()
    return ""


def parse_wechat_html(raw_html: str, url: str) -> dict:
    title = first_wechat_match([
        r"var\s+msg_title\s*=\s*'([^']*)'",
        r'<meta property="og:title" content="([^"]*)"',
    ], raw_html)
    account = first_wechat_match([
        r'id="js_author_name"[^>]*>(.*?)</span>',
        r"var\s+nickname\s*=\s*'([^']*)'",
    ], raw_html)
    publish = first_wechat_match([
        r'id="publish_time"[^>]*>(.*?)</em>',
        r"var\s+publish_time\s*=\s*'([^']*)'",
    ], raw_html)
    match = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*<script', raw_html, flags=re.S)
    if not match:
        raise SystemExit("WeChat HTML fallback could not find #js_content.")
    parser = WechatContentParser()
    parser.feed(match.group(1))
    content = clean_content(html.unescape("".join(parser.parts)))
    return {
        "url": url,
        "title": html.unescape(title) or "公众号文章",
        "account": html.unescape(account) or "账号未识别",
        "publish_time": html.unescape(publish) or "未识别",
        "content": content,
        "source": "WeChat HTML fallback",
    }


def first_match(patterns, text: str) -> str:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.M)
        if m:
            return m.group(1).strip()
    return ""


def parse_reader(raw: str, url: str) -> dict:
    if "环境异常" in raw or "requiring CAPTCHA" in raw:
        return parse_wechat_html(read_wechat_html(url), url)
    title = first_match([
        r"^Title:\s*(.+)$",
        r"^#\s+(.+)$",
    ], raw)
    account = first_match([
        r"^(?:作者|Author|账号|公众号)[:：]\s*(.+)$",
        r"^(.+?)\s+微信号[:：]",
    ], raw)
    publish = first_match([
        r"(\d{4}年\d{1,2}月\d{1,2}日)",
        r"(\d{4}-\d{1,2}-\d{1,2})",
    ], raw)
    content = raw
    marker = "Markdown Content:"
    if marker in raw:
        content = raw.split(marker, 1)[1].strip()
    content = clean_content(content)
    if not title:
        title = first_match([r"^#\s+(.+)$", r"^(.{6,80})$"], content) or "公众号文章"
    return {
        "url": url,
        "title": title,
        "account": account or "账号未识别",
        "publish_time": publish or "未识别",
        "content": content,
        "source": "Jina Reader",
    }


def clean_content(text: str) -> str:
    lines = []
    skip_patterns = [
        r"^URL Source:",
        r"^Title:",
        r"^Markdown Content:",
        r"^!\[\]\(",
        r"^阅读原文$",
        r"^写留言$",
        r"^微信扫一扫",
    ]
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if any(re.search(p, stripped) for p in skip_patterns):
            continue
        lines.append(stripped)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def build_markdown(meta: dict) -> str:
    return f"""# {meta['title']}

## 原文信息

| 字段 | 内容 |
|---|---|
| 原文标题 | {meta['title']} |
| 发布平台 | 微信公众号 |
| 账号名称 | {meta['account']} |
| 发布时间 | {meta['publish_time']} |
| 原文链接 | {meta['url']} |
| 数据来源 | {meta.get('source', 'Jina Reader')} |

---

## 正文重排版

{meta['content']}

---

## 文章总结

请总结这篇文章的主旨、关键论证、读者能带走的结论，以及文章背后的转化/表达意图。

---

## 核心观点

请基于正文提炼 3-5 个核心观点。

---

## 这篇文章能让我学到什么

请补充可迁移的方法、判断框架和行动建议。

---

## 这篇文章真正的价值

请分析它解决了什么问题、降低了什么认知成本、为什么值得收藏。

---

## 为什么这篇文章值得传播

请从标题、选题、人群痛点、结构、表达方式和情绪价值分析。

---

## 可复用写作结构

请拆解这篇文章的写作结构，并给出可复用模板。

---

## 选题拓展

请基于这篇文章拓展 20 个选题，按方向分组。
"""


def find_cached(output_dir: Path, url: str):
    if not output_dir.exists():
        return None
    for path in output_dir.rglob("*.md"):
        try:
            if url in path.read_text(encoding="utf-8", errors="ignore"):
                return path
        except OSError:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Read a WeChat article with Jina Reader and create a digest Markdown.")
    parser.add_argument("--url")
    parser.add_argument("--input", help="Copied share text containing a URL.")
    parser.add_argument("--output-dir", default="outputs/wechat-article-digest")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--keep-process", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    url = args.url or extract_url(args.input or "")
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = Path(args.workspace) / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    cached = find_cached(out_dir, url)
    if cached:
        print(str(cached))
        return

    raw = read_with_jina(url, fresh=args.fresh)
    meta = parse_reader(raw, url)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work_dir = out_dir / f"wechat-{stamp}"
    process_dir = work_dir / "_process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (process_dir / "jina_reader_raw.md").write_text(raw, encoding="utf-8")

    filename = f"{safe_filename(meta['title'])}_公众号_{safe_filename(meta['account'])}_{stamp}.md"
    final_path = work_dir / filename
    final_path.write_text(build_markdown(meta), encoding="utf-8")

    if not args.keep_process:
        shutil.rmtree(process_dir, ignore_errors=True)
    print(str(final_path))


if __name__ == "__main__":
    main()
