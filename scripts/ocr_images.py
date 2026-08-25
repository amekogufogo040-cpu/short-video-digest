#!/usr/bin/env python3
"""Cross-platform local OCR for covers and image-based post bodies."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def vision(paths: list[Path]) -> dict[str, list[dict]]:
    command = ["swift", str(HERE / "ocr_image_text.swift"), *(str(path) for path in paths)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=90, check=True)
    payload = json.loads(result.stdout)
    return payload if isinstance(payload, dict) else {}


def rapidocr(paths: list[Path]) -> dict[str, list[dict]]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    output: dict[str, list[dict]] = {}
    for path in paths:
        result, _ = engine(str(path))
        items: list[dict] = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            text = str(item[1]).strip()
            if not text:
                continue
            confidence = item[2] if len(item) > 2 else 0
            try:
                confidence = float(confidence)
            except (TypeError, ValueError):
                confidence = 0
            box = item[0] if isinstance(item[0], (list, tuple)) else []
            xs = [float(point[0]) for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
            ys = [float(point[1]) for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
            items.append({
                "text": text,
                "confidence": confidence,
                "x": min(xs) if xs else 0,
                "y": min(ys) if ys else 0,
                "width": max(xs) - min(xs) if xs else 0,
                "height": max(ys) - min(ys) if ys else 0,
            })
        output[str(path)] = items
    return output


def main() -> None:
    paths = [Path(value).expanduser().resolve() for value in sys.argv[1:]]
    if not paths:
        raise SystemExit("usage: ocr_images.py <image> [<image> ...]")
    try:
        payload = vision(paths) if sys.platform == "darwin" else rapidocr(paths)
    except (ImportError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
        try:
            payload = rapidocr(paths)
        except (ImportError, OSError, RuntimeError):
            payload = {str(path): [] for path in paths}
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
