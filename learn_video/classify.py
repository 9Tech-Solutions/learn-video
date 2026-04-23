"""Post-fusion classification: suggests a downstream form for /learn-eval.

One cheap Flash Lite call after the content is fused. Tells /learn-eval
whether this looks like a reusable ``skill``, a guardrail ``rule``, a
one-off ``tip``, a context-only ``note``, or low-signal ``discard`` material.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from . import cache, config, logging_, model_client
from .state import FusedBlock, RecommendedForm

_MAX_CONTENT_CHARS = 12_000


class FormClassification(BaseModel):
    form: Literal["skill", "rule", "tip", "note", "discard"]
    reason: str = Field(min_length=1)


_SYSTEM_PROMPT = """You are classifying video notes to route them in a knowledge system.

Output one of:
- "skill":   teaches a reusable technique or pattern with enough structure
             to turn into a SKILL.md (how/when/examples). E.g. a coding
             tutorial with a specific workflow.
- "rule":    a guardrail, convention, or do/don't worth enforcing project-wide.
             E.g. "always use parameterized queries," "never mutate props."
- "tip":     one small trick or shortcut, not enough to stand as a skill.
             E.g. a single terminal keybind, a lesser-known CLI flag.
- "note":    context worth remembering but not a reusable rule. Industry
             news, market commentary, a product demo, a personal anecdote.
- "discard": no reusable signal. Pure entertainment, broken content,
             filler with no teaching.

Pick the one that fits best. Return a one-sentence reason.
"""


def _brief_content(title: str, video_kind: str, blocks: list[FusedBlock]) -> str:
    lines: list[str] = [f"Title: {title}", f"Video kind: {video_kind}", "", "Blocks:"]
    used = 0
    for b in blocks:
        piece = f"- [{int(b.t // 60):02d}:{int(b.t % 60):02d}] {b.fused}"
        if used + len(piece) > _MAX_CONTENT_CHARS:
            lines.append("[...truncated...]")
            break
        lines.append(piece)
        used += len(piece)
    return "\n".join(lines)


def node(state: dict[str, Any]) -> dict[str, Any]:
    video_id = state["video_id"]
    paths = cache.paths_for(video_id)

    meta = cache.read_meta(paths)
    if not state.get("fresh") and meta.get("recommended_form"):
        return {
            "recommended_form": meta["recommended_form"],
            "recommended_form_reason": meta.get("recommended_form_reason") or "",
        }

    blocks = list(state.get("fused_blocks") or [])
    if not blocks:
        return {
            "recommended_form": "discard",
            "recommended_form_reason": "no content produced by pipeline",
        }

    model_id = config.resolve_model_id(
        role="targeting",  # cheap text tier
        tier=state.get("tier", "lite"),
        offline=bool(state.get("offline")),
        model_override=None,
    )
    model = model_client.tag_model(model_client.build_chat_model(model_id), model_id)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _brief_content(
                title=state.get("title") or "(untitled)",
                video_kind=state.get("video_kind") or "unknown",
                blocks=blocks,
            ),
        },
    ]

    with logging_.stage("CLASSIFY", f"{model_id} suggesting downstream form"):
        classification: FormClassification = model_client.invoke_structured(
            model, FormClassification, messages
        )

    form: RecommendedForm = classification.form
    logging_.emit("CLASSIFY", f"→ {form}: {classification.reason}")

    cache.update_meta(
        paths,
        recommended_form=form,
        recommended_form_reason=classification.reason,
    )
    return {
        "recommended_form": form,
        "recommended_form_reason": classification.reason,
    }
