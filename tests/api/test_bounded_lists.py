"""Every list endpoint must be bounded (architecture 13.10, definition of done)."""

from protect_api.main import app


def _query_params(route) -> set[str]:
    return {p.name for p in route.dependant.query_params}


def test_every_list_endpoint_has_a_limit():
    unbounded = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "GET" not in methods or not path.startswith("/api/v1"):
            continue
        if path.endswith(
            ("}", "/me", "/invitation", "/schema", "/templates", "/capabilities", "/adapters")
        ):
            continue  # single objects and fixed small sets
        if "limit" not in _query_params(route):
            unbounded.append(path)
    assert unbounded == [], f"list endpoints without a limit: {unbounded}"
