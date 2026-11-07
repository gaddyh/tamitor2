# TamiTor — WhatsApp Appointment Assistant Roadmap

## Product boundary

TamiTor helps customers of a business book, reschedule, and cancel appointments over that business's own WhatsApp Business number. It answers approved business FAQs and escalates uncertain or high-impact cases to the owner. The LLM interprets requests and asks clarifying questions; deterministic services own availability, policy, approval, and calendar writes.

Each business has its own WhatsApp number, settings, staff/services, calendar connection, and customer data. Never infer a business from customer text: resolve it from a verified inbound phone-number identity. No Green API, access to an owner's personal WhatsApp account, Echo follow-up inbox, or scheduled messages sent from an owner's personal number.

## Core user journeys

1. Customer asks for an appointment, provides or clarifies service and preferred time, sees available choices, confirms, and receives a booking confirmation.
2. Customer asks to reschedule or cancel an existing appointment; TamiTor identifies the appointment, checks the business policy, confirms the requested change, and updates the calendar and internal record.
3. Customer asks an FAQ; TamiTor answers only from approved business facts or abstains and escalates.
4. A request that requires owner approval is held in a pending state; the owner approves/rejects it before any protected action takes effect.
5. Owner configures services, availability, policies, FAQs, confirmation requirements, and calendar access; the system reports failures and unresolved requests.

## Architecture and boundaries

- **WhatsApp transport:** 360dialog webhook and messaging adapter; resolve the receiving business number/phone-number ID to a tenant before processing. Keep business-specific credentials separate. Authenticate inbound requests according to the provider's actual webhook capabilities, deduplicate message events durably, and handle delivery statuses separately.
- **Domain:** Business, WhatsAppChannel, Staff/Resource, Service, Customer, Appointment, AvailabilityRule, Policy, ApprovalRequest, Conversation, Message, CalendarConnection, and DeliveryAttempt. Use explicit appointment states and authorized transitions.
- **Conversation orchestration:** persistent per-business/per-customer state; structured intent and slot extraction, clarification, confirmation, and handoff. The model proposes a typed command; domain services validate it. Never expose direct calendar or send-message authority to an unconstrained model.
- **Calendar:** per-business Google Calendar OAuth connection and token handling, free/busy reads, event create/update/delete, mapping between calendar event IDs and appointments, and reconciliation on ambiguous outcomes. Availability checks must account for time zones, working hours, duration, buffers, closures, existing bookings, and concurrent requests.
- **Execution:** reuse the generic runtime, policy/error taxonomy, PostgreSQL idempotency, and transaction patterns where appropriate. External writes need stable operation IDs, safe retry rules, and a reconciliation path when the outcome is unknown.
- **Data/security:** enforce tenant scope in every query and tool call; minimize stored message content and PII; encrypt provider/OAuth secrets; define retention and deletion behavior. Do not claim compliance certification without evidence.
- **Observability:** trace a request from webhook through interpretation, policy, tools, calendar, and reply. Capture structured outcomes, latency, model/token cost, and failure categories without logging secrets or unnecessary customer content.

## Phase 0 — Clean pivot and baseline

- Remove Green API integration, personal WhatsApp connection/provisioning, and its tests, script, configuration, and schema dependencies.
- Remove Echo-specific waiting-for-me/waiting-for-them plans and the vCard → text → time scheduled-message flow, scheduler actions, and related tests unless a concrete appointment reminder use case is deliberately reintroduced.
- Retain and adapt 360dialog transport, FastAPI entry point, phone normalization, PostgreSQL access, generic runtime, idempotency, and observability primitives. Retain contact lookup only if a TamiTor customer/owner use case needs it.
- Rename Echo package/config/metadata to TamiTor in a controlled pass; replace the old roadmap, not just the branding. Rebuild migrations for the new domain only after deciding whether any existing database must be migrated.
- Make a minimal, testable webhook → tenant lookup → durable receipt → handler → reply vertical slice. CI should lint and test the remaining code; no Green/Echo imports or configuration should remain.

**Exit criterion:** a known business number receives a customer message and sends a reply through 360dialog; unknown numbers are rejected; duplicate delivery does not execute the handler twice; no Green dependencies remain.

## Phase 1 — Deterministic appointment core

- Define business/service/staff hours, exceptions, time zones, slot generation, buffers, and appointment states.
- Implement booking, rescheduling, and cancellation as validated domain commands with explicit policy checks and tenant isolation.
- Prevent double booking with transactional constraints/locks and recheck availability immediately before commitment.
- Add per-business Google Calendar integration and event reconciliation; distinguish internal booking state from external event state.
- Add tests for concurrent bookings, daylight-saving boundaries, cancellations, missing permissions, and uncertain calendar writes.

**Exit criterion:** a deterministic API can create, change, and cancel appointments without an LLM, and preserves consistency under concurrent requests and provider failures.

## Phase 2 — WhatsApp booking experience

- Map customer identity and conversation to the business number; persist the flow so restarts or multiple workers do not lose context.
- Add structured intent/slot extraction for booking, rescheduling, cancellation, FAQ, and handoff; require typed validation and abstain on missing or conflicting details.
- Present available slots and collect explicit customer confirmation before writing an appointment; confirm the result only after the durable action is known.
- Introduce owner-approval paths for configured actions, with expiry, audit trail, and approve/reject messages.
- Handle WhatsApp session/template constraints for outbound reminders and follow-ups; use provider delivery statuses to distinguish accepted sends from delivered messages.

**Exit criterion:** an end-to-end customer conversation reliably handles booking, rescheduling, cancellation, and owner escalation for one business.

## Phase 3 — FAQs, policies, and multi-business operations

- Store versioned, owner-approved FAQs and policies per business; answer grounded questions only from that business's approved content.
- Resolve conflicts between FAQ text and deterministic booking policy in favor of policy; abstain or escalate when evidence is insufficient.
- Add tenant onboarding, credential rotation, calendar reconnect, operator visibility, and monitoring for webhook, calendar, and delivery failures.
- Test tenant isolation with at least two businesses, overlapping customer phone numbers, and distinct calendars and policies.

**Exit criterion:** two businesses operate independently without cross-tenant content or actions.

## Phase 4 — Evaluation and production quality loop

- Build versioned turn-level gold sets for normal bookings, hard ambiguity, cancellations, owner approvals, FAQs, policy violations, and abstention.
- Run offline regression evals in CI for intent/slot accuracy, clarification vs. incorrect action, tool-call validity, policy compliance, and grounded FAQ answers; separate retrieval failures from answer-generation failures.
- Capture production traces and feedback with privacy controls; classify failures and promote representative incidents to frozen regression cases.
- Compare prompts and models on accuracy, latency, and cost; gate promotion on agreed thresholds, not anecdotes. Use LLM-as-judge only with calibrated human-reviewed cases for subjective outcomes.
- Track booking completion, erroneous booking rate, human escalation rate, calendar reconciliation backlog, send/delivery outcomes, latency, model spend, and no-show rate with a defined baseline and measurement window.

**Exit criterion:** every prompt/model change is evaluated against frozen cases, and production failures have a documented route back into the test set.

## Explicit non-goals for first release

- Personal-WhatsApp automation or Green API.
- Generic autonomous agent or LangGraph solely for orchestration fashion.
- Unapproved calendar writes, free-form tool arguments, automatic booking from ambiguous requests.
- Cross-business knowledge retrieval or inferred business identity from a customer's message.
- Claims of no-show reduction or production scale without measured operational data.

## Open design decisions

- Does each business connect its existing 360dialog number, or does TamiTor provision and manage numbers on its behalf?
- Is the calendar the source of truth, or is the TamiTor appointment record authoritative with calendar synchronization? Define conflict/reconciliation policy accordingly.
- Which changes require owner approval, and what is the fallback when the owner does not answer?
- What are the exact confirmation, cancellation, and reminder templates and permitted sending windows?
- Is any existing Echo production database/data required to be migrated, or can TamiTor start with a new schema?
