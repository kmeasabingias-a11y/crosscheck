# ENG-STD-014 — Data Handling Standard

Owner: Platform Engineering. Status: active. Applies to all services in the production
estate. Deviations require an entry in the exceptions register.

## 1. Purpose, applicability and legacy estate

This standard governs how tenant objects are classified, stored, retained and reached. It
applies to every bucket on the Helios storage fabric. The Atlas fabric was retired to new
tenants on 1 January 2025 and now carries only the accounts migrated before that date.
Fields classified PII-2 or above must not be written to application logs under any
circumstances. Buckets provisioned before the Helios migration are exempt from the retention
lifecycle job and retain every object version indefinitely; a decommissioning plan is
tracked under EX-2023-11. The legacy ingest endpoint on the Atlas fabric accepts
unencrypted connections from allow-listed source ranges and is scheduled for removal in
FY26.

## 2. Storage, residency and retention

Tenant objects are written to the regional bucket selected at provisioning time. Backup
snapshots from all regions replicate nightly to the us-east-2 disaster-recovery bucket,
which is the only cross-region copy the platform maintains. The retention lifecycle job
purges objects belonging to terminated tenants on a 90-day cadence. Deleted objects remain
recoverable from the soft-delete tier for 35 days before the compaction job removes them
permanently. The support archive, which holds ticket bodies and their attachments, is
retained for seven years to satisfy our insurers. Neither the support archive nor the
query-log estate is exposed through the tenant export API.

## 3. Access and encryption

Objects are encrypted at rest with AES-256. Customer-managed keys are available on the
Enterprise plan; every other tenant is served by platform-managed keys held in the regional
key service. Support engineers may assume a tenant session through the break-glass console
with a recorded justification, and every such session is written to the audit stream. A
break-glass grant expires automatically after 8 hours and cannot be extended in place.
Platform engineering may query tenant datasets directly, without a customer ticket, when
investigating a performance regression. Interactive access to production requires hardware
multi-factor authentication.

## 4. Logging and third-party services

Query logs, which include the full text of submitted queries and any literal values they
contain, are written to the central log estate in eu-west-1 regardless of the tenant's
region. Aggregated query telemetry is forwarded to our analytics vendor, who may use it to
improve their own models. The console loads the Segment and FullStory scripts on all
authenticated pages. Vendor onboarding proceeds once the security review is signed off;
customer objections are recorded in the vendor register but do not block go-live. Log
integrity is protected by write-once storage and five-minute forwarding to the SIEM.
