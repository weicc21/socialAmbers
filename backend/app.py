from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request


def create_app() -> Flask:
    app = Flask(__name__)
    messages: list[dict[str, Any]] = []
    messages_lock = Lock()

    @app.get("/api/health")
    def health() -> tuple[Any, int]:
        return jsonify({"status": "ok", "service": "socialambers-api"}), 200

    @app.get("/api/messages")
    def list_messages() -> tuple[Any, int]:
        with messages_lock:
            return jsonify({"messages": list(reversed(messages))}), 200

    @app.post("/api/messages")
    def create_message() -> tuple[Any, int]:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"error": "text is required"}), 400

        with messages_lock:
            message = {
                "id": len(messages) + 1,
                "text": text,
                "created_at": datetime.now(UTC).isoformat(),
            }
            messages.append(message)
        return jsonify(message), 201

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
