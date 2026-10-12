"""Live CAD: the engine's own geometry drawn as native, editable objects in a running FreeCAD.

The engine stays the source of truth: `scene` turns its numbers into drawing items, `bridge` sends
them to the small server `cad/siteplan_live.FCMacro` runs inside FreeCAD (127.0.0.1 only, behind
a token), `live` holds a session (a site's steps, the objects drawn, test towers moved or removed)
and checks every change against the engine's rules, and `server` offers it to Claude Code as MCP
tools."""
