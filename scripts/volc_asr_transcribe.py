#!/usr/bin/env python3
import argparse
import json
import os
import time
import uuid
from pathlib import Path

import requests


SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
SUCCESS = "20000000"
PROCESSING = {"20000001", "20000002"}
TRANSIENT = {"55000000"}


def build_headers(task_id: str, args: argparse.Namespace) -> dict:
    headers = {
        "X-Api-Resource-Id": args.resource_id,
        "X-Api-Request-Id": task_id,
    }
    api_key = args.api_key or os.getenv("VOLC_ASR_API_KEY") or os.getenv("VOLCENGINE_ASR_API_KEY")
    app_id = args.app_id or os.getenv("VOLC_ASR_APP_ID")
    access_key = args.access_key or os.getenv("VOLC_ASR_ACCESS_KEY") or os.getenv("VOLC_ASR_TOKEN")
    if api_key:
        headers["X-Api-Key"] = api_key
    elif app_id and access_key:
        headers["X-Api-App-Key"] = app_id
        headers["X-Api-Access-Key"] = access_key
    else:
        raise SystemExit(
            "Missing credentials. Set VOLC_ASR_API_KEY for the new console, "
            "or VOLC_ASR_APP_ID + VOLC_ASR_ACCESS_KEY for the old console."
        )
    return headers


def status_from(resp: requests.Response) -> tuple[str, str]:
    return (
        resp.headers.get("X-Api-Status-Code", ""),
        resp.headers.get("X-Api-Message", ""),
    )


def write_outputs(out_dir: Path, task_id: str, result: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "volc_asr_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    text = (result.get("result") or {}).get("text") or ""
    (out_dir / "volc_asr_transcript.txt").write_text(text, encoding="utf-8")

    utterances = (result.get("result") or {}).get("utterances") or []
    lines = [f"# Volcengine ASR Transcript\n\nTask ID: `{task_id}`\n\n"]
    if text:
        lines.extend(["## Full Text\n\n", text, "\n\n"])
    if utterances:
        lines.append("## Segments\n\n")
        for item in utterances:
            start = (item.get("start_time") or 0) / 1000
            end = (item.get("end_time") or 0) / 1000
            seg_text = item.get("text") or ""
            speaker = item.get("additions", {}).get("speaker")
            label = f" speaker={speaker}" if speaker is not None else ""
            lines.append(f"- `{start:.2f}-{end:.2f}`{label} {seg_text}\n")
    (out_dir / "volc_asr_transcript.md").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe an audio URL with Volcengine bigmodel AUC ASR.")
    parser.add_argument("--audio-url", required=True, help="Publicly reachable audio URL.")
    parser.add_argument("--format", default="mp3", choices=["raw", "wav", "mp3", "ogg"])
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--api-key", help="New console X-Api-Key. Prefer env VOLC_ASR_API_KEY.")
    parser.add_argument("--app-id", help="Old console X-Api-App-Key. Prefer env VOLC_ASR_APP_ID.")
    parser.add_argument("--access-key", help="Old console X-Api-Access-Key. Prefer env VOLC_ASR_ACCESS_KEY.")
    parser.add_argument("--resource-id", default="volc.seedasr.auc")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--enable-ddc", action="store_true", help="Enable semantic smoothing.")
    parser.add_argument("--speaker-info", action="store_true", help="Enable speaker clustering.")
    args = parser.parse_args()

    task_id = str(uuid.uuid4())
    headers = build_headers(task_id, args)
    submit_headers = {**headers, "X-Api-Sequence": "-1"}
    body = {
        "user": {"uid": "codex-local"},
        "audio": {
            "format": args.format,
            "url": args.audio_url,
            "language": args.language,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": args.enable_ddc,
            "enable_speaker_info": args.speaker_info,
            "show_utterances": True,
        },
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "volc_asr_submit_body.json").write_text(
        json.dumps({**body, "audio": {**body["audio"], "url": args.audio_url}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "volc_asr_task_id.txt").write_text(task_id, encoding="utf-8")

    submit = requests.post(SUBMIT_URL, headers=submit_headers, json=body, timeout=30)
    submit_code, submit_msg = status_from(submit)
    if submit_code != SUCCESS:
        raise SystemExit(f"Submit failed: status={submit_code} message={submit_msg} body={submit.text[:500]}")

    deadline = time.time() + args.timeout
    last_payload = {}
    while time.time() < deadline:
        query = requests.post(QUERY_URL, headers=headers, json={}, timeout=30)
        code, msg = status_from(query)
        try:
            last_payload = query.json() if query.text.strip() else {}
        except ValueError:
            last_payload = {"raw": query.text}

        if code == SUCCESS:
            write_outputs(out_dir, task_id, last_payload)
            print(out_dir / "volc_asr_transcript.md")
            return
        if code in TRANSIENT and (
            "POOL_FAILURE" in msg or "remote or network error" in msg
        ):
            time.sleep(args.poll_interval)
            continue
        if code not in PROCESSING:
            raise SystemExit(f"Query failed: status={code} message={msg} body={query.text[:1000]}")
        time.sleep(args.poll_interval)

    (out_dir / "volc_asr_last_query.json").write_text(
        json.dumps(last_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raise SystemExit(f"Timed out waiting for task {task_id}")


if __name__ == "__main__":
    main()
