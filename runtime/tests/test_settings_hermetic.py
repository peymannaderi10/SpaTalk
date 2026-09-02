"""The suite must not inherit the developer's environment (QA gate B, finding 1).

``Settings`` reads ``.env`` because a running service should. A test run must not: on a
machine that holds a real Turnstile secret, a real edge key or a real Gemini key, the widget
and SMS tests took a different path from a clean checkout, and one of them posted the live
Turnstile secret to Cloudflare during ``pytest``. ``SPATALK_NO_ENV_FILE=1`` turns the dotenv
file off for good, ``tests/conftest.py`` sets it for the whole session, and every helper
passes ``_env_file=None`` as well.

These tests write a fully populated ``.env`` into a temporary directory and prove that none
of it reaches ``Settings``.
"""

import os

import pytest

DOTENV = """\
DATABASE_URL=postgresql+asyncpg://leaked:leaked@leaked:5432/leaked
TEST_DATABASE_URL=postgresql+asyncpg://leaked:leaked@leaked:5432/leaked_test
PUBLIC_BASE_URL=https://leaked.example.com
MEDIA_WS_HOST=leaked.example.com
SECRET_KEY=leaked-secret-key
TELNYX_API_KEY=leaked-telnyx-key
SONIOX_API_KEY=leaked-soniox-key
INWORLD_API_KEY=leaked-inworld-key
GOOGLE_API_KEY=leaked-google-key
LLM_MODEL=leaked-model
DEEPGRAM_API_KEY=leaked-deepgram-key
SLACK_SIGNING_SECRET=leaked-slack-signing-secret
SLACK_BOT_TOKEN=xoxb-leaked
EDGE_SHARED_KEY=leaked-edge-key
TELNYX_PUBLIC_KEY=leaked-telnyx-public-key
TURNSTILE_SITE_KEY=leaked-turnstile-site-key
TURNSTILE_SECRET_KEY=leaked-turnstile-secret-key
INTERNAL_API_KEY=leaked-internal-key
GIT_COMMIT=leakedcommit
INSTAGRAM_APP_ID=leaked-ig-app-id
INSTAGRAM_APP_SECRET=leaked-ig-app-secret
FACEBOOK_APP_ID=leaked-fb-app-id
FACEBOOK_APP_SECRET=leaked-fb-app-secret
META_TOKEN_ENCRYPTION_KEY=leaked-fernet-key
INSTAGRAM_WEBHOOK_VERIFY_TOKEN=leaked-verify-token
"""

# Every key the file above sets, paired with the settings field it would land on.
LEAKY_FIELDS = {
    "DATABASE_URL": "database_url",
    "TEST_DATABASE_URL": "test_database_url",
    "PUBLIC_BASE_URL": "public_base_url",
    "MEDIA_WS_HOST": "media_ws_host",
    "SECRET_KEY": "secret_key",
    "TELNYX_API_KEY": "telnyx_api_key",
    "SONIOX_API_KEY": "soniox_api_key",
    "INWORLD_API_KEY": "inworld_api_key",
    "GOOGLE_API_KEY": "google_api_key",
    "LLM_MODEL": "llm_model",
    "DEEPGRAM_API_KEY": "deepgram_api_key",
    "SLACK_SIGNING_SECRET": "slack_signing_secret",
    "SLACK_BOT_TOKEN": "slack_bot_token",
    "EDGE_SHARED_KEY": "edge_shared_key",
    "TELNYX_PUBLIC_KEY": "telnyx_public_key",
    "TURNSTILE_SITE_KEY": "turnstile_site_key",
    "TURNSTILE_SECRET_KEY": "turnstile_secret_key",
    "INTERNAL_API_KEY": "internal_api_key",
    "GIT_COMMIT": "git_commit",
    "INSTAGRAM_APP_ID": "instagram_app_id",
    "INSTAGRAM_APP_SECRET": "instagram_app_secret",
    "FACEBOOK_APP_ID": "facebook_app_id",
    "FACEBOOK_APP_SECRET": "facebook_app_secret",
    "META_TOKEN_ENCRYPTION_KEY": "meta_token_encryption_key",
    "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "instagram_webhook_verify_token",
}


@pytest.fixture
def populated_dotenv(tmp_path, monkeypatch):
    """A directory holding a full ``.env``, made the working directory, with the real process
    environment cleared of every key in it so only the file could supply a value."""
    (tmp_path / ".env").write_text(DOTENV, encoding="utf-8")
    for key in LEAKY_FIELDS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_the_dotenv_on_disk_is_the_only_possible_source_of_these_values(
    populated_dotenv, monkeypatch
):
    """Control: with the switch off the file really is found and really does leak.

    Without this the hermetic assertions below would pass against an empty file too.
    """
    from spatalk.settings import NO_ENV_FILE_VAR, Settings

    monkeypatch.delenv(NO_ENV_FILE_VAR, raising=False)
    leaked = Settings()
    assert leaked.turnstile_secret_key == "leaked-turnstile-secret-key"
    assert leaked.google_api_key == "leaked-google-key"
    assert leaked.edge_shared_key == "leaked-edge-key"


def test_the_switch_makes_settings_ignore_a_populated_dotenv(populated_dotenv):
    """The whole point: under SPATALK_NO_ENV_FILE=1, which conftest sets for the session,
    a fully populated .env on disk supplies not one value."""
    from spatalk.settings import NO_ENV_FILE_VAR, Settings

    assert os.environ.get(NO_ENV_FILE_VAR) == "1", "conftest must set the switch session-wide"

    settings = Settings()
    defaults = Settings.model_fields
    for env_key, field in LEAKY_FIELDS.items():
        value = getattr(settings, field)
        assert "leaked" not in str(value).lower(), f"{env_key} leaked in as {field}={value!r}"
        assert value == defaults[field].default, f"{field} is not its default"


def test_the_switch_leaves_every_field_a_helper_did_not_name_at_its_default(populated_dotenv):
    """A test helper naming one field still gets defaults for every field it did not name."""
    from spatalk.settings import Settings

    settings = Settings(secret_key="s3cret")
    assert settings.secret_key == "s3cret"
    assert settings.turnstile_secret_key == ""
    assert settings.edge_shared_key == ""
    assert settings.google_api_key == ""


def test_env_file_none_ignores_the_dotenv_even_without_the_switch(
    populated_dotenv, monkeypatch
):
    """Belt and braces: the argument every test helper now passes works on its own."""
    from spatalk.settings import NO_ENV_FILE_VAR, Settings

    monkeypatch.delenv(NO_ENV_FILE_VAR, raising=False)
    settings = Settings(_env_file=None, secret_key="s3cret")
    assert settings.turnstile_secret_key == ""
    assert settings.google_api_key == ""
    assert settings.edge_shared_key == ""


def test_real_environment_variables_still_win_under_the_switch(populated_dotenv, monkeypatch):
    """The switch turns off the *file*, not the environment: Docker and CI still configure
    the service the documented way."""
    from spatalk.settings import Settings

    monkeypatch.setenv("GOOGLE_API_KEY", "from-the-environment")
    assert Settings().google_api_key == "from-the-environment"


async def test_turnstile_verification_with_no_secret_never_touches_the_network():
    """An empty secret cannot verify anything, so it refuses without opening a socket.

    This is the other half of finding 1: on a machine whose .env held a live Turnstile
    secret, the widget tests posted it to Cloudflare during pytest.
    """
    import httpx

    from spatalk.text import chat

    # verify_turnstile swallows every exception and refuses, so a raising stub would look
    # like a pass. Record the attempt instead and assert nothing was recorded.
    attempts: list[tuple] = []

    def explode(*args, **kwargs):
        attempts.append((args, kwargs))
        raise RuntimeError("no network in tests")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", explode)
        assert await chat.verify_turnstile("any-token", "") is False
        assert await chat.verify_turnstile("", "") is False

    assert attempts == [], "verify_turnstile opened an HTTP client with no secret"


async def test_the_real_turnstile_call_is_bounded_by_a_five_second_timeout():
    """A hung Cloudflare must not hang a socket handshake for ever."""
    import httpx

    from spatalk.text import chat

    seen = {}

    class RecordingClient:
        def __init__(self, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None):
            seen["url"] = url
            return httpx.Response(200, json={"success": True})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx, "AsyncClient", RecordingClient)
        assert await chat.verify_turnstile("token", "a-secret") is True

    assert seen["timeout"] == 5.0
    assert seen["url"] == chat.TURNSTILE_VERIFY_URL
