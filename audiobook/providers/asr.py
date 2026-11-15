"""Lazy faster-whisper adapter and a deterministic mock adapter for tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from audiobook.domain.models import Transcript, TranscriptSegment


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class ASRProvider:
    def transcribe(self, audio_file: str | Path, language: str = "zh", word_timestamps: bool = True) -> Transcript:
        raise NotImplementedError


class FasterWhisperProvider(ASRProvider):
    def __init__(self, model_size: str | None = None, device: str | None = None, compute_type: str | None = None):
        load_dotenv(PROJECT_ROOT / ".env")
        self.model_size = model_size or os.getenv("ASR_MODEL", "small")
        self.device = device or os.getenv("ASR_DEVICE", "cpu")
        self.compute_type = compute_type or os.getenv(
            "ASR_COMPUTE_TYPE", "int8" if self.device == "cpu" else "float16"
        )
        self.model_path = os.getenv("ASR_MODEL_PATH", "").strip()
        self.hf_home = Path(os.getenv("HF_HOME", str(PROJECT_ROOT / ".cache" / "huggingface")))
        self.local_files_only = _env_bool("ASR_LOCAL_FILES_ONLY", False)
        self._model = None

    def _cached_model_path(self) -> Path | None:
        requested_path = Path(self.model_path) if self.model_path else Path(self.model_size)
        if requested_path.is_dir():
            return requested_path

        model_dir = self.hf_home / "hub" / f"models--Systran--faster-whisper-{self.model_size}"
        snapshots_dir = model_dir / "snapshots"
        if not snapshots_dir.is_dir():
            return None

        required_files = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}
        for snapshot in sorted(snapshots_dir.iterdir(), reverse=True):
            if snapshot.is_dir() and required_files.issubset({item.name for item in snapshot.iterdir()}):
                return snapshot
        return None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("未安装 faster-whisper，请先安装项目依赖。") from exc
            cached_path = self._cached_model_path()
            model_ref = str(cached_path) if cached_path else self.model_size
            local_only = self.local_files_only or cached_path is not None
            if self.local_files_only and cached_path is None and not Path(self.model_size).is_dir():
                raise RuntimeError(
                    f"本地没有找到 faster-whisper 模型「{self.model_size}」。"
                    f"请先运行 `py scripts/download_model.py`，或将 ASR_LOCAL_FILES_ONLY 设置为 false。"
                )
            try:
                self._model = WhisperModel(
                    model_ref,
                    device=self.device,
                    compute_type=self.compute_type,
                    local_files_only=local_only,
                )
            except Exception as exc:
                if "ConnectTimeout" in str(exc) or "LocalEntryNotFoundError" in str(exc):
                    raise RuntimeError(
                        "无法访问 Hugging Face 且本地没有可用模型缓存。"
                        "请先在可联网环境运行 `py scripts/download_model.py`，或检查 HF_ENDPOINT/网络设置。"
                    ) from exc
                raise
        return self._model

    def transcribe(self, audio_file: str | Path, language: str = "zh", word_timestamps: bool = True) -> Transcript:
        model = self._load_model()
        segments, info = model.transcribe(
            str(audio_file),
            language=language,
            word_timestamps=word_timestamps,
            vad_filter=True,
            beam_size=5,
        )
        output: list[TranscriptSegment] = []
        for segment in segments:
            words: list[dict[str, Any]] = []
            for word in segment.words or []:
                words.append(
                    {
                        "start": float(word.start),
                        "end": float(word.end),
                        "word": word.word,
                        "probability": float(getattr(word, "probability", 0.0) or 0.0),
                    }
                )
            avg_logprob = float(getattr(segment, "avg_logprob", -1.0) or -1.0)
            confidence = max(0.0, min(1.0, 1.0 + avg_logprob / 2.0))
            output.append(
                TranscriptSegment(
                    start=float(segment.start),
                    end=float(segment.end),
                    text=str(segment.text).strip(),
                    confidence=round(confidence, 4),
                    words=words,
                    audio_file=str(audio_file),
                )
            )
        return Transcript(
            audio_file=str(audio_file),
            language=str(getattr(info, "language", language) or language),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
            segments=output,
        )


class MockASRProvider(ASRProvider):
    """Load a transcript fixture keyed by file name for tests and demos."""

    def __init__(self, fixture: dict[str, Any] | str | Path):
        if isinstance(fixture, (str, Path)):
            fixture = json.loads(Path(fixture).read_text(encoding="utf-8"))
        self.fixture = fixture

    def transcribe(self, audio_file: str | Path, language: str = "zh", word_timestamps: bool = True) -> Transcript:
        name = Path(audio_file).name
        payload = self.fixture.get(name, self.fixture.get("default", {}))
        segments = [
            TranscriptSegment(
                start=float(raw.get("start", 0.0)),
                end=float(raw.get("end", 0.0)),
                text=str(raw.get("text", "")),
                confidence=float(raw.get("confidence", 0.95)),
                words=list(raw.get("words", []) or []),
                audio_file=str(audio_file),
            )
            for raw in payload.get("segments", [])
        ]
        return Transcript(
            audio_file=str(audio_file),
            language=payload.get("language", language),
            duration=payload.get("duration"),
            segments=segments,
        )
