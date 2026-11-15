"""Streamlit entry point for the audiobook production MVP."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

def _read_uploaded_text(uploaded_file) -> str:
    raw = uploaded_file.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("原文文件无法按 UTF-8 或 GB18030 解码。")


def _result_json(
    result: dict,
    issue_statuses: dict[str, str] | None = None,
    post_result: dict | None = None,
) -> dict:
    issue_statuses = issue_statuses or {}
    review_issues = []
    for item in result["issues"]:
        issue = item.to_dict()
        issue["review_status"] = issue_statuses.get(item.issue_id, "待确认")
        review_issues.append(issue)
    return {
        "mode": result["mode"],
        "script": {"segments": [item.to_dict() for item in result["script"]]},
        "transcript": result["transcript"].to_dict(),
        "alignment": {"items": [item.to_dict() for item in result["alignments"]]},
        "review": {"issues": review_issues},
        "post": post_result or {"cues": [], "unmatched": []},
    }


ISSUE_LABELS = {
    "omission": "可能漏读",
    "insertion": "可能多读",
    "replacement": "可能错读或替换",
    "reorder": "语序可能变化",
    "segmentation": "暂时无法可靠对齐",
    "cutoff": "可能被截断",
    "silence": "出现较长静音",
    "clipping": "可能有削波",
    "tooling": "音频工具无法读取",
    "quality_unavailable": "音频质量检查未完成",
    "other": "其他问题",
}

SEVERITY_LABELS = {
    "high": "优先处理",
    "medium": "建议复听",
    "low": "顺手确认",
}


def _issue_label(issue_type: str) -> str:
    return ISSUE_LABELS.get(issue_type, issue_type or "未分类问题")


def _severity_label(severity: str) -> str:
    return SEVERITY_LABELS.get(severity, severity or "待确认")


def _format_time(value: float | None) -> str:
    if value is None:
        return "未定位"
    total = max(0, int(value))
    minutes, seconds = divmod(total, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _issue_reason(issue) -> str:
    reasons = {
        "omission": "录音转写中没有找到与原文对应的内容，可能是漏读，也可能是 ASR 没听清。",
        "insertion": "录音转写中出现了原文没有的内容，可能是多读、口头改词或 ASR 误识别。",
        "replacement": "录音和原文有部分文字不同，可能是错读、同义替换，也可能是 ASR 误识别。",
        "segmentation": "系统还不能足够有把握地把这段原文对应到录音中的位置。",
        "silence": "系统在这段音频中发现了较长的静音，可能是停顿过长或录音中断。",
        "clipping": "音量峰值过高，可能出现破音；需要实际听一下确认。",
        "tooling": "音频质量检查工具没有成功读取文件，因此这部分结果不能作为判断依据。",
        "quality_unavailable": "当前环境没有完成静音/削波检查，这不是文本差异；文本审听结果仍可参考。",
    }
    return reasons.get(issue.issue_type, "系统发现了一个需要人工复听确认的异常。")


def _issue_action(issue) -> str:
    if issue.audio_start is not None:
        return f"先播放 { _format_time(issue.audio_start) } 附近，确认后再决定是否返工。"
    return "这条没有可靠时间码，请在原音频中按片段顺序人工确认。"


def _sorted_issues(issues):
    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        issues,
        key=lambda issue: (
            severity_order.get(issue.severity, 3),
            issue.audio_start if issue.audio_start is not None else float("inf"),
        ),
    )


def main() -> None:
    import streamlit as st

    from audiobook.report import json_bytes, markdown_report, project_zip, timeline_csv
    from audiobook.storage.session import JobStorage
    from audiobook.pipeline.post import load_asset_library, recommend_cues
    from audiobook.workflow import run_review

    st.set_page_config(page_title="有声书生产工作流", page_icon="🎧", layout="wide")
    st.title("有声书生产工作流 MVP")
    st.caption("当前主链路：画本 → 审听 → 对轨结果与审听报告")

    if "job_storage" not in st.session_state:
        st.session_state.job_storage = JobStorage()
    if st.button("清理当前任务"):
        st.session_state.job_storage.clear()
        st.session_state.job_storage = JobStorage()
        st.session_state.pop("result", None)
        st.session_state.pop("review_statuses", None)
        st.session_state.pop("review_run_id", None)
        st.rerun()

    with st.sidebar:
        st.header("项目设置")
        chapter_id = st.text_input("章节 ID", value="chapter-01")
        mode_label = st.selectbox("音频组织方式", ["自动判断", "一段一个音频", "一章长音频"])
        mode = {"自动判断": "auto", "一段一个音频": "short", "一章长音频": "long"}[mode_label]
        roles = st.text_area("已知角色（可选）", placeholder="林默\n苏晚")
        scene_notes = st.text_area("场景说明（可选）", placeholder="夜晚、雨天、室内")
        st.divider()
        st.caption(f"ASR 模型：{os.getenv('ASR_MODEL', 'small')}")
        st.caption(f"设备：{os.getenv('ASR_DEVICE', 'cpu')}")
        if not os.getenv("LLM_API_KEY"):
            st.info("未配置 LLM_API_KEY，将使用降级画本模式。")

    source = st.file_uploader("上传原文（TXT/Markdown）", type=["txt", "md"])
    audio_files = st.file_uploader(
        "上传音频（MP3/WAV/M4A/FLAC）",
        type=["mp3", "wav", "m4a", "flac"],
        accept_multiple_files=True,
    )

    if st.button("运行画本与审听", type="primary", disabled=not source or not audio_files):
        from audiobook.providers.asr import FasterWhisperProvider

        try:
            source_text = _read_uploaded_text(source)
            saved_audio = [
                st.session_state.job_storage.save_bytes(uploaded.name, uploaded.getvalue())
                for uploaded in audio_files
            ]
            with st.status("正在处理有声书项目…", expanded=True) as status:
                st.write("生成结构化画本…")
                st.write("运行 ASR 和文本比对…")
                result = run_review(
                    source_text=source_text,
                    audio_files=saved_audio,
                    mode=mode,
                    chapter_id=chapter_id,
                    roles=roles,
                    scene_notes=scene_notes,
                    asr=FasterWhisperProvider(
                        model_size=os.getenv("ASR_MODEL", "small"),
                        device=os.getenv("ASR_DEVICE", "cpu"),
                        compute_type=os.getenv("ASR_COMPUTE_TYPE"),
                    ),
                )
                status.update(label="处理完成", state="complete")
            st.session_state.result = result
            st.session_state.review_statuses = {}
            st.session_state.review_run_id = st.session_state.get("review_run_id", 0) + 1
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get("result")
    if not result:
        st.info("先上传原文和音频，再点击“运行画本与审听”。首次运行 ASR 可能需要下载模型。")
        with st.expander("第一次使用，按这 3 步就够了", expanded=True):
            st.markdown(
                """
                1. 上传一个 `.txt` 原文和一个音频文件。
                2. 点击 **运行画本与审听**，等待处理完成。
                3. 先看页面上方的 **检查结论**，再到 **审听结果** 逐条播放确认。

                看到“可能漏读/错读”不代表一定有问题，它表示系统发现了值得人工听一下的地方。
                """
            )
        return

    script = result["script"]
    transcript = result["transcript"]
    alignments = result["alignments"]
    issues = result["issues"]
    asset_library_path = Path(__file__).resolve().parent / "library" / "audio-assets.json"
    post_result = recommend_cues(
        script,
        alignments,
        load_asset_library(asset_library_path),
        scene_notes=result.get("scene_notes", ""),
    )
    review_statuses = st.session_state.setdefault("review_statuses", {})
    review_run_id = st.session_state.setdefault("review_run_id", 1)
    for issue in issues:
        review_statuses.setdefault(issue.issue_id, "待确认")

    # Put a plain-language conclusion before the technical tabs. New users should
    # not need to understand JSON, confidence scores, or alignment statuses first.
    ordered_issues = _sorted_issues(issues)
    issue_counts = Counter(issue.issue_type for issue in issues)
    active_issues = [
        issue
        for issue in issues
        if review_statuses.get(issue.issue_id, "待确认") not in {"误报/无需返工", "已处理"}
    ]
    high_count = sum(issue.severity == "high" for issue in active_issues)
    processed_count = sum(review_statuses.get(issue.issue_id) == "已处理" for issue in issues)
    review_count = sum(item.review_required for item in script)
    st.subheader("检查结论")
    st.caption("先看这里判断要不要复听；“可能”表示系统发现疑点，不是最终裁定。")
    if not issues:
        st.success("目前没有发现文本差异或音频质量异常。建议仍随机抽听几段，确认录音整体自然。")
    else:
        if high_count:
            st.warning(f"发现 {len(issues)} 个问题，当前还有 {len(active_issues)} 个未关闭，其中 {high_count} 个优先处理。")
        else:
            st.info(f"发现 {len(issues)} 个问题，当前还有 {len(active_issues)} 个未关闭。")

        summary_columns = st.columns(3)
        summary_columns[0].metric("待处理", len(active_issues))
        summary_columns[1].metric("优先处理", high_count)
        summary_columns[2].metric("已处理", processed_count)
        st.write(
            "；".join(
                f"{_issue_label(issue_type)} {count} 条" for issue_type, count in issue_counts.most_common()
            )
        )
        st.markdown("**建议先处理**")
        for issue in ordered_issues[:3]:
            time_text = _format_time(issue.audio_start)
            st.markdown(
                f"- **{_issue_label(issue.issue_type)}** · {time_text} · {issue.segment_id}："
                f"{_issue_reason(issue)}"
            )

    tabs = st.tabs(["画本结果", "审听结果", "对轨结果", "后期建议", "导出"])

    with tabs[0]:
        st.subheader("画本：系统如何拆分原文")
        st.caption("这里的角色和情绪是给后续配音、审听用的提示；不确定的片段会标记为待复核。")
        script_columns = st.columns(3)
        script_columns[0].metric("片段数", len(script))
        script_columns[1].metric("角色/旁白", len({item.speaker for item in script}))
        script_columns[2].metric("待人工复核", review_count)
        script_rows = [
            {
                "片段": item.segment_id,
                "类型": "旁白" if item.type == "narration" else "对白",
                "角色": item.speaker or "未知",
                "原文": item.text,
                "情绪": item.emotion,
                "状态": "待复核" if item.review_required else "可继续",
            }
            for item in script
        ]
        st.dataframe(script_rows, use_container_width=True, hide_index=True)
        with st.expander("查看画本技术字段"):
            st.json([item.to_dict() for item in script])

    with tabs[1]:
        if not issues:
            st.success("没有自动检测到需要复听的问题。你可以直接下载报告，或随机抽听几段。")
        else:
            st.subheader("问题清单")
            filter_label = st.selectbox(
                "筛选问题",
                ["全部", "待处理", "优先处理", "已确认问题", "误报/无需返工", "已处理"],
                help="先处理“优先处理”，听完后把每条标记为已确认问题、误报或已处理。",
            )
            if filter_label == "待处理":
                visible_issues = [issue for issue in ordered_issues if issue in active_issues]
            elif filter_label == "优先处理":
                visible_issues = [
                    issue for issue in ordered_issues
                    if issue in active_issues and issue.severity == "high"
                ]
            elif filter_label == "全部":
                visible_issues = ordered_issues
            else:
                visible_issues = [
                    issue for issue in ordered_issues
                    if review_statuses.get(issue.issue_id, "待确认") == filter_label
                ]
            st.caption(f"当前显示 {len(visible_issues)} / {len(issues)} 条。点击任意一条展开。")
            issue_rows = [
                {
                    "优先级": _severity_label(issue.severity),
                    "问题": _issue_label(issue.issue_type),
                    "处理状态": review_statuses.get(issue.issue_id, "待确认"),
                    "时间": _format_time(issue.audio_start),
                    "片段": issue.segment_id,
                    "原文": issue.expected_text,
                    "录音听到（ASR）": issue.heard_text or "未识别到文本",
                }
                for issue in visible_issues
            ]
            if issue_rows:
                st.dataframe(issue_rows, use_container_width=True, hide_index=True)
            else:
                st.info("这个筛选条件下没有问题。")
            for issue in visible_issues:
                title = (
                    f"{_issue_label(issue.issue_type)} · {_severity_label(issue.severity)} · "
                    f"{_format_time(issue.audio_start)} · {issue.segment_id}"
                )
                with st.expander(title):
                    status_options = ["待确认", "已确认问题", "误报/无需返工", "已处理"]
                    current_status = review_statuses.get(issue.issue_id, "待确认")
                    selected_status = st.selectbox(
                        "处理状态",
                        status_options,
                        index=status_options.index(current_status),
                        key=f"review_status_{review_run_id}_{issue.issue_id}",
                    )
                    review_statuses[issue.issue_id] = selected_status
                    st.markdown(f"**这是什么意思？** {_issue_reason(issue)}")
                    st.markdown(f"**建议怎么做？** {_issue_action(issue)}")
                    st.markdown(f"**原文**：{issue.expected_text or '（音频质量问题，无对应原文）'}")
                    st.markdown(f"**录音听到（ASR）**：{issue.heard_text or '（未识别到文本）'}")
                    if issue.audio_start is not None and issue.audio_end is not None:
                        st.caption(
                            f"定位范围：{_format_time(issue.audio_start)} - {_format_time(issue.audio_end)} "
                            f"（{issue.audio_start:.2f}s - {issue.audio_end:.2f}s）"
                        )
                    if issue.audio_file and Path(issue.audio_file).exists():
                        st.audio(
                            Path(issue.audio_file).read_bytes(),
                            start_time=max(0, int(issue.audio_start or 0)),
                        )
                    with st.expander("查看技术详情"):
                        technical_issue = issue.to_dict()
                        technical_issue["review_status"] = selected_status
                        st.json(technical_issue)

    with tabs[2]:
        st.subheader("对轨：原文片段对应到音频哪里")
        st.caption("当前是句子级定位；低置信度或缺失时间码的片段仍需要人工确认。")
        alignment_rows = [
            {
                "片段": item.segment_id,
                "开始": _format_time(item.start),
                "结束": _format_time(item.end),
                "匹配状态": "已匹配" if item.status == "matched" else "待复核",
                "置信度": f"{item.confidence:.0%}",
                "说明": item.notes,
            }
            for item in alignments
        ]
        st.dataframe(alignment_rows, use_container_width=True, hide_index=True)
        with st.expander("查看对轨技术字段"):
            st.json([item.to_dict() for item in alignments])

    with tabs[3]:
        st.subheader("后期：资源库 BGM 建议")
        st.caption("这里只生成候选 cue 表，不会修改原始人声音频，也不会自动混音。")
        cue_columns = st.columns(3)
        cue_columns[0].metric("候选 cue", len(post_result["cues"]))
        cue_columns[1].metric("没有匹配", len(post_result["unmatched"]))
        cue_columns[2].metric("资源库素材", len(load_asset_library(asset_library_path)))
        if post_result["cues"]:
            st.dataframe(
                [
                    {
                        "Cue": cue["cue_id"],
                        "片段": cue["segment_id"],
                        "素材": cue["asset_id"],
                        "时间": f"{_format_time(cue['start'])} - {_format_time(cue['end'])}",
                        "对白压低": f"{cue['ducking_db']} dB",
                        "状态": "待确认",
                        "理由": cue["reason"],
                    }
                    for cue in post_result["cues"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("当前场景没有找到足够匹配的 BGM，系统没有强行推荐。")
        if post_result["unmatched"]:
            with st.expander("查看没有匹配的片段"):
                st.dataframe(post_result["unmatched"], use_container_width=True, hide_index=True)

    with tabs[4]:
        payload = _result_json(result, review_statuses, post_result)
        st.download_button("下载 script.json", json_bytes(payload["script"]), "script.json", "application/json")
        st.download_button("下载 transcript.json", json_bytes(payload["transcript"]), "transcript.json", "application/json")
        st.download_button("下载 alignment.json", json_bytes(payload["alignment"]), "alignment.json", "application/json")
        st.download_button("下载 review.json", json_bytes(payload["review"]), "review.json", "application/json")
        st.download_button("下载 post-cues.json", json_bytes(payload["post"]), "post-cues.json", "application/json")
        st.download_button("下载 timeline.csv", timeline_csv(alignments), "timeline.csv", "text/csv")
        st.download_button(
            "下载审听报告",
            markdown_report(issues, issue_statuses=review_statuses).encode("utf-8"),
            "review.md",
            "text/markdown",
        )
        st.download_button(
            "下载完整项目 ZIP",
            project_zip(
                script,
                transcript,
                alignments,
                issues,
                issue_statuses=review_statuses,
                post_result=post_result,
            ),
            "audiobook-project.zip",
            "application/zip",
        )


if __name__ == "__main__":
    main()
