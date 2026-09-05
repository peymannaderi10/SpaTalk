import os
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- hermetic settings (QA gate B, finding 1) -------------------------------------------
# ``env_file=".env"`` is right for a running service and wrong for a test run: on a machine
# that holds real provider keys the suite would silently inherit them and behave differently
# from a clean checkout. With SPATALK_NO_ENV_FILE=1 in the environment, every ``Settings()``
# ignores the dotenv file entirely and reads only its defaults, explicit keyword arguments
# and real environment variables. tests/conftest.py sets it for the whole session.
NO_ENV_FILE_VAR = "SPATALK_NO_ENV_FILE"
_TRUTHY = {"1", "true", "yes", "on"}


def env_file_disabled() -> bool:
    """True when the environment explicitly forbids reading ``.env``."""
    return os.environ.get(NO_ENV_FILE_VAR, "").strip().lower() in _TRUTHY


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk"
    test_database_url: str = "postgresql+asyncpg://spatalk:spatalk@localhost:5434/spatalk_test"
    public_base_url: str = "http://localhost:8000"
    media_ws_host: str = "localhost:8000"
    secret_key: str = "dev-secret-change-me"

    telnyx_api_key: str = ""
    soniox_api_key: str = ""
    inworld_api_key: str = ""
    inworld_voice: str = "Ashley"
    inworld_model: str = "inworld-tts-2"
    soniox_voice: str = "Bryce"
    google_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    stt_provider: str = "soniox"
    tts_provider: str = "inworld"
    deepgram_api_key: str = ""

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_from: str = "frontdesk@localhost"
    slack_signing_secret: str = ""

    # --- text channels (text-channels plan, Task B2) ---
    # Shared secret the edge worker presents on forwarded webhooks.
    edge_shared_key: str = ""
    # Telnyx account public key (base64), used when no edge worker fronts the webhook.
    telnyx_public_key: str = ""

    # --- web chat widget (text-channels plan, Task B4) ---
    # Cloudflare Turnstile. The site key is public and is served to the widget; the secret
    # key is what makes the check real. With no secret key set, the socket does not challenge.
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""

    # --- portal control plane (portal plan, Task C3) ---
    # The shared key the portal presents on every /internal call. Empty means the internal
    # API refuses everyone: it fails closed, never open.
    internal_api_key: str = ""
    # The deployed revision, set by the Dockerfile and reported by /healthz so the agency
    # admin page can say what is running.
    git_commit: str = ""

    # --- human takeover (text-channels plan, Task B5) ---
    # With a bot token, item delivery opens a Slack thread per conversation and staff can
    # reply in it. Without one, delivery stays on the incoming webhook and there is no thread.
    slack_bot_token: str = ""

    # --- Instagram and Messenger (instagram plan, Task D1) ---
    # One Meta app per surface: Instagram Business Login and Facebook Login for Pages. The
    # secrets are also the webhook signing keys, which is why both are verified in D2.
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    # Fernet key for tokens at rest (spatalk.social.crypto). Empty means no Meta token can be
    # stored at all: encryption raises rather than writing one in the clear.
    meta_token_encryption_key: str = ""
    meta_graph_version: str = "v21.0"
    # The string Meta echoes back on `GET /instagram/webhook` (api-surface.md, plan D). It
    # lives here because settings.py belongs to this task and D2's webhook needs it.
    instagram_webhook_verify_token: str = ""

    # --- operations (operations plan, Task E4) --------------------------------------------
    # Where the nightly audit's report and every operational alert are sent. Empty means the
    # report is still computed and stored; only the email is skipped.
    ops_email: str = ""
    # The model that re-judges the day's bands. Flash with thinking enabled, not Pro:
    # gemini-2.5-pro answers 404 "no longer available to new users" on the founder's Google
    # AI Studio key (promptfoo run A, 2026-09-02), and a band judgement is an offline call
    # where reasoning time is free but a per-token price is not.
    # gemini-2.5-flash went 404 on the founder's key on 2026-09-05 ("no longer available to
    # new users"); the judge now runs on the same model as the voice path.
    judge_model: str = "gemini-3.5-flash-lite"

    # --- operations: monitoring and alerts (operations plan, Task E7) ---------------------
    # One SMS per incident per six hours, on top of the email. Empty means email only.
    # The number an alert is sent *from* is the first tenant SMS number the registry knows:
    # there is one Telnyx account and the runtime owns no separate operations number.
    ops_sms_number: str = ""
    # Sentry is initialised only when this is set, and never with PII: phone numbers and
    # email addresses are masked out of every event and breadcrumb before it leaves.
    sentry_dsn: str = ""
    # "json" makes loguru emit one JSON object per line, which is what a log shipper on the
    # VPS can read. Anything else keeps the human-readable console format.
    log_format: str = "text"

    # --- operations: the second LLM vendor (operations plan, Task E6) ---------------------
    # `llm_model` names the vendor as well as the model: a bare name is Google,
    # `openai:<model>` is OpenAI, in voice and in text alike. This key is needed only for
    # the second one, and the swap is `LLM_MODEL=openai:gpt-4.1-nano` plus this key
    # (docs/runbooks/model-swap.md).
    openai_api_key: str = ""

    # --- operations: LLM failover (llm failover plan, Tasks F1 and F2) ---------------------
    # The second model, in the same `vendor:model` syntax as `LLM_MODEL`. Empty is today's
    # behaviour exactly: one vendor, no failover, no second key needed. Set it to a model at
    # a *different* vendor (`LLM_MODEL_FALLBACK=openai:gpt-4.1-mini`) and every turn, on the
    # phone and on text, gets a second chance at another company when the first one fails.
    llm_model_fallback: str = ""
    # When a vendor is treated as down: this many failures inside the window, and it is not
    # tried again for the cooldown. Three in a minute is a dead vendor, not a bad minute
    # (founder call 2026-09-03: Google answered 503 for twenty minutes).
    llm_breaker_failures: int = 3
    llm_breaker_window_secs: int = 60
    llm_breaker_cooldown_secs: int = 300
    # One key per OpenAI-compatible vendor in `spatalk.brain.driver.VENDORS` (addendum,
    # founder decision 2026-09-03 ~21:40: the cheapest model must be an env value away).
    # All empty by default; a vendor `LLM_MODEL` does not name needs no key.
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    xai_api_key: str = ""
    groq_api_key: str = ""
    together_api_key: str = ""
    fireworks_api_key: str = ""
    dashscope_api_key: str = ""
    compat_api_key: str = ""
    # Each vendor's host, overriding the table's default, so a region change is an env value
    # too. `LLM_COMPAT_BASE_URL` is the only one with no default: `compat:` is the generic
    # OpenAI-compatible host and has nothing sensible to fall back to.
    llm_openai_base_url: str = ""
    llm_openrouter_base_url: str = ""
    llm_deepseek_base_url: str = ""
    llm_xai_base_url: str = ""
    llm_groq_base_url: str = ""
    llm_together_base_url: str = ""
    llm_fireworks_base_url: str = ""
    llm_dashscope_base_url: str = ""
    llm_compat_base_url: str = ""

    # --- whatsapp (plan W) ----------------------------------------------------------------
    # One platform number fronts every tenant at MVP: the id Meta assigns the WhatsApp
    # business number, and the token the Cloud API calls carry. Empty means the runtime has
    # no WhatsApp door at all, which is a working configuration, not an error.
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    # The HMAC key for POST /whatsapp/webhook and the string echoed back on the GET
    # handshake. The app secret is usually the same value as FACEBOOK_APP_SECRET.
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    # Approved message templates, used whenever the 24-hour window is shut. Names, not
    # wording: the wording lives in WhatsApp Manager and is what Meta approved.
    whatsapp_template_item: str = "front_desk_item"
    whatsapp_template_digest: str = "front_desk_digest"
    whatsapp_template_lang: str = "en"

    # --- hermetic settings (QA gate B, finding 1) -----------------------------------------
    def __init__(self, **values: Any) -> None:
        """Honour SPATALK_NO_ENV_FILE=1 by not reading ``.env`` at all.

        The switch is read at construction time, not at import time, so it works however
        early ``spatalk.settings`` happens to be imported. An explicit ``_env_file`` keyword
        always wins, which is what the tests pass as belt and braces.
        """
        if env_file_disabled():
            values.setdefault("_env_file", None)
        super().__init__(**values)


@lru_cache
def get_settings() -> Settings:
    return Settings()
