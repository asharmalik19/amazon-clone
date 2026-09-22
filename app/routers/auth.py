"""Signing up, signing in, signing out.

Three screens' worth of routes and one shape between them: a `GET` renders the form, the
matching `POST` either succeeds and redirects, or re-renders the same form with the
fields the shopper typed still in them and a visible error against the one that is
wrong. Nothing here answers with a bare status code -- a form that rejects you without
saying why is a dead end, and this app does not have those.

Three rules the routes share:

- **Plain forms, no HTMX.** Signing in changes the whole page -- the header, the greeting,
  every "sign in" link on it -- so swapping a fragment would leave the rest of the screen
  claiming the visitor is still a stranger. A full navigation is the honest response, and
  it is also the one that works with JavaScript off.
- **Success is a 303.** The browser follows with a `GET`, so refreshing afterwards cannot
  re-post a signup, and the back button lands on a page rather than on a resubmission
  warning.
- **Errors are a 400, not a redirect.** The response *is* the form, with the values still
  in it. A redirect would either lose what was typed or need somewhere to stash it.

What is deliberately not here: password reset (there is no mail to send it with), email
verification, and anything about merging the anonymous cart into the account -- that is
Phase 12, and until it lands, signing in leaves the cart cookie exactly as it found it.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from app.db import DbSession
from app.nav import shell
from app.security import (
    check_credentials,
    clear_session,
    create_user,
    email_problem,
    find_user_by_email,
    issue_session,
    name_problem,
    normalize_email,
    password_problem,
)
from app.templating import templates

router = APIRouter()

# Where a shopper lands after signing in, signing up, or signing out. The storefront
# rather than the page they came from: `?next=` from a form post is an open redirect
# waiting to be written carefully, and the journey in specs/mission.md starts at the
# catalog anyway. The header they land on is the receipt -- it greets them by name.
LANDING = "/"


def _form_response(
    request: Request,
    db: DbSession,
    template: str,
    context: dict,
    *,
    status_code: int = 200,
) -> Response:
    """Render an auth form, with the page shell it needs around it.

    `shell` is what draws the header, so these pages get the same one as everything
    else -- including its cart badge, because a shopper who fills a cart and then goes to
    sign in should not watch it appear to empty itself. No nav link is active: signing in
    is not a shelf of the catalog.
    """
    return templates.TemplateResponse(
        request, template, context | shell(db, request), status_code=status_code
    )


@router.get("/signup")
async def signup_form(request: Request, db: DbSession):
    """The create-an-account form.

    Offered even to a shopper who is already signed in, rather than redirected away: a
    second account on a shared machine is a real thing to want, and the header says who
    is currently signed in either way.
    """
    return _form_response(request, db, "signup.html", {"values": {}, "errors": {}})


@router.post("/signup")
async def signup(
    request: Request,
    db: DbSession,
    name: str = Form("", description="What the header greets the shopper by."),
    email: str = Form("", description="The address the account is registered to."),
    password: str = Form("", description="The new password."),
    password_confirm: str = Form("", description="The same password again."),
):
    """Create an account and sign the new shopper straight in.

    Every field is validated before anything is written, and all the failures are
    reported at once: a form that reveals one problem per submission makes a shopper
    guess how many are left.

    The password is checked against itself as well as against the length rule, because
    the only way to notice a typo in a field nobody can read is to type it twice -- and a
    new account whose password is a typo is an account its owner cannot get back into.
    """
    values = {"name": name.strip(), "email": email.strip()}
    normalized = normalize_email(email)

    errors: dict[str, str] = {}
    if problem := name_problem(values["name"]):
        errors["name"] = problem
    if problem := email_problem(normalized):
        errors["email"] = problem
    elif find_user_by_email(db, normalized) is not None:
        # Said plainly rather than hidden. Whether an address has an account here is
        # something anyone can discover from the sign-up form of any site that refuses
        # duplicates, so a vague "something went wrong" would cost a shopper their next
        # step without costing an attacker anything.
        errors["email"] = "That email already has an account. Sign in instead."
    if problem := password_problem(password):
        errors["password"] = problem
    elif password != password_confirm:
        errors["password_confirm"] = "Those passwords do not match."

    if errors:
        # The passwords are not echoed back into the response: the fields are rendered
        # empty, as every browser's own form restore does, so a rejected signup does not
        # leave a plaintext password sitting in the page source or in a proxy's log.
        return _form_response(
            request, db, "signup.html", {"values": values, "errors": errors}, status_code=400
        )

    user = create_user(db, name=values["name"], email=normalized, password=password)
    # The dependency never commits, so the write is committed here, where it is visible.
    db.commit()

    response = RedirectResponse(LANDING, status_code=303)
    # Only after the commit: a cookie naming a user row that was never written would sign
    # somebody in as nobody.
    issue_session(response, user)
    return response


@router.get("/signin")
async def signin_form(request: Request, db: DbSession):
    """The sign-in form."""
    return _form_response(request, db, "signin.html", {"values": {}, "errors": {}})


@router.post("/signin")
async def signin(
    request: Request,
    db: DbSession,
    email: str = Form("", description="The address the account is registered to."),
    password: str = Form("", description="The account's password."),
):
    """Sign an existing shopper in.

    A wrong password and an email with no account get the *same* message, against the
    form rather than against either field. Signing in is the one place where saying which
    half was wrong would turn the form into a way to test whether an address has an
    account here -- and unlike the signup form, this one has no reason to answer that.

    `check_credentials` answers the whole question in one call, including spending the
    hashing time on an address with no account -- see its comment. Splitting it into a
    lookup and a comparison here would make a missing account measurably faster than a
    wrong password, which is the same disclosure by a slower route.
    """
    user = check_credentials(db, normalize_email(email), password)

    if user is None:
        return _form_response(
            request,
            db,
            "signin.html",
            {
                "values": {"email": email.strip()},
                "errors": {"form": "That email or password is not right."},
            },
            status_code=400,
        )

    response = RedirectResponse(LANDING, status_code=303)
    issue_session(response, user)
    return response


@router.post("/signout")
async def signout(request: Request, db: DbSession):
    """Sign the shopper out.

    A `POST`, with no `GET` alongside it: sign-out is a state change, and as a link it
    could be triggered by anything that prefetches or embeds a URL -- including another
    site's `<img>`. The header renders it as a one-button form for exactly that reason.

    Idempotent. Clearing a session nobody has is not an error, so a double-submitted
    button or a stale second tab lands on the storefront signed out, which is the state
    the shopper asked for.
    """
    response = RedirectResponse(LANDING, status_code=303)
    clear_session(response)
    # The cart cookie is deliberately left alone. It is the anonymous cart's key, not the
    # account's, and dropping it would throw away a basket that signing out never touched.
    # Phase 12 is where the two become one question.
    return response
