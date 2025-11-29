from server.services.edges import EdgeType, build_edge, dedupe_edges, merge_edges, normalize_id, normalize_layout_target


def test_normalize_id_and_layout_target():
    assert normalize_id("@+id/homeFragment") == "homefragment"
    assert normalize_id("app:id/detail") == "detail"
    assert normalize_layout_target("activity_main.xml") == "layout/activity_main.xml"
    assert normalize_layout_target("res/layout/home.xml") == "layout/home.xml"


def test_build_and_dedupe_edges():
    e1 = build_edge(EdgeType.NAV_DESTINATION, "home")
    e2 = build_edge(EdgeType.NAV_DESTINATION, "home")
    e3 = build_edge(EdgeType.NAV_ACTION, "detail", {"source": "home", "id": "to_detail"})
    deduped = dedupe_edges([e1, e2, e3])
    assert len(deduped) == 2
    merged = merge_edges([e1], [e3])
    assert any(edge["type"] == EdgeType.NAV_DESTINATION for edge in merged)
    assert any(edge["type"] == EdgeType.NAV_ACTION for edge in merged)
