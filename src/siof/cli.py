from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .deslopper import DeSlopper
from .green_guard import GreenGuard
from .indexer import PythonIndexer
from .mcp_server import MCPGraphServer
from .memex import Memex

logger = logging.getLogger(__name__)


def _db_path(value: str | None) -> Path:
    if value:
        return Path(value)
    return Path(".siof/siof.db")


def cmd_index(args: argparse.Namespace) -> int:
    idx = PythonIndexer(repo=Path(args.repo), db_path=_db_path(args.db))
    idx.init()
    try:
        if args.index_command == "build":
            # Build with progress tracking
            print("Starting full index build...", file=sys.stderr)
            result = idx.build()
            print(f"✓ Discovered {result['files']} files", file=sys.stderr)
            print(
                f"✓ Parsed {result['artifacts']} artifacts ({result['parse_errors']} errors)",
                file=sys.stderr,
            )
            print(f"✓ Built {result['nodes']} nodes and {result['edges']} edges", file=sys.stderr)
            print(f"✓ Extracted {result['dependency_seeds']} dependency seeds", file=sys.stderr)
            print(json.dumps(result, indent=2))
        elif args.index_command == "update":
            changed = [Path(p) for p in (args.changed_files or [])]
            print(f"Updating index for {len(changed)} changed files...", file=sys.stderr)
            result = idx.update(changed)
            print(
                f"✓ Update complete: {result['nodes']} nodes, {result['edges']} edges",
                file=sys.stderr,
            )
            print(json.dumps(result, indent=2))
        elif args.index_command == "verify":
            print("Verifying graph integrity...", file=sys.stderr)
            result = idx.verify()
            print(
                f"✓ Verification complete: {result['dead_nodes']} dead nodes found", file=sys.stderr
            )
            print(json.dumps(result, indent=2))
    finally:
        idx.close()
    return 0


def cmd_slop(args: argparse.Namespace) -> int:
    d = DeSlopper(repo=Path(args.repo), db_path=_db_path(args.db))
    try:
        result = d.run(mode=args.slop_command)
        print(
            json.dumps(
                {
                    "findings": len(result.findings),
                    "files_changed": result.files_changed,
                },
                indent=2,
            )
        )
        return 1 if args.slop_command == "strict" and result.findings else 0
    finally:
        d.close()


def cmd_mcp(args: argparse.Namespace) -> int:
    server = MCPGraphServer(db_path=_db_path(args.db))
    try:
        if args.mcp_command == "serve":
            server.serve_stdio()
    finally:
        server.close()
    return 0


def cmd_memex(args: argparse.Namespace) -> int:
    m = Memex(repo=Path(args.repo), db_path=_db_path(args.db))
    try:
        if args.memex_command == "ingest":
            print(json.dumps(m.ingest(), indent=2))
        elif args.memex_command == "query":
            print(json.dumps(m.query(args.text), indent=2))
    finally:
        m.close()
    return 0


def cmd_green(args: argparse.Namespace) -> int:
    g = GreenGuard(db_path=_db_path(args.db))
    try:
        if args.green_command == "run":
            if not args.command:
                raise SystemExit("missing command after --")
            result = g.run_command(args.command, hard_co2_kg=args.hard_co2)
            print(json.dumps(result, indent=2))
            return 0 if result["returncode"] == 0 else result["returncode"]
        elif args.green_command == "report":
            print(json.dumps(g.report(args.run_id), indent=2))
    finally:
        g.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="siof")
    parser.add_argument("--db", default=".siof/siof.db")

    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index")
    p_index.add_argument("--repo", default=".")
    s_index = p_index.add_subparsers(dest="index_command", required=True)
    s_index.add_parser("build")
    p_up = s_index.add_parser("update")
    p_up.add_argument("changed_files", nargs="*")
    s_index.add_parser("verify")
    p_index.set_defaults(func=cmd_index)

    p_slop = sub.add_parser("slop")
    p_slop.add_argument("--repo", default=".")
    s_slop = p_slop.add_subparsers(dest="slop_command", required=True)
    s_slop.add_parser("audit")
    s_slop.add_parser("fix")
    s_slop.add_parser("strict")
    p_slop.set_defaults(func=cmd_slop)

    p_mcp = sub.add_parser("mcp")
    s_mcp = p_mcp.add_subparsers(dest="mcp_command", required=True)
    s_mcp.add_parser("serve")
    p_mcp.set_defaults(func=cmd_mcp)

    p_memex = sub.add_parser("memex")
    p_memex.add_argument("--repo", default=".")
    s_memex = p_memex.add_subparsers(dest="memex_command", required=True)
    s_memex.add_parser("ingest")
    p_q = s_memex.add_parser("query")
    p_q.add_argument("text")
    p_memex.set_defaults(func=cmd_memex)

    p_green = sub.add_parser("green")
    s_green = p_green.add_subparsers(dest="green_command", required=True)
    p_gr = s_green.add_parser("run")
    p_gr.add_argument("--hard-co2", type=float, default=None)
    p_gr.add_argument("command", nargs=argparse.REMAINDER)
    p_gp = s_green.add_parser("report")
    p_gp.add_argument("run_id")
    p_green.set_defaults(func=cmd_green)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"SIOF starting with command: {args.command}")
    result = args.func(args)
    return int(result) if result is not None else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
