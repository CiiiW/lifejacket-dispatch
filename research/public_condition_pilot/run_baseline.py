"""Run or serve the isolated image-only development baseline."""

import argparse
import json
from pathlib import Path

from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.research.condition_baseline import PILOT, BaselineStore


def scripted_client():
    client = ScriptedLLMClient.scenario("sea_lion")
    client.queue(
        "detection",
        {"animals": [{"box": [50, 50, 950, 950], "description": "Scripted test target"}]},
    )
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=PILOT)
    parser.add_argument("--run-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--live", action="store_true", help="Call configured Vertex model on original photos"
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Scripted orchestration check; no accuracy measurement",
    )
    parser.add_argument("--resume", action="store_true", help="Skip saved nonfailed attempts")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve private review app instead of running batch",
    )
    parser.add_argument("--port", type=int, default=8813)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    store = BaselineStore(
        args.collection,
        args.run_dir,
        scripted=args.dry_run,
        client_factory=scripted_client if args.dry_run else None,
    )
    if args.serve:
        import uvicorn
        from lifejacket.research.review_app import create_app

        uvicorn.run(create_app(store), host="127.0.0.1", port=args.port)
        return
    for key in list(store.rows)[: args.limit]:
        result = store.analyze(key, resume=args.resume)
        print(
            json.dumps(
                {
                    "case_id": key,
                    "status": result["status"],
                    "seconds": result["latency_seconds"],
                    "error": result.get("error"),
                }
            ),
            flush=True,
        )
    print(json.dumps(store.summary(), indent=2), flush=True)


if __name__ == "__main__":
    main()
