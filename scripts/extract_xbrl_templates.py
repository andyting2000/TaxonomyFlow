#!/usr/bin/env python3
"""
XBRL Template Extractor for SSMxT 2022 Taxonomy

Extracts MPERS template structures from the official SSM XBRL taxonomy ZIP file.
Analyzes presentation, formula, and definition linkbases to:
1. Identify all template codes (010000-750000)
2. Extract concept hierarchies from presentation linkbases
3. Determine required fields from formula and definition linkbases
4. Generate structured JSON templates for the application

Usage:
    python scripts/extract_xbrl_templates.py SSMxT_2022v1.zip

Output:
    mpers_templates.json - Complete template structure with required field metadata
"""

import zipfile
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from collections import OrderedDict
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# XBRL namespaces
NAMESPACES = {
    'link': 'http://www.xbrl.org/2003/linkbase',
    'xlink': 'http://www.w3.org/1999/xlink',
    'xbrli': 'http://www.xbrl.org/2003/instance',
    'xbrldt': 'http://xbrl.org/2005/xbrldt',
    'variable': 'http://xbrl.org/2008/variable',
    'formula': 'http://xbrl.org/2008/formula',
    'ea': 'http://xbrl.org/2008/assertion/existence',
    'cf': 'http://xbrl.org/2008/filter/concept',
    'xs': 'http://www.w3.org/2001/XMLSchema'
}


class XBRLTemplateExtractor:
    """Extract MPERS templates from SSMxT taxonomy ZIP"""

    def __init__(self, zip_path: str):
        self.zip_path = zip_path
        self.zip_file: Optional[zipfile.ZipFile] = None
        self.all_namespaces: Dict[str, str] = {}
        self.templates: Dict[str, Dict] = {}
        self.concept_labels: Dict[str, str] = {}  # Store human-readable labels

    def extract_templates(self) -> Dict[str, Dict]:
        """Main extraction pipeline"""
        try:
            logger.info(f"Opening ZIP file: {self.zip_path}")
            self.zip_file = zipfile.ZipFile(self.zip_path, 'r')

            # Step 1: Scan all files to collect namespaces
            logger.info("Step 1: Collecting namespaces from all files...")
            self._collect_namespaces()
            logger.info(
                f"✓ Collected {len(self.all_namespaces)} namespace prefixes")

            # Step 2: Extract concept labels from label linkbases
            logger.info("Step 2: Extracting concept labels...")
            self._extract_concept_labels()
            logger.info(
                f"✓ Extracted {len(self.concept_labels)} concept labels")

            # Step 3: Find all MPERS template definitions
            logger.info("Step 3: Finding MPERS template definitions...")
            template_definitions = self._find_template_definitions()
            logger.info(f"✓ Found {len(template_definitions)} MPERS templates")

            # Step 4: Extract concepts for each template
            logger.info("Step 4: Extracting concepts for each template...")
            for code, template_info in template_definitions.items():
                logger.info(
                    f"  Processing template {code}: {template_info['description']}")
                concepts = self._extract_template_concepts(
                    template_info['role_uri'],
                    code
                )

                if concepts:
                    self.templates[code] = {
                        'code': code,
                        'description': template_info['description'],
                        'role_uri': template_info['role_uri'],
                        'concepts': concepts,
                        'required_concepts': template_info.get('required_concepts', []),
                        'total_concepts': len(concepts),
                        'required_count': len(template_info.get('required_concepts', []))
                    }
                    logger.info(
                        f"    ✓ Extracted {len(concepts)} concepts, {len(template_info.get('required_concepts', []))} required")
                else:
                    logger.warning(
                        f"    ⚠ No concepts found for template {code}")

            # Step 5: Identify required fields from formulas and definitions
            logger.info(
                "Step 5: Identifying required fields from business rules...")
            self._identify_required_fields()

            logger.info(
                f"\n✅ Extraction complete! Generated {len(self.templates)} templates")

            return self.templates

        finally:
            if self.zip_file:
                self.zip_file.close()

    def _collect_namespaces(self):
        """Scan all XML/XSD files to build global namespace map"""
        for file_info in self.zip_file.filelist:
            file_path = file_info.filename.lower()

            # Only process XML and XSD files
            if not file_path.endswith(('.xml', '.xsd')):
                continue

            try:
                with self.zip_file.open(file_info.filename) as f:
                    # Parse XML
                    tree = ET.parse(f)
                    root = tree.getroot()

                    # Extract namespace declarations from root element
                    for attr_name, attr_value in root.attrib.items():
                        if attr_name.startswith('{http://www.w3.org/2000/xmlns/}'):
                            # Extract prefix from {namespace}prefix format
                            prefix = attr_name.split('}')[1]
                            if prefix and prefix not in self.all_namespaces:
                                self.all_namespaces[prefix] = attr_value
                        elif attr_name == 'xmlns':
                            # Default namespace
                            if 'default' not in self.all_namespaces:
                                self.all_namespaces['default'] = attr_value

            except Exception as e:
                # Skip files that can't be parsed (not XML)
                logger.debug(f"Skipped {file_info.filename}: {e}")
                continue

    def _extract_concept_labels(self):
        """Extract human-readable labels for concepts from label linkbases"""
        # Find all label linkbase files
        label_files = [
            f for f in self.zip_file.filelist
            if '/lab_' in f.filename.lower() and f.filename.lower().endswith('.xml')
        ]

        for file_info in label_files:
            try:
                with self.zip_file.open(file_info.filename) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    # Find all labelLink elements
                    for label_link in root.findall('.//link:labelLink', NAMESPACES):
                        # Build mapping of labels to concepts
                        loc_map = {}  # label -> concept_id

                        # First pass: collect all loc elements
                        for loc in label_link.findall('link:loc', NAMESPACES):
                            label = loc.get(
                                '{http://www.w3.org/1999/xlink}label')
                            href = loc.get(
                                '{http://www.w3.org/1999/xlink}href')

                            if label and href and '#' in href:
                                concept_id = href.split('#')[1]
                                # Convert underscores to colons (XSD convention)
                                concept_id = concept_id.replace('_', ':')
                                loc_map[label] = concept_id

                        # Second pass: collect label text (prefer English labels)
                        for label_elem in label_link.findall('link:label', NAMESPACES):
                            label_ref = label_elem.get(
                                '{http://www.w3.org/1999/xlink}label')
                            role = label_elem.get(
                                '{http://www.w3.org/1999/xlink}role', '')
                            lang = label_elem.get(
                                '{http://www.w3.org/XML/1998/namespace}lang', '')
                            label_text = label_elem.text

                            # Only use standard labels (not documentation, etc.)
                            if label_text and 'label' in role.lower() and label_ref:
                                # PREFER ENGLISH LABELS (xml:lang="en")
                                # Skip if not English and we already have a label
                                is_english = lang == 'en' or lang == 'en-US'

                                # Find matching concept from labelArc
                                for arc in label_link.findall('link:labelArc', NAMESPACES):
                                    arc_to = arc.get(
                                        '{http://www.w3.org/1999/xlink}to')
                                    arc_from = arc.get(
                                        '{http://www.w3.org/1999/xlink}from')

                                    if arc_to == label_ref and arc_from in loc_map:
                                        concept_id = loc_map[arc_from]

                                        # Store label with preference: English > any existing
                                        # Only overwrite if: (1) no label exists, (2) new label is English, or (3) this is a standard label
                                        should_store = (
                                            concept_id not in self.concept_labels or
                                            is_english or
                                            ('standard' in role.lower()
                                             and lang != 'ms')
                                        )

                                        if should_store:
                                            self.concept_labels[concept_id] = label_text.strip(
                                            )
                                            if is_english:
                                                logger.debug(
                                                    f"      EN: {concept_id} = {label_text.strip()}")

            except Exception as e:
                logger.warning(
                    f"Failed to parse label file {file_info.filename}: {e}")
                continue

    def _find_template_definitions(self) -> Dict[str, Dict]:
        """Find all MPERS template role definitions"""
        templates = {}

        # Look for role definition files - check BOTH rol_*.xsd and presentation linkbases
        role_files = [
            f for f in self.zip_file.filelist
            if '/mpers/' in f.filename.lower() and
            (f.filename.lower().endswith('.xml')
             or f.filename.lower().endswith('.xsd'))
        ]

        logger.info(
            f"  Scanning {len(role_files)} MPERS files for role definitions...")

        for file_info in role_files:
            try:
                with self.zip_file.open(file_info.filename) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    # Find roleType elements (in .xsd files)
                    for role_type in root.findall('.//link:roleType', NAMESPACES):
                        role_uri = role_type.get('roleURI', '')

                        # Extract 6-digit code from role URI - try multiple patterns
                        # Pattern 1: role-XXXXXX (most common)
                        match = re.search(r'role-(\d{6})', role_uri)
                        if not match:
                            # Pattern 2: _XXXXXX at end of URI
                            match = re.search(r'_(\d{6})$', role_uri)

                        if not match:
                            logger.debug(
                                f"    Skipping role URI (no code): {role_uri}")
                            continue

                        code = match.group(1)

                        # Get description from definition element
                        definition_elem = role_type.find(
                            'link:definition', NAMESPACES)
                        description = definition_elem.text.strip(
                        ) if definition_elem is not None and definition_elem.text else f"Template {code}"

                        if code not in templates:
                            templates[code] = {
                                'code': code,
                                'description': description,
                                'role_uri': role_uri,
                                'required_concepts': []
                            }
                            logger.debug(
                                f"    Found template {code}: {description}")

                    # Also check roleRef elements in linkbases (backup method)
                    for role_ref in root.findall('.//link:roleRef', NAMESPACES):
                        role_uri = role_ref.get('roleURI', '')

                        match = re.search(r'role-(\d{6})', role_uri)
                        if not match:
                            match = re.search(r'_(\d{6})$', role_uri)

                        if match:
                            code = match.group(1)
                            if code not in templates:
                                # Placeholder - will get description from roleType later
                                templates[code] = {
                                    'code': code,
                                    'description': f"Template {code}",
                                    'role_uri': role_uri,
                                    'required_concepts': []
                                }

            except Exception as e:
                logger.debug(f"Failed to parse file {file_info.filename}: {e}")
                continue

        return OrderedDict(sorted(templates.items()))

    def _extract_template_concepts(self, role_uri: str, template_code: str) -> List[Dict]:
        """Extract concepts for a specific template from presentation linkbase"""
        concepts = []

        # Strategy 1: Look for file with template code in filename
        # Example: pre_ssmt-fs-mpers_2022-12-31_role-020000.xml
        target_filename_pattern = f"role-{template_code}.xml"

        # Find presentation linkbase files for MPERS
        pres_files = [
            f for f in self.zip_file.filelist
            if '/mpers/' in f.filename.lower() and
            '/pre_' in f.filename.lower() and
            f.filename.lower().endswith('.xml')
        ]

        # First try: exact filename match
        matching_file = None
        for f in pres_files:
            if target_filename_pattern.lower() in f.filename.lower():
                matching_file = f
                break

        if matching_file:
            logger.debug(
                f"    Found presentation file: {matching_file.filename}")
            try:
                with self.zip_file.open(matching_file.filename) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    # Find presentationLink with matching role
                    for pres_link in root.findall('.//link:presentationLink', NAMESPACES):
                        link_role = pres_link.get(
                            '{http://www.w3.org/1999/xlink}role', '')

                        # Try exact match first
                        if link_role == role_uri:
                            concepts = self._parse_presentation_link(
                                pres_link, template_code)
                            if concepts:
                                return concepts

                    # If no exact role match, try parsing first presentationLink
                    first_link = root.find(
                        './/link:presentationLink', NAMESPACES)
                    if first_link is not None:
                        concepts = self._parse_presentation_link(
                            first_link, template_code)
                        if concepts:
                            logger.debug(
                                f"    Using first presentation link (role URI didn't match)")
                            return concepts

            except Exception as e:
                logger.warning(
                    f"Failed to parse presentation file {matching_file.filename}: {e}")

        # Second try: scan all presentation files for matching role URI
        if not concepts:
            for file_info in pres_files:
                try:
                    with self.zip_file.open(file_info.filename) as f:
                        tree = ET.parse(f)
                        root = tree.getroot()

                        # Find presentationLink with matching role
                        for pres_link in root.findall('.//link:presentationLink', NAMESPACES):
                            link_role = pres_link.get(
                                '{http://www.w3.org/1999/xlink}role', '')

                            if link_role == role_uri:
                                concepts = self._parse_presentation_link(
                                    pres_link, template_code)

                                if concepts:
                                    logger.debug(
                                        f"    Found matching role in: {file_info.filename}")
                                    return concepts

                except Exception as e:
                    logger.debug(
                        f"Failed to parse presentation file {file_info.filename}: {e}")
                    continue

        return concepts

    def _parse_presentation_link(self, pres_link: Element, template_code: str) -> List[Dict]:
        """Parse a single presentationLink to extract concept hierarchy"""
        # Build location map: label -> concept_id
        loc_map = {}
        for loc in pres_link.findall('link:loc', NAMESPACES):
            label = loc.get('{http://www.w3.org/1999/xlink}label')
            href = loc.get('{http://www.w3.org/1999/xlink}href')

            if label and href and '#' in href:
                concept_id = href.split('#')[1]
                # Convert underscores to colons
                concept_id = concept_id.replace('_', ':')
                loc_map[label] = concept_id

        # Build parent-child relationships from arcs
        parent_child = {}  # parent_label -> [(child_label, order)]
        for arc in pres_link.findall('link:presentationArc', NAMESPACES):
            arc_from = arc.get('{http://www.w3.org/1999/xlink}from')
            arc_to = arc.get('{http://www.w3.org/1999/xlink}to')
            order = float(arc.get('order', '0'))
            use = arc.get('use', 'optional')

            if arc_from and arc_to:
                if arc_from not in parent_child:
                    parent_child[arc_from] = []
                parent_child[arc_from].append((arc_to, order, use))

        # Find root concepts (concepts that are parents but not children)
        all_children = set()
        for children in parent_child.values():
            for child, _, _ in children:
                all_children.add(child)

        roots = [label for label in parent_child.keys()
                 if label not in all_children]

        # Traverse hierarchy depth-first
        concepts = []

        def traverse(label: str, level: int = 0, parent_id: Optional[str] = None):
            concept_id = loc_map.get(label)
            if not concept_id:
                return

            # Skip abstract elements in final output (but traverse their children)
            is_abstract = 'Abstract' in concept_id or 'Table' in concept_id or 'LineItems' in concept_id

            if not is_abstract:
                # Extract namespace prefix
                namespace = concept_id.split(
                    ':')[0] if ':' in concept_id else 'ssmt'

                # Get human-readable label
                readable_label = self.concept_labels.get(
                    concept_id, self._concept_id_to_label(concept_id))

                concept_info = {
                    'id': concept_id,
                    'label': readable_label,
                    'namespace': namespace,
                    'level': level,
                    'parent': parent_id,
                    'required': False,  # Will be updated later
                    'position': len(concepts)
                }

                concepts.append(concept_info)

            # Traverse children
            if label in parent_child:
                # Sort children by order
                children = sorted(parent_child[label], key=lambda x: x[1])
                for child_label, _, _ in children:
                    traverse(child_label, level + 1, concept_id)

        # Start traversal from roots
        for root in roots:
            traverse(root, 0, None)

        return concepts

    def _concept_id_to_label(self, concept_id: str) -> str:
        """Convert concept ID to human-readable label (fallback)"""
        # Remove namespace prefix
        if ':' in concept_id:
            concept_id = concept_id.split(':', 1)[1]

        # Insert spaces before capitals
        label = re.sub(r'([A-Z])', r' \1', concept_id).strip()

        return label

    def _identify_required_fields(self):
        """Identify required fields from formula and definition linkbases"""
        # Find formula linkbase files
        formula_files = [
            f for f in self.zip_file.filelist
            if '/mpers/' in f.filename.lower() and
            '/formula_' in f.filename.lower() and
            f.filename.lower().endswith('.xml')
        ]

        required_concepts = set()

        # Parse formula linkbases for existenceAssertion rules
        for file_info in formula_files:
            try:
                with self.zip_file.open(file_info.filename) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    xlink_ns = '{http://www.w3.org/1999/xlink}'

                    # Map conceptName filter labels -> concept qname
                    concept_name_map = {}
                    for concept_name in root.findall('.//cf:conceptName', NAMESPACES):
                        label = concept_name.get(f'{xlink_ns}label')
                        qname_elem = concept_name.find(
                            './/cf:qname', NAMESPACES)

                        if label and qname_elem is not None and qname_elem.text:
                            concept_name_map[label] = qname_elem.text.strip()

                    # Build graph of variable/filter links so we can walk through boolean/or filters
                    filter_graph = {}

                    for arc in root.findall('.//variable:variableFilterArc', NAMESPACES):
                        arc_from = arc.get(f'{xlink_ns}from')
                        arc_to = arc.get(f'{xlink_ns}to')

                        if arc_from and arc_to:
                            filter_graph.setdefault(
                                arc_from, set()).add(arc_to)

                    for arc in root.findall('.//variable:variableArc', NAMESPACES):
                        arcrole = arc.get(f'{xlink_ns}arcrole', '')
                        if not arcrole.endswith('variable-set'):
                            continue

                        arc_from = arc.get(f'{xlink_ns}from')
                        arc_to = arc.get(f'{xlink_ns}to')

                        if arc_from and arc_to:
                            filter_graph.setdefault(
                                arc_from, set()).add(arc_to)

                    # Traverse from each existenceAssertion to collect all linked conceptName filters
                    for assertion in root.findall('.//ea:existenceAssertion', NAMESPACES):
                        assertion_label = assertion.get(f'{xlink_ns}label')
                        if not assertion_label:
                            continue

                        stack = [assertion_label]
                        visited = set()

                        while stack:
                            node = stack.pop()
                            if node in visited:
                                continue
                            visited.add(node)

                            if node in concept_name_map:
                                required_concepts.add(concept_name_map[node])

                            for nxt in filter_graph.get(node, set()):
                                if nxt not in visited:
                                    stack.append(nxt)

            except Exception as e:
                logger.warning(
                    f"Failed to parse formula file {file_info.filename}: {e}")
                continue

        # Parse definition linkbases for "all" arcroles
        def_files = [
            f for f in self.zip_file.filelist
            if '/mpers/' in f.filename.lower() and
            '/def_' in f.filename.lower() and
            f.filename.lower().endswith('.xml')
        ]

        for file_info in def_files:
            try:
                with self.zip_file.open(file_info.filename) as f:
                    tree = ET.parse(f)
                    root = tree.getroot()

                    for def_link in root.findall('.//link:definitionLink', NAMESPACES):
                        # Build location map
                        loc_map = {}
                        for loc in def_link.findall('link:loc', NAMESPACES):
                            label = loc.get(
                                '{http://www.w3.org/1999/xlink}label')
                            href = loc.get(
                                '{http://www.w3.org/1999/xlink}href')

                            if label and href and '#' in href:
                                concept_id = href.split(
                                    '#')[1].replace('_', ':')
                                loc_map[label] = concept_id

                        # Find definitionArc with arcrole="all"
                        for arc in def_link.findall('link:definitionArc', NAMESPACES):
                            arcrole = arc.get(
                                '{http://www.w3.org/1999/xlink}arcrole', '')

                            if 'all' in arcrole.lower():
                                # Both from and to are required
                                arc_from = arc.get(
                                    '{http://www.w3.org/1999/xlink}from')
                                arc_to = arc.get(
                                    '{http://www.w3.org/1999/xlink}to')

                                if arc_from in loc_map:
                                    required_concepts.add(loc_map[arc_from])
                                if arc_to in loc_map:
                                    required_concepts.add(loc_map[arc_to])

            except Exception as e:
                logger.warning(
                    f"Failed to parse definition file {file_info.filename}: {e}")
                continue

        logger.info(
            f"  ✓ Identified {len(required_concepts)} required concepts from business rules")

        # Update templates with required field information
        for template_code, template_data in self.templates.items():
            for concept in template_data['concepts']:
                if concept['id'] in required_concepts:
                    concept['required'] = True

            # Update required count
            required_count = sum(
                1 for c in template_data['concepts'] if c['required'])
            template_data['required_count'] = required_count
            template_data['required_concepts'] = [c['id']
                                                  for c in template_data['concepts'] if c['required']]

    def save_to_json(self, output_path: str):
        """Save extracted templates to JSON file"""
        output_data = {
            '_metadata': {
                'extracted_from': Path(self.zip_path).name,
                'total_templates': len(self.templates),
                'total_concepts': sum(t['total_concepts'] for t in self.templates.values()),
                'total_required': sum(t['required_count'] for t in self.templates.values()),
                'namespaces': self.all_namespaces
            },
            'templates': self.templates
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        logger.info(f"\n✅ Saved templates to: {output_path}")
        logger.info(f"   Total templates: {len(self.templates)}")
        logger.info(
            f"   Total concepts: {sum(t['total_concepts'] for t in self.templates.values())}")
        logger.info(
            f"   Total required: {sum(t['required_count'] for t in self.templates.values())}")


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python extract_xbrl_templates.py <path_to_SSMxT_ZIP>")
        print("\nExample:")
        print("  python scripts/extract_xbrl_templates.py SSMxT_2022v1.zip")
        sys.exit(1)

    zip_path = sys.argv[1]

    if not Path(zip_path).exists():
        print(f"Error: File not found: {zip_path}")
        sys.exit(1)

    # Extract templates
    extractor = XBRLTemplateExtractor(zip_path)
    templates = extractor.extract_templates()

    # Save to JSON
    output_path = 'mpers_templates.json'
    extractor.save_to_json(output_path)

    # Print summary (UTF-8 safe)
    print("\n" + "="*80)
    print("EXTRACTION SUMMARY")
    print("="*80)

    for code in sorted(templates.keys()):
        template = templates[code]
        print(f"{code}: {template['description']}")
        print(
            f"  -> {template['total_concepts']} concepts ({template['required_count']} required)")

    print("="*80)
    print(f"\nTemplate extraction complete!")
    print(f"Output saved to: {output_path}")


if __name__ == '__main__':
    main()
