"""The setback band and the green strip on every drawing, each with its width and the strip with
the rule that asks it (2026-10-21, the user: he could not tell why the green border shows in one
layout and not another, or why the loop road stands at different distances from the boundary).
The band and the depths are the independent validator's own (validator.zones), so a drawing and
a verdict never disagree. Made-up land (the contract fixtures' rectangle)."""

import ezdxf
from shapely.geometry import Point
from validator_helpers import fixture

from siteplan.cad import scene
from siteplan.service import render
from siteplan.validator import context as judging
from siteplan.validator import zones

TEST_CLASS = "normative"


def _plan():
    made = fixture("rectangle")
    return made, render.plan_of(made.site, made.candidate, made.rules, made.brief)


def test_every_stretch_says_how_deep_its_setback_is_as_the_validator_holds_it():
    made, plan = _plan()
    ctx = judging.build(made.site, made.rules, made.brief, made.candidate)
    reading = render._reading(made.rules, ctx)
    front, side = zones.setback_depths(ctx, reading)
    zone = zones.setback_zone(ctx, reading)
    assert plan.setback and abs(sum(p.area for p in plan.setback) - zone.area) < 0.01
    said = {w.text for w in plan.edge_labels if w.text.startswith("setback")}
    assert said and said <= {f"setback {front:g} m", f"setback {side:g} m"}
    assert len([w for w in plan.edge_labels if w.text.startswith("setback")]) >= 4  # each side
    for words in plan.edge_labels:  # every label stands on the plot, inside its band
        assert made.site.net_plot.value.to_shapely().buffer(0.01).contains(Point(words.at))


def test_the_green_strip_says_its_width_and_the_rule_or_why_there_is_none():
    made, plan = _plan()
    strip_words = [w.text for w in plan.edge_labels if w.text.startswith("green strip")]
    setback_note, strip_note = plan.margin_notes
    assert setback_note.startswith("Setback (shaded): ")
    if made.candidate.program.green_strip:
        assert strip_words and all(("G.O.7 2016" in w or "rule 5(f)" in w
                                    or "rule 7(a)(viii)" in w) for w in strip_words)
        assert strip_note.startswith("Green strip: ")
    else:
        assert not strip_words and strip_note.startswith("No green strip: ")


def test_a_layout_with_a_low_block_names_rule_5f_and_one_without_never_does():
    made, plan = _plan()
    ctx = judging.build(made.site, made.rules, made.brief, made.candidate)
    asks = zones.strips_asked(ctx, render._reading(made.rules, ctx))
    said = " ".join(plan.margin_notes)
    assert ("rule 5(f), for a block below 21 m" in said) == any(
        render._low_strip(made.rules, a) for a in asks)


def test_the_picture_the_plain_dxf_and_freecad_carry_the_band_and_the_words(tmp_path):
    _, plan = _plan()
    svg = render.write_svg(plan, tmp_path / "p.svg", "T", "", []).read_text()
    assert "setback " in svg and "Setback (shaded)" in svg and 'fill="#efe9dc"' in svg
    doc = ezdxf.readfile(render.write_dxf(plan, tmp_path / "p.dxf", []))
    msp = doc.modelspace()
    assert len(msp.query(f'LWPOLYLINE[layer=="{render.SETBACK_LAYER}"]')) >= 1
    texts = [e.dxf.text for e in msp.query('TEXT[layer=="SOLVER-MARGIN-LABELS"]')]
    assert texts and all(t.startswith(("SETBACK ", "GREEN STRIP ")) for t in texts)
    notes = " ".join(e.dxf.text for e in msp.query('TEXT[layer=="SOLVER-NOTES"]'))
    assert "Setback (shaded)" in notes
    items = [i for _, group in scene.candidate_layers(plan, None, "") for i in group]
    ids = {i["id"] for i in items}
    assert "layout-setback-1" in ids
    assert any(i["id"].startswith("layout-margin-") and i["text"].startswith("setback ")
               for i in items)


def test_a_high_rises_strip_is_never_called_a_low_blocks():
    """A high-rise band states its own strip (`StripAsk.given`) as a Table III row does: labelled
    by that, Dhulapally's comb at Stilt + 10 read 'rule 5(f), low block' round its 2 m strip."""
    made = fixture("rectangle")
    rules = made.rules
    high = zones.StripAsk(rules.green_strip.width_m.value, True, True, True)
    low = zones.StripAsk(1.0, True, True, True)
    assert "G.O.7 2016" in render._strip_words(rules, [high], high.width_m) or \
        "rule 7(a)(viii)" in render._strip_words(rules, [high], high.width_m)
    assert render._strip_words(rules, [low], 1.0) == "green strip 1 m, rule 5(f), low block"
    # measured across a tapering tip a 2 m strip reads 3 m: the label says the width asked
    assert render._strip_words(rules, [high], 3.0).startswith(
        f"green strip {high.width_m:g} m, ")
    assert "rule 5(f)" not in render._strip_note(rules, [high])
    assert "rule 5(f), for a block below 21 m" in render._strip_note(rules, [low])


def test_without_the_rules_a_plan_is_drawn_as_before():
    made = fixture("rectangle")
    plan = render.plan_of(made.site, made.candidate)
    assert plan.setback == () and plan.edge_labels == () and plan.margin_notes == ()
