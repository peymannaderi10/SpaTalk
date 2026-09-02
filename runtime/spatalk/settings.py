from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
