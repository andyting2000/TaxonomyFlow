# cli.py - UPDATED with template code update command
import asyncio
import click
from database import get_db

@click.group()
def cli():
    """XBRL Management CLI"""
    pass

@cli.command()
def load_xml_templates():
    """Load XML templates into database with embeddings (deprecated - functionality moved to main.py startup)"""
    print("⚠️  This command is deprecated.")
    print("XML templates are now automatically loaded on application startup.")
    print("See main.py lifespan event for template loading logic.")

@cli.command()
def check_templates():
    """Check loaded XML templates in database"""
    
    async def check():
        async for db in get_db():
            try:
                from sqlalchemy import select, func
                from database import XMLTemplateField
                
                # Count total templates
                count_stmt = select(func.count(XMLTemplateField.id))
                result = await db.execute(count_stmt)
                total = result.scalar()
                
                print(f"\n📊 Total template fields loaded: {total}")
                
                # Sample some fields
                sample_stmt = select(XMLTemplateField).limit(10)
                result = await db.execute(sample_stmt)
                samples = result.scalars().all()
                
                print("\n📋 Sample template fields:")
                for field in samples:
                    print(f"  - field_id: {field.field_id}")
                    print(f"    label: {field.label}")
                    print(f"    xbrl_tag: {field.xbrl_tag}")
                    print(f"    statement: {field.statement_type}")
                    print(f"    has_embedding: {field.embedding is not None}")
                    print()
                
            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
    
    asyncio.run(check())

@cli.command()
def check_matches():
    """Check extracted items with template matches"""
    
    async def check():
        async for db in get_db():
            try:
                from sqlalchemy import select, func
                from database import ExtractedDataItem
                
                # Count items with template matches
                count_stmt = select(func.count(ExtractedDataItem.id)).where(
                    ExtractedDataItem.template_field_id.isnot(None)
                )
                result = await db.execute(count_stmt)
                matched = result.scalar()
                
                # Total items
                total_stmt = select(func.count(ExtractedDataItem.id))
                result = await db.execute(total_stmt)
                total = result.scalar()
                
                print(f"\n📊 Matching Statistics:")
                print(f"  Total items: {total}")
                print(f"  Items with template matches: {matched}")
                print(f"  Match rate: {(matched/total*100):.1f}%" if total > 0 else "N/A")
                
                # Sample matched items
                sample_stmt = select(ExtractedDataItem).where(
                    ExtractedDataItem.template_field_id.isnot(None)
                ).limit(5)
                result = await db.execute(sample_stmt)
                samples = result.scalars().all()
                
                print(f"\n📋 Sample matched items:")
                for item in samples:
                    print(f"  - Label: {item.extracted_label[:50]}...")
                    print(f"    Template field ID: {item.template_field_id}")
                    print()
                
            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
    
    asyncio.run(check())

@cli.command()
@click.option('--job-id', type=int, help='Job ID to fix matches for')
def fix_template_matches(job_id):
    """Re-match extracted items to template fields"""
    
    async def fix():
        async for db in get_db():
            try:
                from sqlalchemy import select, text
                from database import ExtractedDataItem, FinancialStatementPage, XMLTemplateField
                from services.semantic_matcher import semantic_matcher
                
                # Get items for the job
                stmt = (
                    select(ExtractedDataItem)
                    .join(FinancialStatementPage)
                    .where(FinancialStatementPage.job_id == job_id)
                    .where(ExtractedDataItem.template_field_id.is_(None))  # Only unmatched
                )
                
                result = await db.execute(stmt)
                items = result.scalars().all()
                
                print(f"\n🔍 Found {len(items)} unmatched items for job {job_id}")
                
                if not semantic_matcher.is_available():
                    print("❌ Semantic matcher not available")
                    return
                
                matched_count = 0
                
                for item in items:
                    # Try to find a match
                    query_embedding = await semantic_matcher.encode_text(item.extracted_label)
                    
                    if not query_embedding:
                        continue
                    
                    # Search for match
                    sql = text("""
                        SELECT 
                            field_id,
                            label,
                            xbrl_tag,
                            1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                        FROM xml_template_fields
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> CAST(:query_embedding AS vector)
                        LIMIT 1
                    """)
                    
                    embedding_literal = '[' + ','.join(map(str, query_embedding)) + ']'
                    
                    result = await db.execute(sql, {"query_embedding": embedding_literal})
                    match = result.fetchone()
                    
                    if match and float(match[3]) >= 0.6:  # 60% similarity threshold
                        item.template_field_id = match[0]
                        matched_count += 1
                        print(f"  ✅ Matched: '{item.extracted_label[:40]}...' → {match[1]} ({float(match[3]):.2f})")
                
                await db.commit()
                print(f"\n✅ Fixed {matched_count} matches")
                
            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()
    
    asyncio.run(fix())

@cli.command()
def list_template_codes():
    """List all XML template files with their current codes"""
    
    from pathlib import Path
    import xml.etree.ElementTree as ET
    
    template_dir = Path('mpers_template')
    
    if not template_dir.exists():
        print(f"❌ Template directory not found: {template_dir}")
        return
    
    xml_files = sorted(template_dir.glob('*.xml'))
    
    if not xml_files:
        print(f"❌ No XML files found in {template_dir}")
        return
    
    print(f"\n📋 Found {len(xml_files)} XML template files:\n")
    print(f"{'File Name':<50} {'Current Code':<15} {'Title':<50}")
    print("=" * 115)
    
    for xml_file in xml_files:
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            # Get code and title from root attributes and metadata
            code = root.get('code', 'N/A')
            
            # Try to get title from metadata
            metadata = root.find('metadata')
            title = 'N/A'
            if metadata is not None:
                title_elem = metadata.find('title')
                if title_elem is not None:
                    title = title_elem.text or 'N/A'
            
            # Truncate long titles
            if len(title) > 47:
                title = title[:44] + '...'
            
            print(f"{xml_file.name:<50} {code:<15} {title:<50}")
            
        except Exception as e:
            print(f"{xml_file.name:<50} {'ERROR':<15} {str(e):<50}")
    
    print("\n")

@cli.command()
@click.option('--file', required=True, help='XML template filename (e.g., statement_of_financial_position.xml)')
@click.option('--new-code', required=True, help='New 6-digit code (e.g., 210000)')
def update_template_code(file, new_code):
    """Update the code attribute in an XML template file"""
    
    from pathlib import Path
    import xml.etree.ElementTree as ET
    
    template_dir = Path('mpers_template')
    file_path = template_dir / file
    
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return
    
    # Validate new code (should be 6 digits)
    if not new_code.isdigit() or len(new_code) != 6:
        print(f"❌ Invalid code format. Code must be exactly 6 digits (e.g., 210000)")
        return
    
    try:
        # Parse XML
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Get old code
        old_code = root.get('code', 'N/A')
        
        # Update code attribute
        root.set('code', new_code)
        
        # Also update in metadata if it exists
        metadata = root.find('metadata')
        if metadata is not None:
            code_elem = metadata.find('code')
            if code_elem is not None:
                code_elem.text = new_code
            else:
                # Create code element if it doesn't exist
                code_elem = ET.SubElement(metadata, 'code')
                code_elem.text = new_code
        
        # Write back to file
        tree.write(file_path, encoding='utf-8', xml_declaration=True)
        
        print(f"✅ Successfully updated {file}")
        print(f"   Old code: {old_code}")
        print(f"   New code: {new_code}")
        print(f"\n⚠️  Remember to run 'python cli.py load_xml_templates' to reload templates into database!")
        
    except Exception as e:
        print(f"❌ Error updating template: {e}")
        import traceback
        traceback.print_exc()

@cli.command()
@click.option('--mapping-file', required=True, help='CSV file with mappings (filename,new_code)')
def bulk_update_codes(mapping_file):
    """Bulk update template codes from a CSV file

    CSV format:
    filename,new_code
    statement_of_financial_position.xml,210000
    directors_report.xml,120000
    """

    from pathlib import Path
    import xml.etree.ElementTree as ET
    import csv

    template_dir = Path('mpers_template')
    mapping_path = Path(mapping_file)

    if not mapping_path.exists():
        print(f"❌ Mapping file not found: {mapping_path}")
        return

    print(f"📋 Reading mappings from {mapping_file}\n")

    updated_count = 0
    error_count = 0

    try:
        with open(mapping_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                filename = row['filename'].strip()
                new_code = row['new_code'].strip()

                file_path = template_dir / filename

                # Validate
                if not file_path.exists():
                    print(f"❌ File not found: {filename}")
                    error_count += 1
                    continue

                if not new_code.isdigit() or len(new_code) != 6:
                    print(f"❌ Invalid code for {filename}: {new_code}")
                    error_count += 1
                    continue

                try:
                    # Parse and update
                    tree = ET.parse(file_path)
                    root = tree.getroot()

                    old_code = root.get('code', 'N/A')
                    root.set('code', new_code)

                    # Update metadata
                    metadata = root.find('metadata')
                    if metadata is not None:
                        code_elem = metadata.find('code')
                        if code_elem is not None:
                            code_elem.text = new_code
                        else:
                            code_elem = ET.SubElement(metadata, 'code')
                            code_elem.text = new_code

                    # Write back
                    tree.write(file_path, encoding='utf-8', xml_declaration=True)

                    print(f"✅ {filename}: {old_code} → {new_code}")
                    updated_count += 1

                except Exception as e:
                    print(f"❌ Error updating {filename}: {e}")
                    error_count += 1

        print(f"\n📊 Summary:")
        print(f"   Updated: {updated_count}")
        print(f"   Errors: {error_count}")
        print(f"\n⚠️  Remember to run 'python cli.py load_xml_templates' to reload templates into database!")

    except Exception as e:
        print(f"❌ Error reading mapping file: {e}")
        import traceback
        traceback.print_exc()

@cli.command()
def regenerate_taxonomy_embeddings():
    """Regenerate embeddings for MBRS taxonomy tags using combined approach (label + XBRL tag)"""

    async def regenerate():
        async for db in get_db():
            try:
                from sqlalchemy import select, func
                from database import MBRSTaxonomyTag
                from services.semantic_matcher import semantic_matcher

                # Check if semantic matcher is available
                if not semantic_matcher.is_available():
                    print("❌ Semantic matcher not available")
                    return

                # Get all taxonomy tags
                stmt = select(MBRSTaxonomyTag)
                result = await db.execute(stmt)
                tags = result.scalars().all()

                print(f"\n🔄 Regenerating embeddings for {len(tags)} taxonomy tags...")
                print("Using combined approach: label + XBRL tag\n")

                # Create combined texts
                combined_texts = []
                for tag in tags:
                    combined_text = await semantic_matcher.create_combined_embedding(tag.label, tag.xbrl_tag)
                    # The method returns an embedding, but we need the text for batch encoding
                    # So let's recreate the text
                    readable_tag = semantic_matcher._xbrl_tag_to_readable(tag.xbrl_tag)
                    combined_text = f"{tag.label} {readable_tag}"
                    combined_texts.append(combined_text)

                # Generate embeddings in batches
                print("Generating embeddings...")
                embeddings = await semantic_matcher.encode_batch(combined_texts, batch_size=20)

                # Update database
                print("Updating database...")
                for tag, embedding in zip(tags, embeddings):
                    tag.embedding = embedding

                await db.commit()

                # Report statistics
                count_stmt = select(func.count(MBRSTaxonomyTag.id)).where(
                    MBRSTaxonomyTag.embedding.isnot(None)
                )
                result = await db.execute(count_stmt)
                count_with_embeddings = result.scalar()

                print(f"\n✅ Successfully regenerated embeddings")
                print(f"   Total tags: {len(tags)}")
                print(f"   Tags with embeddings: {count_with_embeddings}")

            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()

    asyncio.run(regenerate())

@cli.command()
def check_taxonomy_embeddings():
    """Check taxonomy tags embedding status"""

    async def check():
        async for db in get_db():
            try:
                from sqlalchemy import select, func
                from database import MBRSTaxonomyTag

                # Count total tags
                total_stmt = select(func.count(MBRSTaxonomyTag.id))
                result = await db.execute(total_stmt)
                total = result.scalar()

                # Count tags with embeddings
                with_embeddings_stmt = select(func.count(MBRSTaxonomyTag.id)).where(
                    MBRSTaxonomyTag.embedding.isnot(None)
                )
                result = await db.execute(with_embeddings_stmt)
                with_embeddings = result.scalar()

                print(f"\n📊 Taxonomy Embedding Statistics:")
                print(f"   Total taxonomy tags: {total}")
                print(f"   Tags with embeddings: {with_embeddings}")
                print(f"   Tags without embeddings: {total - with_embeddings}")

                if total > 0:
                    percentage = (with_embeddings / total) * 100
                    print(f"   Coverage: {percentage:.1f}%")

                # Sample tags
                sample_stmt = select(MBRSTaxonomyTag).limit(5)
                result = await db.execute(sample_stmt)
                samples = result.scalars().all()

                print(f"\n📋 Sample taxonomy tags:")
                for tag in samples:
                    print(f"  - Label: {tag.label[:50]}")
                    print(f"    XBRL Tag: {tag.xbrl_tag}")
                    print(f"    Has embedding: {tag.embedding is not None}")
                    print()

            except Exception as e:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()

    asyncio.run(check())

if __name__ == "__main__":
    cli()