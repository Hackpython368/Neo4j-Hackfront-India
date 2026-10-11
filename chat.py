"""Chat orchestration: remember -> retrieve -> answer -> remember."""
import agent
import graph_repo as repo
from errors import BadRequest


def _summary(entry):
    return {
        "issue_id": entry["issue"]["id"],
        "title": entry["issue"]["title"],
        "status": entry["issue"]["status"],
        "score": entry["score"],
    }


def handle_chat(customer_id, message, conversation_id=None):
    message = (message or "").strip()
    if not message:
        raise BadRequest("message is required")

    customer = repo.get_customer(customer_id)

    new_conversation = conversation_id is None
    if new_conversation:
        conversation_id = repo.start_conversation(customer_id)["id"]
    else:
        repo.assert_conversation(customer_id, conversation_id)

    repo.add_message(conversation_id, "user", message)

    # Retrieve this customer's history from the graph and rank it for this message.
    ctx = repo.get_customer_context(customer_id, exclude_conversation_id=conversation_id)
    ranked = agent.rank_issues(message, ctx["issues"])
    primary = agent.pick_primary(message, ranked)

    history = repo.get_messages(conversation_id)
    reply, mode = agent.generate_reply(customer, history, ctx, ranked, primary)

    repo.add_message(conversation_id, "assistant", reply)
    if primary:
        repo.link_conversation_issue(conversation_id, primary["issue"]["id"])

    return {
        "conversation_id": conversation_id,
        "new_conversation": new_conversation,
        "reply": reply,
        "mode": mode,
        "context_used": {
            "customer": customer,
            "primary": primary,
            "ranked": [_summary(e) for e in ranked[:5]],
            "products": ctx["products"],
            "past_conversations": len(ctx["past_conversations"]),
        },
    }
