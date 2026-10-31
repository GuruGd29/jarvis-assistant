-- The Jarvis web app. Chat transcripts live in Hermes (Sessions API); these tables hold the app's own state.

-- Chats started from the app, newest first in the sidebar. Messages are read back from Hermes.
CREATE TABLE IF NOT EXISTS web_chats (
  session_id text PRIMARY KEY,
  title      text NOT NULL DEFAULT 'New chat',
  preview    text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Browsers (the iPhone Home Screen app) that allowed notifications.
CREATE TABLE IF NOT EXISTS push_subscriptions (
  endpoint   text PRIMARY KEY,
  p256dh     text NOT NULL,
  auth       text NOT NULL,
  user_agent text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_ok_at timestamptz
);

-- Everything Jarvis wanted to tell the user. Shown in the app's Activity list; pushed only when that
-- kind of notification is switched on in Settings.
CREATE TABLE IF NOT EXISTS activity (
  id         bigserial PRIMARY KEY,
  kind       text NOT NULL,          -- reminders | renewals | problems | reports | replies
  title      text NOT NULL,
  body       text NOT NULL,
  data       jsonb NOT NULL DEFAULT '{}',
  pushed     boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at    timestamptz
);
CREATE INDEX IF NOT EXISTS activity_created ON activity (created_at DESC);

-- Small app settings, one JSON value per key (e.g. "notifications").
CREATE TABLE IF NOT EXISTS app_settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
