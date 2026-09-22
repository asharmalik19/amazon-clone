"""Every failure a shopper can be shown, rendered as a page of this storefront.

Two handlers, one template. The first covers the errors the app raises on purpose -- an
unknown slug, a hand-built quantity, a `GET` at a `POST`-only address -- and the second
covers the ones nobody planned for. Before this, only 404 had a page: everything else
fell through to FastAPI's `{"detail": ...}` JSON for a deliberate error and to
Starlette's bare `Internal Server Error` text for a crash. Both are the wrong answer to
give somebody who is shopping, and the second is the one that decides what a bad day
looks like.

What a crash must never do is explain itself. The traceback goes to the platform log,
where it is useful; the page gets a sentence and a way back to the catalog, because a
stack trace on a public URL is a map of the application for anybody who can provoke one.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.templating import templates

logger = logging.getLogger("amazonia")

# What to say instead of the reason phrase, for the statuses this app can actually
# produce. Written for a shopper: what happened, in a sentence, with no HTTP in it.
#
# A route that raised a sentence of its own keeps it -- see `_heading` -- so this table
# is the fallback for the errors that arrive with nothing but a status code: Starlette's
# own 404 for an unrouted path, and its 405 for the wrong method on a real one.
_COPY: dict[int, tuple[str, str]] = {
    400: (
        "We could not use that request.",
        "Something in the address or the form was not something this site accepts. "
        "Going back and trying again from the page itself usually settles it.",
    ),
    404: (
        "We could not find that page.",
        "The page may have moved, or the address may have a typo in it.",
    ),
    405: (
        "That address does not answer that kind of request.",
        "It is reachable from the site itself -- following a link or submitting the "
        "form on the page will use the method it expects.",
    ),
    500: (
        "Something went wrong on our side.",
        "The fault is ours, not yours, and it has been logged. Reloading the page or "
        "starting again from the catalog is worth a try.",
    ),
}

# For a status not in the table at all. Deliberately vague about the cause, because at
# that point the app genuinely does not know what happened.
_FALLBACK = (
    "Something went wrong.",
    "The page could not be shown. The catalog is still there, and the link below "
    "leads back to it.",
)


def _copy(status_code: int) -> tuple[str, str]:
    """The heading and the explanation for `status_code`."""
    return _COPY.get(status_code, _FALLBACK)


def _heading(exc: StarletteHTTPException) -> str:
    """The sentence to put at the top of the page for `exc`.

    A route that raised a message of its own ("We could not find that product.") gets to
    keep it: it knows something this module does not. Starlette's own default detail is
    the bare reason phrase -- "Not Found", "Method Not Allowed" -- which is a status code
    spelled out in words rather than anything a shopper asked for, so that is the case
    the table above replaces.
    """
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:  # a status outside the registry: nothing to compare the detail to
        phrase = ""
    if exc.detail and exc.detail != phrase:
        return exc.detail
    return _copy(exc.status_code)[0]


def _page(request: Request, status_code: int, heading: str, note: str) -> Response:
    """Render the error page, at the status the failure actually was.

    The status is preserved rather than flattened to 200: a crawler, a monitor and a
    browser's history all read it, and a 500 that reports itself as a success is a
    500 nobody finds out about.

    No shell context is passed, for the same reason the 404 has never had any (see
    `app/nav.py`): the header greets the shopper and counts their cart from the
    database, and an error page is exactly where the database may be the thing that
    broke. The header renders its signed-out, count-less state instead -- a click
    rather than a lie, and no second query to fail inside the handler for the first one.
    """
    return templates.TemplateResponse(
        request,
        "error.html",
        {"heading": heading, "note": note, "status_code": status_code},
        status_code=status_code,
    )


async def http_error_page(request: Request, exc: StarletteHTTPException) -> Response:
    """Render any `HTTPException` as a page of the storefront.

    This is every error the app raises on purpose, plus the two Starlette raises for it:
    404 for a path with no route and 405 for the wrong method on one that exists.

    HTMX requests get the page too, and it costs nothing: htmx does not swap the body of
    a non-2xx response, so what a fragment request receives here is discarded. The
    alternative -- a second, terser branch for the same failure -- would be a second
    thing to keep true for no gain.
    """
    response = _page(request, exc.status_code, _heading(exc), _copy(exc.status_code)[1])
    # `WWW-Authenticate` on a 401, `Allow` on a 405: headers that are part of what the
    # status means, and dropping them would make the response a worse answer than the
    # JSON one it replaces.
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def unhandled_error_page(request: Request, _: Exception) -> Response:
    """Render an unexpected exception as a 500 page, and log the traceback.

    Starlette re-raises after this returns, so the exception still reaches the server's
    own error log with its traceback intact; `logger.exception` adds the request that
    provoked it, which is the part that makes the traceback actionable.

    Nothing about the exception reaches the page -- not its message and not its type.
    An exception string is written for whoever wrote the code, and it routinely contains
    a query, a path or a value that is nobody else's business. That is why the argument
    is discarded rather than used: there is no field on this page for it to end up in.
    """
    logger.exception("unhandled error serving %s %s", request.method, request.url.path)
    heading, note = _copy(500)
    return _page(request, 500, heading, note)


def register(app: FastAPI) -> None:
    """Point `app` at both handlers.

    The `Exception` handler only gets to answer while the app is not in debug mode:
    Starlette's `ServerErrorMiddleware` renders its own traceback page first when
    `app.debug` is true. So debug is left at FastAPI's default of false and never read
    from the environment -- there is no switch for someone to flip on the live site, and
    `tests/test_errors.py` asserts it stays that way.
    """
    app.add_exception_handler(StarletteHTTPException, http_error_page)
    app.add_exception_handler(Exception, unhandled_error_page)
