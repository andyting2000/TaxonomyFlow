# services/prompts/__init__.py
"""
Prompts Package
Contains all prompt templates for Stage 1 and Stage 2 processing
"""

from .stage1_prompts import CLASSIFICATION_PROMPT, FEW_SHOT_EXAMPLES
from .stage2_prompt_builder import Stage2PromptBuilder

__all__ = [
    'CLASSIFICATION_PROMPT',
    'FEW_SHOT_EXAMPLES',
    'Stage2PromptBuilder',
]