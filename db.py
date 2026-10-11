# """Thin Neo4j wrapper: one shared driver, read/write helpers, schema setup."""
# import os

# from dotenv import load_dotenv
# from neo4j import GraphDatabase

# load_dotenv()

# _driver = None


# def get_driver():
#     global _driver
#     if _driver is None:
#         _driver = GraphDatabase.driver(
#             os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
#             auth=(
#                 os.environ.get("NEO4J_USERNAME", "neo4j"),
#                 os.environ.get("NEO4J_PASSWORD", ""),
#             ),
#         )
#     return _driver


import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH, override=True, encoding="utf-8-sig")

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI")
        if not uri:
            raise RuntimeError(
                f"NEO4J_URI is not set. Expected a .env file at: {ENV_PATH} "
                f"(exists: {ENV_PATH.exists()})"
            )
        print(f"[db] connecting to {uri}")
        _driver = GraphDatabase.driver(
            uri,
            auth=(
                os.environ.get("NEO4J_USERNAME", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", ""),
            ),
        )
    return _driver

def _database():
    return os.environ.get("NEO4J_DATABASE", "neo4j")


def run_read(query, **params):
    with get_driver().session(database=_database()) as session:
        return session.execute_read(
            lambda tx: [r.data() for r in tx.run(query, **params)]
        )


def run_write(query, **params):
    with get_driver().session(database=_database()) as session:
        return session.execute_write(
            lambda tx: [r.data() for r in tx.run(query, **params)]
        )


SCHEMA = [
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (n:Customer) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT customer_email IF NOT EXISTS FOR (n:Customer) REQUIRE n.email IS UNIQUE",
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (n:Product) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT product_name IF NOT EXISTS FOR (n:Product) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT issue_id IF NOT EXISTS FOR (n:Issue) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ticket_id IF NOT EXISTS FOR (n:Ticket) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT resolution_id IF NOT EXISTS FOR (n:Resolution) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (n:Conversation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT message_id IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX issue_status IF NOT EXISTS FOR (n:Issue) ON (n.status)",
    "CREATE INDEX ticket_status IF NOT EXISTS FOR (n:Ticket) ON (n.status)",
]


def init_schema():
    for statement in SCHEMA:
        run_write(statement)


def verify():
    get_driver().verify_connectivity()


def close():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
