from __future__ import annotations

import json
from pathlib import Path

import yaml

from .schema import TenantConfig

FILES = ("tenant.yaml", "services.yaml", "knowledge.md", "scripts.yaml", "guard.yaml")


def load_bundle(path: Path) -> TenantConfig:
    path = Path(path)
    missing = [f for f in FILES if not (path / f).exists()]
    if missing:
        raise ValueError(f"bundle {path} missing {missing}")
    tenant = yaml.safe_load((path / "tenant.yaml").read_text(encoding="utf-8"))
    services = yaml.safe_load((path / "services.yaml").read_text(encoding="utf-8"))
    scripts = yaml.safe_load((path / "scripts.yaml").read_text(encoding="utf-8"))
    guard = yaml.safe_load((path / "guard.yaml").read_text(encoding="utf-8")) or {}
    knowledge = (path / "knowledge.md").read_text(encoding="utf-8")
    data = {
        **tenant,
        "services": services["services"],
        "scripts": scripts,
        "lexicons": guard,
        "knowledge": knowledge,
    }
    try:
        return TenantConfig.model_validate(data)
    except Exception as e:  # pydantic ValidationError is a ValueError subclass
        raise ValueError(f"invalid bundle {path}: {e}") from e


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
