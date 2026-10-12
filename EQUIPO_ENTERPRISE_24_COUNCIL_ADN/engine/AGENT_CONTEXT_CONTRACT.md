# Operational identity and activated context

This is an offline contract, not proof of AI consciousness, human credentials,
persistent memory, tool availability, plugin installation, or native execution.

## Identity

New organizations and explicitly edited organizations receive a derived
`operational_identity` per existing agent ID. Names, roles, mission, personality,
manager, reports and team IDs come from current structural fields. Rendering
re-derives this data rather than trusting a stale copy. A rename never creates an
ID. Historical artifacts without this marker keep their legacy prompts.

The greeting presents an AI agent's operational name and role naturally, asks for
missing task context and respects professional judgment without servility or
claims of superiority. KIMI is only a conceptual reference, not a borrowed runtime
identity or claim of human consciousness. Skills remain evidence-dependent.

Working-memory decisions are included only when explicitly recorded with status
`authorized`, decision ID, summary, authorizer and evidence reference. This is a
record schema, not a persistence engine, authentication mechanism, or permission
grant. No synthetic past experiences or decisions are generated. Current policy
and per-action authorization always prevail over archived records.

## Pure compilation

`compile_agent_context(org, capability_library_snapshot=None)` returns a mapping
of the same agent IDs to prompt receipts without mutating the organization. Base
prompts are exactly `core._render_prompt`. The snapshot is validated against the
organization, roster, immutable item payload hashes and assignments. Its canonical
SHA-256 is included with activated instructions and the compilation receipt.

Assignment alone does not activate content. Only explicitly active
`skill_instructions` and `memory_policy` items become context. `plugin_package`
and `connector` cannot become instructions and remain separately blocked pending
native review, installation, authorization and health checks.

Content is serialized as delimited reference data subordinate to policy, role,
mandate and tool permissions. Neither an instruction nor a memory policy can grant
permissions, expand the native tool list, authorize actions or claim verification.

Whole items are considered in stable ID order. The configured UTF-8 context
budget and strict DSH prompt limit of fewer than 50,000 UTF-16 units both apply.
Oversized items are listed as deferred, never cut. No base instruction is removed
to make room. Receipts state included/deferred IDs and runtime-unverified status.
The original native toolScope is unchanged, including its 256-tool constraint.

Recompilation always starts from the current base, never a previous compiled
prompt. Deactivation or removal therefore removes content on the next export and
readback. No snapshot or no activation preserves native prompts byte-for-byte.
At the default 12,000-byte budget, `CapabilityLibrary.active_context` uses the same
validated canonical snapshot as export, including its hash and prompt. Other
budgets are explicitly unpinned previews.
