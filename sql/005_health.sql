-- Medicines and their doses (one row per scheduled dose, created when it falls due).
CREATE TABLE IF NOT EXISTS medications (
  id          bigserial PRIMARY KEY,
  name        text NOT NULL,
  dose        text,                       -- e.g. "500 mg", "60000 IU"
  times       text[] NOT NULL,            -- local times "HH:MM"
  weekdays    smallint[],                 -- 0=Mon .. 6=Sun; NULL = every day
  start_on    date NOT NULL DEFAULT current_date,
  end_on      date,
  notes       text,
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS medication_doses (
  id            bigserial PRIMARY KEY,
  medication_id bigint NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
  due_at        timestamptz NOT NULL,
  reminded_at   timestamptz,
  status        text NOT NULL DEFAULT 'due' CHECK (status IN ('due', 'taken', 'skipped')),
  answered_at   timestamptz,
  UNIQUE (medication_id, due_at)
);
-- Lab values over time.
CREATE TABLE IF NOT EXISTS lab_results (
  id         bigserial PRIMARY KEY,
  test       text NOT NULL,
  value      numeric NOT NULL,
  unit       text,
  ref_low    numeric,
  ref_high   numeric,
  ref_text   text,
  tested_on  date NOT NULL,
  source     text NOT NULL,              -- file name, or "told to Jarvis"
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (test, tested_on, source)
);
