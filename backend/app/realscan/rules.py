import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    defect_class: str
    anchor: str
    severity: str
    cve_ref: str
    source_ref: str
    mask_output: bool = False


@dataclass(frozen=True)
class Advisory:
    component: str
    affected: str
    fixed: str
    cve: str
    source_ref: str


RULES = (
    Rule(
        rule_id="C02-SQL",
        defect_class="C02",
        anchor="ast.Call(func=execute)",
        severity="high",
        cve_ref="",
        source_ref="CWE-89",
    ),
    Rule(
        rule_id="C03-CMD",
        defect_class="C03",
        anchor="os.popen|subprocess(shell=True)",
        severity="high",
        cve_ref="",
        source_ref="CWE-78",
    ),
    Rule(
        rule_id="C01-DEP",
        defect_class="C01",
        anchor="requirements.pin",
        severity="medium",
        cve_ref="see ADVISORIES",
        source_ref="public advisory table",
    ),
    Rule(
        rule_id="C05-CRED",
        defect_class="C05",
        anchor="ast.Assign(upper_sensitive_name, constant)",
        severity="high",
        cve_ref="",
        source_ref="CWE-798",
        mask_output=True,
    ),
)

ADVISORIES = (
    Advisory("requests", "2.19.1", "2.20.0", "CVE-2018-18074", "NVD:CVE-2018-18074"),
    Advisory("PyYAML", "5.1", "5.3.1", "CVE-2020-1747", "NVD:CVE-2020-1747"),
    Advisory("Jinja2", "2.10.1", "2.11.3", "CVE-2020-28493", "NVD:CVE-2020-28493"),
)

SENSITIVE_NAME = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY)", re.IGNORECASE)
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
PIN_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([0-9][0-9A-Za-z_.\-]*)\s*$")


def version_tuple(value):
    parts = []
    for chunk in re.split(r"[.\-+]", str(value)):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(0)
    return tuple(parts)


def verify_advisories(advisories=None):
    errors = []
    for advisory in advisories or ADVISORIES:
        if not advisory.component:
            errors.append("advisory component must not be empty")
        if not CVE_PATTERN.match(advisory.cve):
            errors.append("advisory cve format invalid: " + str(advisory.cve))
        if not advisory.source_ref:
            errors.append("advisory source_ref must not be empty")
        if version_tuple(advisory.affected) >= version_tuple(advisory.fixed):
            errors.append("advisory version range must be increasing: " + advisory.component)
    return errors


def match_pin(name, version, advisories=None):
    hits = []
    for advisory in advisories or ADVISORIES:
        if advisory.component.lower() != str(name).lower():
            continue
        if version_tuple(version) == version_tuple(advisory.affected):
            hits.append(advisory)
        elif version_tuple(version) < version_tuple(advisory.affected):
            hits.append(advisory)
    return hits