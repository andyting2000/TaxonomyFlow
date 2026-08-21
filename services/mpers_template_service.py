# services/mpers_template_service.py - COMPLETE FIXED VERSION
"""
MPERS Template Service - Manages the official MPERS template structure
Provides a fixed hierarchical template for data entry and validation
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from collections import OrderedDict
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MPERSTemplateService:
    """
    Service to manage MPERS template structure
    Provides the official hierarchy and expected fields for MPERS XBRL
    """
    
    def __init__(self, template_file: str = 'mpers_template.json'):
        self.template_file = template_file
        self.template_structure = OrderedDict()
        self.flat_fields = {}
        self.statement_fields = {}
        self.required_fields = set()
        self.optional_fields = set()
        
        self.load_template()
    
    def load_template(self):
        """Load MPERS template from JSON file"""
        template_path = Path(self.template_file)
        
        if not template_path.exists():
            logger.error(f"MPERS template file not found: {self.template_file}")
            return False
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Detect which format we have
            if 'templates' in data:
                # Old mpers_template_analyzer format
                self._load_from_analyzer_format(data)
            elif self._is_enhanced_format(data):
                # New enhanced format (from generate_mpers_template.py)
                self._load_from_enhanced_format(data)
            else:
                # mbrs_structure.json format
                self._load_from_structure_format(data)
            
            # Build helper indexes
            self._build_indexes()
            
            logger.info(f"✅ Loaded MPERS template: {len(self.template_structure)} statements, {len(self.flat_fields)} total fields")
            return True
            
        except Exception as e:
            logger.error(f"Error loading MPERS template: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _is_enhanced_format(self, data: Dict) -> bool:
        """Check if data is in enhanced format"""
        # Enhanced format has statements with 'fields' arrays
        for key, value in data.items():
            if key.startswith('_'):  # Skip metadata
                continue
            if isinstance(value, dict) and 'fields' in value:
                return True
        return False
    
    def _load_from_enhanced_format(self, data: Dict):
        """Load from enhanced format (mpers_template_enhanced.json)"""
        self.template_structure = OrderedDict()
        
        for statement_type, statement_data in data.items():
            # Skip metadata
            if statement_type.startswith('_'):
                continue
            
            # Enhanced format already has the right structure
            if not isinstance(statement_data, dict):
                continue
            
            fields = statement_data.get('fields', [])
            
            self.template_structure[statement_type] = {
                'name': statement_data.get('name', statement_type),
                'description': statement_data.get('description', ''),
                'fields': fields
            }
    
    def _load_from_structure_format(self, data: Dict):
        """Load from mbrs_structure.json format (hierarchical)"""
        self.template_structure = OrderedDict()
        
        for statement_type, statement_data in data.items():
            elements = statement_data.get('elements', [])
            
            self.template_structure[statement_type] = {
                'name': statement_type,
                'fields': []
            }
            
            for idx, element in enumerate(elements):
                field_info = {
                    'id': element['id'],
                    'label': element['label'],
                    'level': element.get('level', 0),
                    'position': idx,
                    'statement_type': statement_type,
                    'xbrl_tag': element['id'],
                    'required': element.get('level', 0) <= 1,
                    'data_type': 'monetary',
                    'period_type': 'instant' if 'Asset' in element['id'] or 'Liability' in element['id'] or 'Equity' in element['id'] else 'duration'
                }
                
                self.template_structure[statement_type]['fields'].append(field_info)
    
    def _load_from_analyzer_format(self, data: Dict):
        """Load from mpers_template_analyzer format"""
        templates = data.get('templates', {})
        
        self.template_structure = OrderedDict()
        
        for statement_type, fields in templates.items():
            self.template_structure[statement_type] = {
                'name': statement_type,
                'fields': []
            }
            
            for xbrl_tag, field_info in fields.items():
                field_data = {
                    'id': xbrl_tag,
                    'label': self._tag_to_label(xbrl_tag),
                    'xbrl_tag': xbrl_tag,
                    'position': field_info.get('position', 0),
                    'statement_type': statement_type,
                    'required': field_info.get('expected', False),
                    'frequency': field_info.get('frequency', 0),
                    'level': 0,
                    'data_type': 'monetary',
                    'period_type': 'duration'
                }
                
                self.template_structure[statement_type]['fields'].append(field_data)
            
            # Sort by position
            self.template_structure[statement_type]['fields'].sort(
                key=lambda x: x['position']
            )
    
    def _build_indexes(self):
        """Build helper indexes for quick lookup"""
        self.flat_fields = {}
        self.statement_fields = {}
        self.required_fields = set()
        self.optional_fields = set()
        
        for statement_type, statement_data in self.template_structure.items():
            self.statement_fields[statement_type] = []
            
            for field in statement_data['fields']:
                field_id = field['id']
                
                # Add to flat lookup
                self.flat_fields[field_id] = field
                
                # Add to statement fields
                self.statement_fields[statement_type].append(field_id)
                
                # Track required vs optional
                if field.get('required', False):
                    self.required_fields.add(field_id)
                else:
                    self.optional_fields.add(field_id)
    
    def _tag_to_label(self, tag: str) -> str:
        """Convert XBRL tag to readable label"""
        import re
        label = re.sub(r'([A-Z])', r' \1', tag).strip()
        return label
    
    def get_template_structure(self) -> OrderedDict:
        """Get the complete template structure"""
        return self.template_structure
    
    def get_statement_types(self) -> List[str]:
        """Get list of all statement types"""
        return list(self.template_structure.keys())
    
    def get_statement_fields(self, statement_type: str) -> List[Dict]:
        """Get all fields for a specific statement type"""
        statement = self.template_structure.get(statement_type)
        if statement:
            return statement['fields']
        return []
    
    def get_field_info(self, field_id: str) -> Optional[Dict]:
        """Get information about a specific field"""
        return self.flat_fields.get(field_id)
    
    def is_required_field(self, field_id: str) -> bool:
        """Check if a field is required in MPERS"""
        return field_id in self.required_fields
        
    async def find_matching_field_hybrid(
        self, 
        extracted_label: str, 
        statement_type: Optional[str] = None,
        position_hint: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Tuple[Optional[str], float]:
        """
        HYBRID matching: Combines string matching + semantic embeddings - FIXED VERSION
        """
        from difflib import SequenceMatcher
        
        # Normalize extracted label
        label_normalized = extracted_label.lower().strip()
        
        # Search in specific statement or all statements
        search_statements = [statement_type] if statement_type else self.get_statement_types()
        
        # Step 1: String-based matching (existing logic)
        string_matches = {}  # field_id -> score
        
        for stmt_type in search_statements:
            fields = self.get_statement_fields(stmt_type)
            
            for field in fields:
                field_label = field['label'].lower().strip()
                field_id = field['id']
                
                # Calculate string similarity
                base_score = SequenceMatcher(None, label_normalized, field_label).ratio()
                
                # Word overlap bonus
                words_extracted = set(label_normalized.split())
                words_field = set(field_label.split())
                
                if words_extracted and words_field:
                    overlap = len(words_extracted & words_field)
                    total = len(words_extracted | words_field)
                    word_score = overlap / total if total > 0 else 0
                    
                    score = (base_score * 0.7) + (word_score * 0.3)
                else:
                    score = base_score
                
                # Position bonus
                if position_hint is not None:
                    field_position = field['position']
                    position_diff = abs(position_hint - field_position)
                    max_diff = len(fields) / 2
                    position_bonus = max(0, 1 - (position_diff / max_diff)) * 0.1
                    score += position_bonus
                
                # Required field bonus
                if field.get('required', False):
                    score += 0.05
                
                string_matches[field_id] = score
        
        # Step 2: Semantic matching (if database available) - FIXED VERSION
        semantic_matches = {}

        if db is not None:
            try:
                from services.semantic_matcher import semantic_matcher
                from sqlalchemy import text
                
                if semantic_matcher.is_available():
                    # Generate embedding for extracted label
                    query_embedding = await semantic_matcher.encode_text(label_normalized)
                    
                    if query_embedding and len(query_embedding) == 1752:  # Verify correct dimensions
                        try:
                            if statement_type:
                                stmt_field_ids = [f['id'] for f in self.get_statement_fields(statement_type)]
                                
                                if len(stmt_field_ids) == 0:
                                    logger.info(f"Skipping semantic search - no template fields for statement type: {statement_type}")
                                    semantic_matches = {} 
                                else:
                                    # Use direct parameter binding compatible with pgvector
                                    sql = text("""
                                        SELECT 
                                            xbrl_tag,
                                            1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                                        FROM mbrs_taxonomy_tags
                                        WHERE embedding IS NOT NULL
                                            AND label NOT LIKE '%[abstract]%'
                                            AND xbrl_tag = ANY(:field_ids)
                                        ORDER BY embedding <=> CAST(:query_embedding AS vector)
                                        LIMIT 10
                                    """)
                                    
                                    # Format embedding as PostgreSQL array literal
                                    embedding_literal = '[' + ','.join(map(str, query_embedding)) + ']'
                                    
                                    result = await db.execute(sql, {
                                        "query_embedding": embedding_literal,
                                        "field_ids": stmt_field_ids
                                    })
                                    
                                    rows = result.fetchall()
                                    
                                    for row in rows:
                                        field_id = row[0]
                                        similarity = float(row[1])
                                        semantic_matches[field_id] = similarity
                                    
                                    logger.info(f"✅ Semantic search found {len(semantic_matches)} matches for '{extracted_label}' in {statement_type}")
                            else:
                                # General search without statement filtering
                                sql = text("""
                                    SELECT 
                                        xbrl_tag,
                                        1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                                    FROM mbrs_taxonomy_tags
                                    WHERE embedding IS NOT NULL
                                        AND label NOT LIKE '%[abstract]%'
                                    ORDER BY embedding <=> CAST(:query_embedding AS vector)
                                    LIMIT 10
                                """)
                                
                                embedding_literal = '[' + ','.join(map(str, query_embedding)) + ']'
                                
                                result = await db.execute(sql, {
                                    "query_embedding": embedding_literal
                                })
                                
                                rows = result.fetchall()
                                
                                for row in rows:
                                    field_id = row[0]
                                    similarity = float(row[1])
                                    semantic_matches[field_id] = similarity
                                
                                logger.info(f"✅ General semantic search found {len(semantic_matches)} matches")
                        
                        except Exception as sql_error:
                            logger.warning(f"Semantic search SQL failed: {sql_error}")
                            semantic_matches = {}
                    else:
                        logger.warning(f"Invalid embedding dimensions: {len(query_embedding) if query_embedding else 0}, expected 1752")
                        semantic_matches = {}
            
            except Exception as e:
                logger.info(f"Semantic matching not available: {e}")
                semantic_matches = {}
        
        # Step 3: Combine scores
        combined_scores = {}
        all_field_ids = set(string_matches.keys()) | set(semantic_matches.keys())
        
        for field_id in all_field_ids:
            string_score = string_matches.get(field_id, 0.0)
            semantic_score = semantic_matches.get(field_id, 0.0)
            
            # Weighted combination
            if semantic_score > 0:
                combined_score = (string_score * 0.4) + (semantic_score * 0.6)
            else:
                # No semantic score available, use string only
                combined_score = string_score
            
            combined_scores[field_id] = combined_score
        
        # Find best match
        if not combined_scores:
            return None, 0.0
        
        best_field_id = max(combined_scores, key=combined_scores.get)
        best_score = combined_scores[best_field_id]
        
        # Log the match details
        if semantic_matches and best_field_id in semantic_matches:
            logger.info(
                f"Hybrid match for '{extracted_label}': {best_field_id} "
                f"(string: {string_matches.get(best_field_id, 0):.2f}, "
                f"semantic: {semantic_matches.get(best_field_id, 0):.2f}, "
                f"combined: {best_score:.2f})"
            )
        
        return best_field_id, best_score

    def find_matching_field(
        self, 
        extracted_label: str, 
        statement_type: Optional[str] = None,
        position_hint: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Tuple[Optional[str], float]:
        """
        Find matching field - delegates to hybrid method if db available
        """
        # For backward compatibility and async context
        # If no db, use string matching only
        if db is None:
            return self._find_matching_field_string_only(
                extracted_label, statement_type, position_hint
            )
        
        # Use hybrid matching (this needs to be called with await in async context)
        # For now, return string-only - caller should use find_matching_field_hybrid directly
        return self._find_matching_field_string_only(
            extracted_label, statement_type, position_hint
        )

    def _find_matching_field_string_only(
        self, 
        extracted_label: str, 
        statement_type: Optional[str] = None,
        position_hint: Optional[int] = None
    ) -> Tuple[Optional[str], float]:
        """
        Original string-only matching (kept for backward compatibility)
        """
        from difflib import SequenceMatcher
        
        label_normalized = extracted_label.lower().strip()
        search_statements = [statement_type] if statement_type else self.get_statement_types()
        
        best_match = None
        best_score = 0.0
        
        for stmt_type in search_statements:
            fields = self.get_statement_fields(stmt_type)
            
            for field in fields:
                field_label = field['label'].lower().strip()
                field_id = field['id']
                
                base_score = SequenceMatcher(None, label_normalized, field_label).ratio()
                
                words_extracted = set(label_normalized.split())
                words_field = set(field_label.split())
                
                if words_extracted and words_field:
                    overlap = len(words_extracted & words_field)
                    total = len(words_extracted | words_field)
                    word_score = overlap / total if total > 0 else 0
                    score = (base_score * 0.7) + (word_score * 0.3)
                else:
                    score = base_score
                
                if position_hint is not None:
                    field_position = field['position']
                    position_diff = abs(position_hint - field_position)
                    max_diff = len(fields) / 2
                    position_bonus = max(0, 1 - (position_diff / max_diff)) * 0.1
                    score += position_bonus
                
                if field.get('required', False):
                    score += 0.05
                
                if score > best_score:
                    best_score = score
                    best_match = field_id
        
        return best_match, best_score
    
    def get_template_for_statement(self, statement_type: str) -> List[Dict]:
        """Get template with empty values for a statement type"""
        fields = self.get_statement_fields(statement_type)
        
        template = []
        for field in fields:
            template.append({
                'field_id': field['id'],
                'label': field['label'],
                'xbrl_tag': field['xbrl_tag'],
                'position': field['position'],
                'level': field.get('level', 0),
                'required': field.get('required', False),
                'value_current_year': None,
                'value_previous_year': None,
                'data_type': field.get('data_type', 'monetary'),
                'period_type': field.get('period_type', 'duration')
            })
        
        return template
    
    def validate_data_completeness(self, statement_type: str, provided_fields: List[str]) -> Dict:
        """Validate if all required fields are provided"""
        expected_fields = set(self.statement_fields.get(statement_type, []))
        provided_set = set(provided_fields)
        
        missing = expected_fields - provided_set
        missing_required = [f for f in missing if f in self.required_fields]
        missing_optional = [f for f in missing if f in self.optional_fields]
        
        extra = provided_set - expected_fields
        
        return {
            'is_complete': len(missing_required) == 0,
            'missing_required': missing_required,
            'missing_optional': missing_optional,
            'extra_fields': list(extra),
            'completion_rate': len(provided_set & expected_fields) / len(expected_fields) if expected_fields else 0
        }
    
    def get_field_order(self, field_id: str) -> int:
        """Get the position/order of a field in its statement"""
        field_info = self.get_field_info(field_id)
        if field_info:
            return field_info.get('position', 999)
        return 999
    
    def export_template_to_csv(self, output_file: str):
        """Export template to CSV for reference"""
        import csv
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Statement Type', 'Position', 'Field ID', 'Label', 
                'XBRL Tag', 'Required', 'Level', 'Period Type'
            ])
            
            for statement_type, statement_data in self.template_structure.items():
                for field in statement_data['fields']:
                    writer.writerow([
                        statement_type,
                        field['position'],
                        field['id'],
                        field['label'],
                        field['xbrl_tag'],
                        'Yes' if field.get('required', False) else 'No',
                        field.get('level', 0),
                        field.get('period_type', 'duration')
                    ])
        
        logger.info(f"Template exported to {output_file}")
    
    def get_statistics(self) -> Dict:
        """Get statistics about the template"""
        total_fields = len(self.flat_fields)
        total_required = len(self.required_fields)
        total_optional = len(self.optional_fields)
        
        statement_stats = {}
        for stmt_type in self.get_statement_types():
            fields = self.get_statement_fields(stmt_type)
            required_count = sum(1 for f in fields if f.get('required', False))
            
            statement_stats[stmt_type] = {
                'total_fields': len(fields),
                'required_fields': required_count,
                'optional_fields': len(fields) - required_count
            }
        
        return {
            'total_statements': len(self.template_structure),
            'total_fields': total_fields,
            'total_required': total_required,
            'total_optional': total_optional,
            'by_statement': statement_stats
        }


# Global instance
mpers_template_service = MPERSTemplateService()


def get_template_service() -> MPERSTemplateService:
    """Get the global template service instance"""
    return mpers_template_service


def reload_template():
    """Reload the template from file"""
    return mpers_template_service.load_template()