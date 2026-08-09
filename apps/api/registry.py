"""The catalogue of API endpoints — the single source of truth that drives the
scope checkboxes on the key-creation form, the docs/sample panel on the
settings tab, and the scope check in ``api.auth``.

Adding an endpoint later = add its view, then describe it here.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    description: str
    example: str
    required: bool = False


@dataclass(frozen=True)
class Endpoint:
    id: str  # scope identifier stored in ApiKey.scopes
    title: str
    description: str
    path: str  # URL path under the site root
    params: list[Param] = field(default_factory=list)
    # Query strings for the generated sample request, first one is shown.
    sample_query: str = ""
    scoped: bool = True  # False = any valid key may call it (utility endpoints)


ENDPOINTS: list[Endpoint] = [
    Endpoint(
        id="income",
        title="Income",
        description=(
            "Gross and net income per month across all workplaces, for one "
            "month, a whole year, or a range of months. Months are marked "
            "actual, planned or projected — the same numbers the Analytics "
            "page shows."
        ),
        path="/api/v1/income/",
        params=[
            Param("year", "A whole calendar year.", "2026"),
            Param("month", "One month of that year (needs year).", "7"),
            Param("start", "First month of a range, as YYYY-MM.", "2026-01"),
            Param("end", "Last month of a range, as YYYY-MM.", "2026-06"),
        ],
        sample_query="?start=2026-01&end=2026-06",
    ),
    Endpoint(
        id="ping",
        title="Ping",
        description=(
            "Checks that a key works and reports its name, scopes and expiry. "
            "Any valid key may call this — it needs no scope."
        ),
        path="/api/v1/ping/",
        scoped=False,
    ),
]


def scoped_endpoints() -> list[Endpoint]:
    return [ep for ep in ENDPOINTS if ep.scoped]


def valid_scope_ids() -> set[str]:
    return {ep.id for ep in scoped_endpoints()}


def sample_python(endpoint: Endpoint, base_url: str) -> str:
    """A ready-to-run stdlib-only Python snippet for calling ``endpoint``."""
    url = f"{base_url}{endpoint.path}{endpoint.sample_query}"
    return f'''import json
import urllib.request

API_KEY = "bg_…your key…"

request = urllib.request.Request(
    "{url}",
    headers={{"Authorization": f"Bearer {{API_KEY}}"}},
)
with urllib.request.urlopen(request) as response:
    data = json.load(response)

print(json.dumps(data, indent=2))'''
