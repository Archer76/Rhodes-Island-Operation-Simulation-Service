"""Fail-closed release gate for the sole stdout machine report (no human fallback)."""
from __future__ import annotations

import json

PREFIX = "RIOS_SELFTEST_REPORT="


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _ids(value, label: str) -> list[str]:
    _require(isinstance(value, list) and bool(value), label + ": expected nonempty ID list")
    _require(all(isinstance(x, str) and x.strip() for x in value), label + ": invalid ID")
    _require(len(value) == len(set(value)), label + ": duplicate ID")
    return value


def _integer(value, label: str) -> int:
    _require(type(value) is int and value >= 0, label + ": expected nonnegative integer")
    return value


def _object(value, label: str) -> dict:
    _require(isinstance(value, dict), label + ": expected object")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "report JSON: duplicate field " + key)
        result[key] = value
    return result


def validate_selftest(stdout: str, returncode: int, manifest: dict) -> dict:
    """Return the validated report or raise a named ValueError on any rejection.

    Expected IDs come exclusively from the independently loaded static manifest.
    Inventory entries are static callsites, not runtime check counts; prerequisites
    has no callsite. Required callsites match required_ids; error observations do
    not constitute successful-path acceptance obligations.
    """
    manifest = _object(manifest, "expected manifest")
    _require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
             "expected manifest: unknown schema_version")
    _require(manifest.get("profile") == "all-required", "expected manifest: wrong profile")
    expected = _ids(manifest.get("required_ids"), "expected required_ids")
    inventory = manifest.get("inventory")
    _require(isinstance(inventory, list) and bool(inventory), "expected inventory: missing or empty")
    inventory_ids = []
    required_callsites = set()
    for entry in inventory:
        entry = _object(entry, "expected inventory entry")
        _require(isinstance(entry.get("id"), str) and bool(entry["id"].strip()),
                 "expected inventory: invalid ID")
        inventory_ids.append(entry["id"])
        kind = entry.get("kind")
        _require(kind in ("required_callsite", "error_observation"), "expected inventory: unknown kind")
        if kind == "required_callsite":
            required_callsites.add(entry.get("id"))
        else:
            _require(entry.get("id") not in expected, "expected inventory: error_observation is required")
    _ids(inventory_ids, "expected inventory")
    _require(required_callsites == set(expected) - {"prerequisites"},
             "expected inventory: required callsites differ from required_ids")
    minimum_checks = _object(manifest.get("minimum_checks", {}), "expected minimum_checks")
    for cid, minimum in minimum_checks.items():
        _require(cid in expected, "expected minimum_checks: unknown required ID " + cid)
        _require(_integer(minimum, "expected minimum_checks " + cid) >= 1,
                 "expected minimum_checks " + cid + ": must be positive")
    _require(isinstance(stdout, str), "stdout: expected text")
    lines = [line for line in stdout.splitlines() if PREFIX in line]
    _require(len(lines) == 1, "stdout report prefix: expected exactly one line, got %d" % len(lines))
    _require(lines[0].startswith(PREFIX) and lines[0].count(PREFIX) == 1,
             "stdout report prefix: must start its own line")
    try:
        report = json.loads(lines[0][len(PREFIX):], object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise ValueError("report JSON: " + str(exc)) from exc
    report = _object(report, "report")
    _require(type(report.get("schema_version")) is int and report["schema_version"] == 1,
             "report: unknown schema_version")
    _require(report.get("profile") == "all-required", "report: wrong profile")
    _require(report.get("completed") is True, "report: incomplete (completed must be true)")
    _require(type(returncode) is int and returncode == 0, "process returncode: must be zero")
    _require(type(report.get("rc")) is int and report["rc"] == 0, "report rc: must be zero")
    _require(report.get("passed") is True, "report passed: must be true")
    _require(report.get("errors") == [], "report errors: missing or nonempty")
    reported_ids = _ids(report.get("manifest"), "report manifest")
    _require(set(reported_ids) == set(expected), "report manifest: IDs differ from static required_ids")
    cases = report.get("cases")
    _require(isinstance(cases, list), "report cases: expected list")
    case_ids = [_object(c, "case").get("id") for c in cases]
    _ids(case_ids, "report cases")
    _require(set(case_ids) == set(expected), "report cases: missing or unknown case ID")
    summary = dict.fromkeys(("pass", "fail", "skip", "exercised"), 0)
    for case in cases:
        label = "case " + case["id"]
        _require(case.get("required") is True, label + ": required must be true")
        _require(isinstance(case.get("name"), str) and bool(case["name"].strip()), label + ": missing name")
        _require(isinstance(case.get("reason"), str), label + ": missing reason")
        checks = case.get("checks")
        _require(isinstance(checks, list) and bool(checks), label + ": no checks exercised")
        exercised = failed = 0
        statuses = []
        for i, check in enumerate(checks):
            cl = label + " check %d" % i
            check = _object(check, cl)
            _require(check.get("case_id") == case["id"], cl + ": wrong case_id")
            _require(isinstance(check.get("name"), str) and bool(check["name"].strip()), cl + ": missing name")
            _require(isinstance(check.get("reason"), str), cl + ": missing reason")
            _require(isinstance(check.get("got"), str), cl + ": missing got")
            if "expected_false" in check:
                _require(type(check["expected_false"]) is bool, cl + ": invalid expected_false")
            status = check.get("status")
            _require(status in ("pass", "fail", "skip"), cl + ": invalid status")
            ex = _integer(check.get("exercised"), cl + " exercised")
            _require(ex in (0, 1), cl + ": exercised must be 0 or 1")
            if status == "pass":
                _require(ex == 1, cl + ": pass without exercise")
            if status == "skip":
                _require(ex == 0, cl + ": skip claims exercise")
            statuses.append(status)
            exercised += ex
            failed += status == "fail"
        status = "fail" if "fail" in statuses else "skip" if "skip" in statuses else "pass"
        _require(case.get("status") == status, label + ": status differs from checks")
        _require(_integer(case.get("check_count"), label + " check_count") == len(checks), label + ": check_count mismatch")
        _require(_integer(case.get("failed_checks"), label + " failed_checks") == failed, label + ": failed_checks mismatch")
        _require(_integer(case.get("exercised"), label + " exercised") == exercised, label + ": exercised mismatch")
        _require(status == "pass", label + ": required " + status + " rejected: " + case["reason"])
        minimum = minimum_checks.get(case["id"], 1)
        _require(exercised >= minimum, label + ": exercised below static minimum_checks %d" % minimum)
        summary[status] += 1
        summary["exercised"] += exercised
    actual = _object(report.get("summary"), "report summary")
    _require(set(actual) == set(summary), "report summary: fields mismatch")
    for key, value in summary.items():
        _require(_integer(actual[key], "summary " + key) == value, "summary " + key + ": recomputed mismatch")
    return report
