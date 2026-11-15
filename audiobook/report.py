"""Export helpers for JSON, CSV and Markdown artifacts."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from audiobook.domain.models import AlignmentItem, ReviewIssue, ScriptSegment, Transcript


ISSUE_TYPE_LABELS = {
    "omission": "可能漏读",
    "insertion": "可能多读",
    "replacement": "可能错读或替换",
    "segmentation": "暂时无法可靠对齐",
    "silence": "出现较长静音",
    "clipping": "可能有削波",
    "quality_unavailable": "音频质量检查未完成",
}


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def markdown_report(
    issues: list[ReviewIssue],
    project_title: str = "有声书审听报告",
    issue_statuses: dict[str, str] | None = None,
) -> str:
    issue_statuses = issue_statuses or {}
    lines = [f"# {project_title}", "", f"问题数量：{len(issues)}", ""]
    if not issues:
        lines.append("未发现文本差异或音频质量问题；仍建议人工抽听确认。")
        return "\n".join(lines) + "\n"
    lines.extend(["| ID | 片段 | 类型 | 严重程度 | 处理状态 | 时间码 | 原文 | ASR | 建议 |", "|---|---|---|---|---|---|---|---|---|"])
    for issue in issues:
        timecode = "-"
        if issue.audio_start is not None and issue.audio_end is not None:
            timecode = f"{issue.audio_start:.2f}s - {issue.audio_end:.2f}s"
        cells = [
            issue.issue_id,
            issue.segment_id,
            ISSUE_TYPE_LABELS.get(issue.issue_type, issue.issue_type),
            issue.severity,
            issue_statuses.get(issue.issue_id, "待确认"),
            timecode,
            issue.expected_text.replace("|", "\\|"),
            issue.heard_text.replace("|", "\\|"),
            issue.suggestion.replace("|", "\\|"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def timeline_csv(alignments: list[AlignmentItem]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["segment_id", "audio_file", "start", "end", "match_type", "confidence", "status", "notes"])
    writer.writeheader()
    for item in alignments:
        writer.writerow(item.to_dict())
    return buffer.getvalue().encode("utf-8-sig")


def project_zip(
    script: list[ScriptSegment],
    transcript: Transcript,
    alignments: list[AlignmentItem],
    issues: list[ReviewIssue],
    project_title: str = "audiobook-project",
    issue_statuses: dict[str, str] | None = None,
    post_result: dict[str, Any] | None = None,
) -> bytes:
    issue_statuses = issue_statuses or {}
    review_issues = []
    for item in issues:
        issue = item.to_dict()
        issue["review_status"] = issue_statuses.get(item.issue_id, "待确认")
        review_issues.append(issue)
    files = {
        "script.json": json_bytes({"title": project_title, "segments": [item.to_dict() for item in script]}),
        "transcript.json": json_bytes(transcript.to_dict()),
        "alignment.json": json_bytes({"items": [item.to_dict() for item in alignments]}),
        "review.json": json_bytes({"issues": review_issues}),
        "post-cues.json": json_bytes(post_result or {"cues": [], "unmatched": []}),
        "timeline.csv": timeline_csv(alignments),
        "review.md": markdown_report(issues, project_title, issue_statuses).encode("utf-8"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
