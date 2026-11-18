from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import (
    ApiError,
    ERROR_SPECS,
    ErrorCode,
    Envelope,
    error_response,
    ok_response,
)
from app.config import load_config
from app.main import create_app


class EnvelopeTest(unittest.TestCase):
    def test_error_code_table_is_single_source(self) -> None:
        self.assertEqual(len(ERROR_SPECS), len(ErrorCode))
        codes = {spec.code.value for spec in ERROR_SPECS.values()}
        self.assertEqual(len(codes), len(ErrorCode))
        for code in ErrorCode:
            self.assertIn(code, ERROR_SPECS)
        for code in (
            ErrorCode.RECALC_CONFLICT,
            ErrorCode.RECALC_FAILED,
            ErrorCode.DEFINITION_MISSING,
            ErrorCode.REPORT_INCONSISTENT,
            ErrorCode.SNAPSHOT_INTEGRITY,
        ):
            self.assertIn(code, ERROR_SPECS)
        self.assertEqual(ERROR_SPECS[ErrorCode.RECALC_CONFLICT].http_status, 409)
        self.assertEqual(ERROR_SPECS[ErrorCode.RECALC_FAILED].http_status, 500)
        self.assertEqual(ERROR_SPECS[ErrorCode.DEFINITION_MISSING].http_status, 422)
        for code in (
            ErrorCode.SELFCHECK_LOCKED,
            ErrorCode.SELFCHECK_TIMEOUT,
            ErrorCode.SELFCHECK_READONLY_VIOLATION,
            ErrorCode.SELFCHECK_REPORT_WRITE_FAILED,
            ErrorCode.SELFCHECK_BASELINE_INVALID,
            ErrorCode.SELFCHECK_MANUAL_PENDING,
        ):
            self.assertIn(code, ERROR_SPECS)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_LOCKED].http_status, 409)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_TIMEOUT].http_status, 504)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_READONLY_VIOLATION].http_status, 500)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_REPORT_WRITE_FAILED].http_status, 500)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_BASELINE_INVALID].http_status, 422)
        self.assertEqual(ERROR_SPECS[ErrorCode.SELFCHECK_MANUAL_PENDING].http_status, 422)

    def test_http_status_mapping(self) -> None:
        self.assertEqual(ERROR_SPECS[ErrorCode.NOT_NORMALIZED].http_status, 422)
        self.assertEqual(ERROR_SPECS[ErrorCode.OUT_OF_SCOPE].http_status, 202)
        self.assertEqual(ERROR_SPECS[ErrorCode.NO_VERDICT].http_status, 409)
        self.assertEqual(ERROR_SPECS[ErrorCode.CIRCUIT_OPEN].http_status, 423)
        self.assertEqual(ERROR_SPECS[ErrorCode.GATE_TIMEOUT].http_status, 504)
        self.assertEqual(ERROR_SPECS[ErrorCode.CREDENTIAL_RISK].http_status, 500)

    def test_ok_envelope(self) -> None:
        envelope = ok_response({"status": "ok"}, trace_id="t-1")
        self.assertEqual(envelope.code, 0)
        self.assertEqual(envelope.trace_id, "t-1")

    def test_error_envelope_keeps_code(self) -> None:
        error = ApiError(ErrorCode.IDEMPOTENT_HIT, "fingerprint exists")
        payload = error_response(error, "t-2")
        self.assertEqual(payload.code, "VF-1003")
        self.assertIn("幂等命中", payload.message)
        self.assertIsNone(payload.data)

    def test_api_error_http_status(self) -> None:
        self.assertEqual(ApiError(ErrorCode.BACKDOOR).http_status, 403)

    def test_healthz_returns_envelope_and_trace(self) -> None:
        config = load_config()
        client = TestClient(create_app(config))
        response = client.get("/healthz", headers={"x-trace-id": "trace-health"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["trace_id"], "trace-health")
        self.assertEqual(body["data"]["brand"], config.product.brand)
        self.assertEqual(body["data"]["release_auto_branch"], "release/auto")
        self.assertEqual(response.headers.get("x-trace-id"), "trace-health")

    def test_unexpected_exception_is_wrapped(self) -> None:
        config = load_config()
        app = create_app(config)
        app.router.routes = [route for route in app.router.routes if getattr(route, "name", None) != "console"]

        @app.get("/boom")
        async def boom():
            raise RuntimeError("kaboom")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], "VF-0000")

    def test_envelope_is_generic(self) -> None:
        envelope = Envelope[int](code=0, data=42)
        self.assertEqual(envelope.data, 42)


if __name__ == "__main__":
    unittest.main()