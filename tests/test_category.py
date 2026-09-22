"""Phase 7: browsing one category, and the same filter composed with search.

As with search, the assertions run against the committed catalog rather than invented
fixtures, and results are compared by slug -- pulled out of the links the cards render --
because that is the observable fact about a listing page: which products came back, and
in what order.
"""

import html
import re

import pytest

from tests.test_search import results, search


@pytest.fixture
def categories(catalog) -> list[dict]:
    """The catalog's categories, in the display order the nav should use."""
    return sorted(catalog["categories"], key=lambda category: category["position"])


@pytest.fixture
def slugs_by_category(catalog) -> dict[str, list[str]]:
    """Every product slug, grouped by category, in each shelf's own display order."""
    grouped: dict[str, list[str]] = {}
    for entry in sorted(catalog["products"], key=lambda e: e["title"]):
        grouped.setdefault(entry["category"], []).append(entry["slug"])
    return grouped


def nav_links(body: str) -> list[str]:
    """The hrefs of the category bar, in the order it renders them."""
    bar = re.search(r'<nav [^>]*aria-label="Shop by category".*?</nav>', body, re.S)
    assert bar, "the category bar is not on the page"
    return re.findall(r'href="([^"]+)"', bar.group())


def current_nav_link(body: str) -> str | None:
    """The href of the nav link marked as the shopper's current place, if any."""
    bar = re.search(r'<nav [^>]*aria-label="Shop by category".*?</nav>', body, re.S)
    assert bar
    marked = re.findall(r'<a href="([^"]+)"[^>]*aria-current', bar.group())
    assert len(marked) <= 1, f"more than one nav link claims to be current: {marked}"
    return marked[0] if marked else None


# --- the category page -------------------------------------------------------------


def test_a_category_page_shows_exactly_that_category(client, categories, slugs_by_category):
    for category in categories:
        response = client.get(f"/category/{category['slug']}")
        assert results(response) == slugs_by_category[category["slug"]], category["slug"]


def test_the_category_page_names_the_category_and_counts_it(client, slugs_by_category):
    body = client.get("/category/books").text
    assert "Books" in body
    assert f"{len(slugs_by_category['books'])} products" in body


def test_the_category_pages_partition_the_catalog(client, categories, catalog):
    """Every product sits on exactly one shelf, and every shelf is reachable."""
    seen: list[str] = []
    for category in categories:
        seen += results(client.get(f"/category/{category['slug']}"))
    assert sorted(seen) == sorted(entry["slug"] for entry in catalog["products"])


def test_category_products_are_rendered_with_the_same_card_component(client, catalog):
    response = client.get("/category/books")
    body = html.unescape(response.text)
    slugs = set(results(response))
    assert body.count("<article") == len(slugs)
    for entry in (e for e in catalog["products"] if e["slug"] in slugs):
        cents = entry["price_cents"]
        assert entry["title"] in body
        assert f'/static/{entry["images"][0]}"' in body
        assert f"${cents // 100:,}.{cents % 100:02d}" in body
        assert f"{entry['rating']:.1f} out of 5 stars" in body


def test_an_unknown_category_is_a_404_page_not_a_json_error(client):
    response = client.get("/category/haberdashery")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "We could not find that category." in response.text
    # A dead end that only apologises is still a dead end.
    assert 'href="/"' in response.text


def test_an_unknown_category_slug_is_not_echoed_back(client):
    """An unknown slug is attacker-supplied text; the page has nothing to say about it."""
    response = client.get("/category/<script>alert(1)</script>")
    assert response.status_code == 404
    assert "<script>alert(1)" not in response.text
    assert "alert(1)" not in response.text


def test_every_seeded_category_page_answers(client, catalog):
    """No category in the nav is a link to a 404."""
    for category in catalog["categories"]:
        assert client.get(f"/category/{category['slug']}").status_code == 200


# --- the nav bar -------------------------------------------------------------------


def test_the_nav_offers_the_full_catalog_and_every_category_in_order(client, categories):
    expected = ["/"] + [f"/category/{category['slug']}" for category in categories]
    assert nav_links(client.get("/").text) == expected


def test_the_nav_is_on_every_listing_page_and_the_product_page(client, categories):
    expected = ["/"] + [f"/category/{category['slug']}" for category in categories]
    for path in ("/", "/search?q=avocado", "/category/books", "/product/verity-colleen-hoover"):
        assert nav_links(client.get(path).text) == expected, path


def test_the_nav_names_the_categories_the_way_the_catalog_does(client, categories):
    # Unescaped, because "Home & Kitchen" reaches the page as "Home &amp; Kitchen".
    body = html.unescape(client.get("/").text)
    for category in categories:
        assert category["name"] in body, category["slug"]


def test_the_active_nav_link_is_where_the_shopper_actually_is(client):
    assert current_nav_link(client.get("/").text) == "/"
    assert current_nav_link(client.get("/category/books").text) == "/category/books"
    assert current_nav_link(client.get("/search?q=book&category=books").text) == "/category/books"


def test_no_nav_link_is_active_on_a_page_that_is_not_one_of_them(client):
    """A product is not a listing, so no shelf in the bar is the page being looked at."""
    assert current_nav_link(client.get("/product/verity-colleen-hoover").text) is None
    assert current_nav_link(client.get("/search?q=avocado").text) is None


def test_the_product_page_links_to_its_own_category(client, catalog):
    entry = next(e for e in catalog["products"] if e["slug"] == "verity-colleen-hoover")
    body = client.get(f"/product/{entry['slug']}").text
    assert f'href="/category/{entry["category"]}"' in body


def test_a_page_with_no_catalog_behind_it_has_no_category_bar(empty_client):
    """An empty grey strip would read as a broken header rather than an absent one."""
    body = empty_client.get("/").text
    assert 'aria-label="Shop by category"' not in body
    assert "Category browsing arrives in a later build" not in body


def test_the_404_page_has_no_category_bar_and_still_renders(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert 'aria-label="Shop by category"' not in response.text
    assert "Back to the catalog" in response.text


# --- search composed with the category filter --------------------------------------


def filtered(client, query: str, category: str) -> list[str]:
    """Search for `query` inside `category` and return the slugs that came back."""
    return results(client.get("/search", params={"q": query, "category": category}))


def test_a_filtered_search_is_the_intersection_of_the_two(client, slugs_by_category):
    """Neither half is allowed to win: it has to match the words *and* be on the shelf."""
    words = search(client, "the")
    shelf = slugs_by_category["books"]
    both = filtered(client, "the", "books")
    assert both, "the fixture query no longer matches anything in Books"
    assert both == [slug for slug in words if slug in set(shelf)]
    assert set(both) < set(words) and set(both) <= set(shelf)


def test_the_filter_excludes_matches_that_sit_on_another_shelf(client):
    """"Fire" is a Fire TV in Electronics and a fire pit's worth of nothing in Books."""
    assert set(filtered(client, "fire", "electronics")) == set(search(client, "fire"))
    assert filtered(client, "fire", "books") == []


def test_a_filtered_search_keeps_catalog_order(client):
    found = filtered(client, "the", "books")
    assert found == [slug for slug in results(client.get("/")) if slug in set(found)]


def test_a_blank_query_with_a_filter_is_the_category_page(client):
    assert filtered(client, "", "books") == results(client.get("/category/books"))


def test_a_filtered_search_says_which_shelf_it_searched(client):
    body = client.get("/search?q=the&category=books").text
    assert "Results for &ldquo;the&rdquo; in Books" in body


def test_the_filter_row_offers_every_shelf_the_query_actually_hit(client, catalog):
    """A filter that leads to an empty page is not worth offering, so it is not drawn."""
    body = client.get("/search?q=the").text
    hit = {
        entry["category"]
        for entry in catalog["products"]
        if entry["slug"] in search(client, "the")
    }
    for category in catalog["categories"]:
        link = f'href="/search?q=the&amp;category={category["slug"]}"'
        assert (link in body) == (category["slug"] in hit), category["slug"]


def test_the_filter_row_counts_the_matches_on_each_shelf(client, catalog):
    body = html.unescape(client.get("/search?q=the").text)
    for category in catalog["categories"]:
        count = len(filtered(client, "the", category["slug"]))
        if count:
            assert f"{category['name']} ({count})" in body, category["slug"]
    assert f"All categories ({len(search(client, 'the'))})" in body


def test_the_filter_row_is_not_drawn_when_there_is_no_choice_to_make(client):
    """One shelf matching and no filter on means six links that all say the same thing."""
    assert search(client, "Verity") == ["verity-colleen-hoover"]
    assert "Refine by category" not in client.get("/search?q=Verity").text


def test_a_filtered_search_can_be_widened_back_to_the_whole_catalog(client):
    body = client.get("/search?q=the&category=books").text
    assert "Refine by category" in body
    assert 'href="/search?q=the"' in body


def test_the_search_box_stays_scoped_while_a_shopper_is_on_a_shelf(client):
    """The roadmap's acceptance check: narrow to a category, then search inside it."""
    for path in ("/category/books", "/search?q=the&category=books"):
        body = client.get(path).text
        assert 'action="/search" method="get"' in body, path
        assert '<input type="hidden" name="category" value="books">' in body, path
        # Invisible scoping would be a search that lies about its results.
        assert "Search in Books" in body, path


def test_the_search_box_is_not_scoped_where_no_shelf_is_in_play(client):
    for path in ("/", "/search?q=avocado"):
        body = client.get(path).text
        assert 'name="category"' not in body, path


def test_a_search_from_a_product_page_stays_on_that_products_shelf(client):
    body = client.get("/product/verity-colleen-hoover").text
    assert '<input type="hidden" name="category" value="books">' in body


# --- the states around the filter --------------------------------------------------


def test_a_filter_that_empties_the_results_says_so_and_offers_the_way_out(client):
    response = client.get("/search", params={"q": "avocado", "category": "books"})
    assert response.status_code == 200
    assert "No results for &ldquo;avocado&rdquo; in Books" in response.text
    assert "<article" not in response.text
    # The same search across the whole catalog, one click away.
    assert 'href="/search?q=avocado"' in response.text
    assert "Search all categories instead" in response.text
    # ...and it says how much is waiting there, so the click is worth making.
    assert "one product elsewhere in the catalog does" in response.text


def test_the_filtered_empty_state_counts_the_matches_it_is_offering(client):
    response = client.get("/search", params={"q": "fire", "category": "books"})
    found = len(search(client, "fire"))
    assert found > 1
    assert f"{found} products elsewhere in the catalog do." in response.text


def test_a_search_that_matches_nothing_anywhere_keeps_the_general_empty_state(client):
    response = client.get("/search", params={"q": "ukulele", "category": "books"})
    assert response.status_code == 200
    assert "No results for &ldquo;ukulele&rdquo; in Books" in response.text
    assert "Search all categories instead" not in response.text
    assert 'href="/"' in response.text


def test_an_unknown_filter_widens_the_search_and_admits_it(client):
    """A bookmark kept past a catalog reshuffle: the search answers, it does not 422."""
    response = client.get("/search", params={"q": "avocado", "category": "haberdashery"})
    assert response.status_code == 200
    assert results(response) == search(client, "avocado")
    assert "does not match any category we have" in response.text


def test_an_unknown_filter_is_not_echoed_back(client):
    response = client.get("/search", params={"q": "avocado", "category": "<script>x</script>"})
    assert response.status_code == 200
    assert "<script>x" not in response.text
    assert "does not match any category we have" in response.text


def test_a_blank_filter_is_the_same_as_no_filter(client):
    for value in ("", "   "):
        response = client.get("/search", params={"q": "avocado", "category": value})
        assert results(response) == search(client, "avocado")
        assert "does not match any category we have" not in response.text
        assert 'name="category"' not in response.text


@pytest.mark.parametrize(
    "value",
    ["%", "_", "books%", "' OR 1=1 --", "🍌", "books/../electronics", "0", "-" * 500],
)
def test_nonsense_in_the_filter_answers_with_a_page_rather_than_an_error(client, value):
    response = client.get("/search", params={"q": "avocado", "category": value})
    assert response.status_code == 200
    assert results(response) == search(client, "avocado")


def test_an_empty_catalog_has_no_category_pages_to_browse(empty_client):
    assert empty_client.get("/category/books").status_code == 404
