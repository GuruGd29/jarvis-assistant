-- Tasks and reminders. remind_at drives Telegram reminders; due_on drives the briefing.
CREATE TABLE IF NOT EXISTS tasks (
  id           bigserial PRIMARY KEY,
  title        text NOT NULL,
  notes        text,
  due_on       date,
  remind_at    timestamptz,
  reminded_at  timestamptz,
  priority     smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),  -- 1 high, 2 normal, 3 low
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS tasks_open_due ON tasks (due_on) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS tasks_pending_reminders ON tasks (remind_at) WHERE status = 'open' AND reminded_at IS NULL;
