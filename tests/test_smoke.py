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


def test_no_header_control_is_inert_any_more(client):
    """Nothing on screen may look live before its phase lands -- and now none is unbuilt.

    Search left this list in Phase 6, the category bar in Phase 7, the cart in Phase 8
    and the account control in Phase 11, which is the point of the list: a control
    becomes live in exactly one phase, and until then it is visibly inert rather than
    absent. Every one of them has now landed, so the assertion is that no "arrives in a
    later build" placeholder is left anywhere in the header.
    """
    body = client.get("/").text
    assert "arrives in a later build" not in body
    # The controls those placeholders stood in for, each now a real one.
    assert 'action="/search"' in body
    assert 'href="/category/' in body
    assert 'href="/cart"' in body
    assert 'href="/signin"' in body


def test_unknown_page_is_not_a_crash(client):
    assert client.get("/no-such-page").status_code == 404


def test_static_files_are_served(client):
    response = client.get("/static/favicon.svg")
    assert response.status_code == 200
