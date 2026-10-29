-- Outward actions (e.g. adding a calendar event) that need the user's own "yes" before they run.
-- Jarvis proposes; the Hermes plugin marks approved_at from the user's next message; only then can it execute.
CREATE TABLE IF NOT EXISTS pending_actions (
  id          bigserial PRIMARY KEY,
  kind        text NOT NULL,            -- e.g. calendar.create_event
  payload     jsonb NOT NULL,
  summary     text NOT NULL,            -- what the user is asked to approve
  created_at  timestamptz NOT NULL DEFAULT now(),
  approved_at timestamptz,
  executed_at timestamptz,
  result      jsonb
);
