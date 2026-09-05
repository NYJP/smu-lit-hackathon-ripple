"""PRD section 11: "Scoping is one function. access.visible_document_ids(user)
and the two role checks are the only place ownership is consulted. No
router may filter by owner_id itself. A test asserts that every router
module importing document-touching queries also imports access."

This is a static discipline check, not a behavioural one: any router source
file that references `owner_id` directly must also import `api.access`, so
a future contributor cannot quietly add a second, unscoped `WHERE owner_id
= ?` path without this test failing.
"""

from __future__ import annotations

from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "api" / "routers"


def test_every_router_touching_owner_id_imports_access():
    offenders = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "owner_id" not in source:
            continue
        imports_access = (
            "from api.access import" in source
            or "from api import access" in source
            or "import api.access" in source
        )
        if not imports_access:
            offenders.append(path.name)
    assert not offenders, (
        f"Router module(s) reference owner_id without importing api.access: {offenders}. "
        "Every document-touching query must route through access.visible_document_ids "
        "(or the other access.py helpers) — see PRD section 11."
    )


def test_access_module_is_the_only_place_defining_visible_document_ids():
    """A cheap guard against a second accessor being introduced elsewhere."""
    api_dir = ROUTERS_DIR.parent
    definitions = []
    for path in api_dir.rglob("*.py"):
        if path.name == "__pycache__":
            continue
        source = path.read_text(encoding="utf-8")
        if "def visible_document_ids(" in source:
            definitions.append(path.relative_to(api_dir))
    assert definitions == [Path("access.py")]
