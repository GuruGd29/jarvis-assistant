"""Made-up bank emails for the AI bank reader cases (MA-01, MA-02): banks without a built-in reader, a card
statement, a foreign-currency charge, and emails that must not be stored. Amounts are in rupees (the test setup)."""
from datetime import datetime

RECEIVED = datetime(2026, 11, 1, 10, 0)
EMAILS = [  # (label, subject, body, expected outcome, expected amount or None)
    ("SBI UPI debit", "Transaction alert",
     "Dear Customer, Your A/C XXXXX4321 has been debited by Rs.2,350.00 on 31-10-26 transfer to SWIGGY Ref No 630412. "
     "If not done by you, call 1800 11 2211 -SBI", "transaction", 2350.0),
    ("Kotak salary credit", "Credit alert",
     "Rs. 85,000.00 is credited to your Kotak Bank a/c XX1122 on 01-Nov-2026 by NEFT from ACME TECHNOLOGIES PVT LTD.",
     "transaction", 85000.0),
    ("Axis card purchase", "Transaction alert on Axis Bank Credit Card",
     "Thank you for using your Axis Bank Credit Card no. XX7788 for INR 1,299.00 at MYNTRA on 30-10-2026 18:22:10 IST. "
     "Available limit: INR 1,48,701.00", "transaction", 1299.0),
    ("Axis card statement", "Your Axis Bank Credit Card Statement for October 2026",
     "Dear Customer, your statement for Axis Bank Credit Card XX7788 is ready. Total Amount Due: INR 18,450.00. "
     "Minimum Amount Due: INR 920.00. Payment Due Date: 18 Nov 2026.", "card_statement", 18450.0),
    ("Chase USD purchase", "Your Chase card transaction",
     "A charge of $42.50 at STARBUCKS was made on your Chase Sapphire card ending in 9012 on Oct 30, 2026.",
     "other_currency", None),
    ("Loan offer", "Pre-approved personal loan for you!",
     "Congratulations! Get a pre-approved personal loan of up to Rs 5,00,000 at just 10.5% p.a. Apply now.",
     "not_a_transaction", None),
    ("OTP", "OTP for your transaction",
     "482913 is your OTP for a transaction of Rs 1,999.00 at AMAZON on your SBI card XX4455. Valid for 10 minutes. "
     "Do not share it with anyone.", "not_a_transaction", None),
    ("Declined", "Transaction declined",
     "Your transaction of Rs. 4,500.00 at FLIPKART on your Kotak Debit Card XX3344 was declined due to insufficient "
     "balance.", "not_a_transaction", None),
]
