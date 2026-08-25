#!/usr/bin/env python3
"""Run the unified digest flow and save its final note in an Obsidian vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
SHARED = HERE / "short_video_digest.py"


def vault_child(vault: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute():
        raise SystemExit(f"{label} must be relative to the Obsidian vault.")
    vault = vault.expanduser().resolve()
    child = (vault / relative).resolve()
    try:
        child.relative_to(vault)
    except ValueError as exc:
        raise SystemExit(f"{label} escapes the Obsidian vault: {relative}") from exc
    return child


def safe_filename(text: str) -> str:
    text = (text or "未命名").strip()
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:90] or "未命名"


def yaml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def field(markdown: str, label: str) -> str:
    match = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|\n]+)", markdown)
    return match.group(1).strip() if match else ""


def source_url(text: str) -> str:
    match = re.search(r"https?://[^\s，。；、]+", text or "")
    if not match:
        raise SystemExit("No URL found. Provide a Xiaohongshu, Douyin, or WeChat article URL.")
    return match.group(0).rstrip("。,.，")


def download_cover(url: str, attachments: Path, identity: str, referer: str) -> Path | None:
    if not url or url in {"接口未返回", "未获取"}:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
        with urllib.request.urlopen(req, timeout=90) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    except Exception:
        return None
    if not data:
        return None
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(content_type)
    if not ext:
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        ext = mimetypes.guess_extension(content_type) or ".jpg"
    digest = hashlib.sha256((identity or url).encode()).hexdigest()[:10]
    path = attachments / f"{digest}{ext}"
    path.write_bytes(data)
    return path


def download_images(urls: list[str], attachments: Path, identity: str, referer: str) -> list[Path]:
    paths: list[Path] = []
    for index, url in enumerate(urls, 1):
        path = download_cover(url, attachments, f"{identity}-{index}", referer)
        if path:
            paths.append(path)
    return paths


def ocr_cover_title(path: Path) -> str:
    """Read a large, centered Chinese title from a downloaded cover on macOS."""
    if sys.platform != "darwin" or not path.is_file():
        return ""
    script = HERE / "ocr_image_text.swift"
    try:
        result = subprocess.run(
            ["swift", str(script), str(path)],
            text=True,
            capture_output=True,
            timeout=45,
            check=True,
        )
        payload = json.loads(result.stdout)
        items = payload.get(str(path), []) if isinstance(payload, dict) else payload
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return ""
    candidates = []
    for item in items if isinstance(items, list) else []:
        text = str(item.get("text", "")).strip().strip("“”\"'")
        if not re.search(r"[\u4e00-\u9fff]", text):
            continue
        if float(item.get("width", 0)) < 0.35 or float(item.get("height", 0)) < 0.05:
            continue
        if float(item.get("x", 0)) < 0.04 or float(item.get("x", 0)) > 0.6:
            continue
        candidates.append((float(item.get("y", 0)), text))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    title = "，".join(text for _, text in candidates[:3])
    return re.sub(r"\s+", "", title).strip("，。！？：")


def ocr_images(paths: list[Path], author: str = "") -> dict[str, str]:
    if not paths:
        return {}
    script = HERE / "ocr_images.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), *(str(path) for path in paths)],
            text=True,
            capture_output=True,
            timeout=180,
            check=True,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    output: dict[str, str] = {}
    for path in paths:
        items = payload.get(str(path), []) if isinstance(payload, dict) else []
        texts = [str(item.get("text", "")).strip() for item in items if isinstance(item, dict)]
        texts = [text for text in texts if text]
        if texts:
            output[str(path)] = format_ocr_text("\n".join(texts), author)
    return output


def format_ocr_text(text: str, author: str = "") -> str:
    """Clean UI noise and restore readable paragraphs without rewriting OCR text."""
    if not text:
        return ""
    noise = {
        "详情", "•••", "...", "…", "面", "展开", "收起", "分享", "评论", "点赞",
    }
    author = re.sub(r"\s+", "", author or "")
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", "", raw).strip()
        # Repeated creator watermarks and screenshot metadata are not note content.
        line = re.sub(r"[<〈]?小北带你飞[>〉]?", "", line)
        line = re.sub(r"(?:来自iPhone\d*ProMax|发布于[^\d\s]+|\d+(?:\.\d+)?万?广阅读)", "", line)
        line = line.strip("<>〈〉·•")
        if not line or line in noise:
            continue
        if author and (line == author or line.startswith(author)):
            continue
        if re.fullmatch(r"(?:\d+秒前|\d+分钟前|\d+小时前|昨天|刚刚|\d{1,2}:\d{2})", line):
            continue
        # Engagement timestamps are sometimes OCR'd together with a trailing UI label.
        if re.search(r"(?:\d+秒前|\d+分钟前|\d+小时前|昨天|刚刚)", line):
            continue
        lines.append(line.strip("|"))
    if not lines:
        return ""

    # OCR often wraps one sentence at an arbitrary width. Start a new paragraph
    # only at clear sentence punctuation or a recognizable discourse transition.
    transitions = ("但你", "问题是", "那如果", "我觉得", "唯一需要", "这就", "因此", "所以")
    paragraphs: list[str] = []
    current = ""
    for index, line in enumerate(lines):
        if not current:
            current = line
        else:
            current += line
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        ends_sentence = bool(re.search(r"[。！？!?；;]$", current))
        transition_break = bool(next_line.startswith(transitions)) and not current.endswith(("：", ":", "，", ","))
        if ends_sentence or transition_break:
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)

    cleaned: list[str] = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if paragraph and not re.search(r"[。！？!?]$", paragraph):
            paragraph += "。"
        cleaned.append(paragraph)
    return "\n\n".join(cleaned)


def cached_note(notes_dir: Path, url: str) -> Path | None:
    if not notes_dir.exists():
        return None
    for path in notes_dir.glob("*.md"):
        try:
            if url in path.read_text(encoding="utf-8", errors="ignore"):
                return path
        except OSError:
            pass
    return None


def run_digest(input_text: str, temp_dir: Path, fresh: bool, complete_data: bool, no_asr: bool) -> dict:
    cmd = [sys.executable, str(SHARED), "--input", input_text, "--output-dir", str(temp_dir)]
    if fresh:
        cmd.append("--fresh")
    if complete_data:
        cmd.append("--complete-data")
    if no_asr:
        cmd.append("--no-asr")
    # Keep the parser response long enough to localize every XHS image.
    cmd.append("--keep-process")
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise SystemExit(detail[-2000:] or f"Digest script failed with exit code {exc.returncode}.") from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # Volc ASR may print a process artifact path before the final JSON.
        starts = [match.start() for match in re.finditer(r"(?m)^\s*\{", result.stdout)]
        for start in reversed(starts):
            candidate = result.stdout[start:].strip()
            if not candidate.startswith("{"):
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise SystemExit(f"Digest script returned invalid JSON: {result.stdout[-1000:]}")


def platform_key(platform: str) -> str:
    return {"小红书": "xiaohongshu", "抖音": "douyin", "视频号": "shipinhao", "微信公众号": "wechat"}.get(platform, "web")


def content_type(platform: str, body: str) -> tuple[str, str]:
    if platform in {"抖音", "视频号"} or "## 口播文稿整理版" in body:
        return "video_transcript", "视频文稿"
    if platform == "小红书":
        return "article", "图文笔记"
    if platform == "微信公众号":
        return "article", "长文章"
    return "link", "网页资料"


def source_body(body: str, platform: str, image_links: list[str], ocr_texts: list[str] | None = None) -> str:
    if platform == "小红书":
        match = re.search(r"## 口播文稿整理版\s*\n\s*(.*?)(?=\n---\n\s*## 文章总结|\Z)", body, re.S)
        transcript = match.group(1).strip() if match else ""
        description = field(body, "作品描述")
        if description == "接口未返回":
            description = ""
        if description:
            content = description
        elif (not transcript or transcript == "未获取到口播文稿。") and not any(ocr_texts or []):
            content = "> [!warning] 暂未获取到正文\n> 已保留全部原图；当前设备未能识别出图片正文。"
        else:
            content = transcript if transcript and transcript != "未获取到口播文稿。" else ""
        result = f"## 原笔记正文\n\n{content}"
        if image_links:
            result += "\n\n## 图片素材\n\n" + "\n".join(
                f"![图{index}]({link})" for index, link in enumerate(image_links, 1)
            )
        if any(ocr_texts or []):
            result += "\n\n## 图片正文 OCR\n\n" + "\n\n".join(
                f"### 图{index}\n\n{text}" for index, text in enumerate(ocr_texts, 1) if text
            )
        if description and transcript and transcript != "未获取到口播文稿。":
            result += f"\n\n## 口播文稿\n\n{transcript}"
        return result
    if platform == "抖音" and ocr_texts is not None:
        result = "## 原笔记正文\n\n"
        if any(ocr_texts):
            result += "\n\n".join(
                f"### 图{index}\n\n{text}" for index, text in enumerate(ocr_texts, 1) if text
            )
        else:
            result += "> [!warning] 已保留全部原图；当前设备未能识别出图片正文。"
        result += "\n\n## 图片素材\n\n" + "\n".join(
            f"![图{index}]({link})" for index, link in enumerate(image_links, 1)
        )
        return result
    if platform == "微信公众号":
        match = re.search(r"## 正文重排版\s*\n\s*(.*?)(?=\n---\n\s*## 文章总结|\Z)", body, re.S)
        content = match.group(1).strip() if match else ""
        return f"## 文章正文\n\n{content or '> [!warning] 暂未获取到正文'}"
    match = re.search(r"## 口播文稿整理版\s*\n\s*(.*?)(?=\n---\n\s*## 文章总结|\Z)", body, re.S)
    content = match.group(1).strip() if match else ""
    description = field(body, "作品描述")
    result = ""
    if description and description != "接口未返回":
        result += f"## 作品描述\n\n{description}\n\n"
    if image_links and not ocr_texts:
        result += f"## 封面\n\n![{platform}封面]({image_links[0]})\n\n"
    if ocr_texts:
        result += "## 图片正文 OCR\n\n" + "\n\n".join(
            f"### 图{index}\n\n{text}" for index, text in enumerate(ocr_texts, 1) if text
        ) + "\n\n"
        result += "## 图片素材\n\n" + "\n".join(
            f"![图{index}]({link})" for index, link in enumerate(image_links, 1)
        ) + "\n\n"
    if content and content != "未获取到口播文稿。":
        result += f"## 口播文稿\n\n{content}"
    elif not ocr_texts:
        result += "## 口播文稿\n\n> [!warning] 暂未获取到口播文稿"
    return result


def build_note(body: str, title: str, platform: str, author: str, source: str, image_links: list[str], ocr_texts: list[str] | None = None) -> str:
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    date = now[:10]
    source_key = platform_key(platform)
    _, type_name = content_type(platform, body)
    if platform in {"小红书", "抖音"} and ocr_texts is not None:
        type_name = "图文笔记"
    content_kind = "video_transcript" if type_name == "视频文稿" else "article" if type_name in {"图文笔记", "长文章"} else "link"
    tags = ["第二大脑/采集", f"来源/{platform or '网页'}", f"类型/{type_name}"]
    lines = [
        "---",
        f"id: {uuid.uuid4()}",
        "type: source-note",
        "status: 待消化",
        f"source: {platform or '网页'}",
        f"source_platform: {source_key}",
        f"original_url: {source}",
        f"author: {author or '未知作者'}",
        f"content_type: {content_kind}",
        f"captured_at: {now}",
        f"updated_at: {now}",
        "tags:",
        *[f"  - {tag}" for tag in tags],
        "---",
        "",
        f"# {safe_filename(title)}",
        "",
        "<!-- biji-sync:start -->",
        "> [!info] 来源卡片",
        f"> **{platform or '网页'} · {type_name}{(' · ' + author) if author and author not in {'博主未返回', '未知作者'} else ''}**",
        f"> [打开原内容](<{source}>) · 采集于 {date}",
        "",
        source_body(body, platform, image_links, ocr_texts),
        "<!-- biji-sync:end -->",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a Xiaohongshu, Douyin, or WeChat digest into Obsidian.")
    parser.add_argument("--input", required=True, help="Share text or URL.")
    parser.add_argument("--vault", required=True, help="Absolute Obsidian vault path.")
    parser.add_argument("--notes-dir", required=True, help="Note directory relative to the vault.")
    parser.add_argument("--attachments-dir", help="Attachment directory relative to the vault.")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--complete-data", action="store_true")
    parser.add_argument("--no-asr", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="Re-fetch even when the source URL is already saved.")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not (vault / ".obsidian").is_dir():
        raise SystemExit(f"Not an Obsidian vault (missing .obsidian): {vault}")
    notes_dir = vault_child(vault, Path(args.notes_dir), "notes-dir")
    default_attachment_dir = Path("00-收件箱/网络采集/_附件") / time.strftime("%Y") / time.strftime("%m")
    attachments_dir = vault_child(vault, Path(args.attachments_dir) if args.attachments_dir else default_attachment_dir, "attachments-dir")
    notes_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)

    url = source_url(args.input)
    if not args.overwrite:
        cached = cached_note(notes_dir, url)
        if cached:
            print(json.dumps({"cached": True, "markdown": str(cached), "cover": ""}, ensure_ascii=False, indent=2))
            return

    with tempfile.TemporaryDirectory(prefix="short-video-digest-") as temp:
        result = run_digest(args.input, Path(temp), args.fresh, args.complete_data, args.no_asr)
        final_path = Path(result.get("final_markdown", ""))
        if not final_path.is_file():
            raise SystemExit("Digest completed without a final Markdown file.")
        body = final_path.read_text(encoding="utf-8")
        image_urls: list[str] = []
        for parse_path in Path(temp).rglob("parse_result.json"):
            try:
                payload = json.loads(parse_path.read_text(encoding="utf-8"))
                image_urls.extend(str(url) for url in (payload.get("data", {}).get("imageUrls") or []) if url)
            except (OSError, json.JSONDecodeError, AttributeError):
                pass

    platform = {"xhs": "小红书", "douyin": "抖音", "shipinhao": "视频号", "wechat": "微信公众号"}.get(result.get("platform", ""), field(body, "发布平台"))
    title = field(body, "原作品标题") or field(body, "原文标题") or (re.search(r"^#\s+(.+)$", body, re.M) or ["", "未命名"])[1].strip()
    author = field(body, "博主名称") or field(body, "账号名称") or ""
    cover_url = field(body, "封面 URL")
    identity = field(body, "作品 ID")
    if not identity or identity in {"接口未返回", "未获取", "未命名"}:
        identity = url
    has_body_images = platform in {"小红书", "抖音"} and bool(image_urls)
    asset_urls = image_urls if has_body_images else ([cover_url] if platform in {"抖音", "视频号"} else [])
    assets = download_images(asset_urls, attachments_dir, identity, url)
    ocr_by_path = ocr_images(assets, author) if has_body_images else {}
    if platform == "视频号" and assets and title == "未命名":
        title = ocr_cover_title(assets[0]) or title
    if title == "未命名" and platform == "视频号":
        transcript_match = re.search(r"## 口播文稿整理版\s*\n\s*(.*?)(?=\n---\n\s*## 文章总结|\Z)", body, re.S)
        first_sentence = re.split(r"(?<=[。！？])", transcript_match.group(1).strip())[0] if transcript_match else ""
        if first_sentence:
            title = first_sentence[:60]
    asset_links = [path.relative_to(vault).as_posix() for path in assets]
    stamp = time.strftime("%Y-%m-%d")
    filename = f"{stamp} {safe_filename(title)}.md"
    note = notes_dir / filename
    ocr_texts = [ocr_by_path.get(str(path), "") for path in assets] if has_body_images else None
    note.write_text(build_note(body, title, platform, author, url, asset_links, ocr_texts), encoding="utf-8")
    print(json.dumps({"cached": False, "markdown": str(note), "cover": str(assets[0]) if assets else "", "assets": [str(path) for path in assets], "platform": platform, "title": title, "author": author}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
