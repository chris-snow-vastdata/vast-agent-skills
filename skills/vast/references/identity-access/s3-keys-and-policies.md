# S3 keys, identity policies and bucket policies

KB (5.5): "Managing S3 User Permissions" https://kb.vastdata.com/documentation/docs/managing-s3-user-permissions-55.md,
"Managing Identity Policies" https://kb.vastdata.com/documentation/docs/managing-identity-policies-55.md,
"Managing Bucket Policies" https://kb.vastdata.com/documentation/docs/managing-bucket-policies-55.md,
"Identity and Bucket Policy Reference" https://kb.vastdata.com/documentation/docs/identity-and-bucket-policy-reference-55.md,
"Security Token Service (STS) and IAM Roles" https://kb.vastdata.com/documentation/docs/security-token-service-sts-and-iam-roles-55.md

## Where an S3 user's rights come from

1. **Authentication**: an access key pair of a user in the tenant (local or external), or STS
   temporary credentials from an IAM role (OIDC or permanent-key AssumeRole).
2. **Identity policies** attached to the user, the user's groups, or the IAM role. Cover all
   S3 actions, including creating and deleting buckets (which ACLs cannot control).
3. **Bucket policy** on the bucket's view (S3 Native security flavor only).
4. **User flags** `allow_create_bucket`, `allow_delete_bucket`, `s3_superuser` (full access,
   overriding ACLs). Terraform docs note an attached identity policy overrides these flags
   when they conflict.
5. **Ownership and ACLs** on buckets and objects.

An explicit `Deny` in any applicable policy wins over an `Allow` (AWS semantics, KB reference
describes `Effect: Deny`). Identity policies with the S3 security flavor also govern NFS and
SMB access to that view (KB "Managing Identity Policies").

## Identity policy object (5.5 API: `/s3policies/`)

```json
{"name": "analytics-raw-read", "tenant_id": 3, "enabled": true,
 "policy": "{\"Version\":\"2012-10-17\",\"Statement\":[...]}"}
```

- `policy` is a JSON **string** (max length 6145 on 5.5.3 spec); `name` required; `tenant_id`
  defaults to 1 (the default tenant): always set it.
- Attach by putting the policy id into `s3_policies_ids` of users/groups (replace semantics),
  or `s3_policies` of an IAM role.
- Replicated policies arrive **disabled** on the destination; enable on failover (KB).

## Policy documents (AWS IAM JSON subset)

Resources: the KB reference uses `arn:aws:s3:::<bucket>` and `arn:aws:s3:::<bucket>/*`; the
identity-policy page also shows bare `<bucket>` and `<bucket>/*`. Use the ARN form unless the
release's KB says otherwise. Variables (KB): `${BucketName}`, `${ObjectName}`, `${username}`,
`${sourceip}`. Supported actions and condition keys per action: KB reference page.

Read-only on one bucket:

```json
{"Version": "2012-10-17", "Statement": [
  {"Sid": "ReadBucket", "Effect": "Allow",
   "Action": ["s3:ListBucket", "s3:GetObject", "s3:GetBucketLocation"],
   "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"]}]}
```

Read-write but no deletes:

```json
{"Version": "2012-10-17", "Statement": [
  {"Sid": "RW", "Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetObject", "s3:PutObject"],
   "Resource": ["arn:aws:s3:::<bucket>", "arn:aws:s3:::<bucket>/*"]},
  {"Sid": "NoDelete", "Effect": "Deny", "Action": ["s3:DeleteObject"],
   "Resource": ["arn:aws:s3:::<bucket>/*"]}]}
```

Per-user home prefix (one policy for a whole group):

```json
{"Version": "2012-10-17", "Statement": [
  {"Sid": "Home", "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
   "Resource": ["arn:aws:s3:::<bucket>/home/${username}/*"]}]}
```

Allow creating buckets (identity policy only; a bucket policy cannot contain it):
`"Action": ["s3:CreateBucket"], "Resource": ["*"]`.

Conditions: `"Condition": {"<operator>": {"<key>": "<value>"}}`, e.g.
`{"Bool": {"aws:SecureTransport": "True"}}` to require HTTPS (KB examples). VAST DB row/column
security statements are also identity-policy statements (see `references/database.md`).

## Bucket policies

- Set with the S3 API (`PutBucketPolicy`, `GetBucketPolicy`, `DeleteBucketPolicy`) by the bucket
  owner or a user with `s3:PutBucketPolicy`; not through VMS.
- Only on views with S3 enabled and the **S3 Native** security flavor; one per bucket (a new
  one replaces the old); max 20 KB; deleted with the view or when S3 is removed from the view.
- Must have `Principal`. VAST forms (KB): `"*"` (any authenticated principal; anyone if the view
  allows anonymous access), or `{"User": ["alice", "bob"], "Group": ["finance"]}`; with
  multi-domain AD use `user@domain` / `Group@domain`.
- Resources must include the bucket name; `CreateBucket` not allowed.

```bash
aws s3api put-bucket-policy --endpoint-url https://<S3 VIP or DNS> --bucket <bucket> --policy file://policy.json
aws s3api get-bucket-policy --endpoint-url https://<S3 VIP or DNS> --bucket <bucket>
```

## Key lifecycle checklist

- Create per application or person, never shared; record which client uses which access key.
- The secret is shown once (API response, CLI output, UI copy button). With Terraform, use
  `pgp_public_key` so state holds only an encrypted secret.
- Rotate with overlap (workflow 3 in `references/identity-access.md`); disable before delete; delete promptly once unused.
- Keys survive password changes; they are tied to the user record. Changing a directory
  user's UID can drop their keys (KB "S3 error: The AWS access key Id you provided does not
  exist in our records" https://kb.vastdata.com/docs/s3-error-the-aws-access-key-id-you-provided-does-not-exist-in-our-records.md).
- Prefer STS/IAM roles (temporary credentials) for ephemeral compute: KB "STS AssumeRole with a
  Permanent Access Key Pair (No OIDC)" https://kb.vastdata.com/docs/sts-assumerole-with-a-permanent-access-key-pair-no-oidc.md.
