#!/usr/bin/env python3
"""A throwaway Render-Deploy-Hook stand-in, so the deploy path can be tested offline.

It exists because the real hook URL is a credential that is not in this
environment, and an untested deploy script is worse than none: it is a script
that will fail for the first time during a real release. This stub accepts a POST
exactly like Render's hook does and records it, so
``scripts/render_deploy.py --hook-url http://127.0.0.1:9099/hook`` can be run end
to end and observed to do the right thing.

It is a test fixture, not part of the product. It is never referenced by
``render.yaml`` and never runs in a deployment.

    python scripts/mock_deploy_hook.py --port 9099
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class _HookHandler(BaseHTTPRequestHandler):
    """Accept POSTs as a deploy trigger; report them on GET."""

    triggers = 0
    #: The status the POST answers with. 202 mirrors the live Render hook, which
    #: accepts the trigger without claiming the build succeeded.
    status_code = 202

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).triggers += 1
        body = json.dumps({"deploy": {"id": f"mock-{self.triggers}", "status": "created"}}).encode()
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"mock hook: deploy triggered (#{self.triggers})", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"triggers": type(self).triggers}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        """Silence the default per-request access log; the trigger line is enough."""
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Stand-in Render Deploy Hook for offline testing.")
    parser.add_argument("--port", type=int, default=9099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--status", type=int, default=202, help="Status the hook answers with; 202 mirrors Render.")
    args = parser.parse_args()
    _HookHandler.status_code = args.status

    server = HTTPServer((args.host, args.port), _HookHandler)
    print(f"mock deploy hook listening on http://{args.host}:{args.port}/hook", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
