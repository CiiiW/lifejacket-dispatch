"""Serve only the isolated, fictional component-test bundle on loopback.

The app entry point never imports the fixture. This server has no API, managed
auth, application imports, database access, permissions or notifications.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8920)
    args = parser.parse_args()
    if not (args.web_dir / "index.html").is_file():
        parser.error("Build the separate fictional component fixture first")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), partial(NoCacheHandler, directory=str(args.web_dir))
    )
    print("Fictional component fixture only; no API or real sign-in.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
