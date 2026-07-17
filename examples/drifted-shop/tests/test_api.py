from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200


def test_default_page_size_is_twenty_five() -> None:
    route = next(route for route in app.routes if getattr(route, "path", None) == "/v1/products")
    page_size = next(field for field in route.dependant.query_params if field.name == "page_size")
    assert page_size.default == 25
