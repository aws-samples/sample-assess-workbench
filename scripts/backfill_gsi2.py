#!/usr/bin/env python3
"""Backfill GSI2 attributes on existing project items.

Scans all PROJECT#*/METADATA items in the DynamoDB table and writes
GSI2PK / GSI2SK on any that are missing them. This is a one-time
migration to support the per-user project query index added in the
multi-tenancy sprint.

Key schema:
    GSI2PK = USER#{created_by}   (USER#unknown for items with no owner)
    GSI2SK = {created_at}        (ISO-8601 timestamp)

Deployment order:
    1. Deploy Terraform (creates GSI2 on the table)
    2. Deploy Lambda code (new projects get GSI2 attrs automatically)
    3. Run this script (backfills existing projects)

Usage:
    # Dry run — prints what would be updated, writes nothing
    python scripts/backfill_gsi2.py --table my-table-name --dry-run

    # Live run
    python scripts/backfill_gsi2.py --table my-table-name

    # Use a specific AWS profile
    python scripts/backfill_gsi2.py --table my-table-name --profile prod-readonly
"""
import argparse
import sys
import boto3
from boto3.dynamodb.conditions import Attr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--table', required=True, help='DynamoDB table name')
    parser.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    parser.add_argument('--profile', default=None, help='AWS profile name')
    parser.add_argument('--region', default=None, help='AWS region (defaults to profile/env default)')
    return parser.parse_args()


def scan_project_metadata(table) -> list[dict]:
    """Scan all PROJECT#*/METADATA items from the table.

    Handles pagination automatically.

    Args:
        table: boto3 DynamoDB Table resource.

    Returns:
        List of project METADATA items.
    """
    items = []
    kwargs = {
        'FilterExpression': Attr('SK').eq('METADATA') & Attr('PK').begins_with('PROJECT#'),
    }

    while True:
        response = table.scan(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        kwargs['ExclusiveStartKey'] = last_key

    return items


def backfill(table, items: list[dict], dry_run: bool) -> tuple[int, int, int, int]:
    """Write GSI2PK / GSI2SK on items that are missing them.

    Args:
        table: boto3 DynamoDB Table resource.
        items: Project METADATA items from the scan.
        dry_run: If True, print changes without writing.

    Returns:
        Tuple of (total, already_set, updated, unknown_owner).
    """
    total = len(items)
    already_set = 0
    updated = 0
    unknown_owner = 0

    for item in items:
        pk = item.get('PK', '')
        project_id = item.get('project_id', pk.replace('PROJECT#', ''))

        # Skip items that already have GSI2 attrs
        if item.get('GSI2PK') and item.get('GSI2SK'):
            already_set += 1
            continue

        created_by = item.get('created_by', '').strip()
        created_at = item.get('created_at', '')

        if not created_by:
            gsi2_pk = 'USER#unknown'
            unknown_owner += 1
        else:
            gsi2_pk = f'USER#{created_by}'

        if not created_at:
            # Fallback: use updated_at, then a sentinel value
            created_at = item.get('updated_at', '1970-01-01T00:00:00+00:00')

        if dry_run:
            print(
                f"  [DRY RUN] {project_id}: "
                f"GSI2PK={gsi2_pk!r}  GSI2SK={created_at!r}"
                + (' (no owner — assigned USER#unknown)' if not item.get('created_by') else '')
            )
        else:
            table.update_item(
                Key={'PK': pk, 'SK': 'METADATA'},
                UpdateExpression='SET GSI2PK = :pk, GSI2SK = :sk',
                ExpressionAttributeValues={':pk': gsi2_pk, ':sk': created_at},
                # Only write if still missing — safe to re-run
                ConditionExpression=Attr('GSI2PK').not_exists() | Attr('GSI2SK').not_exists(),
            )

        updated += 1

    return total, already_set, updated, unknown_owner


def main() -> None:
    args = parse_args()

    session_kwargs = {}
    if args.profile:
        session_kwargs['profile_name'] = args.profile
    if args.region:
        session_kwargs['region_name'] = args.region

    session = boto3.Session(**session_kwargs)
    dynamodb = session.resource('dynamodb')
    table = dynamodb.Table(args.table)

    print(f"Table:   {args.table}")
    print(f"Mode:    {'DRY RUN (no writes)' if args.dry_run else 'LIVE (will write to DynamoDB)'}")
    print()

    print("Scanning for PROJECT#*/METADATA items...")
    items = scan_project_metadata(table)
    print(f"Found {len(items)} project(s).\n")

    if not items:
        print("Nothing to do.")
        sys.exit(0)

    total, already_set, updated, unknown_owner = backfill(table, items, args.dry_run)

    print()
    print("── Summary ──────────────────────────────────────")
    print(f"  Total projects scanned : {total}")
    print(f"  Already had GSI2 attrs : {already_set}")
    print(f"  {'Would update' if args.dry_run else 'Updated'}          : {updated}")
    if unknown_owner:
        print(
            f"  Assigned USER#unknown  : {unknown_owner}  "
            "(projects with no created_by — reassign manually if needed)"
        )
    print("─────────────────────────────────────────────────")

    if args.dry_run and updated > 0:
        print("\nRe-run without --dry-run to apply changes.")


if __name__ == '__main__':
    main()
