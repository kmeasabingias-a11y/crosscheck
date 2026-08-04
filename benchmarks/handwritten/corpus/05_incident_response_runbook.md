# Incident Response Runbook v4

For the on-call security engineer. Follow the steps in order. If a step cannot be
completed, say so in the incident channel and continue — do not stall the timeline.

## 1. Scope, severity and objectives

This runbook, version 4, replaces the Security Incident Playbook version 2, which is
withdrawn and must not be used. Severity 1 is loss of or unauthorised access to tenant data.
Severity 2 is a control failure with no confirmed data access. Severity 3 is a degraded
control with compensating coverage. Severity 4 is an informational finding. The platform
availability objective is 99.9% measured monthly, and an availability breach is handled
under the reliability process, not this one. Page the security lead for Severity 1 and 2
within ten minutes of triage.

## 2. Detection and triage

Alerts arrive from the SIEM, from the bug bounty inbox, and from customer support. Confirm
the alert is real before declaring anything. Triage begins by searching the request logs for
the affected user's email address, which is recorded on every authenticated request, and
then widening to the account identifier and the source address range. Establish a first and
last observed timestamp before you write anything in the incident channel. Do not restart
the affected service until evidence collection has started; a restart destroys the process
memory you will want later.

## 3. Notification

Customer notification is sent within 72 hours of an incident being declared, using the
templates in the trust centre repository. Regulator notification is prepared within 72 hours
where the incident is reportable, and is sent by the legal team, not by engineering.
Severity 3 and 4 incidents are recorded in the incident register and are not communicated to
customers. Draft every external message in the incident channel and have the legal team
approve it before it leaves; do not send a correction to a list that never received the
original.

## 4. Evidence preservation and review

Snapshot the affected hosts and export the relevant log ranges before any remediation.
Investigators retain elevated access for the duration of the incident and for 14 days
afterwards so that evidence can be re-examined without a fresh approval cycle. Hash every
exported artefact and record the hash in the incident record. Hold the post-incident review
within ten working days of closure, blameless, with the actions assigned to named owners and
a due date on each.
