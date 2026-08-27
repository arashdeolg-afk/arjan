"""CLI: serve the app (default) or seed demo projects.

    PYTHONPATH=src python3 -m forge            # serve on 127.0.0.1:8484
    PYTHONPATH=src python3 -m forge demo       # create sample projects
    PYTHONPATH=src python3 -m forge serve --port 9000 --open

Data lives in FORGE_DATA (default: data/forge, gitignored like the rest
of this repo's local data).
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from . import __version__, templates
from .runner import Runner
from .server import make_server
from .store import Store

DEFAULT_PORT = 8484


def default_data_dir() -> str:
    return os.environ.get("FORGE_DATA", os.path.join("data", "forge"))


def cmd_demo(args) -> int:
    store = Store(args.data)
    existing = {m["name"] for m in store.list_projects()}
    made = []
    for name, template in templates.DEMO_PROJECTS:
        if name in existing:
            continue
        meta = store.create(name, template)
        made.append(meta)
    if made:
        print("Created sample projects:")
        for meta in made:
            print(f"  {meta['name']:<16} ({meta['template']})  -> {meta['id']}")
    else:
        print("Sample projects already exist — nothing to do.")
    print(f"\nStart the app:  PYTHONPATH=src python3 -m forge serve")
    return 0


def cmd_serve(args) -> int:
    store = Store(args.data)
    runner = Runner()
    try:
        httpd = make_server(args.host, args.port, store, runner)
    except OSError as e:
        print(f"could not bind {args.host}:{args.port} — {e}", file=sys.stderr)
        print("try another port:  python3 -m forge serve --port 8642",
              file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}"
    key_state = "found" if os.environ.get("ANTHROPIC_API_KEY") or \
        store.get_settings().get("anthropic_api_key") else "not set (AI pane off)"
    print(f"""
  ┌─────────────────────────────────────────────┐
  │  forge {__version__} — build websites & apps         │
  │                                             │
  │  app      {url:<34}│
  │  data     {args.data:<34}│
  │  ai key   {key_state:<34}│
  │                                             │
  │  ctrl-c to stop                             │
  └─────────────────────────────────────────────┘
""")
    if args.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        runner.stop_all()
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge", description="Build websites and apps in your browser.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="start the app (default)")
    serve.add_argument("--host", default=os.environ.get("FORGE_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int,
                       default=int(os.environ.get("FORGE_PORT", DEFAULT_PORT)))
    serve.add_argument("--data", default=default_data_dir())
    serve.add_argument("--open", action="store_true",
                       help="open the app in your browser")

    demo = sub.add_parser("demo", help="seed sample projects")
    demo.add_argument("--data", default=default_data_dir())

    args = parser.parse_args(argv)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command is None:
        args = serve.parse_args([])
    return cmd_serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
