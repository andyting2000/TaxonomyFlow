# Candidate-retrieval failure isolation — #19C-hotfix-0b

Status: **PASS for the focused implementation evidence.**

One malformed or unsupported row no longer collapses advisory #19C. A local
preparation/scoring/context exception produces a `retrieval_failed` row with no
selected concept, `requires_human_review=true`, and zero provider calls. Other
rows continue independently. Empty or unknown safe scope remains empty; the
retriever never broadens to all 923 concepts.

Registry/linkage failure, concept-inventory construction or index corruption,
upstream structure/classification identity failure, invalid authoritative row
identity, and row-limit failure remain stage-fatal.

Retrieval telemetry now records source, skipped, eligible, attempted,
successful, zero-candidate, locally failed, and stage-fatal counts. Up to 100
row errors contain only row identifier, whitelisted reason code, and sanitized
exception class. No source value, arbitrary exception message, or stack trace
is stored.

The minimized Job 68 fixture retains the triggering label, structural row type,
matched `420000` classification, comprehensive-income family, and eight-card
context while replacing company-specific values. Focused verification covers
the real shape, nonmapping classifications, missing/unclassified sections,
unknown group scope, missing metadata, malformed inventory cards, scoring and
context exceptions, isolation, stage-fatal registry/inventory failures,
zero-provider behavior, artifact publication, telemetry, and zero mutations.
The complete #19C selection passed 68 tests, the affected #19A/#19B/Azure-DI/
Celery/API selection passed 128 tests, and the full backend suite passed all
1,471 tests.
