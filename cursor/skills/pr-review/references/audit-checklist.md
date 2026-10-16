# Audit checklist

Each section starts with a **Relevant when** trigger. Skip a section only when the diff genuinely doesn't touch that area, and record the skip so the coverage summary stays honest.

The questions are prompts for investigation, not a form to fill in. A section is done when you've traced the code well enough to answer its questions from what the code actually does — not from what its names suggest it does.

## Contents

1. [Severity rubric](#severity-rubric)
2. [Data layer and migrations](#1-data-layer-and-migrations)
3. [Authorization and access control](#2-authorization-and-access-control)
4. [Concurrency, transactions, idempotency](#3-concurrency-transactions-idempotency)
5. [Lifecycle and state transitions](#4-lifecycle-and-state-transitions)
6. [Input, boundaries, and validation](#5-input-boundaries-and-validation)
7. [Client state and interaction](#6-client-state-and-interaction)
8. [Accessibility, responsiveness, localization](#7-accessibility-responsiveness-localization)
9. [Async work, notifications, deep links](#8-async-work-notifications-deep-links)
10. [File and object storage](#9-file-and-object-storage)
11. [Backward compatibility and blast radius](#10-backward-compatibility-and-blast-radius)
12. [Test quality](#11-test-quality)
13. [Documentation, config, observability](#12-documentation-config-observability)

---

## Severity rubric

Calibrate against consequence, not effort to fix.

| Severity | Meaning |
|---|---|
| **Critical** | Data loss or corruption, authz bypass, secret exposure, or a break that reaches production users on a common path. Should block merge. |
| **High** | Wrong behavior on a realistic path, a migration that can fail or lock in production, a race that costs money or integrity. Fix before merge. |
| **Medium** | Edge case, degraded UX, missing validation with limited blast radius, a test that doesn't test what it claims. Fix soon; can be a follow-up if tracked. |
| **Low** | Naming, dead code, minor duplication, doc drift. Optional — and if you have many of these, group them in the review body instead of posting fifteen inline comments. |

When you're between two levels, ask what happens if nobody fixes it for six months.

---

## 1. Data layer and migrations

**Relevant when:** the diff touches schema, migrations, ORM models, queries, or stored procedures.

- Is the migration reversible, and if not, is that acknowledged? Does the down path actually restore prior state?
- Can it run against production-scale data without an unacceptable lock? (Adding a non-null column with a default, creating an index non-concurrently, and rewriting large tables are the usual offenders.)
- Do new constraints hold for **existing** rows? A constraint valid for new writes can abort the migration on legacy data — check for backfill.
- Do defaults, nullability, and types match what the application code writes and reads? Look specifically at timezone-aware vs naive timestamps, numeric precision for money, and enum/check-constraint values versus the application's string literals.
- Is there a deploy-ordering hazard — does the new code require the migration, or the migration break the old code? Which ships first?
- Are new columns indexed for the queries that filter on them, and does any new index duplicate an existing one?
- Do foreign keys specify the intended cascade behavior, and does that match what the cleanup code assumes?
- If final schema differs from earlier migrations in the same PR, do docs and types describe the **final** state?

## 2. Authorization and access control

**Relevant when:** anything touches auth, roles, tenancy, row filtering, database policies/grants, or a new endpoint or data-access path.

- Every new read and write path: who is allowed, and is that enforced server-side? Client-side gating is UX, not security.
- For row-level policies: do the new or changed policies cover **all** of SELECT/INSERT/UPDATE/DELETE, and does an UPDATE policy have both a USING and a WITH CHECK condition? A missing WITH CHECK lets a caller move a row out of their own scope.
- Did the PR drop or replace a policy that other features relied on? Search for other consumers of the same table.
- For privilege-elevated functions (`SECURITY DEFINER` or equivalent): do they re-check the caller's identity internally, and is `search_path` pinned? Elevated functions are the standard route around row filtering.
- Are grants to application roles minimal, and were any granted broadly to make something work?
- Can an object identifier be swapped for another tenant's identifier (IDOR)? Trace one request with a foreign ID.
- Are secrets, tokens, or internal identifiers newly exposed in responses, logs, error messages, or client bundles?

## 3. Concurrency, transactions, idempotency

**Relevant when:** the change writes to more than one place, retries, has a job/webhook entry point, or can be triggered twice.

- What happens if the request runs twice concurrently? Two approvals, two uploads, two clicks, two tabs.
- Are multi-step writes in one transaction, and does the transaction span everything that must be atomic — including the non-database side effects that can't roll back (emails sent, files deleted, payments charged)? Name the partial-commit state.
- Is there a check-then-act gap (read state, decide, write) without a lock, unique constraint, or conditional update to close it?
- Retries: is the handler idempotent, or does a retried webhook/job double its effect? Is there an idempotency key, and is it actually unique per logical operation?
- Lock ordering: do two paths acquire the same resources in different orders? That's the deadlock.
- Is anything slow (network call, file operation) held inside a transaction or a lock?
- Does read-modify-write on a shared counter or JSON blob lose concurrent updates?

## 4. Lifecycle and state transitions

**Relevant when:** the entity has a status, or the feature has approve/reject/cancel/supersede/retry semantics.

- Enumerate every status and every allowed transition. Is each one implemented, and is each *disallowed* transition actually rejected server-side?
- What happens to an action taken **after** the entity becomes ineligible — approving something already rejected, editing after submission, cancelling after completion, retrying after success? Stale UI plus a slow user produces exactly this.
- Terminal states: can anything move out of one?
- Does superseding or replacing an entity clean up what the old one owned (files, jobs, notifications, denormalized counters)?
- Are all paths covered: create, edit, replace, approve, reject, supersede, cancel, retry, and cleanup?
- Is transition history recorded where the product needs an audit trail?

## 5. Input, boundaries, and validation

**Relevant when:** any new or changed field, parameter, or form.

For each field, walk the values: null, missing, empty string, whitespace-only, cleared-after-being-set, zero, negative, maximum length, over maximum length, unicode/emoji, leading-trailing whitespace, malformed type, and duplicates.

- Is validation enforced at the boundary the attacker can't skip (server/database), not only in the form?
- Do client and server validation agree? Disagreement produces either a rejected valid input or an accepted invalid one.
- Is "cleared" distinguishable from "never set", and does the code handle both?
- Are numeric fields bounded and money handled without floats?
- Is user-supplied text escaped where rendered and parameterized where queried?

## 6. Client state and interaction

**Relevant when:** the diff touches UI components, hooks, or client-side data fetching.

- Does every async action have a loading state that actually disables the trigger? Double-submission is the most common defect in this category.
- Stale closures: does a callback or effect capture a value that's since changed? Check dependency arrays for both missing deps (stale) and unstable deps (loops).
- Can a response land after the component unmounts, or after a newer request for the same data? Is there an abort/ignore mechanism, or can an older response overwrite a newer one?
- Error recovery: after a failure, can the user retry without reloading? Is the error surfaced at all, or swallowed into a console log?
- Is optimistic UI rolled back on failure, and is cached/query state invalidated after a mutation so other views don't show stale data?
- Multiple tabs, back button, refresh mid-flow, and deep-linking into an intermediate step.
- Are values rendered in human-readable form — enum keys, raw timestamps, and IDs leaking into the UI is a small but real finding.

## 7. Accessibility, responsiveness, localization

**Relevant when:** the diff renders anything.

- Keyboard: can every action be reached and triggered? Is focus moved into dialogs and returned on close? Is focus trapped in modals?
- Semantics: real `button`/`a` elements or correct roles; labels tied to inputs; errors associated with their field and announced; icon-only controls named.
- Is state communicated by more than color, and is contrast adequate?
- Does the layout hold at narrow widths and at increased text size? Is anything cut off or unscrollable?
- Are new strings localized in projects that localize, and do date, number, and currency formats respect locale?

## 8. Async work, notifications, deep links

**Relevant when:** the change enqueues jobs, sends notifications, or emits events.

- If the job fails permanently, what does the user see? Silent failure is the default failure mode here.
- Is the notification sent inside the transaction (may notify about an uncommitted change) or after it (may commit without notifying)? Which risk was chosen, and is it the right one?
- Can a notification fire twice, or fire for an entity that has since changed state?
- Do deep links resolve for a signed-out user, a user without access, and a deleted entity — and do they land on the specific item rather than a generic index?
- Are recipients correct at send time, including when membership changed between enqueue and delivery?

## 9. File and object storage

**Relevant when:** the change uploads, replaces, or deletes stored objects.

- Orphans in both directions: object stored but row insert fails; row inserted but upload fails. Which happens on error, and what cleans it up?
- On replace, is the old object deleted — and is it safe to delete if something else references the same key?
- If cleanup fails, is that logged, retried, or silently lost?
- Are object paths namespaced per tenant/user and non-guessable, and are read URLs access-controlled or signed with a sane expiry?
- Are type and size validated server-side, not just by the file picker's `accept` attribute?
- Does deleting the parent entity delete its objects?

## 10. Backward compatibility and blast radius

**Relevant when:** shared code, exported functions, API responses, or existing policies changed.

- Every removed or renamed field, parameter, policy, or export: search the whole repo for consumers, including tests, jobs, and other services.
- Do old clients (mobile apps, cached bundles, third-party API consumers) still work against the new server?
- Does a changed shared helper alter behavior for its existing callers? Read them.
- Are feature flags defaulted safely, and is there a rollback path that doesn't require a data migration?

## 11. Test quality

**Relevant when:** always. Tests are part of the diff under review.

- Does each test assert **behavior and outcome**, or does it merely mirror the implementation and pass regardless of correctness? A test that mocks the function under test, asserts a mock was called, or re-implements the logic in its expectation proves nothing.
- Would each test fail if the bug it guards against were reintroduced? Where a test looks weak, mentally invert the implementation and see if it still passes.
- Are the paths from the coverage matrix with blank test cells the risky ones? Say so in the review.
- Are error paths, authorization denials, and boundary values tested — or only the happy path?
- Any flakiness introduced: real timers, real network, ordering dependence, shared mutable fixtures?

## 12. Documentation, config, observability

**Relevant when:** behavior, schema, config, or interfaces changed.

- Do docs describe the **final** state of the PR, including schema and API changes made in later commits?
- Are new environment variables and config documented, with sane defaults and a clear failure when missing?
- Are new failure paths logged with enough context to debug, and is nothing sensitive logged?
- Does the PR description match what the code does? Divergence usually means scope crept and something went unreviewed.
