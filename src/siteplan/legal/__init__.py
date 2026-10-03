"""Stream A1 of the production architecture (docs/ARCHITECTURE.md): the legal envelope.

CanonicalSiteModel -> ResolvedRules -> BuildableEnvelope, deterministic, before any tower or road
exists. Import each stage from its own module (a package-level `resolve` or `envelope` would hide
the module of the same name):

    from siteplan.legal.resolve import resolve
    from siteplan.legal.envelope import envelope
    from siteplan.legal.debug_drawing import write_debug_dxf, write_debug_svg
    from siteplan.legal.site import site_from_project  # survey glue; it imports the adapters

Nothing here places a tower or draws a road, and nothing imports the generator (towers, layout,
grounds, the road generators in access): tests/test_envelope.py proves it. `siteplan envelope`
runs the whole stage from a project file.
"""
