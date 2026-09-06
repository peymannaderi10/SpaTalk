"""`spatalk serve` exports `.env` into the process and refuses a key whose value is a note.

Two findings from the 2026-09-05 demo, both configuration that looked right and was not.
`SKINCENTRIX_STAFF_SMS` was in `.env` and never reached `os.environ`, so the delivery job,
which reads a destination's address by environment-variable name, texted nobody. And
`TELNYX_PUBLIC_KEY=   # the key from the portal` was read as the comment: python-dotenv and
Docker Compose both take `KEY=   # note` to mean the note, so an "empty" key carried a
sentence and every signature check failed.
"""

from __future__ import annotations

import os


def test_export_env_file_puts_the_file_keys_into_the_environment_without_overriding(tmp_path, monkeypatch):
    from spatalk.settings import export_env_file

    monkeypatch.delenv("SPATALK_NO_ENV_FILE", raising=False)
    monkeypatch.delenv("SPATALK_TEST_EXPORTED", raising=False)
    monkeypatch.setenv("SPATALK_TEST_KEPT", "from-the-process")
    env = tmp_path / ".env"
    env.write_text(
        "SPATALK_TEST_EXPORTED=+14375550100\nSPATALK_TEST_KEPT=from-the-file\n", encoding="utf-8"
    )
    assert export_env_file(env) == ["SPATALK_TEST_EXPORTED"]
    assert os.environ["SPATALK_TEST_EXPORTED"] == "+14375550100"
    # What the process already carries wins: Compose's DATABASE_URL over the file's.
    assert os.environ["SPATALK_TEST_KEPT"] == "from-the-process"
    monkeypatch.delenv("SPATALK_TEST_EXPORTED")


def test_export_env_file_is_a_no_op_without_a_file_or_when_the_file_is_disabled(tmp_path, monkeypatch):
    from spatalk.settings import export_env_file

    monkeypatch.delenv("SPATALK_NO_ENV_FILE", raising=False)
    assert export_env_file(tmp_path / "missing.env") == []
    (tmp_path / ".env").write_text("SPATALK_TEST_DISABLED=1\n", encoding="utf-8")
    monkeypatch.setenv("SPATALK_NO_ENV_FILE", "1")
    monkeypatch.delenv("SPATALK_TEST_DISABLED", raising=False)
    assert export_env_file(tmp_path / ".env") == []
    assert "SPATALK_TEST_DISABLED" not in os.environ


def test_comment_valued_names_the_keys_whose_value_is_a_note():
    from spatalk.settings import comment_valued

    env = {
        "TELNYX_PUBLIC_KEY": "# the key from the portal",
        "ACCENT": "#0f766e",  # a colour is a value, not a note
        "EMPTY": "",
        "REAL": "dQBIFEaABEyUhZ9VI3uixTGt1TO5JSLmvuFVK8jrGqg=",
        "BARE_HASH": "#",
        "INDENTED": "   # also the HMAC key",
    }
    assert comment_valued(env) == ["BARE_HASH", "INDENTED", "TELNYX_PUBLIC_KEY"]


def test_serve_refuses_to_start_on_a_note_valued_key_and_names_it(monkeypatch):
    import uvicorn
    from typer.testing import CliRunner

    from spatalk.cli import app

    started: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.append(kw))
    monkeypatch.setenv("SPATALK_TEST_NOTE", "# any string; echoed back on the hub handshake")
    result = CliRunner().invoke(app, ["serve"])
    assert result.exit_code == 2, result.output
    assert "SPATALK_TEST_NOTE" in result.output
    assert "own line" in result.output
    assert started == []


def test_serve_starts_uvicorn_when_the_environment_is_clean(monkeypatch):
    import uvicorn
    from typer.testing import CliRunner

    from spatalk.cli import app

    started: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.append(kw))
    result = CliRunner().invoke(app, ["serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert started and started[0]["port"] == 8123


def test_the_commit_the_image_baked_survives_an_empty_environment_line(tmp_path, monkeypatch):
    import spatalk.settings as settings_module
    from spatalk.settings import Settings

    marker = tmp_path / "GIT_COMMIT"
    monkeypatch.setattr(settings_module, "BAKED_COMMIT_FILE", marker)
    monkeypatch.setenv("GIT_COMMIT", "")  # what Compose injects from a copied `.env.example`
    assert Settings(_env_file=None).git_commit == ""
    marker.write_text("5e3064a\n", encoding="utf-8")
    assert Settings(_env_file=None).git_commit == "5e3064a"
    # An explicit value still wins over the marker.
    monkeypatch.setenv("GIT_COMMIT", "abc1234")
    assert Settings(_env_file=None).git_commit == "abc1234"
