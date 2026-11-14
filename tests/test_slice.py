"""slice bank emails (jarvis/money.py): the savings account's payments and receipts count; borrowing doesn't.
The emails below follow slice's real layout (Nov 2026), with made-up names, amounts and numbers.

  .venv/bin/python -m unittest tests.test_slice
"""
import unittest
from datetime import date, datetime

from jarvis import money

SENDER = "noreply@slice.bank.in"
WHEN = datetime(2026, 11, 13, 10, 0, tzinfo=money.TZ)
ZWNJ = "‌"  # slice writes it inside amounts


def read(body: str, subject: str = "", sender: str = SENDER) -> dict | None:
    return money.parse_alert(sender, subject, body, WHEN)


class SliceAccount(unittest.TestCase):
    def test_upi_payment_counts(self):
        txn = read("Hi Priya, \n ₹85 debited from your slice account xx4321 via UPI.\n Transaction date \n 13-Nov-26 \n"
                   " To \n RAVI TEA STALL \n RRN \n 631712345678 \n Best, \n Team slice")
        self.assertEqual(txn, {"bank": "slice", "instrument": "slice a/c 4321", "kind": "upi_debit",
                               "direction": "debit", "amount": 85.0, "counterparty": "RAVI TEA STALL",
                               "occurred_on": date(2026, 11, 13), "reference": "631712345678"})

    def test_amounts_with_the_invisible_joiner(self):
        txn = read(f"₹12,{ZWNJ}500 debited from your slice account xx4321 via UPI. Transaction date 02-Nov-26 "
                   "To ANNA STORES RRN 631700000001")
        self.assertEqual((txn["amount"], txn["occurred_on"]), (12500.0, date(2026, 11, 2)))

    def test_older_wording_slice_bank_account(self):
        txn = read("Hi Priya, ₹40 debited from your slice bank account xx4321 via UPI. Transaction date 21-Sep-26 "
                   "To Tea Shop 2 RRN 626412345678 Best, Team slice")
        self.assertEqual((txn["kind"], txn["amount"], txn["counterparty"]), ("upi_debit", 40.0, "Tea Shop 2"))

    def test_imps_out_and_money_received(self):
        sent = read(f"Hi Priya, IMPS transaction of ₹15,{ZWNJ}000 from your slice bank a/c xx4321 is successful! "
                    "Transaction Date 24-Oct-26 Beneficiary Name PRIYA SHARMA Beneficiary Acc No. xx5678 "
                    "Beneficiary Bank HDFC Bank IMPS Ref No. 629712345678 Reach out to our customer support")
        self.assertEqual((sent["kind"], sent["amount"], sent["counterparty"], sent["reference"]),
                         ("imps_debit", 15000.0, "PRIYA SHARMA account ending 5678", "629712345678"))
        self.assertTrue(money._is_self(sent, {"own_names": ["priya sharma"], "own_account_suffixes": []}))
        self.assertTrue(money._is_self(sent, {"own_names": [], "own_account_suffixes": ["5678"]}))
        got = read(f"You have received ₹20,{ZWNJ}000 via IMPS in your slice bank a/c xx4321! Transaction Date "
                   "15-Sep-26 Sender Name ARUN KUMAR IMPS Ref No. 625812345678 Reach out")
        self.assertEqual((got["kind"], got["direction"], got["amount"], got["counterparty"], got["occurred_on"]),
                         ("deposit_credit", "credit", 20000.0, "ARUN KUMAR", date(2026, 9, 15)))

    def test_borrowing_is_left_out(self):
        for body in [
                f"You have received ₹5,{ZWNJ}000 in your slice bank a/c xx4321. Aval. Bal. Rs. 5,210.50! "
                "Transaction Date 12-Nov-26 Sender Name slice Ref No. 631600000002 Reach out",  # borrowed money
                f"You have received ₹20,{ZWNJ}000 via IMPS in your slice bank a/c xx4321! Transaction Date 15-Sep-26 "
                "Sender Name NORTH EAST SMALL FINANCE BANK IMPS Ref No. 625812345678",  # the same, before the rename
                f"You have transferred ₹5,{ZWNJ}000 to your bank account via slice borrow. Order ID: BW1234",
                f"Your repayment of ₹5,{ZWNJ}000 was successful. Transaction ID : RID-abc-123",
                "Your slice email OTP is 123456", "October slice borrow statement"]:
            self.assertIsNone(read(body), body)
        self.assertTrue(money.has_reader(SENDER))  # so these never go to the AI either

    def test_repaying_borrow_from_another_bank_is_not_spending(self):
        self.assertTrue(money.CARD_BILL_PAYEE.search("slice"))
        self.assertTrue(money.CARD_BILL_PAYEE.search(" Slice "))
        self.assertFalse(money.CARD_BILL_PAYEE.search("Slice of Heaven Bakery"))


if __name__ == "__main__":
    unittest.main()
