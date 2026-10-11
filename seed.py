"""Demo data: one customer with an old resolved billing issue and an open,
partly-troubleshot login issue. Safe to run repeatedly."""
import graph_repo as repo

DEMO_EMAIL = "priya.sharma@example.com"


def seed_demo():
    existing = repo.find_customer_by_email(DEMO_EMAIL)
    if existing:
        return existing, False

    customer = repo.create_customer("Priya Sharma", DEMO_EMAIL)
    cid = customer["id"]
    product = repo.add_product_to_customer(cid, "Nimbus Cloud Storage Pro", "account")

    # Older issue, already resolved (should NOT dominate retrieval).
    billing = repo.create_issue(
        cid, product["id"], "Charged twice for March invoice",
        "I see two identical charges for my March subscription.",
        priority="medium", category="billing")
    repo.add_resolution(billing["ticket"]["id"],
                        "Issued refund for the duplicate charge", "worked")

    # Current issue, two failed attempts so far.
    login = repo.create_issue(
        cid, product["id"], "Cannot log in to my account",
        "Login keeps failing with 'invalid credentials' even though the password is correct.",
        priority="high", category="account")
    tid = login["ticket"]["id"]
    repo.add_resolution(tid, "Customer reset password via the email link", "failed")
    repo.add_resolution(tid, "Customer cleared browser cache and cookies and tried an incognito window", "failed")
    return customer, True
