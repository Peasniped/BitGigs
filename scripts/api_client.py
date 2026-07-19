#!/usr/bin/env python
"""BitGigs API test client — stdlib only, no dependencies.

Usage:
    python scripts/api_client.py --key bg_... ping
    python scripts/api_client.py --key bg_... income --year 2026
    python scripts/api_client.py --key bg_... income --year 2026 --month 7
    python scripts/api_client.py --key bg_... income --start 2026-01 --end 2026-06
    python scripts/api_client.py --key bg_... income --year 2026 --json

The key can also come from the BITGIGS_API_KEY environment variable, and the
server address from BITGIGS_API_URL (default http://127.0.0.1:8000). Create
keys in BitGigs under Settings → API.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def call(base_url: str, key: str, path: str, params: dict | None = None) -> dict:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except (json.JSONDecodeError, ValueError):
            sys.exit(f"HTTP {exc.code} from {url} (not a JSON body — is this a BitGigs server?)")
        sys.exit(f"HTTP {exc.code}: [{body.get('error')}] {body.get('detail')}")
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach {base_url}: {exc.reason}")


def fmt_dkk(amount: str) -> str:
    """'12345.67' → '12.345,67 kr.' (en-DK, like the app)."""
    whole, _, cents = amount.partition(".")
    sign, digits = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    grouped = f"{int(digits):,}".replace(",", ".")
    return f"{sign}{grouped},{cents or '00'} kr."


def cmd_ping(args) -> None:
    data = call(args.base_url, args.key, "/api/v1/ping/")
    print("Key OK")
    print(f"  name:    {data['key']}")
    print(f"  scopes:  {', '.join(data['scopes'])}")
    print(f"  expires: {data['expires_at'] or 'never'}")


def cmd_income(args) -> None:
    data = call(args.base_url, args.key, "/api/v1/income/", {
        "year": args.year, "month": args.month,
        "start": args.start, "end": args.end,
    })
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # ASCII only — Windows consoles often run cp1252, which can't print arrows.
    print(f"Income {data['start']} -> {data['end']}  ({data['currency']})")
    print()
    print(f"  {'Month':<9} {'Gross':>16} {'Net':>16}")
    print(f"  {'-' * 9} {'-' * 16} {'-' * 16}")
    for row in data["months"]:
        print(f"  {row['month']:<9} {fmt_dkk(row['gross']):>16} {fmt_dkk(row['net']):>16}")
    print(f"  {'-' * 9} {'-' * 16} {'-' * 16}")
    totals = data["totals"]
    print(f"  {'Total':<9} {fmt_dkk(totals['gross']):>16} {fmt_dkk(totals['net']):>16}")

    for wp in data["workplaces"]:
        print()
        print(f"  {wp['name']}  (gross {fmt_dkk(wp['total_gross'])}, net {fmt_dkk(wp['total_net'])})")
        for row in wp["months"]:
            if row["state"] == "inactive":
                continue
            print(
                f"    {row['month']:<9} {fmt_dkk(row['gross']):>14} gross"
                f" {fmt_dkk(row['net']):>14} net"
                f"  {row['hours']:>7} h  [{row['state']}]"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="BitGigs API test client.")
    parser.add_argument("--key", default=os.environ.get("BITGIGS_API_KEY"),
                        help="API key (or set BITGIGS_API_KEY)")
    parser.add_argument("--base-url", dest="base_url",
                        default=os.environ.get("BITGIGS_API_URL", DEFAULT_BASE_URL),
                        help=f"Server address (default {DEFAULT_BASE_URL})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="Check that the key works")

    income = sub.add_parser("income", help="Gross/net income per month")
    income.add_argument("--year", type=int, help="Whole year, e.g. 2026")
    income.add_argument("--month", type=int, help="One month of --year (1-12)")
    income.add_argument("--start", help="Range start, YYYY-MM")
    income.add_argument("--end", help="Range end, YYYY-MM")
    income.add_argument("--json", action="store_true", help="Print the raw JSON instead")

    args = parser.parse_args()
    if not args.key:
        parser.error("an API key is required: --key bg_… or set BITGIGS_API_KEY")

    {"ping": cmd_ping, "income": cmd_income}[args.command](args)


if __name__ == "__main__":
    main()
