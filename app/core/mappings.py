DOCUMENTS_INDEX_MAPPINGS = {
    "properties": {
        "content": {"type": "text"},
        "embedding": {
            "type": "dense_vector",
            "dims": 384,  # all-MiniLM-L6-v2
            "index": True,
            "similarity": "cosine",
        },
        "metadata": {
            "properties": {
                "id": {"type": "keyword"},
                "page": {"type": "integer"},
                "source": {"type": "keyword"},
                "category": {"type": "keyword"},
                "name": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "chunk_index": {"type": "integer"},
            }
        },
    }
}

USER_MEMORIES_INDEX_MAPPINGS = {
    "properties": {
        "content": {"type": "text"},
        "embedding": {
            "type": "dense_vector",
            "dims": 384,  # all-MiniLM-L6-v2
            "index": True,
            "similarity": "cosine",
        },
        "metadata": {
            "properties": {
                "id": {"type": "keyword"},
                "category": {"type": "keyword"},
                "type": {"type": "keyword"},
                "status": {"type": "keyword"},
                "importance": {"type": "float"},
                "confidence": {"type": "float"},
                "usage_count": {"type": "integer"},
                "last_used_at": {"type": "date"},
                "source": {"type": "keyword"},
                "user_id": {"type": "keyword"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "expires_at": {"type": "date"},
                "valid_from": {"type": "date"},
                "valid_to": {"type": "date"},
            }
        },
    }
}