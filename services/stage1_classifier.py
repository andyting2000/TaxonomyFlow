# services/stage1_classifier.py
"""
Stage 1: Multi-Template Statement Classification Service
Updated to detect MULTIPLE financial statement types per page
"""

import logging
import json
import re
from typing import Dict, Optional, Tuple, List
from huggingface_hub import AsyncInferenceClient
from config import settings
from services.prompts.stage1_prompts import CLASSIFICATION_PROMPT, FEW_SHOT_EXAMPLES
from services.template_group_registry import template_group_display_name_map

logger = logging.getLogger(__name__)


class StatementClassifier:
    """
    Stage 1: Classify financial statement pages
    Now supports MULTIPLE statement types per page
    """
    
    # Metadata lookup only. Classification behavior is unchanged; official
    # semantics and user labels come from the canonical taxonomy-backed registry.
    STATEMENT_TYPES = template_group_display_name_map()
    
    def __init__(self):
        self.provider = settings.model_provider
        self.client = AsyncInferenceClient(
            model=settings.ai_vlm_model_id,
            token=settings.model_api_token or settings.hugging_face_token
        )
        logger.info("✅ Multi-Template Statement Classifier initialized")
    
    def is_available(self) -> bool:
        """Check if classifier is available"""
        return self.client is not None
    
    def _build_classification_prompt(self, page_context: str = "") -> str:
        """
        Build classification prompt with few-shot examples
        
        Args:
            page_context: Optional text extracted from page for context
        
        Returns:
            Complete prompt string
        """
        # Build the prompt with few-shot examples
        prompt_parts = [
            CLASSIFICATION_PROMPT,
            "\n\n# Examples of Correct Multi-Template Classifications:\n"
        ]
        
        # Add few-shot examples
        for example in FEW_SHOT_EXAMPLES:
            prompt_parts.append(f"\n## Example {example['id']}:")
            prompt_parts.append(f"Visual Indicators: {example['indicators']}")
            prompt_parts.append(f"Correct Answer: {example['answer']}\n")
        
        # Add context if provided
        if page_context:
            prompt_parts.append(f"\n\n# Additional Context from Page:")
            prompt_parts.append(f"{page_context[:500]}")  # Limit context length
        
        prompt_parts.append("\n\n# Your Classification:")
        prompt_parts.append("Scan the entire page and identify ALL statement types present.")
        prompt_parts.append("Respond with a valid JSON object containing a 'classifications' array.")
        
        return "\n".join(prompt_parts)
    
    async def classify_page(
        self, 
        image_base64: str,
        page_number: int = 1,
        page_context: Optional[str] = None
    ) -> List[Dict]:
        """
        Classify a financial statement page - RETURNS MULTIPLE CLASSIFICATIONS
        
        Args:
            image_base64: Base64 encoded image
            page_number: Page number in document
            page_context: Optional text context from page
        
        Returns:
            List of classification dictionaries, each with:
            {
                'code': str,
                'confidence': float,
                'section_location': str,
                'reasoning': str
            }
        """
        try:
            # Build prompt
            prompt = self._build_classification_prompt(page_context)

            # Prepare messages for VLM
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }]

            # Log the full prompt being sent to LLM
            logger.info(f"🔍 Classifying page {page_number} (multi-template mode)...")
            logger.info("="*80)
            logger.info("STAGE 1 CLASSIFICATION PROMPT (sent to LLM):")
            logger.info("="*80)
            logger.info(prompt)
            logger.info("="*80)
            logger.info(f"Image: base64 encoded ({len(image_base64)} chars)")
            model_name = settings.ai_vlm_model_id
            logger.info(f"Model: {model_name}")
            logger.info(f"Max tokens: 800, Temperature: 0.1")
            logger.info("="*80)

            # Call Hugging Face VLM
            response = await self.client.chat_completion(
                messages=messages,
                max_tokens=800,  # Increased for multiple classifications
                temperature=0.1   # Low temperature for consistency
            )

            # Extract response
            response_text = response.choices[0].message.content.strip()

            # Log the AI response
            logger.info("="*80)
            logger.info("STAGE 1 AI MODEL RESPONSE:")
            logger.info("="*80)
            logger.info(response_text)
            logger.info("="*80)

            # Parse classifications (now returns list)
            classifications = self._parse_classifications(response_text)
            
            if classifications:
                # Log all detected statement types
                statement_summary = ", ".join([
                    f"{c['code']} ({self.STATEMENT_TYPES.get(c['code'], 'Unknown')})"
                    for c in classifications
                ])
                logger.info(
                    f"✅ Page {page_number}: Found {len(classifications)} statement type(s): {statement_summary}"
                )
            else:
                logger.warning(f"⚠️ Could not classify page {page_number}: {response_text[:200]}")
            
            return classifications
            
        except Exception as e:
            logger.error(f"❌ Error classifying page {page_number}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _parse_classifications(self, response_text: str) -> List[Dict]:
        """
        Parse VLM JSON response to extract multiple classifications
        
        Args:
            response_text: Raw response from VLM
        
        Returns:
            List of classification dictionaries
        """
        try:
            # Clean the response to extract only the JSON object
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if not json_match:
                logger.warning(f"No JSON object found in response: {response_text[:200]}")
                return []
            
            json_string = json_match.group(0)
            data = json.loads(json_string)
            
            # Extract classifications array
            classifications = data.get("classifications", [])
            
            if not isinstance(classifications, list):
                logger.warning(f"'classifications' is not an array: {type(classifications)}")
                return []
            
            # Validate each classification
            valid_classifications = []
            for cls in classifications:
                if not isinstance(cls, dict):
                    continue
                
                code = cls.get("code")
                confidence = cls.get("confidence", 0.0)
                section_location = cls.get("section_location", "unknown")
                reasoning = cls.get("reasoning", "")
                
                # Validate the code
                if code not in self.STATEMENT_TYPES:
                    logger.warning(f"Unknown statement code from LLM: {code}")
                    continue
                
                valid_classifications.append({
                    'code': code,
                    'confidence': float(confidence),
                    'section_location': section_location,
                    'reasoning': reasoning
                })
            
            # Sort by section location (top to bottom) for consistent processing
            location_order = {'top': 1, 'middle': 2, 'bottom': 3, 'full': 4, 
                            'left': 1, 'right': 2, 'unknown': 5}
            valid_classifications.sort(
                key=lambda x: location_order.get(x['section_location'], 5)
            )
            
            return valid_classifications
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from response: {response_text[:200]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing classification response: {e}")
            return []
    
    def get_statement_name(self, code: str) -> str:
        """Get readable name for statement code"""
        return self.STATEMENT_TYPES.get(code, "Unknown Statement")
    
    def get_all_statement_types(self) -> Dict[str, str]:
        """Get all available statement types"""
        return self.STATEMENT_TYPES.copy()


# Global instance
statement_classifier = StatementClassifier()
