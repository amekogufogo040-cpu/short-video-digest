#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Optional


SKILL_DIR = Path(__file__).resolve().parents[1]
PARSE_URL = "https://redfox.hk/story/api/parseWork/parse"

DETAIL = {
    "xhs": {
        "endpoint": "https://redfox.hk/story/api/xhsUser/queryWorkDetail",
        "url_field": "workLink",
        "title": "workTitle",
        "content": "workDesc",
        "work_url": "workUrl",
        "cover": "coverUrl",
        "author": "accountNickname",
        "publish": "workPublishTime",
        "like": "workLikedCount",
        "collect": "workCollectedCount",
        "comment": "workCommentsCount",
        "share": "workSharedCount",
        "type": "workType",
    },
    "douyin": {
        "endpoint": "https://redfox.hk/story/api/dy/data/workDetail",
        "url_field": "opusUrl",
        "title": "title",
        "content": "content",
        "work_url": "opusUrl",
        "cover": "coverUrl",
        "author": "authorName",
        "publish": "publishTime",
        "like": "likeCount",
        "collect": "collectCount",
        "comment": "commentCount",
        "share": "shareCount",
        "type": "workType",
    },
    "shipinhao": {
        "endpoint": "https://redfox.hk/story/api/sph/ability/workLinkDetail",
        "url_field": "url",
        "title": "description",
        "content": "description",
        "work_url": "videoUrl",
        "cover": "coverUrl",
        "author": "nickname",
        "publish": "publishTime",
        "like": "likeCount",
        "collect": "favCount",
        "comment": "commentCount",
        "share": "forwardCount",
        "type": "videoType",
    },
}


def safe_filename(text: str) -> str:
    text = (text or "未命名").strip()
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", "_", text)
    return text[:90] or "未命名"


def extract_url(text: str) -> str:
    m = re.search(r"https?://[^\s，。；、]+", text)
    return m.group(0).rstrip("。,.，")


def is_wechat_url(url: str) -> bool:
    return "mp.weixin.qq.com" in (url or "")


def is_shipinhao_url(url: str) -> bool:
    return "weixin.qq.com/sph/" in (url or "") or "channels.weixin.qq.com" in (url or "")


def run_wechat_digest(args: argparse.Namespace, input_url: str, output_dir: Path) -> None:
    script = SKILL_DIR / "scripts" / "wechat_article_digest.py"
    cmd = [
        sys.executable,
        str(script),
        "--url",
        input_url,
        "--output-dir",
        str(output_dir),
        "--workspace",
        args.workspace,
    ]
    if args.keep_process:
        cmd.append("--keep-process")
    if args.fresh:
        cmd.append("--fresh")
    result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    final_path = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    print(json.dumps({
        "cached": False,
        "final_markdown": final_path,
        "platform": "wechat",
        "title": Path(final_path).name if final_path else "",
        "detail_status": "Jina Reader / WeChat HTML fallback",
    }, ensure_ascii=False, indent=2))


def getenv_from_shell(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return getenv_from_zshrc(name)


def getenv_from_zshrc(name: str) -> str:
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists():
        pattern = re.compile(rf"export\s+{re.escape(name)}=[\"']?([^\"'\n]+)")
        matches = pattern.findall(zshrc.read_text(errors="ignore"))
        if matches:
            return matches[-1].strip()
    return ""


def redfox_key() -> str:
    key = getenv_from_shell("REDFOX_API_KEY")
    if not key:
        raise SystemExit("Missing REDFOX_API_KEY.")
    return key


def post_json(url: str, payload: dict, api_key: str) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "REDFOX_API_KEY": api_key,
            "X-API-KEY": api_key,
            "User-Agent": "short-video-digest/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def parse_work(input_url: str, key: str) -> dict:
    result = post_json(PARSE_URL, {"url": input_url}, key)
    if int(result.get("code", -1)) != 2000 or not result.get("data"):
        raise SystemExit(f"parseWork failed: {result.get('code')} {result.get('msg')}")
    return result


def infer_work_id(url: str, platform: str) -> str:
    if platform == "xhs":
        m = re.search(r"(?:explore|discovery/item)/([0-9a-fA-F]{20,32})", url or "")
        return m.group(1) if m else ""
    if platform == "douyin":
        m = re.search(r"(?:video|modal_id)[/=]([0-9]{12,25})", url or "")
        return m.group(1) if m else ""
    if platform == "shipinhao":
        m = re.search(r"(?:video_id|export_id)[=/]([0-9]{8,})", url or "")
        return m.group(1) if m else ""
    return ""


def resolve_douyin_work_id(url: str) -> str:
    """Resolve a short share URL without scraping page content."""
    if not url:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            target = response.geturl()
        match = re.search(r"/(?:video|modal_id)[/=]([0-9]{12,25})", target)
        return match.group(1) if match else ""
    except (OSError, urllib.error.URLError):
        return ""


def detail_work(platform: str, input_url: str, work_id: str, key: str) -> tuple[dict, dict]:
    if platform not in DETAIL:
        return {}, {}
    cfg = DETAIL[platform]
    payload = {}
    if platform == "douyin":
        resolved_id = work_id or resolve_douyin_work_id(input_url)
        if resolved_id:
            payload["videoId"] = resolved_id
    elif platform == "shipinhao":
        # The real-time endpoint accepts the share URL directly and returns
        # title/description/cover/author without requiring videoId.
        if input_url:
            payload["url"] = input_url
    elif work_id:
        payload["workId"] = work_id
    if input_url:
        payload[cfg["url_field"]] = input_url
    if not payload:
        return {}, {}
    result = post_json(cfg["endpoint"], payload, key)
    return result, result.get("data") or {}


def normalize(platform: str, parse_data: dict, detail_data: dict, source_url: str, canonical_url: str, fallback_work_id: str) -> dict:
    cfg = DETAIL.get(platform, {})
    content = detail_data.get(cfg.get("content", "")) or ""
    title = detail_data.get(cfg.get("title", "")) or parse_data.get("title") or ""
    if not title and content:
        title = re.split(r"\s+#", content, maxsplit=1)[0].strip()[:80]
    title = title or "未命名"
    return {
        "platform": platform,
        "platform_name": "小红书" if platform == "xhs" else "抖音" if platform == "douyin" else "视频号" if platform == "shipinhao" else platform,
        "title": title,
        "content": content,
        "short_url": source_url,
        "work_url": detail_data.get(cfg.get("work_url", "")) or canonical_url,
        "work_id": detail_data.get("workId") or detail_data.get("videoId") or fallback_work_id or infer_work_id(detail_data.get(cfg.get("work_url", ""), "") or canonical_url, platform),
        "author": detail_data.get(cfg.get("author", "")) or "博主未返回",
        "publish_time": detail_data.get(cfg.get("publish", "")) or "接口未返回",
        "work_type": detail_data.get(cfg.get("type", "")) or parse_data.get("awemeType") or "视频",
        "cover_url": detail_data.get(cfg.get("cover", "")) or detail_data.get("cover") or parse_data.get("cover") or "",
        "like_count": detail_data.get(cfg.get("like", "")) or detail_data.get("likeNum") or "接口未返回",
        "collect_count": detail_data.get(cfg.get("collect", "")) or detail_data.get("favoriteNum") or detail_data.get("collectNum") or "接口未返回",
        "comment_count": detail_data.get(cfg.get("comment", "")) or detail_data.get("commentNum") or "接口未返回",
        "share_count": detail_data.get(cfg.get("share", "")) or detail_data.get("shareNum") or detail_data.get("forwardCount") or "接口未返回",
        "video_url": detail_data.get("videoUrl") or parse_data.get("videoUrl") or "",
        "image_urls": parse_data.get("imageUrls") or [],
    }


def call_volc_asr(audio_url: str, out_dir: Path) -> str:
    script = SKILL_DIR / "scripts" / "volc_asr_transcribe.py"
    cmd = [
        sys.executable,
        str(script),
        "--audio-url",
        audio_url,
        "--format",
        "mp3",
        "--out-dir",
        str(out_dir),
        "--timeout",
        "900",
        "--poll-interval",
        "5",
    ]
    env = os.environ.copy()
    for name in (
        "VOLC_ASR_API_KEY",
        "VOLCENGINE_ASR_API_KEY",
        "VOLC_ASR_APP_ID",
        "VOLC_ASR_ACCESS_KEY",
        "VOLC_ASR_TOKEN",
    ):
        configured = getenv_from_zshrc(name)
        if configured:
            env[name] = configured
        elif name in {"VOLC_ASR_API_KEY", "VOLCENGINE_ASR_API_KEY"}:
            env.pop(name, None)
    subprocess.run(cmd, check=True, env=env)
    txt = out_dir / "volc_asr_transcript.txt"
    return txt.read_text(encoding="utf-8").strip() if txt.exists() else ""


def download_video(video_url: str, dest: Path) -> None:
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [
                curl,
                "-L",
                "--fail",
                "--retry",
                "2",
                "-A",
                "Mozilla/5.0",
                "-o",
                str(dest),
                video_url,
            ],
            check=True,
        )
        return

    req = urllib.request.Request(video_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def extract_mp3(video_path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise RuntimeError(
                "ffmpeg not found. Install ffmpeg or `python3.11 -m pip install imageio-ffmpeg` "
                "to enable local Douyin audio fallback."
            ) from exc
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(audio_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def public_audio_url(process_dir: Path, video_url: str) -> tuple[str, Path]:
    public_base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        raise RuntimeError("PUBLIC_BASE_URL is not configured, cannot publish local audio for ASR fallback.")

    public_root = Path(os.environ.get("PUBLIC_FILE_DIR", "/opt/biji-selfhost/data/public"))
    public_asr_dir = public_root / "asr"
    public_asr_dir.mkdir(parents=True, exist_ok=True)

    local_dir = process_dir / "local_audio"
    local_dir.mkdir(parents=True, exist_ok=True)
    token = f"{int(time.time())}-{uuid.uuid4().hex[:12]}"
    video_path = local_dir / f"{token}.mp4"
    audio_path = local_dir / f"{token}.mp3"

    download_video(video_url, video_path)
    extract_mp3(video_path, audio_path)

    public_name = f"{token}.mp3"
    public_path = public_asr_dir / public_name
    shutil.copy2(audio_path, public_path)
    return f"{public_base}/public/asr/{urllib.parse.quote(public_name)}", public_path


def run_asr(video_url: str, process_dir: Path) -> str:
    if not video_url:
        return ""

    out_dir = process_dir / "asr"
    try:
        return call_volc_asr(video_url, out_dir)
    except subprocess.CalledProcessError as direct_error:
        fallback_url, fallback_path = public_audio_url(process_dir, video_url)
        try:
            return call_volc_asr(fallback_url, out_dir)
        except subprocess.CalledProcessError as fallback_error:
            raise RuntimeError(
                "Volc ASR failed with the original video URL and with the local audio fallback. "
                f"original_status={direct_error.returncode} fallback_status={fallback_error.returncode} "
                f"fallback_url={fallback_url}"
            ) from fallback_error
        finally:
            fallback_path.unlink(missing_ok=True)


def simple_paragraphs(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    if not text:
        return "未获取到口播文稿。"
    parts = re.split(r"(?<=[。！？])", text)
    paras = []
    buf = ""
    for part in parts:
        if not part:
            continue
        buf += part
        if len(buf) >= 90:
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
    return "\n\n".join(paras)


def build_markdown(record: dict, transcript: str, detail_status: str) -> str:
    source_note = detail_status or "RedFox parseWork/parse + 火山 ASR"
    data_heading = "为什么数据会好" if all(isinstance(record.get(k), int) and record[k] >= 1000 for k in ["like_count"]) else "为什么数据目前不高但值得参考"
    return f"""# {record['title']}

## 原作品信息

| 字段 | 内容 |
|---|---|
| 原作品标题 | {record['title']} |
| 发布平台 | {record['platform_name']} |
| 博主名称 | {record['author']} |
| 发布时间 | {record['publish_time']} |
| 原链接 | {record['short_url']} |
| 作品链接 | {record['work_url'] or '接口未返回'} |
| 作品 ID | {record['work_id'] or '接口未返回'} |
| 作品类型 | {record['work_type']} |
| 封面 URL | {record['cover_url'] or '接口未返回'} |
| 作品描述 | {record['content'] or '接口未返回'} |
| 点赞数 | {record['like_count']} |
| 收藏数 | {record['collect_count']} |
| 评论数 | {record['comment_count']} |
| 分享数 | {record['share_count']} |
| 数据来源 | {source_note} |

---

## 口播文稿整理版

{simple_paragraphs(transcript)}

---

## 文章总结

请总结这条内容的主旨、关键论证、读者能带走的结论，以及内容背后的转化/表达意图。

---

## 这篇文稿能让我学到什么

请基于上面的整理版文稿补充：核心观点、可迁移方法、适合自己的行动建议。

---

## 这篇内容真正的价值

请补充：它解决了哪个真实问题，给用户降低了什么成本，为什么值得收藏或转发。

---

## {data_heading}

请结合标题、选题、人群、表达结构、数据表现和平台语境分析。

---

## 可复用的创作方法

请提炼为 5-8 步可复用结构。

---

## 选题拓展

请给出 20 个可直接参考的选题标题，按方向分组。
"""


def find_cached(output_dir: Path, url: str) -> Optional[Path]:
    if not output_dir.exists():
        return None
    for path in output_dir.rglob("*.md"):
        try:
            if url and url in path.read_text(encoding="utf-8", errors="ignore"):
                return path
        except OSError:
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a final digest Markdown for one XHS/Douyin/WeChat work.")
    parser.add_argument("--input", required=True, help="Share text or URL.")
    parser.add_argument("--output-dir", default="outputs/short-video-digest")
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--complete-data", action="store_true", help="Call platform detail API.")
    parser.add_argument("--work-id", help="Canonical platform work ID resolved from a browser.")
    parser.add_argument("--work-url", help="Canonical platform work URL resolved from a browser.")
    parser.add_argument("--keep-process", action="store_true")
    parser.add_argument("--no-asr", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="For WeChat/Jina Reader: request fresh content.")
    args = parser.parse_args()

    input_url = extract_url(args.input)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = Path(args.workspace) / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    cached = find_cached(output_dir, input_url)
    if cached:
        print(json.dumps({"cached": True, "final_markdown": str(cached)}, ensure_ascii=False, indent=2))
        return

    if is_wechat_url(input_url) and not is_shipinhao_url(input_url):
        run_wechat_digest(args, input_url, output_dir)
        return

    key = redfox_key()
    parse_result = parse_work(input_url, key)
    parse_data = parse_result["data"]
    platform = parse_data.get("platform") or (
        "xhs" if any(marker in input_url.lower() for marker in ("xhslink", "xiaohongshu.com"))
        else "douyin" if any(marker in input_url.lower() for marker in ("douyin.com", "iesdouyin.com"))
        else "shipinhao" if is_shipinhao_url(input_url)
        else ""
    )
    canonical_url = args.work_url or (input_url if infer_work_id(input_url, platform) else "")
    work_id = args.work_id or infer_work_id(canonical_url or input_url, platform)

    detail_result, detail_data = ({}, {})
    detail_status = ""
    if args.complete_data or platform == "douyin" or platform == "shipinhao":
        try:
            detail_result, detail_data = detail_work(platform, canonical_url or input_url, work_id, key)
            if detail_data:
                detail_status = "RedFox 详情接口 + parseWork/parse + 火山 ASR"
            elif detail_result:
                detail_status = f"详情接口未返回数据：{detail_result.get('msg') or detail_result.get('code')}"
        except Exception as exc:
            detail_status = f"详情接口失败：{exc}"

    record = normalize(platform, parse_data, detail_data, input_url, canonical_url, work_id)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work_dir = output_dir / f"{platform or 'work'}-{stamp}"
    process_dir = work_dir / "_process"
    process_dir.mkdir(parents=True, exist_ok=True)
    (process_dir / "parse_result.json").write_text(json.dumps(parse_result, ensure_ascii=False, indent=2), encoding="utf-8")
    if detail_result:
        (process_dir / "detail_result.json").write_text(json.dumps(detail_result, ensure_ascii=False, indent=2), encoding="utf-8")

    transcript = ""
    if not args.no_asr:
        transcript = run_asr(record["video_url"], process_dir)

    filename = f"{safe_filename(record['title'])}_{record['platform_name']}_{safe_filename(record['author'])}_{stamp}.md"
    final_path = work_dir / filename
    final_path.write_text(build_markdown(record, transcript, detail_status), encoding="utf-8")

    if not args.keep_process:
        shutil.rmtree(process_dir, ignore_errors=True)

    print(json.dumps({
        "cached": False,
        "final_markdown": str(final_path),
        "platform": platform,
        "title": record["title"],
        "author": record["author"],
        "video_url_used_for_asr": record["video_url"],
        "detail_status": detail_status,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
