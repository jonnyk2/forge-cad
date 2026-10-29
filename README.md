# Forge

**Code-first parametric CAD for parts that get 3D-printed or machined — built for an AI to
drive at full strength, and for a human to run without one.**

- A part is a Python file (build123d + forge helpers). The file is the model.
- Every build returns measurements and manufacturability violations with suggested fixes.
- Holes, bosses, inserts, fits are sized for the real process (`FDM(nozzle=0.4)` or `CNC(...)`).
- Export 3MF/STL for the slicer, STEP for a machinist or Fusion, SVG drawings.
- `forge serve` → local web app: 3D viewer, parameter sliders, code editor, checks, export.
- `forge mcp` → MCP server so Claude (or any MCP client) builds, inspects, fixes and exports.

See `SPEC.md` for the design and `docs/WRITING_PARTS.md` for the part-file contract and rules.

## Install

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
forge starters                                          # list templates
```

(`build123d` pulls in the OpenCascade kernel; first install is ~200 MB.)

## Use it yourself

Windows: double-click `INSTALL_AND_TEST.bat` once, then `RUN_APP.bat`.  Anywhere else:

```bash
forge serve ~/ForgeProjects               # opens http://127.0.0.1:8765
```

The served folder holds **projects** (one sub-folder each, any number of part files). First run
seeds an `examples` project from the starters. In the app: pick a project and a part, drag sliders
(rebuilds live), read the Checks panel, edit the code (⌘/Ctrl+Enter to save & build), click
**Export** → 3MF. Section slider cuts the model; **Measure** clicks two points; **Orient** ranks
the six print orientations.

## Vibe-code it (in-app AI)

Click ⚙, paste an Anthropic API key (console.anthropic.com → API keys; stored only in
`~/.forge/config.json`), pick a model. Then type in **Ask the AI**:

> a wall hook for a 25 mm pipe, two M5 screws, PETG, no supports

or, with a part open:

> make the lip 3 mm taller and add a cable slot

The AI reads the part, edits it, builds it, looks at the report/violations/render, fixes, and
hands the result back to the sliders. Every edit lands in the code editor, so you can keep
tweaking by hand.

From the terminal:

```bash
forge build stand.py --angle 70 --export 3mf,step --render
forge check stand.py --wall 1.2            # exits 1 if there are errors
forge orient stand.py
```

## Let Claude Desktop / Claude Code drive (MCP)

`forge mcp-config` prints the JSON and where to put it.  Or add to your MCP config (Claude Desktop / Claude Code `.mcp.json`):

```json
{ "mcpServers": { "forge": { "command": "forge", "args": ["mcp", "/path/to/my_parts"] } } }
```

Then: *"Make me a wall bracket for a 32 mm pipe, two M5 screws, PETG."* Claude calls `guide`,
writes `pipe_bracket.py`, calls `build`, reads the violations and the render, fixes, exports.

## Layout

```
forge/            the library (params, part loader, inspect, dfm/, features, library, export, render, orient)
forge/mcp_server  MCP tools
forge/web         Flask app + single-page viewer/editor
starters/         templates: blank, box_with_lid, bracket, enclosure, phone_stand, spur_gear
docs/             WRITING_PARTS.md — the contract & rules the AI reads first
tests/            pytest; `-m kernel` tests need build123d
```

## Status

v0.1. FDM rules are implemented; CNC has the first four rules (inside-corner radius, sharp
inside corners, pocket depth, thin walls) and the process declaration — the rest is specified
in SPEC.md §7.
