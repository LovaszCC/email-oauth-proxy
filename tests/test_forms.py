from app.web.forms import AccountForm, AuthorizeCompleteForm, LoginForm, parse_form

VALID = {
    "email": " User@Example.com ",
    "provider": "gmail",
    "imap_host": "imap.gmail.com",
    "imap_port": "993",
    "permission_url": "https://accounts.google.com/o/oauth2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "scope": "https://mail.google.com/",
    "client_id": "cid",
    "client_secret": "",
    "redirect_uri": "http://localhost",
}


def test_account_form_valid_to_input():
    form, errors = parse_form(AccountForm, VALID)
    assert errors == {}
    data = form.to_input()
    assert data.email.lower() == "user@example.com"  # email-validator normalizes the domain
    assert data.imap_port == 993
    assert data.client_secret is None
    assert data.use_pkce is False


def test_account_form_checkbox_and_secret():
    form, _ = parse_form(AccountForm, {**VALID, "use_pkce": "on", "client_secret": " s "})
    assert form.use_pkce is True
    assert form.client_secret == "s"


def test_account_form_errors():
    form, errors = parse_form(
        AccountForm,
        {
            **VALID,
            "email": "not-an-email",
            "imap_port": "70000",
            "permission_url": "ftp://x",
            "scope": "",
            "provider": "aol",
        },
    )
    assert form is None
    assert set(errors) == {"email", "imap_port", "permission_url", "scope", "provider"}
    assert "http(s)" in errors["permission_url"]


def test_missing_fields_reported():
    _, errors = parse_form(AccountForm, {})
    assert "email" in errors and "client_id" in errors


def test_login_and_complete_forms():
    form, _ = parse_form(LoginForm, {"username": "a", "password": "b"})
    assert (form.username, form.password) == ("a", "b")
    _, errors = parse_form(AuthorizeCompleteForm, {"redirect_url": "  "})
    assert "redirect_url" in errors
