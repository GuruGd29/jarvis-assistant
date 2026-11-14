-- Repaying slice borrow from another bank (a UPI payment to "slice") is not spending: the payments made with the
-- borrowed money are (jarvis/money.py, CARD_BILL_PAYEE). Rows saved before that rule get the same kind as new ones.
UPDATE transactions SET kind = 'card_bill_payment' WHERE kind = 'upi_debit' AND counterparty ~* '^\s*slice\s*$';
