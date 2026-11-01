-- Bank emails read by the local AI (banks without a built-in reader). One row per email, so each is read once:
-- outcome is 'saved' (a transaction or card statement was stored) or why it was not ('not_a_transaction',
-- 'amount_not_in_email', 'other_currency', ...).
CREATE TABLE IF NOT EXISTS money_ai_seen (
  gmail_id   text PRIMARY KEY,
  outcome    text NOT NULL,
  detail     text,
  checked_at timestamptz NOT NULL DEFAULT now()
);
