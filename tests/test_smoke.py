"""Phase 1: the app boots, both routes answer, and the header shell renders."""


def test_healthz_is_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_home_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_home_has_the_header_shell(client):
    body = client.get("/").text
    assert 'id="site-search"' in body
    assert "Back to top" in body


def test_unbuilt_header_controls_are_inert(client):
    """Nothing on screen may look live before its phase lands."""
    body = client.get("/").text
    assert 'action="/search"' not in body
    assert 'href="/cart"' not in body


def test_unknown_page_is_not_a_crash(client):
    assert client.get("/no-such-page").status_code == 404


def test_static_files_are_served(client):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
