# Verify that the executable diagnostic catalog remains complete and internally consistent.
# 验证可执行诊断目录保持完整且内部一致。

import re

from laundry_contracts.fault_codes import DIAGNOSTIC_DEFINITIONS, DiagnosticCode, DiagnosticKind


def test_every_diagnostic_code_has_one_definition() -> None:
    assert set(DiagnosticCode) == set(DIAGNOSTIC_DEFINITIONS)


def test_diagnostic_codes_use_display_format() -> None:
    for code in DiagnosticCode:
        assert re.fullmatch(r"[WFSD][0-9]{4}", code.value)


def test_diagnostic_code_values_are_unique() -> None:
    code_values = [code.value for code in DiagnosticCode]

    assert len(code_values) == len(set(code_values))


def test_code_prefix_matches_diagnostic_kind() -> None:
    expected_kind_by_prefix = {
        "W": DiagnosticKind.WARNING,
        "F": DiagnosticKind.FAULT,
        "S": DiagnosticKind.SYSTEM_CONDITION,
        "D": DiagnosticKind.DATA_EVENT,
    }

    for code, definition in DIAGNOSTIC_DEFINITIONS.items():
        assert definition.kind is expected_kind_by_prefix[code.value[0]]
