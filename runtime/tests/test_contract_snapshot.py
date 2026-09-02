"""The OpenAPI contract the portal generates its client from (portal plan, Task C3).

`docs/contracts/runtime-internal.openapi.json` is a committed snapshot: the portal's
`client.ts` is generated from it and CI checks both directions for drift. If this test
fails, the contract changed; regenerate it deliberately with `spatalk openapi --internal`.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTRACT = (
    Path(__file__).resolve().parents[2] / "docs" / "contracts" / "runtime-internal.openapi.json"
)


def _generated() -> dict:
    from spatalk.http.internal import openapi_document

    return openapi_document(internal_only=True)


def test_the_generated_document_contains_only_internal_paths():
    doc = _generated()
    assert doc["paths"], "no paths in the generated contract"
    assert all(p.startswith("/internal") for p in doc["paths"])
    assert "/healthz" not in doc["paths"]


def test_the_generated_document_covers_every_endpoint_the_portal_needs():
    paths = set(_generated()["paths"])
    assert {
        "/internal/tenants",
        "/internal/tenants/from-bundle",
        "/internal/tenants/{tenant_id}/config",
        "/internal/tenants/{tenant_id}/config/versions",
        "/internal/tenants/{tenant_id}/config/rollback",
        "/internal/tenants/{tenant_id}/usage",
        "/internal/tenants/{tenant_id}/conversations",
        "/internal/tenants/{tenant_id}/items",
        "/internal/tenants/{tenant_id}/latency",
        "/internal/tenants/{tenant_id}/health",
        "/internal/conversations/{conversation_id}",
        "/internal/items/{item_id}/acknowledge",
        "/internal/items/{item_id}/resolve",
        "/internal/schema/tenant-config",
        "/internal/health",
        "/internal/rates",
        "/internal/audit",
    } <= paths


def test_every_schema_reference_in_the_generated_document_resolves():
    doc = _generated()
    defined = set(doc.get("components", {}).get("schemas", {}))
    refs: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                refs.add(ref.rsplit("/", 1)[-1])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    assert refs <= defined, f"dangling refs: {sorted(refs - defined)}"
    assert defined <= refs, f"unused schemas kept in the contract: {sorted(defined - refs)}"


def test_the_committed_contract_matches_the_generated_document():
    assert CONTRACT.exists(), f"{CONTRACT} is not committed"
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == _generated(), (
        "the runtime's /internal contract drifted from the committed snapshot; "
        "regenerate it with `spatalk openapi --internal`"
    )


def test_the_cli_prints_the_same_document():
    from typer.testing import CliRunner

    from spatalk.cli import app

    result = CliRunner().invoke(app, ["openapi", "--internal"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == _generated()
