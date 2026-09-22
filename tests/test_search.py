"""Phase 6: search over the catalog, and the states around it.

The assertions run against the committed catalog rather than invented fixtures, so what
is checked is the search a shopper actually gets on the live site. Results are compared
by slug -- pulled out of the links the cards render -- because that is the observable
fact about the page: which products came back, and in what order.
"""

import html
import json
import re

import pytest

from app.routers.catalog import MAX_QUERY_TERMS

CATEGORY_ONLY_TERM = "gourmet"
"""A word that appears in a category name and in no product's own text."""


def results(response) -> list[str]:
    """The slugs of the products a listing page shows, in the order it shows them."""
    assert response.status_code == 200
    seen = []
    for slug in re.findall(r'href="/product/([^"?]+)"', response.text):
        if slug not in seen:
            seen.append(slug)
    return seen


def search(client, query: str) -> list[str]:
    """Search for `query` and return the slugs that came back."""
    return results(client.get("/search", params={"q": query}))


def haystacks(entry: dict, catalog: dict) -> dict[str, str]:
    """The four fields search reads, lowercased, for one catalog entry."""
    names = {category["slug"]: category["name"] for category in catalog["categories"]}
    return {
        "title": entry["title"].lower(),
        "description": entry["description"].lower(),
        "key_info": json.dumps(entry["key_info"]).lower(),
        "category": names[entry["category"]].lower(),
    }


def only_in(field: str, catalog: dict) -> tuple[str, str]:
    """A word unique to one product across the whole catalog, found only in `field`.

    Picked from the catalog rather than hard-coded so that rewording a description does
    not quietly turn "search reads descriptions" into a test that passes for the wrong
    reason. Returns the product's slug and the word.
    """
    fields = {entry["slug"]: haystacks(entry, catalog) for entry in catalog["products"]}
    for slug, texts in fields.items():
        others = {name: text for name, text in texts.items() if name != field}
        for word in re.findall(r"[a-z]{5,}", texts[field]):
            if any(word in text for text in others.values()):
                continue
            if sum(any(word in t for t in other.values()) for other in fields.values()) == 1:
                return slug, word
    raise AssertionError(f"no word unique to one product's {field} in the catalog")


@pytest.fixture
def grocery_slugs(catalog) -> set[str]:
    return {entry["slug"] for entry in catalog["products"] if entry["category"] == "grocery"}


# --- finding things ----------------------------------------------------------------


def test_an_exact_word_from_a_title_finds_that_product(client):
    assert search(client, "Verity") == ["verity-colleen-hoover"]


def test_a_partial_word_finds_it_too(client):
    """Half a word typed into the box is still a search, not a miss."""
    assert search(client, "avoca") == ["medium-hass-avocado"]


@pytest.mark.parametrize("query", ["avocado", "AVOCADO", "AvOcAdO"])
def test_search_is_case_insensitive(client, query):
    assert search(client, query) == ["medium-hass-avocado"]


def test_a_word_from_a_description_finds_the_product(client, catalog):
    slug, word = only_in("description", catalog)
    assert search(client, word) == [slug], word


def test_a_word_from_a_key_info_bullet_finds_the_product(client, catalog):
    slug, word = only_in("key_info", catalog)
    assert search(client, word) == [slug], word


def test_a_category_name_finds_every_product_in_it(client, grocery_slugs):
    """ "Gourmet" is in no product's own text -- only in the name of their shelf."""
    assert set(search(client, CATEGORY_ONLY_TERM)) == grocery_slugs


def test_a_product_title_typed_in_full_finds_that_product(client, catalog):
    """The roadmap's acceptance check: type a product name, get that product."""
    slug = "owala-freesip-water-bottle-24oz-denim"
    entry = next(e for e in catalog["products"] if e["slug"] == slug)
    assert entry["slug"] in search(client, entry["title"])


# --- every word has to match -------------------------------------------------------


def test_every_term_has_to_match_somewhere(client):
    """Two words narrow the answer; they do not widen it.

    "fire" alone finds four products and "stick" six. Together they mean the thing a
    shopper is holding in their head, which is neither of those lists.
    """
    fire = search(client, "fire")
    stick = search(client, "stick")
    both = search(client, "fire stick")
    assert both == ["amazon-fire-tv-stick-4k-select", "amazon-fire-tv-stick-hd"]
    assert len(both) < len(fire) and len(both) < len(stick)
    assert set(both) == set(fire) & set(stick)


def test_terms_from_different_fields_still_narrow(client, grocery_slugs):
    """One word from the category name, one from a title -- both have to land."""
    assert search(client, f"{CATEGORY_ONLY_TERM} banana") == ["banana-bunch-4-5-count"]


def test_two_words_that_never_co_occur_find_nothing(client):
    assert search(client, "fire blender") == []


def test_extra_whitespace_between_terms_is_not_a_term(client):
    assert search(client, "  fire \t stick  ") == search(client, "fire stick")


# --- the shape of the results page -------------------------------------------------


def test_results_are_in_catalog_order(client):
    """The same search twice is the same page: no ranking, no reshuffling."""
    catalog_order = results(client.get("/"))
    found = search(client, "a")
    assert found == [slug for slug in catalog_order if slug in set(found)]


def test_results_are_rendered_with_the_same_card_component(client, catalog):
    response = client.get("/search", params={"q": "balloon"})
    body = html.unescape(response.text)
    slugs = results(response)
    assert len(slugs) == 2
    assert body.count("<article") == 2
    for entry in (e for e in catalog["products"] if e["slug"] in slugs):
        cents = entry["price_cents"]
        assert entry["title"] in body
        assert f'/static/{entry["images"][0]}"' in body
        assert f"${cents // 100:,}.{cents % 100:02d}" in body
        assert f"{entry['rating']:.1f} out of 5 stars" in body


def test_the_result_count_is_accurate_and_reads_as_english(client):
    assert "2 products matched" in client.get("/search", params={"q": "balloon"}).text
    assert "1 product matched" in client.get("/search", params={"q": "Verity"}).text


def test_the_query_is_echoed_back_above_the_results(client):
    assert "Results for &ldquo;avocado&rdquo;" in client.get("/search?q=avocado").text


def test_the_search_box_still_holds_the_query_after_the_page_reloads(client):
    """A shopper refining a search edits their words instead of retyping them."""
    assert 'value="avocado"' in client.get("/search?q=avocado").text
    assert 'value=""' in client.get("/").text


def test_the_header_form_is_what_submits_a_search(client):
    """The roadmap's wiring: the header form on every page posts to this route."""
    for path in ("/", "/product/verity-colleen-hoover", "/search?q=avocado"):
        body = client.get(path).text
        assert 'action="/search" method="get"' in body, path
        assert 'name="q"' in body, path
        assert "Search arrives in a later build" not in body, path


# --- the states around it ----------------------------------------------------------


def test_no_matches_is_an_empty_state_that_says_what_was_searched_for(client):
    response = client.get("/search", params={"q": "ukulele"})
    assert response.status_code == 200
    assert "No results for &ldquo;ukulele&rdquo;" in response.text
    assert "<article" not in response.text
    # A dead end that only apologises is still a dead end.
    assert 'href="/"' in response.text


@pytest.mark.parametrize("query", ["", "   ", "\t"])
def test_a_blank_query_shows_the_full_catalog(client, catalog, query):
    """A question nobody asked is not an error and not an empty result."""
    response = client.get("/search", params={"q": query})
    assert results(response) == results(client.get("/"))
    assert response.text.count("<article") == len(catalog["products"])
    assert "No results" not in response.text


def test_search_with_no_query_string_at_all_is_not_a_422(client, catalog):
    """`/search` typed by hand, or the header form submitted with an empty box."""
    response = client.get("/search")
    assert response.status_code == 200
    assert response.text.count("<article") == len(catalog["products"])


def test_an_empty_catalog_gets_its_own_state_not_a_failed_search(empty_client):
    """ "Nothing is installed" and "nothing matched" are different facts, said differently."""
    blank = empty_client.get("/search")
    assert blank.status_code == 200
    assert "The catalog is empty" in blank.text

    searched = empty_client.get("/search", params={"q": "avocado"})
    assert searched.status_code == 200
    assert "No results for &ldquo;avocado&rdquo;" in searched.text


# --- nonsense typed into a public text field ---------------------------------------


@pytest.mark.parametrize("query", ["_", "____", "%%%", "%_%"])
def test_like_wildcards_find_nothing_because_no_product_contains_them(client, query):
    """Unescaped, `%` in the box would mean "every product" and `_` "any character"."""
    assert search(client, query) == []


def test_a_percent_sign_matches_a_percent_sign(client, catalog):
    """The catalog really does say "100% USDA Biobased", so this is the honest answer."""
    found = search(client, "%")
    expected = {
        entry["slug"]
        for entry in catalog["products"]
        if "%" in entry["title"] + entry["description"] + json.dumps(entry["key_info"])
    }
    assert expected, "the catalog no longer contains a literal percent sign"
    assert set(found) == expected
    assert len(found) < len(catalog["products"])


def test_a_query_is_text_on_the_page_and_never_markup(client):
    response = client.get("/search", params={"q": "<script>alert(1)</script>"})
    assert response.status_code == 200
    assert "<script>alert(1)" not in response.text
    assert "&lt;script&gt;alert(1)" in response.text


def test_a_hand_built_query_of_absurd_length_still_answers(client):
    """The field is bounded before it reaches the database, not trusted to be sensible."""
    response = client.get("/search", params={"q": "avocado " * 2000})
    assert response.status_code == 200


def test_past_the_term_cap_the_extra_words_are_dropped_not_the_search(client):
    """Beyond the cap a query answers as its first few words, which is a wider search.

    Dropping conditions can only widen a result set, never point it at the wrong
    products, so the guard fails safe. It is set far past any real product name, so a
    shopper types their way into it only on purpose.
    """
    counted = "fire stick 4k select newest model start streaming"
    assert len(counted.split()) == MAX_QUERY_TERMS
    assert search(client, f"{counted} free live tv alexa") == search(client, counted)
    assert set(search(client, counted)) <= set(search(client, "fire stick"))


@pytest.mark.parametrize(
    "query",
    ["🍌", "café", "select;--", "' OR 1=1 --", "0", "-", "\\", "a b c d e f g h i j"],
)
def test_odd_queries_answer_with_a_page_rather_than_an_error(client, query):
    assert client.get("/search", params={"q": query}).status_code == 200
