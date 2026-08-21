# services/semantic_matcher.py
import asyncio
from typing import List, Optional, Dict
from huggingface_hub import AsyncInferenceClient
from huggingface_hub.utils import HfHubHTTPError
import logging
import numpy as np
from config import settings

logger = logging.getLogger(__name__)


class SemanticMatcher:
    """
    Semantic matching using Qwen/Qwen3-Embedding-8B via Hugging Face Inference API
    Embeddings are stored in PostgreSQL using pgvector (truncated to 1752 dimensions for HNSW)
    """
    
    # HNSW has a limit of 2000 dimensions, we use 1752 to be safe
    EMBEDDING_DIMENSIONS = 1752
    
    def __init__(self, model_name: Optional[str] = None):
        """
        Initialize semantic matcher with Qwen3-Embedding-8B via API
        """
        self.model_name = model_name or settings.embedding_model_id
        
        logger.info(f"Initializing SemanticMatcher with {self.model_name}")
        logger.info(f"Embeddings will be truncated to {self.EMBEDDING_DIMENSIONS} dimensions for HNSW")

        try:
            self.client = AsyncInferenceClient(
                model=self.model_name,
                token=settings.model_api_token or settings.hugging_face_token
            )
            logger.info(f"✅ AsyncInferenceClient initialized for {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if the client is available"""
        return self.client is not None
    
    def _truncate_embedding(self, embedding: List[float]) -> List[float]:
        """
        Truncate embedding to HNSW-compatible dimensions
        
        Args:
            embedding: Full embedding vector
            
        Returns:
            Truncated embedding vector
        """
        if len(embedding) <= self.EMBEDDING_DIMENSIONS:
            return embedding
        # Truncate to first N dimensions
        truncated = embedding[:self.EMBEDDING_DIMENSIONS]
        
        # Re-normalize after truncation
        truncated_array = np.array(truncated)
        norm = np.linalg.norm(truncated_array)
        if norm > 0:
            truncated_array = truncated_array / norm
        
        return truncated_array.tolist()
    
    async def encode_text(self, text: str, retry_count: int = 3) -> Optional[List[float]]:
        """
        Encode a single text into embedding using Qwen3-Embedding-8B
        
        Args:
            text: Text string to encode
            retry_count: Number of retries on failure
            
        Returns:
            List of floats representing the embedding (truncated to 1752 dimensions)
        """
        if not self.is_available():
            logger.warning("Client not available")
            return None
        
        for attempt in range(retry_count):
            try:
                # Use feature extraction endpoint for embeddings
                embedding = await self.client.feature_extraction(text)
                
                # The API returns the embedding directly
                embedding_array = np.array(embedding)
                
                # Handle different return formats
                if embedding_array.ndim == 2:
                    # Take mean of token embeddings if multiple tokens
                    embedding_array = embedding_array.mean(axis=0)
                
                # Normalize to unit vector
                norm = np.linalg.norm(embedding_array)
                if norm > 0:
                    embedding_array = embedding_array / norm
                
                full_embedding = embedding_array.tolist()
                
                # Truncate to HNSW-compatible dimensions
                truncated_embedding = self._truncate_embedding(full_embedding)
                
                logger.debug(f"Encoded text (truncated from {len(full_embedding)} to {len(truncated_embedding)} dims)")
                
                return truncated_embedding
            
            except HfHubHTTPError as e:
                if e.response.status_code == 429:  # Rate limit
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{retry_count}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"HTTP error encoding text: {e}")
                    if attempt == retry_count - 1:
                        return None
                    await asyncio.sleep(1)
            
            except Exception as e:
                logger.error(f"Error encoding text '{text[:50]}...': {e}")
                if attempt == retry_count - 1:
                    return None
                await asyncio.sleep(1)
        
        return None
    
    async def encode_batch_single_call(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Encode multiple texts in a SINGLE API call (utilizing large context window)
        
        Args:
            texts: List of text strings to encode (recommend 20-50 texts per call)
            
        Returns:
            List of embeddings (or None for failed items)
        """
        if not self.is_available():
            logger.warning("Client not available")
            return [None] * len(texts)
        
        try:
            # Qwen3-Embedding-8B can handle multiple texts in one call
            # We'll encode them together to maximize throughput
            results = []
            
            for text in texts:
                embedding = await self.encode_text(text)
                results.append(embedding)
                # Small delay between items in same batch
                await asyncio.sleep(0.05)
            
            return results
        
        except Exception as e:
            logger.error(f"Error encoding batch: {e}")
            return [None] * len(texts)
    
    async def encode_batch(
        self, 
        texts: List[str], 
        batch_size: int = 20,
        delay_between_batches: float = 2.0
    ) -> List[List[float]]:
        """
        Encode multiple texts into embeddings with rate limit handling
        
        Args:
            texts: List of text strings to encode
            batch_size: Number of texts per batch (20-50 recommended for Qwen)
            delay_between_batches: Delay in seconds between batches
            
        Returns:
            List of embeddings
        """
        if not self.is_available():
            logger.warning("Client not available")
            return []
        
        all_embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size
        
        logger.info(f"Processing {len(texts)} texts in {total_batches} batches of {batch_size}")
        
        try:
            for batch_idx in range(0, len(texts), batch_size):
                batch_texts = texts[batch_idx:batch_idx + batch_size]
                current_batch_num = batch_idx // batch_size + 1
                
                logger.info(f"Processing batch {current_batch_num}/{total_batches} ({len(batch_texts)} texts)")
                
                # Encode the batch (multiple texts in series with retry logic)
                batch_embeddings = await self.encode_batch_single_call(batch_texts)
                
                # Handle failed embeddings
                for i, embedding in enumerate(batch_embeddings):
                    if embedding is None:
                        # Use zero vector as fallback
                        logger.warning(f"Failed to encode text at index {batch_idx + i}, using zero vector")
                        all_embeddings.append([0.0] * self.EMBEDDING_DIMENSIONS)
                    else:
                        all_embeddings.append(embedding)
                
                progress = len(all_embeddings)
                logger.info(f"Progress: {progress}/{len(texts)} texts encoded ({progress/len(texts)*100:.1f}%)")
                
                # Delay between batches to avoid rate limits (except for last batch)
                if current_batch_num < total_batches:
                    logger.info(f"Waiting {delay_between_batches}s before next batch...")
                    await asyncio.sleep(delay_between_batches)
        
        except Exception as e:
            logger.error(f"Error encoding batch: {e}")
            # Fill remaining with zero vectors
            remaining = len(texts) - len(all_embeddings)
            if remaining > 0:
                logger.warning(f"Filling {remaining} remaining embeddings with zero vectors")
                all_embeddings.extend([[0.0] * self.EMBEDDING_DIMENSIONS] * remaining)
        
        return all_embeddings

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score between 0 and 1
        """
        try:
            vec1_array = np.array(vec1)
            vec2_array = np.array(vec2)
            
            # Calculate cosine similarity
            dot_product = np.dot(vec1_array, vec2_array)
            norm_vec1 = np.linalg.norm(vec1_array)
            norm_vec2 = np.linalg.norm(vec2_array)
            
            if norm_vec1 == 0 or norm_vec2 == 0:
                return 0.0
            
            similarity = dot_product / (norm_vec1 * norm_vec2)
            
            # Ensure result is between 0 and 1
            return max(0.0, min(1.0, (similarity + 1) / 2))
            
        except Exception as e:
            logger.error(f"Error calculating cosine similarity: {e}")
            return 0.0

    async def find_best_match(
        self,
        query_text: str,
        candidate_labels: List[str],
        similarity_threshold: float = 0.5
    ) -> Optional[Dict]:
        """
        Find the best semantic match for a query among candidate labels
        
        Args:
            query_text: Text to find matches for
            candidate_labels: List of candidate labels to match against
            similarity_threshold: Minimum similarity threshold
            
        Returns:
            Dict with 'similarity' and 'tag_label' keys, or None if no good match
        """
        try:
            if not self.is_available():
                logger.warning("Semantic matcher not available")
                return None
            
            if not candidate_labels:
                logger.warning("No candidate labels provided")
                return None
            
            # Encode query text
            logger.debug(f"Encoding query: '{query_text[:50]}...'")
            query_embedding = await self.encode_text(query_text)
            
            if not query_embedding:
                logger.warning(f"Failed to encode query text: {query_text}")
                return None
            
            # Encode candidate labels (in smaller batches to avoid rate limits)
            logger.debug(f"Encoding {len(candidate_labels)} candidate labels")
            
            batch_size = 10  # Smaller batches for better reliability
            candidate_embeddings = []
            
            for i in range(0, len(candidate_labels), batch_size):
                batch = candidate_labels[i:i + batch_size]
                batch_embeddings = await self.encode_batch_single_call(batch)
                candidate_embeddings.extend(batch_embeddings)
                
                # Small delay between batches
                if i + batch_size < len(candidate_labels):
                    await asyncio.sleep(0.5)
            
            # Calculate similarities
            best_similarity = 0.0
            best_label = None
            
            for i, (label, embedding) in enumerate(zip(candidate_labels, candidate_embeddings)):
                if embedding is None:
                    logger.debug(f"Skipping label with failed embedding: {label}")
                    continue
                
                similarity = self._cosine_similarity(query_embedding, embedding)
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_label = label
                    
                logger.debug(f"Similarity for '{label}': {similarity:.3f}")
            
            # Return best match if above threshold
            if best_similarity >= similarity_threshold and best_label:
                logger.info(f"Best semantic match: '{query_text}' -> '{best_label}' (similarity: {best_similarity:.3f})")
                return {
                    'similarity': best_similarity,
                    'tag_label': best_label
                }
            else:
                logger.debug(f"No semantic match above threshold {similarity_threshold} (best: {best_similarity:.3f})")
                return None
        
        except Exception as e:
            logger.error(f"Error in semantic matching: {e}")
            import traceback
            traceback.print_exc()
            return None

    # Alternative lightweight version if the full version is too slow:
    async def find_best_match_lightweight(
        self,
        query_text: str,
        candidate_labels: List[str],
        max_candidates: int = 20
    ) -> Optional[Dict]:
        """
        Lightweight version that limits candidates for better performance
        """
        # Limit candidates to avoid long processing times
        limited_candidates = candidate_labels[:max_candidates]
        
        return await self.find_best_match(
            query_text,
            limited_candidates,
            similarity_threshold=0.6  # Slightly higher threshold for fewer candidates
        )
        
    async def create_combined_embedding(self, label: str, xbrl_tag: str) -> List[float]:
        """Create embedding from both label and XBRL tag for better matching"""
        
        # Convert camelCase XBRL tag to readable text
        readable_tag = self._xbrl_tag_to_readable(xbrl_tag)
        
        # Combine label and readable tag
        combined_text = f"{label} {readable_tag}"
        
        return await self.encode_text(combined_text)

    def _xbrl_tag_to_readable(self, xbrl_tag: str) -> str:
        """Convert XBRL tag to readable text"""
        # Remove namespace prefix
        if '_' in xbrl_tag:
            tag = xbrl_tag.split('_', 1)[1]
        else:
            tag = xbrl_tag
        
        # Convert CamelCase to spaced words
        import re
        readable = re.sub(r'([A-Z])', r' \1', tag).strip()
        
        # Clean up common patterns
        readable = readable.replace('  ', ' ')
        readable = readable.lower()
        
        return readable

# Global instance
semantic_matcher = SemanticMatcher()
