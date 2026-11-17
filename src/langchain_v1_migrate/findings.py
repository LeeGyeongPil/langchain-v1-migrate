"""The things this tool reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass

#: code -> (slug, severity, fixable by ``fix``)
CODES: dict[str, tuple[str, str, bool]] = {
    "LCM001": ("import-moved", "info", True),
    "LCM002": ("import-split", "info", True),
    "LCM003": ("name-gone", "error", False),
    "LCM004": ("module-gone", "error", False),
    "LCM005": ("manual-import-form", "error", False),
    "LCM006": ("needs-community", "warning", False),
    "LCM007": ("needs-sqlalchemy-asyncio", "warning", False),
    "LCM008": ("hub-deprecated", "warning", False),
    "LCM009": ("legacy-api", "info", False),
    "LCM010": ("notebook-cell-skipped", "warning", False),
    "LCM011": ("parse-error", "error", False),
    "LCM012": ("old-pin", "warning", False),
    "LCM013": ("deps-missing", "warning", True),
}

SEVERITIES = ("error", "warning", "info")


@dataclass
class Finding:
    code: str
    path: str
    line: int
    col: int
    message: str
    old: str = ""
    new: str = ""
    severity: str = ""
    fixable: bool | None = None
    cell: int = 0  # 1-based notebook cell number, 0 for plain files

    def __post_init__(self) -> None:
        _slug, severity, fixable = CODES[self.code]
        if not self.severity:
            self.severity = severity
        if self.fixable is None:
            self.fixable = fixable

    def as_dict(self) -> dict:
        data = asdict(self)
        return {
            "code": data["code"],
            "severity": data["severity"],
            "fixable": data["fixable"],
            "path": data["path"],
            "line": data["line"],
            "cell": data["cell"],
            "col": data["col"],
            "message": data["message"],
            "old": data["old"],
            "new": data["new"],
        }


def summarize(findings: list[Finding], files: int) -> dict:
    return {
        "files": files,
        "fixable": sum(1 for f in findings if f.fixable),
        "errors": sum(1 for f in findings if f.severity == "error"),
        "warnings": sum(1 for f in findings if f.severity == "warning"),
        "info": sum(1 for f in findings if f.severity == "info"),
    }
