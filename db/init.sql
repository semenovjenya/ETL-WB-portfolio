CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL,
    source_path TEXT NOT NULL,
    doc_id TEXT,
    method TEXT,
    endpoint TEXT,
    section TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_source_path ON doc_chunks (source_path);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_id ON doc_chunks (doc_id);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
    ON doc_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE OR REPLACE FUNCTION set_doc_chunks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_doc_chunks_updated_at ON doc_chunks;
CREATE TRIGGER trg_doc_chunks_updated_at
BEFORE UPDATE ON doc_chunks
FOR EACH ROW
EXECUTE FUNCTION set_doc_chunks_updated_at();
