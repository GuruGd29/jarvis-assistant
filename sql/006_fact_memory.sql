-- Jarvis's long-term memory: facts learned from the user's own chat messages, found again by meaning.
ALTER TABLE facts ADD COLUMN IF NOT EXISTS embedding  vector(1024);
ALTER TABLE facts ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
