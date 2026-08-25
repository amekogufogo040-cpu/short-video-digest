#!/usr/bin/env python3
"""Opt-in fallback: extract Douyin copy with RedFox async ASR and save an OB-sync source note.

The normal capture path uses Volcengine ASR in short_video_digest_to_obsidian.py.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, time, uuid
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
SHARED = HERE / "short_video_digest.py"

def key() -> str:
    value = os.environ.get("REDFOX_API_KEY", "").strip()
    if value: return value
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists():
        found = re.findall(r"export\s+REDFOX_API_KEY=[\"']?([^\"'\n]+)", zshrc.read_text(errors="ignore"))
        if found: return found[-1].strip()
    raise SystemExit("Missing REDFOX_API_KEY.")

def post(path: str, payload: dict, api_key: str) -> dict:
    req = Request("https://redfox.hk" + path, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"REDFOX_API_KEY": api_key, "Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=90) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))

def safe(text: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", re.sub(r"\s+", " ", text or "未命名")).strip()[:120] or "未命名"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--vault", required=True)
    ap.add_argument("--notes-dir", required=True)
    ap.add_argument("--task-id")
    args = ap.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    if not (vault / ".obsidian").is_dir(): raise SystemExit(f"Not an Obsidian vault: {vault}")
    notes = (vault / args.notes_dir).resolve(); notes.mkdir(parents=True, exist_ok=True)
    url_match = re.search(r"https?://[^\s，。；、)]+", args.input)
    if not url_match: raise SystemExit("No Douyin URL found.")
    url = url_match.group(0).rstrip("\\")
    api_key = key()
    task_id = args.task_id
    if not task_id:
        submit = post("/story/api/parseWork/audioTextExtract/submit/douyin", {"url": url}, api_key)
        task_id = (submit.get("data") or {}).get("taskId")
        if not task_id: raise SystemExit(json.dumps(submit, ensure_ascii=False))
    result = {}
    for _ in range(36):
        result = post("/story/api/parseWork/audioTextExtract/result/douyin", {"taskId": task_id}, api_key)
        data = result.get("data") or {}
        if data.get("status") in {"succeeded", "failed"}: break
        time.sleep(5)
    data = result.get("data") or {}
    text = (data.get("text") or "").strip()
    if not text: raise SystemExit(f"RedFox transcription failed: {json.dumps(result, ensure_ascii=False)}")
    title_match = re.search(r"看看【([^】]+)的作品】", args.input)
    title = title_match.group(1) if title_match else "抖音视频文稿"
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z"); date = now[:10]
    note_text = "\n".join([
        "---", f"id: {uuid.uuid4()}", "type: source-note", "status: 待消化", "source: 抖音", "source_platform: douyin", f"original_url: {url}", "author: 未知作者", "content_type: video_transcript", f"captured_at: {now}", f"updated_at: {now}", "tags:", "  - 第二大脑/采集", "  - 来源/抖音", "  - 类型/视频文稿", "---", "", f"# {safe(title)}", "", "<!-- biji-sync:start -->", "> [!info] 来源卡片", f"> **抖音 · 视频文稿**", f"> [打开原内容](<{url}>) · 采集于 {date}", "", "## 口播文稿", "", text, "", "<!-- biji-sync:end -->", ""
    ])
    path = notes / f"{date} {safe(title)}.md"; path.write_text(note_text, encoding="utf-8")
    print(json.dumps({"markdown": str(path), "taskId": task_id, "characters": len(text)}, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
