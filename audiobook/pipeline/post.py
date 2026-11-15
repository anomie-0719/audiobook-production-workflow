"""Conservative BGM cue recommendations from the local asset library."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from audiobook.domain.models import AlignmentItem, ScriptSegment


def load_asset_library(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("assets", []))


def _tags(value: str) -> set[str]:
    return {item.strip() for item in re.split(r"[,，、;；\s]+", value or "") if item.strip()}


def recommend_cues(
    script_segments: list[ScriptSegment],
    alignments: list[AlignmentItem],
    assets: list[dict[str, Any]],
    scene_notes: str = "",
) -> dict[str, Any]:
    """Return reviewable cues; never invent an asset or approve a license."""

    alignment_by_id = {item.segment_id: item for item in alignments}
    context_tags = _tags(scene_notes)
    cues: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []

    for segment in script_segments:
        alignment = alignment_by_id.get(segment.segment_id)
        if not alignment or alignment.start is None or alignment.end is None or alignment.end <= alignment.start:
            unmatched.append({"segment_id": segment.segment_id, "reason": "缺少可靠时间轴，暂不生成 cue。"})
            continue

        segment_tags = context_tags | set(segment.scene_tags) | set(segment.sound_tags)
        if segment.emotion and segment.emotion != "unknown":
            segment_tags.add(segment.emotion)
        best_asset = None
        best_score = 0
        for asset in assets:
            if asset.get("type") != "bgm":
                continue
            asset_tags = set(asset.get("mood", [])) | set(asset.get("scene", []))
            score = len(segment_tags & asset_tags)
            if score > best_score:
                best_asset = asset
                best_score = score

        if not best_asset or best_score == 0:
            unmatched.append({"segment_id": segment.segment_id, "reason": "资源库中没有足够匹配的 BGM，不强行推荐。"})
            continue

        is_dialogue = segment.type == "dialogue" or segment.speaker not in {"", "旁白", "unknown"}
        ducking_db = -8 if is_dialogue else -4
        license_name = str(best_asset.get("license", "unknown"))
        license_ok = license_name not in {"", "unknown", "未确认"}
        reason = (
            f"匹配标签：{', '.join(sorted(segment_tags & (set(best_asset.get('mood', [])) | set(best_asset.get('scene', [])))))}；"
            f"授权状态：{license_name}；"
            f"{'对白段建议降低背景音量。' if is_dialogue else '旁白段可保持较低背景音量。'}"
        )
        cues.append(
            {
                "cue_id": f"cue_{len(cues) + 1:03d}",
                "segment_id": segment.segment_id,
                "asset_id": str(best_asset.get("asset_id", "")),
                "start": float(alignment.start),
                "end": float(alignment.end),
                "fade_in_ms": 1200,
                "fade_out_ms": 1800,
                "ducking_db": ducking_db,
                "loop": bool(best_asset.get("loopable", False)),
                "status": "candidate" if license_ok else "review_required",
                "review_required": True,
                "reason": reason,
            }
        )

    return {"cues": cues, "unmatched": unmatched}
