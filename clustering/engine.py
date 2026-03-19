"""L1 Opinion Clustering Engine -- embeds documents and clusters opinions.

NO LLM calls. Pure embedding + clustering.
"""

import logging
from typing import List, Optional

import numpy as np

from models.schemas import ClusterProfile, Document

logger = logging.getLogger(__name__)

# Sentiment lexicon for simple rule-based analysis
_POSITIVE_WORDS = frozenset({
    "good", "great", "excellent", "positive", "benefit", "advantage", "improve",
    "success", "promising", "innovative", "efficient", "effective", "progress",
    "opportunity", "support", "agree", "better", "best", "optimal", "favorable",
    "remarkable", "outstanding", "breakthrough", "helpful", "valuable", "gain",
    "prosper", "thrive", "enhance", "superior", "wonderful", "fantastic",
    "amazing", "brilliant", "exciting", "encourage", "optimistic", "hope",
})

_NEGATIVE_WORDS = frozenset({
    "bad", "poor", "negative", "risk", "danger", "problem", "fail", "failure",
    "concern", "threat", "harmful", "inefficient", "decline", "loss", "worse",
    "worst", "disadvantage", "oppose", "disagree", "difficult", "challenge",
    "crisis", "critical", "alarming", "devastating", "destructive", "flawed",
    "inferior", "terrible", "horrible", "awful", "disastrous", "pessimistic",
    "fear", "worry", "doubt", "skeptical", "controversial", "limitation",
})


class TextEmbedder:
    """Text embedding using sentence-transformers. Runs locally on GPU."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None  # Lazy loading

    @property
    def model(self):  # type: ignore[return]
        """Lazy-load the SentenceTransformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            logger.info("Loaded embedding model: %s", self.model_name)
        return self._model

    def embed(self, texts: List[str]) -> np.ndarray:
        """Embed list of texts. Returns (n_texts, embedding_dim) array."""
        if not texts:
            return np.array([]).reshape(0, 0)
        return self.model.encode(texts, show_progress_bar=False)

    def embed_single(self, text: str) -> np.ndarray:
        """Embed single text."""
        return self.model.encode([text], show_progress_bar=False)[0]


class OpinionClusterEngine:
    """Opinion clustering engine -- embeds documents and clusters opinions.

    NO LLM calls. Pure embedding + clustering.
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        min_cluster_size: int = 3,
        min_samples: int = 2,
    ) -> None:
        self.embedder = TextEmbedder(model_name)
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples

    def cluster(
        self,
        documents: List[Document],
        n_clusters: Optional[int] = None,
    ) -> List[ClusterProfile]:
        """Full clustering pipeline: embed -> cluster -> extract profiles."""
        if not documents:
            logger.warning("No documents provided for clustering")
            return []

        # Single document edge case
        if len(documents) == 1:
            return [self._single_doc_profile(documents[0])]

        # 1. Embed all documents
        texts = [f"{doc.title} {doc.content}" for doc in documents]
        embeddings = self.embedder.embed(texts)

        # 2. Cluster
        if n_clusters is not None:
            actual_n = min(n_clusters, len(documents))
            labels = self._cluster_kmeans(embeddings, actual_n)
        elif len(documents) < self.min_cluster_size:
            # Too few documents for HDBSCAN, put all in one cluster
            labels = np.zeros(len(documents), dtype=int)
        else:
            labels = self._cluster_hdbscan(embeddings)

        # Handle case where all points are noise (-1)
        if np.all(labels == -1):
            logger.warning("All points classified as noise, falling back to single cluster")
            labels = np.zeros(len(documents), dtype=int)

        # Assign noise points to nearest cluster
        labels = self._assign_noise_points(labels, embeddings)

        # 3. Extract profiles for each cluster
        unique_labels = sorted(set(labels))
        profiles: List[ClusterProfile] = []

        for cluster_id in unique_labels:
            mask = labels == cluster_id
            cluster_docs = [doc for doc, m in zip(documents, mask) if m]
            profile = self._extract_profile(
                cluster_id=cluster_id,
                cluster_docs=cluster_docs,
                all_docs=documents,
                embeddings=embeddings,
                cluster_mask=mask,
            )
            profiles.append(profile)

        # Sort by weight descending
        profiles.sort(key=lambda p: p.weight, reverse=True)

        logger.info(
            "Clustered %d documents into %d clusters",
            len(documents),
            len(profiles),
        )
        return profiles

    def _cluster_hdbscan(self, embeddings: np.ndarray) -> np.ndarray:
        """HDBSCAN clustering -- auto-determines cluster count."""
        try:
            import hdbscan
        except ImportError:
            logger.warning(
                "hdbscan not installed, falling back to KMeans with n_clusters=3"
            )
            return self._cluster_kmeans(embeddings, n_clusters=3)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(embeddings)
        return np.array(labels, dtype=int)

    def _cluster_kmeans(self, embeddings: np.ndarray, n_clusters: int) -> np.ndarray:
        """K-Means fallback when user specifies cluster count."""
        from sklearn.cluster import KMeans

        n_clusters = max(1, min(n_clusters, len(embeddings)))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)
        return np.array(labels, dtype=int)

    def _assign_noise_points(
        self, labels: np.ndarray, embeddings: np.ndarray
    ) -> np.ndarray:
        """Assign noise points (label -1) to the nearest valid cluster."""
        noise_mask = labels == -1
        if not np.any(noise_mask):
            return labels

        valid_mask = ~noise_mask
        if not np.any(valid_mask):
            return np.zeros(len(labels), dtype=int)

        labels = labels.copy()
        valid_indices = np.where(valid_mask)[0]
        valid_embeddings = embeddings[valid_indices]

        for idx in np.where(noise_mask)[0]:
            point = embeddings[idx]
            distances = np.linalg.norm(valid_embeddings - point, axis=1)
            nearest_valid_idx = valid_indices[np.argmin(distances)]
            labels[idx] = labels[nearest_valid_idx]

        return labels

    def _extract_profile(
        self,
        cluster_id: int,
        cluster_docs: List[Document],
        all_docs: List[Document],
        embeddings: np.ndarray,
        cluster_mask: np.ndarray,
    ) -> ClusterProfile:
        """Extract ClusterProfile from a cluster's documents."""
        # 1. Weight
        weight = len(cluster_docs) / len(all_docs) if all_docs else 0.0

        # 2. Centroid
        cluster_embeddings = embeddings[cluster_mask]
        centroid = np.mean(cluster_embeddings, axis=0)

        # 3. Keywords via TF-IDF
        texts = [f"{doc.title} {doc.content}" for doc in cluster_docs]
        keywords = self._extract_keywords(texts, top_n=10)

        # 4. Key arguments: sentences closest to centroid
        key_arguments = self._extract_key_arguments(texts, cluster_embeddings, centroid)

        # 5. Label from top keywords (filesystem-safe, no slashes)
        label_words = keywords[:3] if keywords else [f"cluster-{cluster_id}"]
        label = "-".join(w.strip() for w in label_words if w.strip())

        # 6. Sentiment
        sentiment = self._calculate_sentiment(texts)

        return ClusterProfile(
            cluster_id=cluster_id,
            label=label,
            weight=round(weight, 4),
            document_count=len(cluster_docs),
            key_arguments=key_arguments,
            keywords=keywords,
            sentiment=round(sentiment, 4),
            centroid=centroid.tolist(),
        )

    def _extract_key_arguments(
        self,
        texts: List[str],
        cluster_embeddings: np.ndarray,
        centroid: np.ndarray,
        top_n: int = 5,
    ) -> List[str]:
        """Extract sentences closest to the cluster centroid as key arguments."""
        # Split all texts into sentences
        sentences: List[str] = []
        for text in texts:
            for sep in [".", "!", "?"]:
                text = text.replace(sep, sep + "|||")
            parts = text.split("|||")
            for part in parts:
                stripped = part.strip()
                if len(stripped) > 20:  # Skip very short fragments
                    sentences.append(stripped)

        if not sentences:
            return texts[:top_n]

        # Embed sentences and find closest to centroid
        sentence_embeddings = self.embedder.embed(sentences[:200])  # Cap to avoid OOM
        if sentence_embeddings.size == 0:
            return texts[:top_n]

        similarities = _cosine_similarity_batch(sentence_embeddings, centroid)
        top_indices = np.argsort(similarities)[::-1][:top_n]

        return [sentences[i][:300] for i in top_indices]

    def _extract_keywords(self, texts: List[str], top_n: int = 10) -> List[str]:
        """TF-IDF based keyword extraction."""
        if not texts:
            return []

        from sklearn.feature_extraction.text import TfidfVectorizer

        try:
            vectorizer = TfidfVectorizer(
                max_features=500,
                stop_words="english",
                max_df=0.95,
                min_df=1,
                ngram_range=(1, 2),
            )
            tfidf_matrix = vectorizer.fit_transform(texts)
            feature_names = vectorizer.get_feature_names_out()

            # Sum TF-IDF scores across documents
            scores = np.asarray(tfidf_matrix.sum(axis=0)).flatten()
            top_indices = np.argsort(scores)[::-1][:top_n]

            return [str(feature_names[i]) for i in top_indices]
        except ValueError:
            # Can happen with very short or empty texts
            logger.warning("TF-IDF extraction failed, returning empty keywords")
            return []

    def _calculate_sentiment(self, texts: List[str]) -> float:
        """Simple rule-based sentiment (-1.0 to 1.0). No LLM."""
        if not texts:
            return 0.0

        positive_count = 0
        negative_count = 0

        for text in texts:
            words = set(text.lower().split())
            positive_count += len(words & _POSITIVE_WORDS)
            negative_count += len(words & _NEGATIVE_WORDS)

        total = positive_count + negative_count
        if total == 0:
            return 0.0

        score = (positive_count - negative_count) / total
        return max(-1.0, min(1.0, score))

    def _single_doc_profile(self, doc: Document) -> ClusterProfile:
        """Create a profile for a single-document cluster."""
        text = f"{doc.title} {doc.content}"
        keywords = self._extract_keywords([text], top_n=5)
        label = "-".join(w.strip() for w in keywords[:3] if w.strip()) if keywords else doc.title[:50]
        embedding = self.embedder.embed_single(text)
        sentiment = self._calculate_sentiment([text])

        return ClusterProfile(
            cluster_id=0,
            label=label,
            weight=1.0,
            document_count=1,
            key_arguments=[doc.content[:300]],
            keywords=keywords,
            sentiment=round(sentiment, 4),
            centroid=embedding.tolist(),
        )


def _cosine_similarity_batch(
    embeddings: np.ndarray, target: np.ndarray
) -> np.ndarray:
    """Compute cosine similarity between each embedding and a target vector."""
    target_norm = np.linalg.norm(target)
    if target_norm == 0:
        return np.zeros(len(embeddings))

    embedding_norms = np.linalg.norm(embeddings, axis=1)
    # Avoid division by zero
    embedding_norms = np.where(embedding_norms == 0, 1e-10, embedding_norms)

    dots = embeddings @ target
    return dots / (embedding_norms * target_norm)
