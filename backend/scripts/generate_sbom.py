"""Generate a CycloneDX-style SBOM for Rakho's Python dependencies.

An SBOM answers "what is in this build" *after* something in the supply chain
turns out to be compromised, and it only answers it for builds that produced one
at the time. Generating it retroactively is not possible, which is the whole
reason this lives in CI rather than in a runbook.

Written by hand against the installed distribution metadata rather than pulled
from a third-party SBOM tool, for a specific reason: the CI runner installing a
scanner in order to inventory the supply chain is itself a supply-chain
dependency. The metadata is already on disk --- ``importlib.metadata`` reads it,
including each package's declared license and its recorded hash --- so the SBOM
can be produced with nothing installed.

Output: ``sbom/rakho-backend.cdx.json`` (CycloneDX 1.5, JSON).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path

#: The target of a CycloneDX document. Pinned to 1.5: it is what the common
#: scanners and the GitHub dependency-submission API accept.
SPEC_VERSION = "1.5"
OUTPUT = Path("sbom/rakho-backend.cdx.json")


def normalise(name: str) -> str:
    """PyPI's normalised distribution name (PEP 503).

    ``Foo.Bar_baz`` and ``foo-bar-baz`` are the same project, and an SBOM that
    lists both spellings as separate components would double-count advisories
    against them.
    """
    return name.lower().replace("_", "-").replace(".", "-")


def component_for(dist) -> dict:
    """One CycloneDX component from an installed distribution."""
    meta = dist.metadata
    name = normalise(meta["Name"])
    version = dist.version or "0.0.0"

    # ``direct_url.json`` is present only for things installed from a VCS or a
    # local path --- that is, the dependencies whose provenance is *not* PyPI,
    # which are exactly the ones worth recording a source for.
    external = []
    try:
        direct = json.loads(meta.get("direct_url.json") or "{}")
        url = direct.get("url")
        if url:
            external.append({"type": "distribution", "url": url})
    except Exception:  # noqa: BLE001 - provenance is a bonus, never a blocker
        pass

    component = {
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name}@{version}",
        "bom-ref": f"pkg:pypi/{name}@{version}",
    }
    if external:
        component["externalReferences"] = external

    license_name = _license_of(meta)
    if license_name:
        component["licenses"] = [{"license": {"name": license_name}}]

    return component


def _license_of(meta) -> str:
    """The distribution's license string, from either the modern or the old field."""
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    legacy = meta.get("License")
    if legacy and len(legacy) < 200 and "\n" not in legacy:
        # The legacy field is sometimes a whole license *text*; only short
        # values are a name, and a 3,000-word blob in a "name" field is noise.
        return legacy.strip()
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return ""


def build_document() -> dict:
    """The complete CycloneDX document."""
    components = sorted(
        (component_for(dist) for dist in distributions()),
        key=lambda item: (item["name"], item["version"]),
    )
    # Two distributions can normalise to the same name@version (a vendored copy
    # beside the real one); CycloneDX requires unique ``bom-ref``s.
    seen, unique = set(), []
    for component in components:
        if component["bom-ref"] in seen:
            continue
        seen.add(component["bom-ref"])
        unique.append(component)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{_serial(unique)}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": [{"vendor": "Rakho", "name": "generate_sbom", "version": "1.0"}],
            "component": {
                "type": "application",
                "name": "rakho-backend",
                "bom-ref": "rakho-backend",
            },
        },
        "components": unique,
    }


def _serial(components: list[dict]) -> str:
    """A stable UUID derived from the component set.

    Two builds of the same dependencies produce the same serial, which makes
    "did the dependency set actually change?" a question the SBOM can answer by
    comparison instead of by reading the whole file.
    """
    digest = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def main():
    document = build_document()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"SBOM written: {OUTPUT} ({len(document['components'])} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
