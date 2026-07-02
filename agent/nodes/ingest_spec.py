"""ingest_spec node: parse /openapi.json into endpoint specs (no LLM, no probing).

Spec only ingest (ADR-0001: live probing is a later phase). Fetches the OpenAPI
document from the running SUT if the runner did not already put it in state, then
flattens paths x methods into ``EndpointSpec`` records, resolving request body
field names one ref deep.
"""

from __future__ import annotations

import httpx

from ..schemas import EndpointSpec
from ..state import AgentState


def _resolve_body_fields(operation: dict, components: dict) -> list[str]:
    body = operation.get("requestBody")
    if not body:
        return []
    content = body.get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    ref = schema.get("$ref")
    if ref:
        name = ref.split("/")[-1]
        schema = components.get("schemas", {}).get(name, {})
    return sorted(schema.get("properties", {}).keys())


def _parse_endpoints(spec: dict) -> list[EndpointSpec]:
    components = spec.get("components", {})
    endpoints: list[EndpointSpec] = []
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            endpoints.append(
                EndpointSpec(
                    operation_id=operation_id,
                    http_method=method.upper(),
                    path=path,
                    summary=operation.get("summary", ""),
                    description=operation.get("description", ""),
                    body_fields=_resolve_body_fields(operation, components),
                )
            )
    return sorted(endpoints, key=lambda e: e.operation_id)


def ingest_spec(state: AgentState, deps) -> dict:
    spec = state.get("openapi_spec")
    if not spec:
        base = state["sut_base_url"].rstrip("/")
        response = httpx.get(f"{base}/openapi.json", timeout=15.0)
        response.raise_for_status()
        spec = response.json()
    endpoints = _parse_endpoints(spec)
    return {
        "openapi_spec": spec,
        "endpoints": endpoints,
        "history": [f"ingest_spec: parsed {len(endpoints)} operations from OpenAPI"],
    }
