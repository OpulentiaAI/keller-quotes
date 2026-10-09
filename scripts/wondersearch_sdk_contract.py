"""Pinned SDK request mapping, mock-testable but deliberately not a live executor.

The public entry point has an unconditional closed gate. The underscored mapping
functions accept an already-created synthetic client for SDK contract tests only.
They do NOT enforce budget, scope, or SDK retries; do not wire them to live HTTP.
"""
from importlib.metadata import version

from wondersearch_boundary import BASE_URL, SDK_VERSION, BoundaryError, require


def live_client(*, enabled=False):
    if not enabled:
        return None
    # No environment flag or supplied 'approved' boolean can open this gate.
    raise BoundaryError("LIVE_NOT_REVIEWED")


def _synthetic_client(*, api_key, drive_id, transport):
    """Only in-memory httpx.MockTransport is accepted, never a socket transport."""
    require(version("wondersearch") == SDK_VERSION, "PIN_MISMATCH")
    import httpx
    from wondersearch import WonderSearch
    require(type(transport) is httpx.MockTransport and bool(drive_id), "LIVE_NOT_REVIEWED")
    return WonderSearch(api_key=api_key, base_url=BASE_URL, drive_id=drive_id,
                        transport=transport, transfer_transport=transport, version_warnings=False)


def _search_mapping(client, *, query, drive_id, folder_id, effort, operation):
    require(bool(drive_id) and drive_id != "default", "SCOPE_REQUIRED")
    response = client.ask(query, drive_id=drive_id, folder_id=folder_id, effort=effort,
                          group_by_document=True, allow_degraded=False,
                          idempotency_key=operation, timeout=30, timeout_ms=20_000)
    # 0.2.0 stores requested/served effort in raw, not dataclass attributes.
    # Select known fields, never serialize the entire raw SDK response or repr.
    return {key: response.raw[key] for key in ("request_id", "drive_id", "model",
            "effort_requested", "effort_served", "usage", "results")}


def _upload_mapping(client, *, ordered_paths, drive_id, folder_id, operation):
    # Mapping only: a live importer additionally needs pinned originals, whole-doc
    # authorization, known charges/storage, durable receipts and no-retry guards.
    require(bool(drive_id) and drive_id != "default" and bool(ordered_paths), "SCOPE_REQUIRED")
    return client.upload(ordered_paths, drive_id=drive_id, folder_id=folder_id,
                         idempotency_key=operation, concurrency=1, wait=False, timeout=900)
