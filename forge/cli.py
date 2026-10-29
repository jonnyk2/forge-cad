"""Command line:

    forge build part.py [--param value ...] [--export stl,3mf,step] [--render] [--out out/]
    forge check part.py [--param value ...]
    forge orient part.py
    forge new NAME [--from STARTER]
    forge starters
    forge serve [--port 8765] [DIR]
    forge mcp [DIR]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import PartError, build_part, export, load_part, orient, render
from .render import markers_from_violations, section

STARTERS = Path(__file__).resolve().parent.parent / "starters"


def _split_params(rest: list[str]):
    params, other = [], []
    it = iter(rest)
    for tok in it:
        if tok in ("--export", "--out", "--views"):
            other += [tok, next(it, "")]
        elif tok in ("--render", "--section", "--json", "--no-check"):
            other.append(tok)
        else:
            params.append(tok)
    return params, other


def cmd_build(args, rest, check=True):
    part = load_part(args.part)
    p_args, other = _split_params(rest)
    params = part.params_cls.from_cli(p_args) if p_args else None
    o = argparse.ArgumentParser(add_help=False)
    o.add_argument("--export", default="")
    o.add_argument("--out", default=str(Path(args.part).parent / "out"))
    o.add_argument("--render", action="store_true")
    o.add_argument("--section", action="store_true")
    o.add_argument("--json", action="store_true")
    o.add_argument("--views", default="iso,front,top,right")
    o.add_argument("--no-check", action="store_true")
    oa = o.parse_args(other)
    built = build_part(part, params, check=check and not oa.no_check)
    if oa.json:
        import json
        print(json.dumps(built.to_dict(), indent=2, default=str))
    else:
        print(built.summary())
    out = Path(oa.out)
    if oa.export:
        written = export(built, oa.export.split(","), out)
        for fmt, path in written.items():
            print(f"wrote {path}")
    if oa.render:
        p = out / f"{part.name}-{built.params.hash()}.png"
        render(built.shape, p, views=oa.views.split(","), markers=markers_from_violations(built.violations),
               highlight_overhangs=True)
        print(f"wrote {p}")
    if oa.section:
        p = out / f"{part.name}-{built.params.hash()}-section.png"
        section(built.shape, p, "XZ", built.report.center_of_mass[1])
        print(f"wrote {p}")
    return 0 if built.ok else 1


def cmd_orient(args, rest):
    part = load_part(args.part)
    p_args, _ = _split_params(rest)
    built = build_part(part, part.params_cls.from_cli(p_args) if p_args else None, check=False)
    limit = getattr(part.process, "max_overhang", 45.0)
    bridge = getattr(part.process, "max_bridge", 10.0)
    print(orient.summary(orient.rank(built.shape, limit, bridge)))
    return 0


def cmd_new(args, rest):
    src = STARTERS / f"{args.starter}.py"
    if not src.exists():
        print(f"no starter {args.starter!r}; run `forge starters`", file=sys.stderr)
        return 2
    dst = Path(args.name if args.name.endswith(".py") else args.name + ".py")
    if dst.exists():
        print(f"{dst} already exists", file=sys.stderr)
        return 2
    shutil.copy(src, dst)
    print(f"created {dst} from starter {args.starter!r}")
    return 0


def cmd_starters(args, rest):
    for p in sorted(STARTERS.glob("*.py")):
        doc = ""
        try:
            doc = (load_part(p).doc or "").splitlines()[0]
        except Exception as e:
            doc = f"(failed to load: {e})"
        print(f"{p.stem:<22s} {doc}")
    return 0


def cmd_serve(args, rest):
    from .web.app import serve
    serve(Path(args.dir), port=args.port, open_browser=not args.no_open)
    return 0


def cmd_mcp_config(args, rest):
    import json, os, shutil as _sh
    exe = _sh.which("forge") or sys.argv[0]
    proj = str(Path(args.dir).resolve())
    cfg = {"mcpServers": {"forge": {"command": exe, "args": ["mcp", proj]}}}
    print(json.dumps(cfg, indent=2))
    if sys.platform == "win32":
        where = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        where = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        where = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
    print(f"\nClaude Desktop reads: {where}\nClaude Code: put it in .mcp.json in your project.", file=sys.stderr)
    return 0


def cmd_mcp(args, rest):
    from .mcp_server import main as mcp_main
    mcp_main(Path(args.dir))
    return 0


def _utf8_console():
    """Windows consoles default to a legacy codepage that can't print × ≈ °."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(prog="forge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("part")
    c = sub.add_parser("check"); c.add_argument("part")
    o = sub.add_parser("orient"); o.add_argument("part")
    n = sub.add_parser("new"); n.add_argument("name"); n.add_argument("--from", dest="starter", default="blank")
    sub.add_parser("starters")
    s = sub.add_parser("serve"); s.add_argument("dir", nargs="?", default="."); s.add_argument("--port", type=int, default=8765); s.add_argument("--no-open", action="store_true")
    m = sub.add_parser("mcp"); m.add_argument("dir", nargs="?", default=".")
    mc = sub.add_parser("mcp-config"); mc.add_argument("dir", nargs="?", default=str(Path.home() / "ForgeProjects"))
    args, rest = ap.parse_known_args(argv)
    try:
        return {
            "build": cmd_build, "check": cmd_build, "orient": cmd_orient, "new": cmd_new,
            "starters": cmd_starters, "serve": cmd_serve, "mcp": cmd_mcp, "mcp-config": cmd_mcp_config,
        }[args.cmd](args, rest)
    except PartError as e:
        print(f"error: {e}", file=sys.stderr)
        if e.detail:
            print(e.detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
