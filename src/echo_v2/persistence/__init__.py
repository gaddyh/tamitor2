"""Persistence layer for TamiTor.

Contains:
* Business-owned WhatsApp number mapping and durable webhook receipts.
* Postgres-backed webhook dedup and idempotency stores plus a transaction UoW.
* Optional phone identity and contacts for generic lookup use cases.
* A :class:`CredentialCipher` boundary for encrypted provider credentials.
* Alembic migrations under ``alembic/``.
"""
