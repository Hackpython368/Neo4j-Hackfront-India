"""Minimum demo, end to end, no browser needed.

  1. Report an issue            -> stored in Neo4j (Customer, Product, Issue, Ticket)
  2. Log what was already tried -> stored as Resolution nodes
  3. Start a BRAND NEW conversation and say "My account still isn't working"
  4. Show the agent retrieving the relevant history from the graph

Run:  python demo.py
"""
import json
import uuid

from app import create_app


def show(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def main():
    client = create_app().test_client()
    email = f"demo-{uuid.uuid4().hex[:6]}@example.com"

    show("1. Report an issue")
    cust = client.post("/api/customers", json={"name": "Priya Sharma", "email": email}).get_json()
    prod = client.post(f"/api/customers/{cust['id']}/products",
                       json={"name": f"Nimbus Cloud Storage Pro {uuid.uuid4().hex[:4]}", "category": "account"}).get_json()
    created = client.post("/api/issues", json={
        "customer_id": cust["id"], "product_id": prod["id"],
        "title": "Cannot log in to my account",
        "description": "Login fails with 'invalid credentials' although my password is right.",
        "priority": "high", "category": "account"}).get_json()
    ticket = created["ticket"]
    print(f"Stored: {cust['name']} -> {prod['name']} -> {created['issue']['title']} -> {ticket['number']}")

    show("2. Log attempted resolutions")
    for text in ("Customer reset password via the email link",
                 "Customer cleared browser cache and cookies and tried incognito"):
        client.post(f"/api/tickets/{ticket['id']}/resolutions",
                    json={"description": text, "outcome": "failed"})
        print(f"Attempt stored (failed): {text}")

    show("3. NEW conversation: 'My account still isn't working'")
    r = client.post("/api/chat", json={"customer_id": cust["id"],
                                       "message": "My account still isn't working"}).get_json()
    print(f"conversation: {r['conversation_id']} (new={r['new_conversation']}, mode={r['mode']})\n")
    print(r["reply"])

    show("4. History retrieved from Neo4j")
    p = r["context_used"]["primary"]
    print(f"Customer  : {r['context_used']['customer']['name']}")
    print(f"Product   : {p['product']['name']}")
    print(f"Issue     : {p['issue']['title']} [{p['issue']['status']}]")
    print(f"Ticket    : {p['ticket']['number']} [{p['ticket']['status']}]")
    for n, res in enumerate(p["resolutions"], 1):
        print(f"Resolution {n}: {res['description']} -> {res['outcome']}")
    print("Ranking   :", json.dumps(r["context_used"]["ranked"]))


if __name__ == "__main__":
    main()
