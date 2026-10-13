"""What the engine does not check is registered once, with its clause and why (scope.py,
2026-10-13): the building services the firm designs by hand are outside automated scope, and the
obligations that are not services (a road's surface, the site's location, a TDR to load, an
authority) are classified for what they are, never dropped with the services."""

TEST_CLASS = "normative"

from siteplan import scope  # noqa: E402
from siteplan.inventory import INVENTORY, Reading  # noqa: E402

KIND = {r.id: r.kind for r in scope.NOT_CHECKED}


def test_every_entry_names_its_order_and_says_why():
    ids = [r.id for r in scope.NOT_CHECKED]
    assert len(ids) == len(set(ids))
    for r in scope.NOT_CHECKED:
        assert r.name and r.why and ("G.O." in r.clause), r.id


def test_the_building_services_are_outside_automated_scope():
    for service in ("stp_solid_waste", "services_plan", "ev_charging", "dual_piping",
                    "digital_infrastructure"):
        assert KIND[service] is scope.Kind.OUT_OF_SCOPE, service


def test_obligations_that_are_not_services_are_not_excluded_with_them():
    assert KIND["approach_road_surface"] is scope.Kind.SITE_FACT
    assert KIND["no_high_rise_areas"] is scope.Kind.SITE_FACT
    assert KIND["defence_clearance"] is scope.Kind.SITE_FACT
    assert KIND["tdr_loading"] is scope.Kind.CONDITION
    assert KIND["sanctioning_authority"] is scope.Kind.CONDITION


def test_every_entry_is_in_the_inventory_as_not_modelled():
    listed = {e.rule: e for e in INVENTORY if e.topic == "Not checked"}
    for r in scope.NOT_CHECKED:
        assert listed[r.name].reading is Reading.NOT_MODELLED
        assert listed[r.name].clause == r.clause


def test_the_scope_statement_names_every_excluded_requirement():
    statement = scope.scope_statement()
    assert all(r.name in statement for r in scope.NOT_CHECKED)
