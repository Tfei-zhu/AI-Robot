"""Loopback-only S6 browser harness: real API/graph/store, fixed role models.

--docker also uses the real fixed Docker validator. Uvicorn lifespan is off so
production ingestion, Embedding and AMQP are never started by this test harness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from multi_agent_dashboard_fixtures import configure, service, LEGACY
import app.main as main
from app.go_validation.store import GoTaskStore
from contextlib import aclosing
import uvicorn


def create_app(db, *, docker=False):
    configure()
    store = GoTaskStore(str(db))
    # Preserve an actual historical JSON row, without new-model serialization.
    conn = store._db()
    conn.execute("INSERT OR REPLACE INTO go_tasks VALUES (?, ?, ?)",
                 (LEGACY["run_id"], hashlib.sha256(b"admin").hexdigest(), json.dumps(LEGACY)))
    conn.commit()

    class PerRequestDependencies:
        async def run(self, request, principal, session_key):
            from app.go_validation.contracts import GoTaskResult
            async with aclosing(self.stream(request, principal, session_key)) as events:
                async for event in events:
                    if event["type"] == "go_done":
                        return GoTaskResult.model_validate(event["result"])
            raise RuntimeError("test backend did not finish")

        async def stream(self, request, principal, session_key):
            case = "repair" if "[repair]" in request.requirement else "failed" if "[failed]" in request.requirement else "cancel" if "[cancel]" in request.requirement else "passed"
            actual = service(store, case, docker=docker)
            async with aclosing(actual.stream(request, principal, session_key)) as events:
                async for event in events:
                    yield event

    main.go_service, main.go_store = PerRequestDependencies(), store
    return main.app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--docker", action="store_true")
    args = parser.parse_args()
    uvicorn.run(create_app(args.db, docker=args.docker), host="127.0.0.1", port=args.port,
                lifespan="off", log_level="warning")
