# Context-Aware Customer Support Agent (Flask + Neo4j)

An AI support agent that **remembers** each customer's products, issues, tickets and attempted
resolutions in a Neo4j graph, and uses that memory to answer follow-ups like
*"My account still isn't working"* without asking the customer to start over.

## Graph model

```
(Customer)-[:OWNS]->(Product)
(Customer)-[:REPORTED]->(Issue)-[:ABOUT]->(Product)
(Issue)-[:TRACKED_BY]->(Ticket)-[:ATTEMPTED]->(Resolution)
(Customer)-[:HAD]->(Conversation)-[:CONTAINS]->(Message)
(Conversation)-[:DISCUSSED]->(Issue)
```

Core chain from the problem statement: **Customer → Product → Issue → Ticket → Resolution**.
Conversations and messages are stored too, so the agent also remembers earlier chats.

## How the agent works

```
message ─► store in graph ─► retrieve customer's issue chains (1 Cypher query)
        ─► rank by relevance (keyword + synonym overlap, open status, follow-up cues, recency)
        ─► pick the most relevant issue
        ─► reply:  Claude (if ANTHROPIC_API_KEY set)  OR  rule-based fallback
        ─► store reply, link conversation to the issue
```

Both reply modes use the same retrieved context, and both are told to: recall the earlier issue and
ticket status, never repeat steps already attempted, suggest new steps, and escalate after 3 failures.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # set NEO4J_PASSWORD (+ optional ANTHROPIC_API_KEY)
docker compose up -d neo4j                            # skip if your Neo4j is already running
python app.py                                         # http://localhost:5000
```

If you already have a Neo4j container from earlier, reuse it and just put its password in `.env`.

## Minimum demo

**In the browser** (`http://localhost:5000`):
1. Click **Load demo data** (or create a customer + product yourself).
2. **Report an issue** -> stored as Issue + Ticket in Neo4j. Add **attempted steps** under the ticket.
3. Click **Start new conversation** and send *"My account still isn't working"*.
4. The reply recalls the earlier issue, ticket status and failed steps. The **Memory** panel shows the
   Customer → Product → Issue → Ticket → Resolution chain that was retrieved.

**From the terminal:** `python demo.py` runs the same 4 steps and prints the retrieved history.

Open `http://localhost:7474` and run `MATCH p=(:Customer)-[*1..4]->() RETURN p LIMIT 50` to see the graph.

## API

| Method | Path | Body |
|---|---|---|
| POST | /api/customers | `{name, email}` |
| GET | /api/customers | |
| POST | /api/customers/:id/products | `{name, category?}` |
| GET | /api/customers/:id/history | full issue chains + past conversations |
| POST | /api/issues | `{customer_id, product_id, title, description?, priority?, category?}` creates Issue + Ticket |
| POST | /api/tickets/:id/resolutions | `{description, outcome: failed|worked|pending}` |
| PATCH | /api/tickets/:id | `{status: open|in_progress|escalated|resolved|closed}` |
| POST | /api/chat | `{customer_id, message, conversation_id?}` omit `conversation_id` to start a new conversation |
| POST | /api/demo/seed | loads the demo customer |
| GET | /api/health | |

## Tests

```bash
python -m unittest discover -s tests -v
```

Covers relevance ranking, reply content (recall, no repeated steps, escalation, reopen), the chat flow
and API error handling. They use a stubbed graph layer, so no database is needed.

## Files

| File | Role |
|---|---|
| `app.py` | Flask routes and error handling |
| `graph_repo.py` | All Cypher queries and the graph model |
| `agent.py` | Relevance ranking, context formatting, Claude + fallback replies |
| `chat.py` | Remember -> retrieve -> answer -> remember |
| `db.py` | Neo4j driver and schema (constraints/indexes) |
| `seed.py`, `demo.py` | Demo data and terminal demo |
| `templates/index.html` | Demo UI |

## Ideas to extend

- Vector embeddings on Issue/Resolution text for semantic matching (Neo4j vector index).
- Let Claude call tools (create issue, log attempt) instead of using forms.
- Connect the Neo4j MCP server so Claude Desktop can query the same graph directly.
- Auth, per-agent assignment, SLA timers on tickets.
