-- Bank and card transactions parsed from alert emails. One row per alert; gmail_id makes sync idempotent.
CREATE TABLE IF NOT EXISTS transactions (
  id           bigserial PRIMARY KEY,
  gmail_id     text UNIQUE NOT NULL,
  bank         text NOT NULL,                 -- HDFC | ICICI
  instrument   text NOT NULL,                 -- e.g. "HDFC a/c 1328", "ICICI card 8006"
  kind         text NOT NULL,                 -- upi_debit | upi_credit | imps_debit | card_spend | card_refund | card_bill_payment
  direction    text NOT NULL CHECK (direction IN ('debit', 'credit')),
  amount       numeric(14,2) NOT NULL CHECK (amount >= 0),
  counterparty text,
  occurred_on  date NOT NULL,
  occurred_at  timestamptz,
  reference    text,
  is_self      boolean NOT NULL DEFAULT false,  -- transfer between the user's own accounts
  subject      text,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transactions_day ON transactions (occurred_on);
