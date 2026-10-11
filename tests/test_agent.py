import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.pop("ANTHROPIC_API_KEY", None)

import agent  # noqa: E402
import chat  # noqa: E402

CUSTOMER = {"id": "cus_1", "name": "Priya Sharma", "email": "p@example.com"}
PRODUCT = {"id": "prd_1", "name": "Nimbus Cloud Storage Pro", "category": "account"}


def entry(title, desc, status, category, resolutions, created, number):
    return {
        "issue": {"id": "iss_" + number, "title": title, "description": desc,
                  "status": status, "category": category, "createdAt": created},
        "product": PRODUCT,
        "ticket": {"id": "tkt_" + number, "number": number, "status": status, "priority": "high"},
        "resolutions": [{"description": d, "outcome": o, "createdAt": created} for d, o in resolutions],
    }


LOGIN = entry("Cannot log in to my account", "Invalid credentials", "in_progress", "account",
              [("Customer reset password via the email link", "failed"),
               ("Customer cleared browser cache and cookies, tried incognito", "failed")],
              "2026-10-10T10:00:00", "TCK-LOGIN")
BILLING = entry("Charged twice for March invoice", "Two identical charges", "resolved", "billing",
                [("Issued refund for the duplicate charge", "worked")],
                "2026-09-01T10:00:00", "TCK-BILL")
CTX = {"products": [PRODUCT], "issues": [LOGIN, BILLING], "past_conversations": []}


class RankingTests(unittest.TestCase):
    def test_account_message_picks_login_issue(self):
        ranked = agent.rank_issues("My account still isn't working", CTX["issues"])
        primary = agent.pick_primary("My account still isn't working", ranked)
        self.assertEqual(primary["ticket"]["number"], "TCK-LOGIN")

    def test_billing_message_picks_billing_issue(self):
        msg = "I was charged again on my card"
        primary = agent.pick_primary(msg, agent.rank_issues(msg, CTX["issues"]))
        self.assertEqual(primary["ticket"]["number"], "TCK-BILL")

    def test_vague_followup_falls_back_to_open_issue(self):
        msg = "Any update on this?"
        primary = agent.pick_primary(msg, agent.rank_issues(msg, CTX["issues"]))
        self.assertEqual(primary["ticket"]["number"], "TCK-LOGIN")

    def test_unrelated_message_has_no_primary(self):
        msg = "How do I change my shipping address?"
        self.assertIsNone(agent.pick_primary(msg, agent.rank_issues(msg, [BILLING])))


class ReplyTests(unittest.TestCase):
    def reply(self, msg, issues=None):
        issues = CTX["issues"] if issues is None else issues
        ranked = agent.rank_issues(msg, issues)
        primary = agent.pick_primary(msg, ranked)
        return agent.fallback_reply(CUSTOMER, {**CTX, "issues": issues}, ranked, primary)

    def test_recalls_issue_ticket_and_attempts(self):
        text = self.reply("My account still isn't working")
        self.assertIn("Cannot log in to my account", text)
        self.assertIn("TCK-LOGIN", text)
        self.assertIn("reset password", text)
        self.assertIn("cleared browser cache", text)

    def test_does_not_repeat_tried_steps(self):
        text = self.reply("My account still isn't working")
        next_line = [l for l in text.splitlines() if l.startswith("Next")][0]
        self.assertNotIn("password", next_line)
        self.assertNotIn("cache", next_line)

    def test_escalates_after_three_failures(self):
        many = entry("Cannot log in", "x", "in_progress", "account",
                     [("reset password", "failed"), ("cleared cache", "failed"), ("verified email", "failed")],
                     "2026-10-10T10:00:00", "TCK-X")
        self.assertIn("escalat", self.reply("my account still fails", [many]).lower())

    def test_resolved_issue_offers_reopen(self):
        self.assertIn("reopen", self.reply("I was charged again", [BILLING]))

    def test_no_history(self):
        self.assertIn("don't see any earlier issues", self.reply("hello", []))


class ChatFlowTests(unittest.TestCase):
    def test_new_conversation_retrieves_history_and_persists(self):
        stored = []
        with patch.multiple(
            "graph_repo",
            get_customer=lambda cid: CUSTOMER,
            start_conversation=lambda cid: {"id": "cnv_new"},
            add_message=lambda cv, role, content: stored.append((role, content)) or {},
            get_customer_context=lambda cid, exclude_conversation_id=None: CTX,
            get_messages=lambda cv: [{"role": r, "content": c, "createdAt": ""} for r, c in stored],
            link_conversation_issue=lambda cv, iid: stored.append(("link", iid)),
        ):
            out = chat.handle_chat("cus_1", "My account still isn't working")
        self.assertTrue(out["new_conversation"])
        self.assertEqual(out["conversation_id"], "cnv_new")
        self.assertEqual(out["mode"], "rule-based")
        self.assertEqual(out["context_used"]["primary"]["ticket"]["number"], "TCK-LOGIN")
        self.assertIn("TCK-LOGIN", out["reply"])
        self.assertEqual([s[0] for s in stored], ["user", "assistant", "link"])

    def test_empty_message_rejected(self):
        from errors import BadRequest
        with self.assertRaises(BadRequest):
            chat.handle_chat("cus_1", "   ")


class ApiTests(unittest.TestCase):
    def setUp(self):
        with patch("db.verify"), patch("db.init_schema"):
            import app as app_module
            self.client = app_module.create_app().test_client()

    def test_missing_fields_400(self):
        r = self.client.post("/api/issues", json={"customer_id": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("product_id", r.get_json()["error"])

    def test_not_found_404(self):
        from errors import NotFound
        with patch("graph_repo.get_customer", side_effect=NotFound("Customer not found")):
            r = self.client.get("/api/customers/nope/history")
        self.assertEqual(r.status_code, 404)

    def test_index_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
