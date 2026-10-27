import json

import pytest
from django.urls import reverse

from accounts import mfa, passkeys
from accounts.models import LoginFailure, Passkey, User
from core.models import AppSettings
from tests.passkey_fakes import ORIGIN, RP_ID, Authenticator

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def configured(settings):
    settings.PASSKEY_RP_ID = RP_ID
    settings.PASSKEY_ORIGINS = [ORIGIN]


def post_json(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


def register(client, authenticator, name="Pixel 7"):
    """Add the authenticator's passkey to the signed-in account, the way the account page does."""
    options = client.post(reverse("account:passkey_options")).json()
    return post_json(
        client, reverse("account:passkey_add"), {"name": name, "credential": authenticator.register(options)}
    )


def sign_in(client, authenticator, user, **kwargs):
    options = client.post(reverse("accounts:passkey_options")).json()
    credential = authenticator.sign_in(options, user_handle=user.pk.bytes, **kwargs)
    return post_json(client, reverse("accounts:passkey_login"), {"credential": credential, "next": "/tasks/"})


@pytest.fixture
def signed_up(client, user):
    """A user with one passkey, and the authenticator that holds it. The client is signed out again."""
    client.force_login(user)
    authenticator = Authenticator()
    assert register(client, authenticator).status_code == 200
    client.logout()
    return authenticator


# The login page


def test_login_page_offers_passkeys_below_the_password_login(client, user):
    page = client.get(reverse("accounts:login")).text

    assert "Mit Passkey anmelden" in page
    assert 'data-options-url="/accounts/login/passkey/options/"' in page
    # Between the password button and the other ways in, with a line that says "or".
    assert page.index("Anmelden</button>") < page.index('role="separator"') < page.index("Mit Passkey anmelden")


def test_login_page_without_a_domain_has_no_passkeys(client, user, settings):
    settings.PASSKEY_RP_ID = ""
    settings.PASSKEY_ORIGINS = []

    page = client.get(reverse("accounts:login")).text

    assert "Passkey" not in page
    assert 'role="separator"' not in page
    assert client.post(reverse("accounts:passkey_options")).status_code == 404
    assert client.post(reverse("accounts:passkey_login")).status_code == 404


def test_passkey_options_ask_for_a_discoverable_credential_with_user_verification(client, user):
    options = client.post(reverse("accounts:passkey_options")).json()

    assert options["rpId"] == RP_ID
    assert options["userVerification"] == "required"
    assert options.get("allowCredentials", []) == []


# Adding a passkey


def test_adding_a_passkey(client, user):
    client.force_login(user)

    response = register(client, Authenticator(synced=True), name="Pixel 7")

    assert response.status_code == 200
    assert response.json()["redirect"] == "/account/?tab=security"
    passkey = user.passkeys.get()
    assert (passkey.name, passkey.synced) == ("Pixel 7", True)
    assert passkey.last_used_at is None


def test_registration_options_exclude_the_passkeys_the_account_has(client, user):
    client.force_login(user)
    authenticator = Authenticator()
    register(client, authenticator)

    options = client.post(reverse("account:passkey_options")).json()

    assert [c["id"] for c in options["excludeCredentials"]] == [user.passkeys.get().credential_id]
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"


def test_adding_a_passkey_needs_a_login(client, user):
    response = client.post(reverse("account:passkey_options"))

    assert response.status_code == 302


def test_a_passkey_from_another_origin_is_not_added(client, user):
    client.force_login(user)
    options = client.post(reverse("account:passkey_options")).json()

    response = post_json(
        client,
        reverse("account:passkey_add"),
        {"credential": Authenticator().register(options, origin="https://evil.example")},
    )

    assert response.status_code == 400
    assert not Passkey.objects.exists()


def test_a_passkey_checked_without_user_verification_is_not_added(client, user):
    client.force_login(user)
    options = client.post(reverse("account:passkey_options")).json()

    response = post_json(
        client, reverse("account:passkey_add"), {"credential": Authenticator().register(options, verified=False)}
    )

    assert response.status_code == 400


def test_the_same_passkey_is_not_added_twice(client, user):
    client.force_login(user)
    authenticator = Authenticator()
    register(client, authenticator)

    assert register(client, authenticator, name="Nochmal").status_code == 400
    assert user.passkeys.count() == 1


def test_a_registration_answer_needs_the_challenge_that_was_asked(client, user):
    client.force_login(user)
    answer = Authenticator().register(client.post(reverse("account:passkey_options")).json())

    # The challenge is used up by the first try, even a failed one.
    post_json(client, reverse("account:passkey_add"), {"credential": {**answer, "id": "x"}})
    assert post_json(client, reverse("account:passkey_add"), {"credential": answer}).status_code == 400


def test_the_name_of_a_passkey_is_cut_to_its_length(client, user):
    client.force_login(user)

    register(client, Authenticator(), name="x" * 300)

    assert len(user.passkeys.get().name) == passkeys.NAME_MAX_LENGTH


# Signing in


def test_signing_in_with_a_passkey(client, user, signed_up):
    response = sign_in(client, signed_up, user)

    assert response.status_code == 200
    assert response.json()["redirect"] == "/tasks/"
    assert client.get(reverse("core:dashboard")).status_code == 200
    passkey = user.passkeys.get()
    assert passkey.last_used_at is not None
    assert passkey.sign_count == 1


def test_a_passkey_replaces_the_code_of_the_authenticator_app(client, user, signed_up):
    device = mfa.pending_device(user)
    device.confirmed = True
    device.save()

    assert sign_in(client, signed_up, user).status_code == 200
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_redirects_to_other_sites_are_ignored(client, user, signed_up):
    options = client.post(reverse("accounts:passkey_options")).json()
    credential = signed_up.sign_in(options)

    response = post_json(
        client, reverse("accounts:passkey_login"), {"credential": credential, "next": "https://evil.example/"}
    )

    assert response.json()["redirect"] == "/"


def test_an_unknown_passkey_does_not_sign_in(client, user, signed_up):
    response = sign_in(client, Authenticator(), user)

    assert response.status_code == 400
    assert "Passkey" in response.json()["error"]
    assert client.get(reverse("core:dashboard")).status_code == 302
    assert LoginFailure.objects.count() == 1


def test_a_passkey_from_another_origin_does_not_sign_in(client, user, signed_up):
    assert sign_in(client, signed_up, user, origin="https://evil.example").status_code == 400


def test_a_signature_without_user_verification_does_not_sign_in(client, user, signed_up):
    assert sign_in(client, signed_up, user, verified=False).status_code == 400


def test_an_answer_cannot_be_used_twice(client, user, signed_up):
    options = client.post(reverse("accounts:passkey_options")).json()
    credential = signed_up.sign_in(options)
    assert post_json(client, reverse("accounts:passkey_login"), {"credential": credential}).status_code == 200
    client.logout()

    assert post_json(client, reverse("accounts:passkey_login"), {"credential": credential}).status_code == 400


def test_an_answer_without_a_question_is_refused(client, user, signed_up):
    options = {"challenge": "AAAA"}

    response = post_json(
        client, reverse("accounts:passkey_login"), {"credential": signed_up.sign_in(options, user_handle=b"x")}
    )

    assert response.status_code == 400


def test_a_late_answer_is_refused(client, user, signed_up, monkeypatch):
    options = client.post(reverse("accounts:passkey_options")).json()
    monkeypatch.setattr(passkeys, "CHALLENGE_SECONDS", -1)

    response = post_json(client, reverse("accounts:passkey_login"), {"credential": signed_up.sign_in(options)})

    assert response.status_code == 400


def test_garbage_does_not_sign_in(client, user, signed_up):
    client.post(reverse("accounts:passkey_options"))

    for body in ({}, {"credential": "x"}, {"credential": {"id": 1}}):
        assert post_json(client, reverse("accounts:passkey_login"), body).status_code == 400
    assert (
        client.post(reverse("accounts:passkey_login"), "nonsense", content_type="application/json").status_code == 400
    )


def test_an_inactive_account_does_not_sign_in(client, user, signed_up):
    user.is_active = False
    user.save()

    assert sign_in(client, signed_up, user).status_code == 400


def test_too_many_failures_lock_the_passkey_login(client, user, signed_up):
    settings = AppSettings.load()
    settings.login_max_attempts = 2
    settings.save()
    for _ in range(2):
        sign_in(client, Authenticator(), user)

    response = sign_in(client, signed_up, user)

    assert response.status_code == 429
    assert "Zu viele Fehlversuche" in response.json()["error"]


def test_signing_in_clears_the_failures_of_the_account(client, user, signed_up):
    LoginFailure.objects.create(ip_address="127.0.0.1", username="kim")

    sign_in(client, signed_up, user)

    assert not LoginFailure.objects.exists()


# The account page


def test_account_page_lists_the_passkeys(client, user):
    client.force_login(user)
    register(client, Authenticator(), name="Pixel 7")

    page = client.get(reverse("account:settings")).text

    assert "Pixel 7" in page
    assert "noch nicht benutzt" in page
    assert 'data-options-url="/account/passkeys/options/"' in page
    assert "Passkey hinzufügen" in page


def test_account_page_tells_the_administrator_how_to_turn_passkeys_on(client, user, settings):
    settings.PASSKEY_RP_ID = ""
    settings.PASSKEY_ORIGINS = []
    user.role = User.Role.ADMIN
    user.save()
    client.force_login(user)

    page = client.get(reverse("account:settings")).text

    assert "APP_PASSKEY_RP_ID" in page
    assert "Passkey hinzufügen" not in page


def test_account_page_without_a_domain_shows_others_nothing(client, user, settings):
    settings.PASSKEY_RP_ID = ""
    settings.PASSKEY_ORIGINS = []
    user.role = User.Role.EMPLOYEE
    user.save()
    client.force_login(user)

    assert "Passkey" not in client.get(reverse("account:settings")).text


def test_removing_a_passkey(client, user, signed_up):
    client.force_login(user)
    passkey = user.passkeys.get()

    response = client.post(reverse("account:passkey_remove", args=[passkey.pk]))

    assert response.status_code == 302
    assert not Passkey.objects.exists()
    # It no longer signs in.
    client.logout()
    assert sign_in(client, signed_up, user).status_code == 400


def test_nobody_removes_the_passkey_of_another_account(client, user, signed_up):
    other = User.objects.create_user(username="other", password="geheim-123")
    client.force_login(other)

    response = client.post(reverse("account:passkey_remove", args=[user.passkeys.get().pk]))

    assert response.status_code == 404
    assert Passkey.objects.count() == 1


def test_removing_a_passkey_needs_post(client, user, signed_up):
    client.force_login(user)

    assert client.get(reverse("account:passkey_remove", args=[user.passkeys.get().pk])).status_code == 405


def test_deleting_the_account_deletes_its_passkeys(user, signed_up):
    user.delete()

    assert not Passkey.objects.exists()
