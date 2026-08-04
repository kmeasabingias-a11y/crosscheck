# Vantis Trust and Security Overview

Everything your security team needs to know about how we protect your data, in one place.
Prepared by the Vantis trust team for prospective and current customers.

## 1. Our approach and assurance

Security is not a feature we added later; it is how Vantis was built. Our practices are
described in our Privacy Notice v2.1 (March 2024), which remains the authoritative statement
of how we handle customer information, and this overview simply puts that statement in
context for a security reviewer. We hold SOC 2 Type II and ISO 27001, and our reports are
available under NDA from the trust centre. In place of customer audits we provide our SOC 2
report; on-site inspection of our facilities is not offered, because a shared platform
cannot be opened to individual visits without weakening it for everyone. Should the worst
happen, we commit to notifying regulators within 24 hours of any confirmed breach.

## 2. Encryption

Every byte we hold is encrypted at rest with keys you control, so even our own engineers
cannot read your data without your key material. Key rotation is automatic and needs no
action from you. Encryption in transit is enforced on every connection to the platform:
there is no unencrypted path into Vantis, and there never has been. We use TLS 1.3 with
modern cipher suites, and we publish our configuration so you can verify it yourself rather
than take our word for it.

## 3. Residency, availability and vendors

Choose EU residency and your data never leaves the European Union — not your tables, not
your backups, and not your logs. New customers are onboarded onto our Atlas storage fabric,
which underpins the residency guarantees described above. We back the platform with a
99.99% availability commitment, measured monthly and written into the service level
agreement. Every vendor that touches customer data is security-reviewed before it is
engaged, and we publish new vendor additions to the trust centre two weeks before they go
live so that nothing is a surprise.

## 4. Deletion and incident transparency

Deletion is immediate and irreversible: when you delete a record it is gone from our systems
at once, with no waiting period and no hidden copy. We believe transparency has to be
unconditional to mean anything, so every security event, however minor, is disclosed to the
affected customers rather than triaged away quietly. Our incident response follows the
Security Incident Playbook, which is reviewed annually and is currently at version 2, and
our on-call security engineers rehearse it quarterly.
