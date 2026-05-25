from app.main import app


def test_slack_routes_are_not_registered():
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/webhooks/slack/interactivity" not in route_paths
    assert "/_debug/slack" not in route_paths
