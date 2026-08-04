# NIST SP 800-53 REV4 — Audit and Accountability (AU)

## AU-1 — Audit And Accountability Policy And Procedures

Control: The organization:
a. Develops, documents, and disseminates to [Assignment: organization-defined personnel or
roles]:
1. An audit and accountability policy that addresses purpose, scope, roles, responsibilities,
management commitment, coordination among organizational entities, and compliance;
and
2. Procedures to facilitate the implementation of the audit and accountability policy and
associated audit and accountability controls; and
b. Reviews and updates the current:
1. Audit and accountability policy [Assignment: organization-defined frequency]; and
2. Audit and accountability procedures [Assignment: organization-defined frequency].
Supplemental Guidance: This control addresses the establishment of policy and procedures for the
effective implementation of selected security controls and control enhancements in the AU family.
Policy and procedures reflect applicable federal laws, Executive Orders, directives, regulations,
policies, standards, and guidance. Security program policies and procedures at the organization
level may make the need for system-specific policies and procedures unnecessary. The policy can
be included as part of the general information security policy for organizations or conversely, can
be represented by multiple policies reflecting the complex nature of certain organizations. The
procedures can be established for the security program in general and for particular information
systems, if needed. The organizational risk management strategy is a key factor in establishing
policy and procedures. Related control: PM-9.
Control Enhancements: None.
References: NIST Special Publications 800-12, 800-100.
Priority and Baseline Allocation:
P1 LOW AU-1 MOD AU-1 HIGH AU-1

## AU-2 — Audit Events

Control: The organization:
a. Determines that the information system is capable of auditing the following events:
[Assignment: organization-defined auditable events];
b. Coordinates the security audit function with other organizational entities requiring audit-
related information to enhance mutual support and to help guide the selection of auditable
events;
c. Provides a rationale for why the auditable events are deemed to be adequate to support after-
the-fact investigations of security incidents; and
d. Determines that the following events are to be audited within the information system:
[Assignment: organization-defined audited events (the subset of the auditable events defined
in AU-2 a.) along with the frequency of (or situation requiring) auditing for each identified
event].
Supplemental Guidance: An event is any observable occurrence in an organizational information
system. Organizations identify audit events as those events which are significant and relevant to
and Organizations
the security of information systems and the environments in which those systems operate in order
to meet specific and ongoing audit needs. Audit events can include, for example, password
changes, failed logons, or failed accesses related to information systems, administrative privilege
usage, PIV credential usage, or third-party credential usage. In determining the set of auditable
events, organizations consider the auditing appropriate for each of the security controls to be
implemented. To balance auditing requirements with other information system needs, this control
also requires identifying that subset of auditable events that are audited at a given point in time.
For example, organizations may determine that information systems must have the capability to
log every file access both successful and unsuccessful, but not activate that capability except for
specific circumstances due to the potential burden on system performance. Auditing requirements,
including the need for auditable events, may be referenced in other security controls and control
enhancements. Organizations also include auditable events that are required by applicable federal
laws, Executive Orders, directives, policies, regulations, and standards. Audit records can be
generated at various levels of abstraction, including at the packet level as information traverses the
network. Selecting the appropriate level of abstraction is a critical aspect of an audit capability and
can facilitate the identification of root causes to problems. Organizations consider in the definition
of auditable events, the auditing necessary to cover related events such as the steps in distributed,
transaction-based processes (e.g., processes that are distributed across multiple organizations) and
actions that occur in service-oriented architectures. Related controls: AC-6, AC-17, AU-3, AU-12,
MA-4, MP-2, MP-4, SI-4.
Control Enhancements:
(1) AUDIT EVENTS | COMPILATION OF AUDIT RECORDS FROM MULTIPLE SOURCES
[Withdrawn: Incorporated into AU-12].
(2) AUDIT EVENTS | SELECTION OF AUDIT EVENTS BY COMPONENT
[Withdrawn: Incorporated into AU-12].
(3) AUDIT EVENTS | REVIEWS AND UPDATES
The organization reviews and updates the audited events [Assignment: organization-defined
frequency].
Supplemental Guidance: Over time, the events that organizations believe should be audited may
change. Reviewing and updating the set of audited events periodically is necessary to ensure
that the current set is still necessary and sufficient.
(4) AUDIT EVENTS | PRIVILEGED FUNCTIONS
[Withdrawn: Incorporated into AC-6 (9)].
References: NIST Special Publication 800-92; Web: http://idmanagement.gov.
Priority and Baseline Allocation:
P1 LOW AU-2 MOD AU-2 (3) HIGH AU-2 (3)

## AU-3 — Content Of Audit Records

Control: The information system generates audit records containing information that establishes
what type of event occurred, when the event occurred, where the event occurred, the source of the
event, the outcome of the event, and the identity of any individuals or subjects associated with the
event.
Supplemental Guidance: Audit record content that may be necessary to satisfy the requirement of
this control, includes, for example, time stamps, source and destination addresses, user/process
identifiers, event descriptions, success/fail indications, filenames involved, and access control or
flow control rules invoked. Event outcomes can include indicators of event success or failure and
event-specific results (e.g., the security state of the information system after the event occurred).
Related controls: AU-2, AU-8, AU-12, SI-11.
and Organizations
Control Enhancements:
(1) CONTENT OF AUDIT RECORDS | ADDITIONAL AUDIT INFORMATION
The information system generates audit records containing the following additional information:
[Assignment: organization-defined additional, more detailed information].
Supplemental Guidance: Detailed information that organizations may consider in audit records
includes, for example, full text recording of privileged commands or the individual identities
of group account users. Organizations consider limiting the additional audit information to
only that information explicitly needed for specific audit requirements. This facilitates the use
of audit trails and audit logs by not including information that could potentially be misleading
or could make it more difficult to locate information of interest.
(2) CONTENT OF AUDIT RECORDS | CENTRALIZED MANAGEMENT OF PLANNED AUDIT RECORD CONTENT
The information system provides centralized management and configuration of the content to be
captured in audit records generated by [Assignment: organization-defined information system
components].
Supplemental Guidance: This control enhancement requires that the content to be captured in
audit records be configured from a central location (necessitating automation). Organizations
coordinate the selection of required audit content to support the centralized management and
configuration capability provided by the information system. Related controls: AU-6, AU-7.
References: None.
Priority and Baseline Allocation:
P1 LOW AU-3 MOD AU-3 (1) HIGH AU-3 (1) (2)

## AU-4 — Audit Storage Capacity

Control: The organization allocates audit record storage capacity in accordance with [Assignment:
organization-defined audit record storage requirements].
Supplemental Guidance: Organizations consider the types of auditing to be performed and the audit
processing requirements when allocating audit storage capacity. Allocating sufficient audit storage
capacity reduces the likelihood of such capacity being exceeded and resulting in the potential loss
or reduction of auditing capability. Related controls: AU-2, AU-5, AU-6, AU-7, AU-11, SI-4.
Control Enhancements:
(1) AUDIT STORAGE CAPACITY | TRANSFER TO ALTERNATE STORAGE
The information system off-loads audit records [Assignment: organization-defined frequency] onto
a different system or media than the system being audited.
Supplemental Guidance: Off-loading is a process designed to preserve the confidentiality and
integrity of audit records by moving the records from the primary information system to a
secondary or alternate system. It is a common process in information systems with limited
audit storage capacity; the audit storage is used only in a transitory fashion until the system
can communicate with the secondary or alternate system designated for storing the audit
records, at which point the information is transferred.
References: None.
Priority and Baseline Allocation:
P1 LOW AU-4 MOD AU-4 HIGH AU-4
and Organizations

## AU-5 — Response To Audit Processing Failures

Control: The information system:
a. Alerts [Assignment: organization-defined personnel or roles] in the event of an audit
processing failure; and
b. Takes the following additional actions: [Assignment: organization-defined actions to be taken
(e.g., shut down information system, overwrite oldest audit records, stop generating audit
records)].
Supplemental Guidance: Audit processing failures include, for example, software/hardware errors,
failures in the audit capturing mechanisms, and audit storage capacity being reached or exceeded.
Organizations may choose to define additional actions for different audit processing failures (e.g.,
by type, by location, by severity, or a combination of such factors). This control applies to each
audit data storage repository (i.e., distinct information system component where audit records are
stored), the total audit storage capacity of organizations (i.e., all audit data storage repositories
combined), or both. Related controls: AU-4, SI-12.
Control Enhancements:
(1) RESPONSE TO AUDIT PROCESSING FAILURES | AUDIT STORAGE CAPACITY
The information system provides a warning to [Assignment: organization-defined personnel, roles,
and/or locations] within [Assignment: organization-defined time period] when allocated audit
record storage volume reaches [Assignment: organization-defined percentage] of repository
maximum audit record storage capacity.
Supplemental Guidance: Organizations may have multiple audit data storage repositories
distributed across multiple information system components, with each repository having
different storage volume capacities.
(2) RESPONSE TO AUDIT PROCESSING FAILURES | REAL-TIME ALERTS
The information system provides an alert in [Assignment: organization-defined real-time period] to
[Assignment: organization-defined personnel, roles, and/or locations] when the following audit
failure events occur: [Assignment: organization-defined audit failure events requiring real-time
alerts].
Supplemental Guidance: Alerts provide organizations with urgent messages. Real-time alerts
provide these messages at information technology speed (i.e., the time from event detection to
alert occurs in seconds or less).
(3) RESPONSE TO AUDIT PROCESSING FAILURES | CONFIGURABLE TRAFFIC VOLUME THRESHOLDS
The information system enforces configurable network communications traffic volume thresholds
reflecting limits on auditing capacity and [Selection: rejects; delays] network traffic above those
thresholds.
Supplemental Guidance: Organizations have the capability to reject or delay the processing of
network communications traffic if auditing such traffic is determined to exceed the storage
capacity of the information system audit function. The rejection or delay response is triggered
by the established organizational traffic volume thresholds which can be adjusted based on
changes to audit storage capacity.
(4) RESPONSE TO AUDIT PROCESSING FAILURES | SHUTDOWN ON FAILURE
The information system invokes a [Selection: full system shutdown; partial system shutdown;
degraded operational mode with limited mission/business functionality available] in the event of
[Assignment: organization-defined audit failures], unless an alternate audit capability exists.
Supplemental Guidance: Organizations determine the types of audit failures that can trigger
automatic information system shutdowns or degraded operations. Because of the importance
of ensuring mission/business continuity, organizations may determine that the nature of the
audit failure is not so severe that it warrants a complete shutdown of the information system
supporting the core organizational missions/business operations. In those instances, partial
information system shutdowns or operating in a degraded mode with reduced capability may
be viable alternatives. Related control: AU-15.
References: None.
and Organizations
Priority and Baseline Allocation:
P1 LOW AU-5 MOD AU-5 HIGH AU-5 (1) (2)
