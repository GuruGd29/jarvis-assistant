-- Short dated summaries of past chats ("episodes") live beside facts, so later chats can pick up the context.
ALTER TABLE facts ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'fact' CHECK (kind IN ('fact', 'episode'));
