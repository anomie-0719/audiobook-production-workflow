from pathlib import Path

from audiobook.domain.models import AlignmentItem, ScriptSegment
from audiobook.pipeline.post import load_asset_library, recommend_cues


def test_post_recommends_library_asset_with_ducking_for_dialogue():
    root = Path(__file__).resolve().parents[1]
    assets = load_asset_library(root / "library" / "audio-assets.json")
    script = [ScriptSegment("s1", "dialogue", "林默", "你终于来了。")]
    alignments = [AlignmentItem("s1", "chapter.mp3", 1.0, 4.0, "asr_alignment", 0.9, "matched")]

    result = recommend_cues(script, alignments, assets, scene_notes="夜晚、雨天")

    assert result["cues"][0]["asset_id"] == "bgm_rain_01"
    assert result["cues"][0]["ducking_db"] == -8
    assert result["cues"][0]["status"] == "candidate"


def test_post_does_not_force_unmatched_asset():
    script = [ScriptSegment("s1", "narration", "旁白", "晴天。")]
    alignments = [AlignmentItem("s1", "chapter.mp3", 1.0, 2.0, "asr_alignment", 0.9, "matched")]

    result = recommend_cues(script, alignments, [], scene_notes="晴天")

    assert result["cues"] == []
    assert result["unmatched"] == [{"segment_id": "s1", "reason": "资源库中没有足够匹配的 BGM，不强行推荐。"}]
