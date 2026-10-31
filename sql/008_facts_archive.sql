-- Facts removed by the weekly memory clean-up (after the user approved), kept so "restore 12" can bring one back.
CREATE TABLE IF NOT EXISTS facts_archive (
  id          bigint PRIMARY KEY,
  fact        text NOT NULL,
  source      text,
  kind        text NOT NULL,
  embedding   vector(1024),
  created_at  timestamptz,
  updated_at  timestamptz,
  archived_at timestamptz NOT NULL DEFAULT now(),
  reason      text
);
