-- Answers the app gave straight from Jarvis's data, without the AI model (jarvis/web/instant.py). Hermes keeps the
-- rest of each chat; these are shown with it in time order and passed to Hermes with the next message there.
CREATE TABLE IF NOT EXISTS web_instant (
  id          bigserial PRIMARY KEY,
  session_id  text NOT NULL REFERENCES web_chats (session_id) ON DELETE CASCADE,
  question    text NOT NULL,
  answer      text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  told_model  boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS web_instant_session ON web_instant (session_id, created_at);
