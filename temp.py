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