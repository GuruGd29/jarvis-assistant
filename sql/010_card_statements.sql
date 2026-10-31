-- Credit card bills from statement emails (amount due and due date). One row per statement email.
CREATE TABLE IF NOT EXISTS card_statements (
  gmail_id     text PRIMARY KEY,
  card         text NOT NULL,                 -- same naming as transactions.instrument, e.g. "ICICI card 8006"
  name         text,                          -- e.g. "Amazon Pay ICICI"
  statement_on date NOT NULL,
  total_due    numeric(14,2) NOT NULL,
  min_due      numeric(14,2),
  due_on       date,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS card_statements_card ON card_statements (card, statement_on DESC);
