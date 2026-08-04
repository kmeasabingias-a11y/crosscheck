# NIST SP 800-53 REV5 — Audit and Accountability (AU)

## AU-1 — Policy And Procedures

Control:
a. Develop, document, and disseminate to [Assignment: organization-defined personnel or
roles]:
1. [Selection (one or more): Organization-level; Mission/business process-level; System-
level] audit and accountability policy that:
(a) Addresses purpose, scope, roles, responsibilities, management commitment,
coordination among organizational entities, and compliance; and
(b) Is consistent with applicable laws, executive orders, directives, regulations, policies,
standards, and guidelines; and
2. Procedures to facilitate the implementation of the audit and accountability policy and
the associated audit and accountability controls;
b. Designate an [Assignment: organization-defined official] to manage the development,
documentation, and dissemination of the audit and accountability policy and procedures;
and
c. Review and update the current audit and accountability:
1. Policy [Assignment: organization-defined frequency] and following [Assignment:
organization-defined events]; and
2. Procedures [Assignment: organization-defined frequency] and following [Assignment:
organization-defined events].
Discussion: Audit and accountability policy and procedures address the controls in the AU family
that are implemented within systems and organizations. The risk management strategy is an
important factor in establishing such policies and procedures. Policies and procedures contribute
to security and privacy assurance. Therefore, it is important that security and privacy programs
collaborate on the development of audit and accountability policy and procedures. Security and
privacy program policies and procedures at the organization level are preferable, in general, and
may obviate the need for mission- or system-specific policies and procedures. The policy can be
included as part of the general security and privacy policy or be represented by multiple policies
that reflect the complex nature of organizations. Procedures can be established for security and
privacy programs, for mission or business processes, and for systems, if needed. Procedures
describe how the policies or controls are implemented and can be directed at the individual or
role that is the object of the procedure. Procedures can be documented in system security and
privacy plans or in one or more separate documents. Events that may precipitate an update to
audit and accountability policy and procedures include assessment or audit findings, security
incidents or breaches, or changes in applicable laws, executive orders, directives, regulations,
policies, standards, and guidelines. Simply restating controls does not constitute an
organizational policy or procedure.
Related Controls: PM-9, PS-8, SI-12.
Control Enhancements: None.
References: [SP 800-12], [SP 800-30], [SP 800-39], [SP 800-100].
This
publication
is
available
free
of
charge
from:
https://doi.org/10.6028/NIST.SP.800-53r5

## AU-2 — Event Logging

Control:
a. Identify the types of events that the system is capable of logging in support of the audit
function: [Assignment: organization-defined event types that the system is capable of
logging];
b. Coordinate the event logging function with other organizational entities requiring audit-
related information to guide and inform the selection criteria for events to be logged;
c. Specify the following event types for logging within the system: [Assignment: organization-
defined event types (subset of the event types defined in AU-2a.) along with the frequency of
(or situation requiring) logging for each identified event type];
d. Provide a rationale for why the event types selected for logging are deemed to be adequate
to support after-the-fact investigations of incidents; and
e. Review and update the event types selected for logging [Assignment: organization-defined
frequency].
Discussion: An event is an observable occurrence in a system. The types of events that require
logging are those events that are significant and relevant to the security of systems and the
privacy of individuals. Event logging also supports specific monitoring and auditing needs. Event
types include password changes, failed logons or failed accesses related to systems, security or
privacy attribute changes, administrative privilege usage, PIV credential usage, data action
changes, query parameters, or external credential usage. In determining the set of event types
that require logging, organizations consider the monitoring and auditing appropriate for each of
the controls to be implemented. For completeness, event logging includes all protocols that are
operational and supported by the system.
To balance monitoring and auditing requirements with other system needs, event logging
requires identifying the subset of event types that are logged at a given point in time. For
example, organizations may determine that systems need the capability to log every file access
successful and unsuccessful, but not activate that capability except for specific circumstances due
to the potential burden on system performance. The types of events that organizations desire to
be logged may change. Reviewing and updating the set of logged events is necessary to help
ensure that the events remain relevant and continue to support the needs of the organization.
Organizations consider how the types of logging events can reveal information about individuals
that may give rise to privacy risk and how best to mitigate such risks. For example, there is the
potential to reveal personally identifiable information in the audit trail, especially if the logging
event is based on patterns or time of usage.
Event logging requirements, including the need to log specific event types, may be referenced in
other controls and control enhancements. These include AC-2(4), AC-3(10), AC-6(9), AC-17(1),
CM-3f, CM-5(1), IA-3(3.b), MA-4(1), MP-4(2), PE-3, PM-21, PT-7, RA-8, SC-7(9), SC-7(15), SI-3(8),
SI-4(22), SI-7(8), and SI-10(1). Organizations include event types that are required by applicable
laws, executive orders, directives, policies, regulations, standards, and guidelines. Audit records
can be generated at various levels, including at the packet level as information traverses the
network. Selecting the appropriate level of event logging is an important part of a monitoring
and auditing capability and can identify the root causes of problems. When defining event types,
organizations consider the logging necessary to cover related event types, such as the steps in
distributed, transaction-based processes and the actions that occur in service-oriented
architectures.
Related Controls: AC-2, AC-3, AC-6, AC-7, AC-8, AC-16, AC-17, AU-3, AU-4, AU-5, AU-6, AU-7, AU-
11, AU-12, CM-3, CM-5, CM-6, CM-13, IA-3, MA-4, MP-4, PE-3, PM-21, PT-2, PT-7, RA-8, SA-8, SC-
7, SC-18, SI-3, SI-4, SI-7, SI-10, SI-11.
This
publication
is
available
free
of
charge
from:
https://doi.org/10.6028/NIST.SP.800-53r5
Control Enhancements:
(1) EVENT LOGGING | COMPILATION OF AUDIT RECORDS FROM MULTIPLE SOURCES
[Withdrawn: Incorporated into AU-12.]
(2) EVENT LOGGING | SELECTION OF AUDIT EVENTS BY COMPONENT
[Withdrawn: Incorporated into AU-12.]
(3) EVENT LOGGING | REVIEWS AND UPDATES
[Withdrawn: Incorporated into AU-2.]
(4) EVENT LOGGING | PRIVILEGED FUNCTIONS
[Withdrawn: Incorporated into AC-6(9).]
References: [OMB A-130], [SP 800-92].

## AU-3 — Content Of Audit Records

Control: Ensure that audit records contain information that establishes the following:
a. What type of event occurred;
b. When the event occurred;
c. Where the event occurred;
d. Source of the event;
e. Outcome of the event; and
f. Identity of any individuals, subjects, or objects/entities associated with the event.
Discussion: Audit record content that may be necessary to support the auditing function
includes event descriptions (item a), time stamps (item b), source and destination addresses
(item c), user or process identifiers (items d and f), success or fail indications (item e), and
filenames involved (items a, c, e, and f) . Event outcomes include indicators of event success or
failure and event-specific results, such as the system security and privacy posture after the event
occurred. Organizations consider how audit records can reveal information about individuals that
may give rise to privacy risks and how best to mitigate such risks. For example, there is the
potential to reveal personally identifiable information in the audit trail, especially if the trail
records inputs or is based on patterns or time of usage.
Related Controls: AU-2, AU-8, AU-12, AU-14, MA-4, PL-9, SA-8, SI-7, SI-11.
Control Enhancements:
(1) CONTENT OF AUDIT RECORDS | ADDITIONAL AUDIT INFORMATION
Generate audit records containing the following additional information: [Assignment:
organization-defined additional information].
Discussion: The ability to add information generated in audit records is dependent on
system functionality to configure the audit record content. Organizations may consider
additional information in audit records including, but not limited to, access control or flow
control rules invoked and individual identities of group account users. Organizations may
also consider limiting additional audit record information to only information that is
explicitly needed for audit requirements. This facilitates the use of audit trails and audit logs
by not including information in audit records that could potentially be misleading, make it
more difficult to locate information of interest, or increase the risk to individuals' privacy.
Related Controls: None.
This
publication
is
available
free
of
charge
from:
https://doi.org/10.6028/NIST.SP.800-53r5
(2) CONTENT OF AUDIT RECORDS | CENTRALIZED MANAGEMENT OF PLANNED AUDIT RECORD CONTENT
[Withdrawn: Incorporated into PL-9.]
(3) CONTENT OF AUDIT RECORDS | LIMIT PERSONALLY IDENTIFIABLE INFORMATION ELEMENTS
Limit personally identifiable information contained in audit records to the following
elements identified in the privacy risk assessment: [Assignment: organization-defined
elements].
Discussion: Limiting personally identifiable information in audit records when such
information is not needed for operational purposes helps reduce the level of privacy risk
created by a system.
Related Controls: RA-3.
References: [OMB A-130], [IR 8062].

## AU-4 — Audit Log Storage Capacity

Control: Allocate audit log storage capacity to accommodate [Assignment: organization-defined
audit log retention requirements].
Discussion: Organizations consider the types of audit logging to be performed and the audit log
processing requirements when allocating audit log storage capacity. Allocating sufficient audit
log storage capacity reduces the likelihood of such capacity being exceeded and resulting in the
potential loss or reduction of audit logging capability.
Related Controls: AU-2, AU-5, AU-6, AU-7, AU-9, AU-11, AU-12, AU-14, SI-4.
Control Enhancements:
(1) AUDIT LOG STORAGE CAPACITY | TRANSFER TO ALTERNATE STORAGE
Transfer audit logs [Assignment: organization-defined frequency] to a different system,
system component, or media other than the system or system component conducting the
logging.
Discussion: Audit log transfer, also known as off-loading, is a common process in systems
with limited audit log storage capacity and thus supports availability of the audit logs. The
initial audit log storage is only used in a transitory fashion until the system can communicate
with the secondary or alternate system allocated to audit log storage, at which point the
audit logs are transferred. Transferring audit logs to alternate storage is similar to AU-9(2) in
that audit logs are transferred to a different entity. However, the purpose of selecting AU-
9(2) is to protect the confidentiality and integrity of audit records. Organizations can select
either control enhancement to obtain the benefit of increased audit log storage capacity and
preserving the confidentiality, integrity, and availability of audit records and logs.
Related Controls: None.
References: None.

## AU-5 — Response To Audit Logging Process Failures

Control:
a. Alert [Assignment: organization-defined personnel or roles] within [Assignment:
organization-defined time period] in the event of an audit logging process failure; and
b. Take the following additional actions: [Assignment: organization-defined additional actions].
Discussion: Audit logging process failures include software and hardware errors, failures in audit
log capturing mechanisms, and reaching or exceeding audit log storage capacity. Organization-
defined actions include overwriting oldest audit records, shutting down the system, and stopping
This
publication
is
available
free
of
charge
from:
https://doi.org/10.6028/NIST.SP.800-53r5
the generation of audit records. Organizations may choose to define additional actions for audit
logging process failures based on the type of failure, the location of the failure, the severity of
the failure, or a combination of such factors. When the audit logging process failure is related to
storage, the response is carried out for the audit log storage repository (i.e., the distinct system
component where the audit logs are stored), the system on which the audit logs reside, the total
audit log storage capacity of the organization (i.e., all audit log storage repositories combined), or
all three. Organizations may decide to take no additional actions after alerting designated roles
or personnel.
Related Controls: AU-2, AU-4, AU-7, AU-9, AU-11, AU-12, AU-14, SI-4, SI-12.
Control Enhancements:
(1) RESPONSE TO AUDIT LOGGING PROCESS FAILURES | STORAGE CAPACITY WARNING
Provide a warning to [Assignment: organization-defined personnel, roles, and/or locations]
within [Assignment: organization-defined time period] when allocated audit log storage
volume reaches [Assignment: organization-defined percentage] of repository maximum
audit log storage capacity.
Discussion: Organizations may have multiple audit log storage repositories distributed
across multiple system components with each repository having different storage volume
capacities.
Related Controls: None.
(2) RESPONSE TO AUDIT LOGGING PROCESS FAILURES | REAL-TIME ALERTS
Provide an alert within [Assignment: organization-defined real-time period] to
[Assignment: organization-defined personnel, roles, and/or locations] when the following
audit failure events occur: [Assignment: organization-defined audit logging failure events
requiring real-time alerts].
Discussion: Alerts provide organizations with urgent messages. Real-time alerts provide
these messages at information technology speed (i.e., the time from event detection to alert
occurs in seconds or less).
Related Controls: None.
(3) RESPONSE TO AUDIT LOGGING PROCESS FAILURES | CONFIGURABLE TRAFFIC VOLUME THRESHOLDS
Enforce configurable network communications traffic volume thresholds reflecting limits
on audit log storage capacity and [Selection: reject; delay] network traffic above those
thresholds.
Discussion: Organizations have the capability to reject or delay the processing of network
communications traffic if audit logging information about such traffic is determined to
exceed the storage capacity of the system audit logging function. The rejection or delay
response is triggered by the established organizational traffic volume thresholds that can be
adjusted based on changes to audit log storage capacity.
Related Controls: None.
(4) RESPONSE TO AUDIT LOGGING PROCESS FAILURES | SHUTDOWN ON FAILURE
Invoke a [Selection: full system shutdown; partial system shutdown; degraded operational
mode with limited mission or business functionality available] in the event of [Assignment:
organization-defined audit logging failures], unless an alternate audit logging capability
exists.
Discussion: Organizations determine the types of audit logging failures that can trigger
automatic system shutdowns or degraded operations. Because of the importance of
ensuring mission and business continuity, organizations may determine that the nature of
the audit logging failure is not so severe that it warrants a complete shutdown of the system
This
publication
is
available
free
of
charge
from:
https://doi.org/10.6028/NIST.SP.800-53r5
supporting the core organizational mission and business functions. In those instances, partial
system shutdowns or operating in a degraded mode with reduced capability may be viable
alternatives.
Related Controls: AU-15.
(5) RESPONSE TO AUDIT LOGGING PROCESS FAILURES | ALTERNATE AUDIT LOGGING CAPABILITY
Provide an alternate audit logging capability in the event of a failure in primary audit
logging capability that implements [Assignment: organization-defined alternate audit
logging functionality].
Discussion: Since an alternate audit logging capability may be a short-term protection
solution employed until the failure in the primary audit logging capability is corrected,
organizations may determine that the alternate audit logging capability need only provide a
subset of the primary audit logging functionality that is impacted by the failure.
Related Controls: AU-9.
References: None.
