"""
S3 Stale Object Cleanup — Lambda Function
Deletes objects older than a configurable age threshold from a target S3 bucket.

Environment variables (set in Lambda console -> Configuration -> Environment variables):
  BUCKET_NAME             -> name of the bucket to clean up (required)
  AGE_THRESHOLD_DAYS       -> production value, e.g. 30 (default: 30)
  AGE_THRESHOLD_MINUTES    -> TESTING ONLY. If set > 0, this overrides AGE_THRESHOLD_DAYS
                              so you can test with objects that are only a few minutes old.
                              Remove/set to 0 before final production use.
"""

import os
from datetime import datetime, timezone, timedelta

import boto3

s3 = boto3.client("s3")

BUCKET_NAME = os.environ.get("BUCKET_NAME", "your-bucket-name")
AGE_THRESHOLD_DAYS = int(os.environ.get("AGE_THRESHOLD_DAYS", "30"))
AGE_THRESHOLD_MINUTES = int(os.environ.get("AGE_THRESHOLD_MINUTES", "0"))  # testing override


def lambda_handler(event, context):
    now = datetime.now(timezone.utc)

    # Testing mode: use minutes if explicitly set, otherwise use the real 30-day threshold
    if AGE_THRESHOLD_MINUTES > 0:
        cutoff = now - timedelta(minutes=AGE_THRESHOLD_MINUTES)
        print(f"[TEST MODE] Using {AGE_THRESHOLD_MINUTES}-minute threshold.")
    else:
        cutoff = now - timedelta(days=AGE_THRESHOLD_DAYS)
        print(f"[PROD MODE] Using {AGE_THRESHOLD_DAYS}-day threshold.")

    print(f"Bucket: {BUCKET_NAME}")
    print(f"Cutoff time (UTC): {cutoff.isoformat()}")

    objects_to_delete = []

    # ALWAYS paginate — list_objects_v2 caps at 1000 keys per call
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            last_modified = obj["LastModified"]  # tz-aware datetime, already UTC

            if last_modified < cutoff:
                objects_to_delete.append({"Key": key})

    if not objects_to_delete:
        print("No objects older than the threshold. Nothing to delete.")
        return {"statusCode": 200, "deleted_count": 0, "deleted_objects": []}

    deleted_objects = []

    # delete_objects (batch) accepts a max of 1000 keys per call
    for i in range(0, len(objects_to_delete), 1000):
        batch = objects_to_delete[i : i + 1000]
        response = s3.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": batch, "Quiet": False},
        )

        for deleted in response.get("Deleted", []):
            deleted_objects.append(deleted["Key"])

        for error in response.get("Errors", []):
            print(f"ERROR deleting {error['Key']}: {error.get('Message')}")

    print(f"Total objects deleted: {len(deleted_objects)}")
    for key in deleted_objects:
        print(f"Deleted: {key}")

    return {
        "statusCode": 200,
        "deleted_count": len(deleted_objects),
        "deleted_objects": deleted_objects,
    }
