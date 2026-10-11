"""All Cypher lives here.

Graph model
-----------
(Customer)-[:OWNS]->(Product)
(Customer)-[:REPORTED]->(Issue)-[:ABOUT]->(Product)
(Issue)-[:TRACKED_BY]->(Ticket)-[:ATTEMPTED]->(Resolution)
(Customer)-[:HAD]->(Conversation)-[:CONTAINS]->(Message)
(Conversation)-[:DISCUSSED]->(Issue)
"""
import uuid
from datetime import datetime, timezone

from db import run_read, run_write
from errors import BadRequest, NotFound

PRIORITIES = {"low", "medium", "high", "urgent"}
OUTCOMES = {"failed", "worked", "pending"}
TICKET_STATUSES = {"open", "in_progress", "escalated", "resolved", "closed"}


def _id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ---------------------------------------------------------------- customers
def create_customer(name, email):
    rows = run_write(
        """
        CREATE (c:Customer {id: $id, name: $name, email: $email, createdAt: $now})
        RETURN c{.*} AS customer
        """,
        id=_id("cus"), name=name.strip(), email=email.strip().lower(), now=_now(),
    )
    return rows[0]["customer"]


def list_customers():
    rows = run_read(
        "MATCH (c:Customer) RETURN c{.*} AS customer ORDER BY c.createdAt DESC"
    )
    return [r["customer"] for r in rows]


def get_customer(customer_id):
    rows = run_read(
        "MATCH (c:Customer {id: $id}) RETURN c{.*} AS customer", id=customer_id
    )
    if not rows:
        raise NotFound("Customer not found")
    return rows[0]["customer"]


def find_customer_by_email(email):
    rows = run_read(
        "MATCH (c:Customer {email: $email}) RETURN c{.*} AS customer",
        email=email.strip().lower(),
    )
    return rows[0]["customer"] if rows else None


# ----------------------------------------------------------------- products
def add_product_to_customer(customer_id, name, category=None):
    rows = run_write(
        """
        MATCH (c:Customer {id: $cid})
        MERGE (p:Product {name: $name})
          ON CREATE SET p.id = $pid, p.category = $category, p.createdAt = $now
        MERGE (c)-[o:OWNS]->(p)
          ON CREATE SET o.since = $now
        RETURN p{.*} AS product
        """,
        cid=customer_id, name=name.strip(), pid=_id("prd"),
        category=(category or "").strip() or None, now=_now(),
    )
    if not rows:
        raise NotFound("Customer not found")
    return rows[0]["product"]


def list_customer_products(customer_id):
    rows = run_read(
        """
        MATCH (:Customer {id: $cid})-[:OWNS]->(p:Product)
        RETURN p{.*} AS product ORDER BY p.name
        """,
        cid=customer_id,
    )
    return [r["product"] for r in rows]


# ------------------------------------------------- issues, tickets, attempts
def create_issue(customer_id, product_id, title, description="", priority="medium",
                 category=None):
    if priority not in PRIORITIES:
        raise BadRequest(f"priority must be one of {sorted(PRIORITIES)}")
    now = _now()
    rows = run_write(
        """
        MATCH (c:Customer {id: $cid}), (p:Product {id: $pid})
        MERGE (c)-[:OWNS]->(p)
        CREATE (i:Issue {id: $iid, title: $title, description: $description,
                         category: $category, status: 'open',
                         createdAt: $now, updatedAt: $now})
        CREATE (t:Ticket {id: $tid, number: $number, status: 'open',
                          priority: $priority, createdAt: $now, updatedAt: $now})
        CREATE (c)-[:REPORTED]->(i)
        CREATE (i)-[:ABOUT]->(p)
        CREATE (i)-[:TRACKED_BY]->(t)
        RETURN i{.*} AS issue, t{.*} AS ticket, p{.*} AS product
        """,
        cid=customer_id, pid=product_id, iid=_id("iss"), tid=_id("tkt"),
        number="TCK-" + uuid.uuid4().hex[:6].upper(),
        title=title.strip(), description=(description or "").strip(),
        category=(category or "").strip() or None, priority=priority, now=now,
    )
    if not rows:
        raise NotFound("Customer or product not found")
    return rows[0]


def add_resolution(ticket_id, description, outcome="failed"):
    """Record an attempted resolution and move the ticket/issue status along."""
    if outcome not in OUTCOMES:
        raise BadRequest(f"outcome must be one of {sorted(OUTCOMES)}")
    now = _now()
    rows = run_write(
        """
        MATCH (t:Ticket {id: $tid})<-[:TRACKED_BY]-(i:Issue)
        CREATE (r:Resolution {id: $rid, description: $description,
                              outcome: $outcome, createdAt: $now})
        CREATE (t)-[:ATTEMPTED]->(r)
        WITH t, i, r,
             CASE WHEN $outcome = 'worked' THEN 'resolved'
                  WHEN t.status IN ['open', 'resolved', 'closed'] THEN 'in_progress'
                  ELSE t.status END AS newStatus
        SET t.status = newStatus, i.status = newStatus,
            t.updatedAt = $now, i.updatedAt = $now
        RETURN r{.*} AS resolution, newStatus AS ticketStatus
        """,
        tid=ticket_id, rid=_id("res"), description=description.strip(),
        outcome=outcome, now=now,
    )
    if not rows:
        raise NotFound("Ticket not found")
    return rows[0]


def set_ticket_status(ticket_id, status):
    if status not in TICKET_STATUSES:
        raise BadRequest(f"status must be one of {sorted(TICKET_STATUSES)}")
    rows = run_write(
        """
        MATCH (t:Ticket {id: $tid})<-[:TRACKED_BY]-(i:Issue)
        SET t.status = $status,
            i.status = CASE WHEN $status = 'closed' THEN 'resolved' ELSE $status END,
            t.updatedAt = $now, i.updatedAt = $now
        RETURN t{.*} AS ticket
        """,
        tid=ticket_id, status=status, now=_now(),
    )
    if not rows:
        raise NotFound("Ticket not found")
    return rows[0]["ticket"]


# ------------------------------------------------------------ conversations
def start_conversation(customer_id):
    rows = run_write(
        """
        MATCH (c:Customer {id: $cid})
        CREATE (v:Conversation {id: $vid, startedAt: $now})
        CREATE (c)-[:HAD]->(v)
        RETURN v{.*} AS conversation
        """,
        cid=customer_id, vid=_id("cnv"), now=_now(),
    )
    if not rows:
        raise NotFound("Customer not found")
    return rows[0]["conversation"]


def assert_conversation(customer_id, conversation_id):
    rows = run_read(
        """
        MATCH (:Customer {id: $cid})-[:HAD]->(v:Conversation {id: $vid})
        RETURN v.id AS id
        """,
        cid=customer_id, vid=conversation_id,
    )
    if not rows:
        raise NotFound("Conversation not found for this customer")


def add_message(conversation_id, role, content):
    rows = run_write(
        """
        MATCH (v:Conversation {id: $vid})
        CREATE (m:Message {id: $mid, role: $role, content: $content, createdAt: $now})
        CREATE (v)-[:CONTAINS]->(m)
        RETURN m{.*} AS message
        """,
        vid=conversation_id, mid=_id("msg"), role=role, content=content, now=_now(),
    )
    if not rows:
        raise NotFound("Conversation not found")
    return rows[0]["message"]


def get_messages(conversation_id):
    rows = run_read(
        """
        MATCH (:Conversation {id: $vid})-[:CONTAINS]->(m:Message)
        RETURN m{.role, .content, .createdAt} AS message
        ORDER BY m.createdAt
        """,
        vid=conversation_id,
    )
    return [r["message"] for r in rows]


def link_conversation_issue(conversation_id, issue_id):
    run_write(
        """
        MATCH (v:Conversation {id: $vid}), (i:Issue {id: $iid})
        MERGE (v)-[:DISCUSSED]->(i)
        """,
        vid=conversation_id, iid=issue_id,
    )


# ------------------------------------------------------------------ context
def get_customer_context(customer_id, exclude_conversation_id=None, past_limit=3):
    """Everything the agent may need: products, full issue chains, past chats."""
    issues = run_read(
        """
        MATCH (:Customer {id: $cid})-[:REPORTED]->(i:Issue)
        OPTIONAL MATCH (i)-[:ABOUT]->(p:Product)
        OPTIONAL MATCH (i)-[:TRACKED_BY]->(t:Ticket)
        OPTIONAL MATCH (t)-[:ATTEMPTED]->(r:Resolution)
        WITH i, p, t, r ORDER BY r.createdAt
        WITH i, p, t, collect(r{.*}) AS resolutions
        RETURN i{.*} AS issue, p{.*} AS product, t{.*} AS ticket, resolutions
        ORDER BY i.createdAt DESC
        """,
        cid=customer_id,
    )
    past = run_read(
        """
        MATCH (:Customer {id: $cid})-[:HAD]->(v:Conversation)
        WHERE v.id <> $exclude
        MATCH (v)-[:CONTAINS]->(m:Message)
        WITH v, m ORDER BY m.createdAt
        WITH v, collect(m{.role, .content, .createdAt}) AS msgs
        ORDER BY v.startedAt DESC LIMIT $limit
        RETURN v.id AS id, v.startedAt AS startedAt, msgs[-4..] AS recent
        """,
        cid=customer_id, exclude=exclude_conversation_id or "", limit=past_limit,
    )
    return {
        "products": list_customer_products(customer_id),
        "issues": issues,
        "past_conversations": past,
    }
