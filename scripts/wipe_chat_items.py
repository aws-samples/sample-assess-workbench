#!/usr/bin/env python3
"""Wipe all chat session and message items from the DynamoDB table.

One-time cleanup for the per-user chat scoping change. The chat key
schema changed from project+agent scoped to per-user scoped:

    OLD:  SK = CHATSESSION#{agent}#{session_id}
          SK = CHAT#{agent}#{session_id}#{timestamp}#{role}
    NEW:  SK = CHATSESSION#{user_sub}#{agent}#{session_id}
          SK = CHAT#{user_sub}#{agent}#{session_id}#{timestamp}#{role}

Old items lack ``user_sub`` and are unreachable under the new keys, so
they would linger as orphans. Demo chat history is throwaway, so the
decision (see .design_specs/chat-hardening-demo.md) is to wipe rather
than migrate. This deletes every ``CHATSESSION#*`` and ``CHAT#*`` item
regardless of format — run it once at deploy time, before the new
handler serves traffic.

It does NOT touch project metadata, reviews, contexts, or any other
item type — only the two chat SK prefixes.

Deployment order:
    1. Deploy the new chat code (api/core/chat.py, message.py)
    2. Run this script to clear pre-existing chat items

Usage:
    # Dry run — prints what would be deleted, writes nothing
    python scripts/wipe_chat_items.py --table my-table-name --dry-run

    # Live run
    python scripts/wipe_chat_items.py --table my-table-name

    # Use a specific AWS profile / region
    python scripts/wipe_chat_items.py --table my-table-name --profile my-aws-profile
"""
import argparse
import sys
import boto3
from boto3.dynamodb.conditions import Attr

# Sort-key prefixes that identify chat items. Covers both the old
# (project+agent) and new (per-user) key formats.
CHAT_SK_PREFIXES = ('CHATSESSION#', 'CHAT#')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--table', required=True, help='DynamoDB table name')
    parser.add_argument('--dry-run', action='store_true', help='Print deletions without writing')
    parser.add_argument('--profile', default=None, help='AWS profile name')
    parser.add_argument('--region', default=None, help='AWS region (defaults to profile/env default)')
    return parser.parse_args()


def scan_chat_items(table) -> list[dict]:
    """Scan all chat session and message items from the table.

    Matches any item whose SK begins with a chat prefix. Handles
    pagination automatically. Projects only PK/SK to keep the scan cheap.

    Args:
        table: boto3 DynamoDB Table resource.

    Returns:
        List of {'PK': ..., 'SK': ...} key dicts for chat items.
    """
    items: list[dict] = []
    kwargs = {
        'FilterExpression': (
            Attr('SK').begins_with(CHAT_SK_PREFIXES[0])
            | Attr('SK').begins_with(CHAT_SK_PREFIXES[1])
        ),
        'ProjectionExpression': '#pk, #sk',
        'ExpressionAttributeNames': {'#pk': 'PK', '#sk': 'SK'},
    }

    while True:
        response = table.scan(**kwargs)
        items.extend(response.get('Items', []))
        last_key = response.get('LastEvaluatedKey')
        if not last_key:
            break
        kwargs['ExclusiveStartKey'] = last_key

    return items


def delete_chat_items(table, items: list[dict], dry_run: bool) -> int:
    """Delete the given chat items.

    Args:
        table: boto3 DynamoDB Table resource.
        items: Key dicts ({'PK', 'SK'}) to delete.
        dry_run: If True, print deletions without writing.

    Returns:
        Number of items deleted (or that would be deleted in dry-run).
    """
    if dry_run:
        for item in items:
            print(f"  [DRY RUN] delete  PK={item['PK']!r}  SK={item['SK']!r}")
        return len(items)

    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={'PK': item['PK'], 'SK': item['SK']})

    return len(items)


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
    print(f"Mode:    {'DRY RUN (no writes)' if args.dry_run else 'LIVE (will delete from DynamoDB)'}")
    print()

    print("Scanning for CHATSESSION#* and CHAT#* items...")
    items = scan_chat_items(table)
    print(f"Found {len(items)} chat item(s).\n")

    if not items:
        print("Nothing to do.")
        sys.exit(0)

    deleted = delete_chat_items(table, items, args.dry_run)

    print()
    print("── Summary ──────────────────────────────────────")
    print(f"  Chat items {'to delete' if args.dry_run else 'deleted'} : {deleted}")
    print("─────────────────────────────────────────────────")

    if args.dry_run and deleted > 0:
        print("\nRe-run without --dry-run to apply deletions.")


if __name__ == '__main__':
    main()
