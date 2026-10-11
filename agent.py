"""The agent: rank graph history by relevance, then answer with it.

Two reply modes share the same retrieved context:
  * llm        - Claude (needs ANTHROPIC_API_KEY)
  * rule-based - deterministic fallback so the demo works offline
"""
import os
import re

OPEN_STATUSES = {"open", "in_progress", "escalated"}

STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "with", "my", "me", "i", "it", "its", "this", "that",
    "have", "has", "had", "do", "does", "did", "not", "no", "can", "cant",
    "isn't", "isnt", "doesn't", "doesnt", "don't", "dont", "still", "again",
    "working", "work", "works", "worked", "please", "help", "hi", "hello",
    "hey", "any", "update", "yet", "same", "problem", "issue", "thing", "got",
    "get", "just", "now", "so", "but", "you", "your", "we", "our", "am", "im",
    "i'm", "ive", "i've", "tried", "try", "again.", "what", "why", "how",
}

# Tiny synonym groups so "login" matches "account", "charged" matches "billing"...
GROUPS = {
    "account": {"account", "login", "signin", "sign", "password", "access",
                "locked", "username", "credentials", "logged", "log"},
    "billing": {"billing", "payment", "charge", "charged", "refund", "invoice",
                "subscription", "price", "card", "paid", "bill"},
    "delivery": {"delivery", "shipping", "shipment", "order", "package",
                 "tracking", "courier", "arrived", "delayed"},
    "device": {"battery", "charging", "power", "screen", "device", "hardware",
               "overheating", "boot", "restart", "display"},
    "connectivity": {"wifi", "internet", "network", "connect", "connection",
                     "bluetooth", "pairing", "offline", "sync", "router"},
}

FOLLOWUP_CUES = ("still", "again", "same", "yet", "anymore", "already",
                 "update", "any news", "nothing", "not fixed", "came back")

# (suggestion, keywords that show it was already tried)
PLAYBOOKS = {
    "account": [
        ("reset your password with the 'Forgot password' link", ["reset", "password"]),
        ("clear your browser cache and cookies, or try a private/incognito window",
         ["cache", "cookie", "incognito", "private"]),
        ("confirm your email address is verified and the account isn't locked",
         ["verify", "verified", "locked", "unlock"]),
        ("try signing in from a different device or network", ["different device", "another device", "different network"]),
    ],
    "billing": [
        ("check the charge in your payment app and compare it with your invoice", ["invoice", "statement"]),
        ("confirm the payment method on file is valid and not expired", ["payment method", "expired", "card"]),
        ("allow 5-7 business days for refunds to post", ["refund", "business days"]),
    ],
    "delivery": [
        ("check the live tracking link in your confirmation email", ["tracking"]),
        ("confirm the delivery address and any building or gate instructions", ["address"]),
        ("ask neighbours or the front desk whether the parcel was left with them", ["neighbour", "neighbor", "front desk"]),
    ],
    "device": [
        ("do a full power cycle: switch off, unplug for 60 seconds, then restart", ["power cycle", "unplug", "restart"]),
        ("update to the latest firmware or app version", ["firmware", "update"]),
        ("try a different cable and wall adapter", ["cable", "adapter"]),
        ("perform a factory reset (back up your data first)", ["factory reset"]),
    ],
    "connectivity": [
        ("restart your router and the device", ["router", "restart"]),
        ("forget the network or device and pair it again", ["forget", "pair"]),
        ("move closer to the router and disable any VPN", ["vpn", "closer"]),
    ],
    "general": [
        ("restart the app or device and try again", ["restart"]),
        ("update to the latest version", ["update"]),
        ("send me a screenshot or the exact error message you see", ["screenshot", "error message"]),
    ],
}


# ------------------------------------------------------------------ ranking
def tokens(text):
    return set(re.findall(r"[a-z0-9']+", (text or "").lower())) - STOP


def expand(toks):
    out = set(toks)
    for group in GROUPS.values():
        if toks & group:
            out |= group
    return out


def entry_text(entry):
    issue = entry["issue"]
    parts = [issue.get("title"), issue.get("description"), issue.get("category")]
    if entry.get("product"):
        parts.append(entry["product"].get("name"))
    parts += [r.get("description") for r in entry.get("resolutions", [])]
    return " ".join(p for p in parts if p)


def is_followup(message):
    m = message.lower()
    return any(cue in m for cue in FOLLOWUP_CUES)


def rank_issues(message, issues):
    """Score each issue chain against the message. `issues` is newest-first."""
    query = expand(tokens(message))
    followup = is_followup(message)
    ranked = []
    for idx, entry in enumerate(issues):
        overlap = len(query & expand(tokens(entry_text(entry))))
        open_ = entry["issue"].get("status") in OPEN_STATUSES
        score = overlap * 2 + (3 if open_ else 0) + (2 if followup and open_ else 0)
        score += max(0.0, 1.0 - idx * 0.2)  # gentle recency boost
        ranked.append({**entry, "overlap": overlap, "score": round(score, 2)})
    ranked.sort(key=lambda e: e["score"], reverse=True)
    return ranked


def pick_primary(message, ranked):
    """The issue the customer is most likely talking about, or None."""
    if not ranked:
        return None
    if ranked[0]["overlap"] > 0:
        return ranked[0]
    if is_followup(message):
        for entry in ranked:
            if entry["issue"].get("status") in OPEN_STATUSES:
                return entry
    return None


# ------------------------------------------------------------ context text
def _date(value):
    return (value or "")[:10]


def format_context(customer, ctx, ranked, primary):
    lines = [f"CUSTOMER: {customer['name']} <{customer['email']}>"]
    products = ", ".join(p["name"] for p in ctx["products"]) or "none on record"
    lines.append(f"PRODUCTS OWNED: {products}")

    def describe(entry, detail):
        i, t, p = entry["issue"], entry.get("ticket") or {}, entry.get("product") or {}
        out = [
            f'- Issue "{i["title"]}" on {p.get("name", "unknown product")} '
            f'[{i["status"]}], reported {_date(i.get("createdAt"))}; '
            f'ticket {t.get("number", "n/a")} ({t.get("status", "n/a")}, '
            f'priority {t.get("priority", "n/a")})'
        ]
        if detail and i.get("description"):
            out.append(f"    Description: {i['description']}")
        for n, r in enumerate(entry.get("resolutions", []), 1):
            out.append(f"    Attempt {n} ({_date(r.get('createdAt'))}): "
                       f"{r['description']} -> {r['outcome']}")
        if detail and not entry.get("resolutions"):
            out.append("    No resolution attempts recorded yet")
        return "\n".join(out)

    if primary:
        lines.append("\nMOST RELEVANT TO THIS MESSAGE:")
        lines.append(describe(primary, detail=True))
    others = [e for e in ranked if e is not primary]
    if others:
        lines.append("\nOTHER HISTORY:")
        lines += [describe(e, detail=False) for e in others[:4]]
    if not ranked:
        lines.append("\nNo previous issues on record for this customer.")
    if ctx["past_conversations"]:
        lines.append("\nEARLIER CONVERSATIONS (most recent first):")
        for c in ctx["past_conversations"]:
            snippet = " | ".join(f"{m['role']}: {m['content'][:140]}" for m in c["recent"])
            lines.append(f"- {_date(c['startedAt'])}: {snippet}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are a customer support agent with access to this customer's \
support history, retrieved from a graph database. Use it.

Rules:
- Speak to the customer directly and warmly. Be concise (under 150 words).
- Start by showing you remember the relevant earlier issue, ticket status and what was already tried.
- NEVER ask the customer to repeat steps already listed as attempted.
- Suggest one or two NEW next steps. If three or more attempts have failed, or the ticket is \
already escalated, offer to escalate to a specialist.
- If the history does not cover the question, say so and ask for the product and details.
- Never invent history, ticket numbers or dates that are not in the context below.

SUPPORT HISTORY
{context}
"""


# ------------------------------------------------------------ reply builders
def classify(entry):
    cat = ((entry["issue"].get("category") or "")).lower()
    if cat in PLAYBOOKS:
        return cat
    doc = tokens(entry_text(entry))
    best, best_n = "general", 0
    for name, group in GROUPS.items():
        n = len(doc & group)
        if n > best_n:
            best, best_n = name, n
    return best


def next_steps(entry):
    tried = " ".join(r["description"].lower() for r in entry.get("resolutions", []))
    return [s for s, kws in PLAYBOOKS[classify(entry)]
            if not any(k in tried for k in kws)]


def fallback_reply(customer, ctx, ranked, primary):
    first = customer["name"].split()[0]
    if primary is None:
        open_entries = [e for e in ranked if e["issue"]["status"] in OPEN_STATUSES]
        if open_entries:
            bits = "; ".join(
                f'"{e["issue"]["title"]}" (ticket {e["ticket"]["number"]}, {e["ticket"]["status"]})'
                for e in open_entries[:3])
            return (f"Hi {first}! I can see you have open request(s): {bits}. "
                    "Is your question about one of these, or something new? "
                    "If it's new, tell me the product and what's happening.")
        return (f"Hi {first}! I don't see any earlier issues on your account. "
                "Which product is this about, and what exactly is happening?")

    issue, ticket = primary["issue"], primary.get("ticket") or {}
    product = (primary.get("product") or {}).get("name", "your product")
    attempts = primary.get("resolutions", [])
    head = (f'Hi {first}, thanks for following up. I can see your earlier issue '
            f'"{issue["title"]}" with {product} (ticket {ticket.get("number")}, '
            f'currently {issue["status"].replace("_", " ")}), reported {_date(issue.get("createdAt"))}.')

    if issue["status"] == "resolved":
        worked = [r for r in attempts if r["outcome"] == "worked"]
        fix = f' It was resolved by: {worked[-1]["description"]}.' if worked else ""
        return (head + fix + " It sounds like the problem may have come back. "
                "What are you seeing now? I'll reopen the ticket so we keep the full history.")

    parts = [head]
    if attempts:
        parts.append("So far we've tried:")
        parts += [f"  {n}. {r['description']} ({r['outcome']})" for n, r in enumerate(attempts, 1)]
        parts.append("I won't ask you to repeat those.")
    else:
        parts.append("No troubleshooting steps are recorded yet.")

    failed = sum(1 for r in attempts if r["outcome"] == "failed")
    steps = next_steps(primary)
    if failed >= 3 or ticket.get("status") == "escalated" or not steps:
        parts.append("Since the basics haven't solved it, I recommend escalating this ticket "
                     "to a specialist who can see the full history. Shall I do that?")
    else:
        parts.append(f"Next, please {steps[0]}.")
        if len(steps) > 1:
            parts.append(f"If that doesn't help, we can also {steps[1]}.")
    return "\n".join(parts)


def llm_reply(system, messages):
    import anthropic  # imported lazily so the app runs without the package/key

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        max_tokens=600,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def generate_reply(customer, history, ctx, ranked, primary):
    """Returns (reply_text, mode). Falls back if the LLM is unavailable."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            system = SYSTEM_PROMPT.format(context=format_context(customer, ctx, ranked, primary))
            messages = [{"role": m["role"], "content": m["content"]} for m in history]
            text = llm_reply(system, messages)
            if text:
                return text, "llm"
        except Exception as exc:  # network, auth, quota... never break the chat
            print(f"[agent] LLM failed, using rule-based reply: {exc}")
    return fallback_reply(customer, ctx, ranked, primary), "rule-based"
