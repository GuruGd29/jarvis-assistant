CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source file; content_hash drives incremental re-indexing.
CREATE TABLE IF NOT EXISTS documents (
  id           bigserial PRIMARY KEY,
  path         text UNIQUE NOT NULL,
  domain       text NOT NULL,          -- documents | finance | health | notes | email-export
  title        text,
  content_hash text NOT NULL,
  modified_at  timestamptz,
  indexed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
  id          bigserial PRIMARY KEY,
  document_id bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ord         int NOT NULL,
  heading     text,
  page        int,
  content     text NOT NULL,
  embedding   vector(1024) NOT NULL,   -- bge-m3
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(heading,'') || ' ' || content)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks (document_id);

-- Long-term facts Jarvis is told to remember (beyond Hermes's small built-in memory).
CREATE TABLE IF NOT EXISTS facts (
  id         bigserial PRIMARY KEY,
  fact       text NOT NULL,
  source     text,
  created_at timestamptz NOT NULL DEFAULT now()
);
