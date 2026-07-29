"""Idempotently ensure the Neon project backing the pipeline exists.

Infrastructure-as-code for a provider Bicep cannot express (spec Amendment A3).
Run it twice and the second run changes nothing — `infra-provision.yml`
dispatches it by hand, and a script that created a second project on the second
dispatch would be worse than no script at all.

It prints a connection string ONLY with ``--print-connection-string``, which is
for an operator running it locally. Without that flag it reports host, database
and role and nothing secret, so it is safe to run in a CI step whose log is
readable.

The standard library only, deliberately: this runs from a GitHub runner before
``requirements.txt`` is necessarily installed, and it has no need of anything
``urllib`` cannot do.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_API = "https://console.neon.tech/api/v2"


def find_project(projects: list[dict], name: str) -> dict | None:
    """Return the project with exactly this name, or None.

    Exact match, not a substring test: a leftover ``job-market-scout-old``
    must not be mistaken for the live project and quietly reused.
    """
    for project in projects:
        if project.get("name") == name:
            return project
    return None


def build_connection_uri(
    *, host: str, role: str, password: str, database: str
) -> str:
    """Assemble a DSN with TLS requested explicitly.

    Neon refuses non-TLS connections regardless, so ``sslmode=require`` is
    belt-and-braces there — but it also makes the DSN's intent legible, and it
    is what would carry the guarantee to any other provider.

    The password is percent-encoded because a generated one containing ``@`` or
    ``/`` would otherwise terminate the userinfo or the path early, producing a
    DSN that points somewhere else entirely rather than failing outright.
    """
    quoted = urllib.parse.quote(password, safe="")
    return f"postgresql://{role}:{quoted}@{host}/{database}?sslmode=require"


def check_project_shape(
    project: dict, *, expected_region: str, expected_pg_version: int
) -> list[str]:
    """Report the ways an existing project differs from what P6 needs.

    Both of these are **fixed at project creation** on Neon, so noticing them
    late means creating another project and migrating a second time. Checked
    rather than assumed because a project made through the console defaults to
    neither value: the console offers a US region and the newest major.
    """
    problems: list[str] = []
    region = project.get("region_id")
    if region != expected_region:
        problems.append(
            f"region is {region!r}, expected {expected_region!r} — this is fixed "
            "at creation, and a distant region breaks NFR-CC-2's latency budget"
        )
    version = project.get("pg_version")
    if version != expected_pg_version:
        problems.append(
            f"Postgres major is {version}, expected {expected_pg_version} — the "
            "source is pgvector/pgvector:pg16 and CI runs pg16, so a different "
            "major in production means the suite stops being a faithful check"
        )
    return problems


def redact(uri: str) -> str:
    """Mask the password so a DSN can be echoed in a status line."""
    scheme, _, rest = uri.partition("://")
    creds, _, tail = rest.partition("@")
    role, _, _password = creds.partition(":")
    return f"{scheme}://{role}:***@{tail}"


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{_API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # The body carries Neon's actual reason; without it every failure reads
        # as a bare status code and says nothing about what to fix.
        raise SystemExit(
            f"Neon API {method} {path} failed: "
            f"{error.code} {error.read().decode()[:400]}"
        ) from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-name", default="job-market-scout")
    parser.add_argument(
        "--project-id",
        default=os.environ.get("NEON_PROJECT_ID"),
        help=(
            "operate on this project directly instead of listing projects. "
            "Required when NEON_API_KEY is project-scoped, since such a key "
            "cannot list or create projects — which is the least-privilege "
            "credential to give CI, so it is the preferred mode"
        ),
    )
    parser.add_argument(
        "--region",
        default="aws-ap-southeast-2",
        help="Sydney — the nearest Neon region to the VM's newzealandnorth",
    )
    parser.add_argument("--pg-version", type=int, default=16)
    parser.add_argument(
        "--print-connection-string",
        action="store_true",
        help="print the DSN including the password; for local use only",
    )
    args = parser.parse_args()

    token = os.environ.get("NEON_API_KEY")
    if not token:
        raise SystemExit("NEON_API_KEY is not set")

    if args.project_id:
        # A project-scoped key cannot list or create; it can read the one
        # project it is bound to, which is enough to verify and report.
        existing = _request("GET", f"/projects/{args.project_id}", token)["project"]
        print(f"project {existing.get('name')} (id {existing['id']}) — read directly")
    else:
        existing = find_project(
            _request("GET", "/projects", token).get("projects", []), args.project_name
        )
        if existing is not None:
            print(f"project {args.project_name} already exists (id {existing['id']})")

    if existing is not None:
        project_id = existing["id"]
        created = None
        problems = check_project_shape(
            existing,
            expected_region=args.region,
            expected_pg_version=args.pg_version,
        )
        for problem in problems:
            print(f"  WRONG: {problem}", file=sys.stderr)
        if problems:
            raise SystemExit(
                "\nThis project does not match what P6 needs, and neither region "
                "nor major version can be changed after creation. Create a new "
                "project with the right settings and delete this one."
            )
    else:
        created = _request(
            "POST",
            "/projects",
            token,
            {
                "project": {
                    "name": args.project_name,
                    "region_id": args.region,
                    "pg_version": args.pg_version,
                }
            },
        )
        project_id = created["project"]["id"]
        print(f"created project {args.project_name} (id {project_id})")

    endpoints = _request("GET", f"/projects/{project_id}/endpoints", token)
    host = endpoints["endpoints"][0]["host"]
    # Report what the project actually is, never what was asked for: printing
    # `args.region` here made the expected value look like an observation, so
    # the output read as evidence of something it had not checked.
    observed = created["project"] if created is not None else existing
    print(f"project  : {project_id}")
    print(f"host     : {host}")
    print(f"region   : {observed.get('region_id')}")
    print(f"postgres : {observed.get('pg_version')}")

    if not args.print_connection_string:
        return 0

    if created is None:
        # Neon returns a role password exactly once, at creation. Re-deriving
        # it is impossible, so say so rather than printing a DSN that is
        # missing the one part that matters.
        print(
            "\nThe role password is returned only when the project is first "
            "created. Retrieve or reset it in the Neon console:\n"
            f"  https://console.neon.tech/app/projects/{project_id}",
            file=sys.stderr,
        )
        return 0

    role = created["roles"][0]
    database = created["databases"][0]
    print()
    print(
        build_connection_uri(
            host=host,
            role=role["name"],
            password=role["password"],
            database=database["name"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
