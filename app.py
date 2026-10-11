import logging
import os

from flask import Flask, jsonify, render_template, request
from neo4j.exceptions import ConstraintError, ServiceUnavailable

import chat
import db
import graph_repo as repo
import seed
from errors import BadRequest, NotFound

log = logging.getLogger("support-agent")


def body(*required):
    data = request.get_json(silent=True) or {}
    missing = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise BadRequest(f"Missing field(s): {', '.join(missing)}")
    return data


def create_app():
    app = Flask(__name__)

    try:
        db.verify()
        db.init_schema()
    except Exception as exc:
        raise RuntimeError(
            "Could not connect to Neo4j. Check NEO4J_* in .env and that the "
            f"database is running. ({exc})"
        ) from exc

    # ----------------------------------------------------------- errors
    @app.errorhandler(BadRequest)
    def _bad(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(NotFound)
    def _nf(e):
        return jsonify(error=str(e)), 404

    @app.errorhandler(ConstraintError)
    def _conflict(e):
        return jsonify(error="A record with that unique value already exists"), 409

    @app.errorhandler(ServiceUnavailable)
    def _down(e):
        return jsonify(error="Neo4j is unavailable"), 503

    @app.errorhandler(Exception)
    def _boom(e):
        log.exception("Unhandled error")
        return jsonify(error="Internal server error"), 500

    # ------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        db.verify()
        return jsonify(status="ok", llm=bool(os.environ.get("ANTHROPIC_API_KEY")))

    # -------------------------------------------------------- customers
    @app.post("/api/customers")
    def create_customer():
        d = body("name", "email")
        return jsonify(repo.create_customer(d["name"], d["email"])), 201

    @app.get("/api/customers")
    def list_customers():
        return jsonify(repo.list_customers())

    @app.post("/api/customers/<cid>/products")
    def add_product(cid):
        d = body("name")
        return jsonify(repo.add_product_to_customer(cid, d["name"], d.get("category"))), 201

    @app.get("/api/customers/<cid>/history")
    def history(cid):
        customer = repo.get_customer(cid)
        ctx = repo.get_customer_context(cid)
        return jsonify(customer=customer, **ctx)

    # ---------------------------------------------- issues and tickets
    @app.post("/api/issues")
    def create_issue():
        d = body("customer_id", "product_id", "title")
        result = repo.create_issue(
            d["customer_id"], d["product_id"], d["title"],
            d.get("description", ""), d.get("priority", "medium"), d.get("category"))
        return jsonify(result), 201

    @app.post("/api/tickets/<tid>/resolutions")
    def add_resolution(tid):
        d = body("description")
        return jsonify(repo.add_resolution(tid, d["description"], d.get("outcome", "failed"))), 201

    @app.patch("/api/tickets/<tid>")
    def update_ticket(tid):
        d = body("status")
        return jsonify(repo.set_ticket_status(tid, d["status"]))

    # ------------------------------------------------------------- chat
    @app.post("/api/chat")
    def chat_endpoint():
        d = body("customer_id", "message")
        return jsonify(chat.handle_chat(d["customer_id"], d["message"], d.get("conversation_id")))

    # ------------------------------------------------------------- demo
    @app.post("/api/demo/seed")
    def demo_seed():
        customer, created = seed.seed_demo()
        return jsonify(customer=customer, created=created)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="0.0.0.0", port=int(os.environ.get("FLASK_PORT", 5000)), debug=True)
