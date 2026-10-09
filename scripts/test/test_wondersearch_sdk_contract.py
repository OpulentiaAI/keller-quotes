"""Optional pinned SDK contract tests; actual SDK, entirely synthetic MockTransport."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

if os.name != "posix":
    raise unittest.SkipTest("WonderSearch offline boundary requires POSIX file/lock semantics")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wondersearch_sdk_contract as contract
from wondersearch_boundary import BoundaryError, SDK_VERSION

DRIVE = "00000000-0000-4000-8000-000000000001"
FOLDER = "00000000-0000-4000-8000-000000000002"


class ContractTests(unittest.TestCase):
    def test_live_gate_closed_even_when_enabled(self):
        self.assertIsNone(contract.live_client())
        with self.assertRaisesRegex(BoundaryError, "LIVE_NOT_REVIEWED"):
            contract.live_client(enabled=True)

    def test_upload_mapping_preserves_order_scope_and_idempotency_without_wait_or_retry(self):
        client = Mock()
        paths = ["synthetic-b.pdf", "synthetic-a.pdf"]
        contract._upload_mapping(client, ordered_paths=paths, drive_id=DRIVE, folder_id=FOLDER, operation="synthetic-key")
        client.upload.assert_called_once_with(paths, drive_id=DRIVE, folder_id=FOLDER,
            idempotency_key="synthetic-key", concurrency=1, wait=False, timeout=900)

    @unittest.skipUnless(importlib.util.find_spec("wondersearch"), "optional pinned SDK is not installed")
    def test_actual_pinned_sdk_ask_routes_effort_and_folder_with_no_sockets(self):
        import httpx
        self.assertEqual(contract.version("wondersearch"), SDK_VERSION)
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, "api.wondersearch.ai")
            if request.method == "GET" and request.url.path == "/v1/sdk/context":
                return httpx.Response(200, json={"workspace_id": DRIVE, "default_drive_id": FOLDER})
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, f"/v1/drives/{DRIVE}/search")
            body = json.loads(request.content)
            self.assertEqual(body["folder_id"], FOLDER)
            self.assertEqual(body["effort"], "large")
            self.assertEqual(body["query"], "synthetic question")
            self.assertEqual(request.headers["Idempotency-Key"], "synthetic-key")
            return httpx.Response(200, json={"request_id": "synthetic-request", "drive_id": DRIVE,
                "results": [], "usage": {"cost": {"amount": "0.0025", "currency": "USD"}},
                "model": "wondersearch-1.1", "effort_requested": "large", "effort_served": "medium",
                "warnings": [], "unknown_additive": "must-not-forward"})
        with patch("socket.socket", side_effect=AssertionError("network prohibited")):
            with contract._synthetic_client(api_key="synthetic-key", drive_id=DRIVE,
                                             transport=httpx.MockTransport(handler)) as client:
                result = contract._search_mapping(client, query="synthetic question", drive_id=DRIVE,
                                folder_id=FOLDER, effort="large", operation="synthetic-key")
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["effort_served"], "medium")
        self.assertNotIn("unknown_additive", result)

    @unittest.skipUnless(importlib.util.find_spec("wondersearch"), "optional pinned SDK is not installed")
    def test_version_mismatch_and_real_transport_rejected(self):
        import httpx
        with patch.object(contract, "version", return_value="0.3.0"):
            with self.assertRaisesRegex(BoundaryError, "PIN_MISMATCH"):
                contract._synthetic_client(api_key="synthetic", drive_id=DRIVE, transport=httpx.MockTransport(lambda _: None))
        with self.assertRaisesRegex(BoundaryError, "LIVE_NOT_REVIEWED"):
            contract._synthetic_client(api_key="synthetic", drive_id=DRIVE, transport=object())


if __name__ == "__main__":
    unittest.main()
