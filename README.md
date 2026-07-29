# Automated S3 Bucket Cleanup (Objects Older Than 30 Days)

**Objective:** Automate deletion of stale objects (older than 30 days) in an S3 bucket using a Lambda function triggered manually (or on a schedule).

## Architecture

```
S3 Bucket  <---list/delete--->  Lambda Function (Python 3.12+, boto3)
                                       |
                                       v
                              IAM Execution Role
                              (scoped ListBucket + DeleteObject
                               + CloudWatch Logs)
```


## Files in this repo

| File | Purpose |
|---|---|
| `lambda_function.py` | The Lambda handler — paginated list, age comparison, batch delete |
| `iam_trust_policy.json` | Trust policy — allows the Lambda service to assume this role |
| `iam_inline_policy.json` | Permissions policy — scoped `s3:ListBucket` / `s3:DeleteObject` |

> **Note:** bucket names and account IDs in this repo are placeholders. Replace
> `YOUR-BUCKET-NAME` / `your-bucket-name` with your actual bucket before deploying.

---

## Step 1 — S3 Setup

Created a bucket and uploaded several test files.

![S3 bucket, empty, before test files](screenshots/04-s3-bucket-empty.png)

![S3 bucket with test files uploaded (xlsx, docx, txt, pdf)](screenshots/05-s3-bucket-with-files.png)

Since S3 doesn't allow backdating `LastModified`, testing was done by temporarily
lowering the age threshold to **minutes** instead of faking old files — see
`AGE_THRESHOLD_MINUTES` in the code and the Testing section below.

<img width="940" height="360" alt="image" src="https://github.com/user-attachments/assets/ce438a9d-9593-418c-bd54-12b0ace34e55" />

<img width="940" height="290" alt="image" src="https://github.com/user-attachments/assets/ca51a921-6dec-42c6-90b0-e5521ae7b64a" />


---

## Step 2 — IAM Role

Created a dedicated execution role (`s3-cleanup-lambda-role`) with:
- **AWS managed policy:** `AWSLambdaBasicExecutionRole` (CloudWatch logging)
- **Inline policy:** scoped `s3:ListBucket` + `s3:DeleteObject`, restricted to the
  target bucket only (see `iam_inline_policy.json`)

![IAM role showing both attached policies](screenshots/03-iam-role-policies.png)

![IAM role after correcting the inline policy](screenshots/06-iam-role-updated.png)


<img width="940" height="263" alt="image" src="https://github.com/user-attachments/assets/d30fa610-46f8-4ed5-b17f-a74b8c598f5f" />



---

## Step 3 — Lambda Function

Python 3.12+, boto3. Key implementation details:

- **Paginator, not a single call** — `s3.get_paginator("list_objects_v2")`, so
  buckets with more than 1000 objects are still fully scanned.
- **Timezone-aware comparison** — `datetime.now(timezone.utc)` compared directly
  against `LastModified` (already UTC-aware from boto3), avoiding naive/aware
  datetime errors.
- **Batch deletion** — up to 1000 keys per `delete_objects` call rather than one
  API call per object.
- **Logging** — every deleted key, the cutoff timestamp, and the total count are
  printed for CloudWatch visibility.

Environment variables used to control behavior without redeploying code:

![Environment variables: AGE_THRESHOLD_DAYS, AGE_THRESHOLD_MINUTES, BUCKET_NAME](screenshots/02-env-vars-set.png)


<img width="1521" height="492" alt="image" src="https://github.com/user-attachments/assets/55527e1b-61e4-4767-afc4-0df38c600627" />

---

## Step 4 — Testing

1. Set `AGE_THRESHOLD_MINUTES=2` to shrink the staleness window for testing.
2. Uploaded fresh test files, waited past the 2-minute mark, then manually
   triggered the function via the Lambda console **Test** button with an empty
   event body (`{}`).
3. Confirmed via the response payload (`deleted_count`, `deleted_objects`) and
   by checking the S3 console that only objects older than the threshold were
   removed — newer objects were left untouched.
4. Reset `AGE_THRESHOLD_DAYS=30` and cleared `AGE_THRESHOLD_MINUTES` for the
   final production-equivalent run, confirming `deleted_count: 0` against
   freshly uploaded (non-stale) files — proving the real 30-day logic doesn't
   touch recent objects.

---

## Troubleshooting Log

A few real issues came up during setup — documenting them here since they're
common gotchas with this exact pattern:

- **"Log group does not exist"** in CloudWatch — turned out the function had
  never actually executed my code yet; it was still running the default
  "Hello from Lambda!" stub because the real code was pasted but never
  **Deployed**. CloudWatch only creates a log group after a first real
  invocation.

  ![CloudWatch log group not found error](screenshots/01-log-group-error.png)

- **Wrong function targeted in an IDE extension** — a VS Code/AWS Toolkit
  session had a different, unrelated Lambda function open
  (`aws-controltower-NotificationForwarder`), which is protected by an
  org-wide Service Control Policy. Switched to the AWS web console directly
  to avoid ambiguity.

- **Trust policy pasted into the permissions policy slot** — the trust policy
  (`Principal` + `sts:AssumeRole`) and the permissions policy (`Resource` +
  actions) are two separate documents attached in two separate places on an
  IAM role. Pasting one where the other belongs throws IAM policy validation
  errors (`Missing Resource`, `Unsupported Principal`).

- **Trailing whitespace in the bucket ARN** — `"arn:aws:s3:::my-bucket "` (note
  the trailing space) is treated as a literal, different resource by IAM, so
  it silently doesn't match the real bucket even though it looks correct at a
  glance. Caused a persistent `AccessDenied` on `s3:ListBucket` until spotted.

- **Environment variables reset to empty** — after a code deploy through the
  IDE extension, `BUCKET_NAME` and the threshold variables were wiped,
  causing the function to silently fall back to placeholder defaults and
  return `deleted_count: 0` with no error. Re-added them via
  Configuration → Environment variables.

---

## Step 5 — Discussion: Lambda vs. S3 Lifecycle Rules

In production, this exact "delete after 30 days" behavior is natively
supported by **S3 Lifecycle Rules** — no code, no Lambda, no IAM role to
maintain, and no risk of the function silently failing or timing out.

**When Lambda is still the right call instead of a Lifecycle Rule:** Lifecycle
Rules only understand age, prefix, and object tags — they can't express real
conditional logic. Reach for Lambda when the deletion decision depends on
something Lifecycle Rules can't evaluate: parsing filenames or object metadata
against a business rule (e.g., delete `temp-*.csv` only if no matching
`.done` marker file exists), cross-referencing an external system (a database
flag, an API response) before deleting, or chaining other actions alongside
the deletion (notify Slack, archive a record, delete a related DynamoDB row)
that a single declarative rule can't perform on its own.
