"""Which wording of G.O.168 rule 7(a)(viii)'s 2 m planting strip applies (2026-10-12, the architect:
his seven files carry the 2012 text, where every high-rise keeps the strip whatever its setback,
not G.O.Ms.No.7 of 2016's, where only a setback of 9 m and above does). The open reading
`green_strip_order` is carried only when a project selects it, so every other site's rules read
as before. Made-up land."""

TEST_CLASS = "normative"

from legal_fixtures import make_site  # noqa: E402
from shapely.geometry import box  # noqa: E402

from siteplan import rules as law  # noqa: E402
from siteplan.contracts.resolved_rules import (  # noqa: E402
    GO7_2016,
    GO168_2012,
    GREEN_STRIP_ORDER,
    BandKind,
)
from siteplan.legal.resolve import resolve  # noqa: E402

SITE = make_site(box(0, 0, 200, 120))


def _high_rise_bands(resolved):
    return [b for b in resolved.height.bands if b.kind is BandKind.HIGH_RISE]


def test_the_reading_is_carried_only_when_a_project_selects_it():
    default = resolve(SITE)
    assert GREEN_STRIP_ORDER not in {i.id for i in default.interpretations}
    threshold = default.green_strip.where_setback_from_m.value
    assert threshold == law.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M
    chosen = resolve(SITE, selections={GREEN_STRIP_ORDER: GO168_2012})
    assert chosen.interpretation(GREEN_STRIP_ORDER).selected == GO168_2012


def test_the_2012_wording_puts_the_strip_on_every_high_rise_band():
    chosen = resolve(SITE, selections={GREEN_STRIP_ORDER: GO168_2012})
    assert chosen.green_strip.where_setback_from_m.value == 0.0
    assert chosen.green_strip.where_setback_from_m.clause == law.GREEN_STRIP_2012_CLAUSE
    assert all(b.green_strip_m == law.PERIPHERAL_GREEN_STRIP_M for b in _high_rise_bands(chosen))
    default = resolve(SITE)
    below_nine = [b for b in _high_rise_bands(default)
                  if b.setback_m < law.PERIPHERAL_GREEN_STRIP_FROM_SETBACK_M]
    assert below_nine and all(b.green_strip_m is None for b in below_nine)  # 2016: none there


def test_selecting_the_2016_wording_reads_as_the_default():
    chosen = resolve(SITE, selections={GREEN_STRIP_ORDER: GO7_2016})
    default = resolve(SITE)
    assert [b.green_strip_m for b in chosen.height.bands] == \
        [b.green_strip_m for b in default.height.bands]
