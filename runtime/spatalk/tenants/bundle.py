from __future__ import annotations

import json
from pathlib import Path

import yaml

from .schema import TenantConfig

FILES = ("tenant.yaml", "services.yaml", "knowledge.md", "scripts.yaml", "guard.yaml")


def config_from_texts(texts: dict[str, str], source: str = "bundle") -> TenantConfig:
    """The bundle rules applied to the five files' contents, whatever carried them here.

    `load_bundle` reads them from a directory; the portal uploads them to
    `POST /internal/tenants/from-bundle` (portal plan, Task C3). Both land here, so the
    two routes cannot drift apart.
    """
    missing = [f for f in FILES if f not in texts]
    if missing:
        raise ValueError(f"bundle {source} missing {missing}")
    try:
        tenant = yaml.safe_load(texts["tenant.yaml"]) or {}
        services = yaml.safe_load(texts["services.yaml"]) or {}
        scripts = yaml.safe_load(texts["scripts.yaml"]) or {}
        guard = yaml.safe_load(texts["guard.yaml"]) or {}
        data = {
            **tenant,
            "services": services["services"],
            "scripts": scripts,
            "lexicons": guard,
            "knowledge": texts["knowledge.md"],
        }
        return TenantConfig.model_validate(data)
    except Exception as e:  # pydantic ValidationError is a ValueError subclass
        raise ValueError(f"invalid bundle {source}: {e}") from e


def load_bundle(path: Path) -> TenantConfig:
    path = Path(path)
    missing = [f for f in FILES if not (path / f).exists()]
    if missing:
        raise ValueError(f"bundle {path} missing {missing}")
    texts = {f: (path / f).read_text(encoding="utf-8") for f in FILES}
    return config_from_texts(texts, source=str(path))


def config_to_json(cfg: TenantConfig) -> dict:
    return json.loads(cfg.model_dump_json())


def config_from_json(d: dict) -> TenantConfig:
    return TenantConfig.model_validate(d)


def export_bundle(cfg: TenantConfig, path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    d = config_to_json(cfg)
    services = {"services": d.pop("services")}
    scripts = d.pop("scripts")
    lexicons = d.pop("lexicons")
    knowledge = d.pop("knowledge")
    (path / "tenant.yaml").write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    (path / "services.yaml").write_text(yaml.safe_dump(services, sort_keys=False), encoding="utf-8")
    (path / "scripts.yaml").write_text(yaml.safe_dump(scripts, sort_keys=False), encoding="utf-8")
    (path / "guard.yaml").write_text(yaml.safe_dump(lexicons, sort_keys=False), encoding="utf-8")
    (path / "knowledge.md").write_text(knowledge, encoding="utf-8")
