-- Watches (docs/watches.md): something Jarvis checks on a schedule (a redBus fare, BookMyShow bookings opening, a
-- price or some words on a web page) to tell the user when it finds what they asked for. A watch is kept when its
-- day has passed (state 'saved'), so it can be started again for another day.
CREATE TABLE IF NOT EXISTS watches (
  id            serial PRIMARY KEY,
  kind          text NOT NULL,                       -- bus | movie | page
  title         text NOT NULL,
  params        jsonb NOT NULL,                      -- what to look at and when to tell the user, by kind
  every_minutes int NOT NULL DEFAULT 10,
  state         text NOT NULL DEFAULT 'watching',    -- watching | paused | saved
  watch_on      date,                                -- the day being watched; null for a web page
  until_at      timestamptz,                         -- then it stops checking and goes back to saved
  next_at       timestamptz,
  checked_at    timestamptz,
  result        jsonb,                               -- the last check
  failures      int NOT NULL DEFAULT 0,              -- checks in a row that could not read the site
  found_at      timestamptz,                         -- when it last found what the user asked for
  found         jsonb,                               -- {value, text}
  seen          boolean NOT NULL DEFAULT true,       -- false: a find the user has not looked at yet
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Each check's value (cheapest fare, price), for the little chart; kept 30 days.
CREATE TABLE IF NOT EXISTS watch_checks (
  watch_id   int NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
  checked_at timestamptz NOT NULL DEFAULT now(),
  ok         boolean NOT NULL,
  value      numeric,
  met        boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS watch_checks_by_watch ON watch_checks (watch_id, checked_at);

-- Each time a watch was started for a day, and the best it saw: "Used before" in the app.
CREATE TABLE IF NOT EXISTS watch_uses (
  id         serial PRIMARY KEY,
  watch_id   int NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
  watch_on   date,
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at   timestamptz,
  best       numeric,
  found_at   timestamptz
);
