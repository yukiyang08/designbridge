"""Prompt templates for DesignBridge agents, split by node."""

from designbridge.core.prompts.composer import COMPOSER_PROMPT
from designbridge.core.prompts.layout_agent import (
    LAYOUT_AGENT_PROMPT,
    LAYOUT_REFINEMENT_PROMPT,
)
from designbridge.core.prompts.requirement_analyzer import REQUIREMENT_ANALYZER_PROMPT

__all__ = [
    "COMPOSER_PROMPT",
    "REQUIREMENT_ANALYZER_PROMPT",
    "LAYOUT_AGENT_PROMPT",
    "LAYOUT_REFINEMENT_PROMPT",
]
