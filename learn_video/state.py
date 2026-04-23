"""Pipeline state schema — TypedDict + Pydantic payloads.

Kept deliberately free of third-party deps beyond Pydantic so every other
module can import from here without pulling LangChain.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field

Tier = Literal["lite", "pro", "max"]
Role = Literal["targeting", "vision"]
TranscriptSource = Literal["captions", "whisper"]
VideoKind = Literal["visual", "audio", "mixed"]
RecommendedForm = Literal["skill", "rule", "tip", "note", "discard"]


class Target(BaseModel):
    """One visual timestamp worth extracting a frame for."""

    t: float = Field(ge=0.0, description="Timestamp in seconds from start")
    why: str = Field(min_length=1, description="Why this moment needs a frame")


class TargetList(BaseModel):
    targets: list[Target] = Field(default_factory=list)


class FrameRef(BaseModel):
    t: float = Field(ge=0.0)
    image_path: str
    transcript_window: str


class FusedBlock(BaseModel):
    t: float = Field(ge=0.0)
    audio: str
    visual: Optional[str] = None
    fused: str


class VisionInput(BaseModel):
    """Single call input for ``model_client.invoke_vision``.

    Exactly one of ``image_b64`` or ``video_path`` should be set for a media
    attachment; omit both for text-only. ``video_path`` is Gemini-only — the
    adapter raises for Claude/Ollama.
    """

    text: str
    image_b64: Optional[str] = None
    video_path: Optional[str] = None


class PipelineState(TypedDict, total=False):
    # --- Inputs ---
    url: str
    video_id: str
    tier: Tier
    offline: bool
    model_override: Optional[str]
    force_short: bool
    fresh: bool
    notes_only: bool

    # --- Populated during run ---
    cache_dir: str
    title: Optional[str]
    duration_s: Optional[float]
    is_short_video: bool
    video_path: Optional[str]
    captions_path: Optional[str]
    transcript: Optional[str]
    transcript_source: TranscriptSource
    targets: list[Target]
    frames: list[FrameRef]
    fused_blocks: list[FusedBlock]
    final_md_path: Optional[str]

    # --- Classification (set by probe_kind + classify nodes) ---
    video_kind: VideoKind
    video_kind_confidence: float
    video_kind_reason: str
    recommended_form: RecommendedForm
    recommended_form_reason: str

    # --- Audit trail ---
    targeting_model_id: str
    vision_model_id: str
    probe_model_id: str
    error: Optional[str]
