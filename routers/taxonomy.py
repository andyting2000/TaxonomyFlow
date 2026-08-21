# routers/taxonomy.py
import time
import hashlib
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, text, bindparam, Integer
from sqlalchemy.orm import selectinload
from pgvector.sqlalchemy import Vector
from database import get_db, MBRSTaxonomyTag
from schemas import TaxonomyTagResponse, TaxonomyTagCreate, TaxonomySearchResponse
from cache import TaxonomyCache
from services.semantic_matcher import semantic_matcher
from security import require_admin_route_token
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/search/semantic")
async def semantic_search_taxonomy(
    q: str = Query(..., min_length=2, description="Search query"),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, le=50)
):
    """Semantic search using embeddings"""
    
    if not semantic_matcher.is_available():
        raise HTTPException(
            status_code=503, 
            detail="Semantic search not available. Model not loaded."
        )
    
    start_time = time.time()
    
    try:
        # Generate embedding for query (synchronous call)
        query_embedding = await semantic_matcher.encode_text(q)
        
        if not query_embedding:
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        
        # Search using pgvector with bindparam
        sql = text("""
            SELECT 
                id, 
                label, 
                xbrl_tag,
                1 - (embedding <=> :query_embedding) as similarity
            FROM mbrs_taxonomy_tags
            WHERE embedding IS NOT NULL
                AND label NOT LIKE '%[abstract]%'
            ORDER BY embedding <=> :query_embedding
            LIMIT :limit
        """).bindparams(
            bindparam('query_embedding', type_=Vector(1752)),
            bindparam('limit', type_=Integer)
        )

        result = await db.execute(sql, {
            "query_embedding": query_embedding,
            "limit": limit
        })
        
        matches = result.fetchall()
        
        results = [
            {
                "id": match[0],
                "label": match[1],
                "xbrl_tag": match[2],
                "similarity": float(match[3])
            }
            for match in matches
        ]
        
        search_time = time.time() - start_time
        
        return {
            "results": results,
            "search_time": search_time,
            "total_results": len(results),
            "method": "semantic"
        }
        
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search", response_model=TaxonomySearchResponse)
async def search_taxonomy_tags(
    q: str = Query(..., min_length=2, description="Search query"),
    db: AsyncSession = Depends(get_db)
):
    """Full-text search with PostgreSQL"""
    
    start_time = time.time()
    
    # Normalize query
    q_normalized = q.strip().lower()
    
    # Check cache first
    cached_results = await TaxonomyCache.get_search_results(q_normalized)
    if cached_results is not None:
        search_time = time.time() - start_time
        logger.info(f"Cache hit for query '{q}' ({search_time:.3f}s)")
        
        return TaxonomySearchResponse(
            results=cached_results,
            cached=True,
            search_time=search_time,
            total_results=len(cached_results)
        )
    
    try:
        # Use full-text search if available, fallback to ILIKE
        # Check if search_vector column exists
        check_column = await db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'mbrs_taxonomy_tags' 
            AND column_name = 'search_vector'
        """))
        has_fts = check_column.scalar() is not None
        
        if has_fts:
            # Full-text search
            # Prepare search query - handle multi-word searches
            search_terms = q_normalized.split()
            ts_query = ' & '.join(search_terms)  # AND search
            
            sql = text("""
                SELECT 
                    id, 
                    label,
                    xbrl_tag,
                    ts_rank(search_vector, to_tsquery('english', :query)) as rank
                FROM mbrs_taxonomy_tags
                WHERE search_vector @@ to_tsquery('english', :query)
                    AND label NOT LIKE '%[abstract]%'
                ORDER BY rank DESC, 
                    CASE 
                        WHEN LOWER(label) = :exact THEN 1
                        WHEN LOWER(label) LIKE :starts_with THEN 2
                        WHEN LOWER(xbrl_tag) = :exact THEN 3
                        ELSE 4
                    END,
                    label
                LIMIT 50
            """)
            
            result = await db.execute(sql, {
                "query": ts_query,
                "exact": q_normalized,
                "starts_with": f"{q_normalized}%"
            })
            rows = result.fetchall()
            
            # Format results - show both label and xbrl_tag for clarity
            results = []
            for row in rows:
                label = row[1]
                xbrl_tag = row[2]
                
                # Create a more user-friendly display
                # If label is too verbose, use xbrl_tag as the main display
                if len(label) > 100:
                    # Use xbrl_tag converted to readable format
                    display_label = ' '.join(
                        # Convert CamelCase to spaces
                        ''.join([' ' + c if c.isupper() else c for c in xbrl_tag]).strip().split()
                    )
                    full_label = f"{display_label} • {label[:80]}..."
                else:
                    full_label = label
                
                results.append({
                    "id": row[0],
                    "label": full_label,
                    "original_label": label,
                    "xbrl_tag": xbrl_tag
                })
            
            logger.info(f"Full-text search '{q}' found {len(results)} results")
            
        else:
            # Fallback to ILIKE search
            logger.warning("Full-text search not available, using ILIKE")
            
            search_pattern = f"%{q_normalized}%"
            
            stmt = (
                select(
                    MBRSTaxonomyTag.id, 
                    MBRSTaxonomyTag.label,
                    MBRSTaxonomyTag.xbrl_tag
                )
                .where(
                    and_(
                        or_(
                            func.lower(MBRSTaxonomyTag.label).like(search_pattern),
                            func.lower(MBRSTaxonomyTag.xbrl_tag).like(search_pattern)
                        ),
                        ~MBRSTaxonomyTag.label.contains('[abstract]')
                    )
                )
                .order_by(
                    func.case(
                        (func.lower(MBRSTaxonomyTag.label) == q_normalized, 1),
                        (func.lower(MBRSTaxonomyTag.label).like(f"{q_normalized}%"), 2),
                        (func.lower(MBRSTaxonomyTag.xbrl_tag) == q_normalized, 3),
                        (func.lower(MBRSTaxonomyTag.xbrl_tag).like(f"{q_normalized}%"), 4),
                        else_=5
                    ),
                    MBRSTaxonomyTag.label
                )
                .limit(50)
            )
            
            result = await db.execute(stmt)
            rows = result.all()
            
            results = []
            for row in rows:
                label = row.label
                xbrl_tag = row.xbrl_tag
                
                # Create readable display
                if len(label) > 100:
                    display_label = ' '.join(
                        ''.join([' ' + c if c.isupper() else c for c in xbrl_tag]).strip().split()
                    )
                    full_label = f"{display_label} • {label[:80]}..."
                else:
                    full_label = label
                
                results.append({
                    "id": row.id,
                    "label": full_label,
                    "original_label": label,
                    "xbrl_tag": xbrl_tag
                })
        
        # Cache results
        await TaxonomyCache.set_search_results(q_normalized, results)
        
        search_time = time.time() - start_time
        logger.info(f"Search for '{q}': {len(results)} results ({search_time:.3f}s)")
        
        return TaxonomySearchResponse(
            results=results,
            cached=False,
            search_time=search_time,
            total_results=len(results)
        )
        
    except Exception as e:
        logger.error(f"Search error for query '{q}': {e}")
        import traceback
        traceback.print_exc()
        
        return TaxonomySearchResponse(
            results=[],
            cached=False,
            search_time=time.time() - start_time,
            total_results=0
        )

@router.get("/debug/sample", dependencies=[Depends(require_admin_route_token)])
async def get_sample_tags(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, le=100)
):
    """Get sample taxonomy tags for debugging"""
    
    result = await db.execute(
        select(MBRSTaxonomyTag.id, MBRSTaxonomyTag.label, MBRSTaxonomyTag.xbrl_tag)
        .where(~MBRSTaxonomyTag.label.contains('[abstract]'))
        .order_by(MBRSTaxonomyTag.label)
        .limit(limit)
    )
    
    tags = result.all()
    return {
        "count": len(tags),
        "samples": [
            {
                "id": tag.id,
                "label": tag.label,
                "xbrl_tag": tag.xbrl_tag
            }
            for tag in tags
        ]
    }

@router.get("/debug/search-raw", dependencies=[Depends(require_admin_route_token)])
async def debug_search_raw(
    q: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Debug search with raw SQL"""
    
    # Try different search patterns
    patterns_to_try = [
        f"%{q.lower()}%",
        f"{q.lower()}%",
        f"% {q.lower()}%",
    ]
    
    results = {}
    
    for i, pattern in enumerate(patterns_to_try):
        sql = text("""
            SELECT id, label, xbrl_tag 
            FROM mbrs_taxonomy_tags 
            WHERE (LOWER(label) LIKE :pattern OR LOWER(xbrl_tag) LIKE :pattern)
            AND label NOT LIKE '%[abstract]%'
            LIMIT 10
        """)
        
        result = await db.execute(sql, {"pattern": pattern})
        rows = result.fetchall()
        
        results[f"pattern_{i}_{pattern}"] = [
            {"id": row[0], "label": row[1], "xbrl_tag": row[2]}
            for row in rows
        ]
    
    # Also try exact matches
    sql_exact = text("""
        SELECT id, label, xbrl_tag 
        FROM mbrs_taxonomy_tags 
        WHERE (LOWER(label) = :exact OR LOWER(xbrl_tag) = :exact)
        LIMIT 10
    """)
    
    result = await db.execute(sql_exact, {"exact": q.lower()})
    rows = result.fetchall()
    results["exact_match"] = [
        {"id": row[0], "label": row[1], "xbrl_tag": row[2]}
        for row in rows
    ]
    
    return {
        "query": q,
        "patterns_tested": patterns_to_try,
        "results": results
    }

@router.get("/tags", response_model=List[TaxonomyTagResponse])
async def get_taxonomy_tags(
    db: AsyncSession = Depends(get_db),
    namespace: Optional[str] = Query(None),
    period_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0)
):
    """Get taxonomy tags with optional filtering"""
    
    stmt = select(MBRSTaxonomyTag).order_by(MBRSTaxonomyTag.label)
    
    if namespace:
        stmt = stmt.where(MBRSTaxonomyTag.namespace == namespace)
    
    if period_type:
        stmt = stmt.where(MBRSTaxonomyTag.period_type == period_type)
    
    # Exclude abstract tags by default
    stmt = stmt.where(~MBRSTaxonomyTag.label.contains('[abstract]'))
    
    stmt = stmt.limit(limit).offset(offset)
    
    result = await db.execute(stmt)
    tags = result.scalars().all()
    
    return tags


@router.get("/tags/{tag_id}", response_model=TaxonomyTagResponse)
async def get_taxonomy_tag(tag_id: int, db: AsyncSession = Depends(get_db)):
    """Get specific taxonomy tag"""
    
    result = await db.execute(select(MBRSTaxonomyTag).where(MBRSTaxonomyTag.id == tag_id))
    tag = result.scalar_one_or_none()
    
    if not tag:
        raise HTTPException(status_code=404, detail="Taxonomy tag not found")
    
    return tag


@router.post(
    "/tags",
    response_model=TaxonomyTagResponse,
    dependencies=[Depends(require_admin_route_token)]
)
async def create_taxonomy_tag(tag: TaxonomyTagCreate, db: AsyncSession = Depends(get_db)):
    """Create new taxonomy tag"""
    
    # Check if tag already exists
    existing = await db.execute(
        select(MBRSTaxonomyTag).where(
            and_(
                MBRSTaxonomyTag.xbrl_tag == tag.xbrl_tag,
                MBRSTaxonomyTag.namespace == tag.namespace
            )
        )
    )
    
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tag already exists")
    
    # Create new tag
    new_tag = MBRSTaxonomyTag(**tag.dict())
    db.add(new_tag)
    await db.commit()
    
    # Clear search cache
    await TaxonomyCache.invalidate_search_cache()
    
    return new_tag


@router.get("/namespaces")
async def get_namespaces(db: AsyncSession = Depends(get_db)):
    """Get list of available namespaces"""
    
    result = await db.execute(
        select(MBRSTaxonomyTag.namespace, func.count(MBRSTaxonomyTag.id).label('count'))
        .group_by(MBRSTaxonomyTag.namespace)
        .order_by(MBRSTaxonomyTag.namespace)
    )
    
    return [{"namespace": row.namespace, "count": row.count} for row in result]


@router.get("/stats")
async def get_taxonomy_stats(db: AsyncSession = Depends(get_db)):
    """Get taxonomy statistics"""
    
    # Total count
    total_count = await db.execute(select(func.count(MBRSTaxonomyTag.id)))
    
    # Count by namespace
    namespace_stats = await db.execute(
        select(MBRSTaxonomyTag.namespace, func.count(MBRSTaxonomyTag.id).label('count'))
        .group_by(MBRSTaxonomyTag.namespace)
    )
    
    # Count by period type
    period_stats = await db.execute(
        select(MBRSTaxonomyTag.period_type, func.count(MBRSTaxonomyTag.id).label('count'))
        .group_by(MBRSTaxonomyTag.period_type)
    )
    
    return {
        "total_tags": total_count.scalar(),
        "by_namespace": {row.namespace: row.count for row in namespace_stats},
        "by_period_type": {row.period_type: row.count for row in period_stats}
    }

@router.get("/status")
async def get_taxonomy_status(db: AsyncSession = Depends(get_db)):
    """Get taxonomy loading status"""
    
    # Total count
    total_result = await db.execute(select(func.count(MBRSTaxonomyTag.id)))
    total = total_result.scalar()
    
    # Sample labels
    sample_result = await db.execute(
        select(MBRSTaxonomyTag.label)
        .limit(5)
        .order_by(MBRSTaxonomyTag.label)
    )
    samples = [row.label for row in sample_result.all()]
    
    return {
        "total_tags": total,
        "is_loaded": total > 0,
        "sample_labels": samples,
        "message": "Taxonomy loaded" if total > 0 else "No taxonomy data. Run 'python cli.py load_sample_taxonomy'"
    }
