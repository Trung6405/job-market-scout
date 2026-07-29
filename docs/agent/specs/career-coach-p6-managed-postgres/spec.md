# Spec: Career Coach P6 — Always-On Managed Postgres

> **Status:** Approved
> **Created:** 2026-07-29 · **Approved:** 2026-07-29
> **Implementation plan:** [plan.md](../../plans/career-coach-p6-managed-postgres/plan.md)
> **Umbrella PRS:** `docs/project/specification/career-coach-agent-prs.md` (v1.1) — this is phase **P6**, the first phase of **Stage 2**, delivering the enabling half of FR-CC-13.

---

## Problem

Everything the system knows lives in a Postgres container on the scout VM, and
that VM is deliberately deallocated for roughly 23 hours a day to keep it off
the meter. For a batch pipeline that publishes a static dashboard once a
morning, this is fine: the database only has to exist while the run is
happening. It stops being fine the moment anyone wants to *ask* the system
something. A question arriving at 9pm reaches a machine that is powered off,
and no amount of work on the asking side changes that — the data is simply
unreachable for most of the day. Stage 2 of the Career Coach is built entirely
around on-demand questions, so the storage layer has to become independent of
the VM's power state before any of it can be built.

This is also the one commitment in the Career Coach feature that is hard to
undo. It was deliberately isolated behind a sign-off gate rather than bundled
into the grounding work, because a managed database carries standing cost and
because a pipeline pointed at a new system of record does not casually point
back.

## Success Criteria

- The gap and resource data can be queried successfully at a time when the
  scout VM is deallocated.
- A full pipeline run completes against the new database with no observable
  change in behaviour — the same listings scored, the same tips generated, the
  same dashboard rendered.
- Every run recorded before the move is still visible in the history page
  afterwards, and every resource in the corpus is still retrievable with its
  embedding intact.
- For a grace period after the move, returning to the previous database is a
  configuration change, not a restore.
- No standing cloud cost begins without it having been explicitly confirmed
  and accepted first.

---

## Requirements

### Must have

- A managed Postgres instance whose reachability does not depend on the scout
  VM being allocated, carrying the pgvector extension the corpus needs.
- The contents of all six tables present on it — `listings`, `runs`,
  `run_listings`, `listing_gaps`, `listing_tips`, `resources` — with vector
  embeddings preserved, verified by comparing row counts between source and
  target before anything is switched over.
- After cutover, the pipeline reads and writes exclusively to the managed
  instance, achieved through configuration alone with no change to application
  code or queries.
- Connections encrypted in transit.
- The cutover gated on a human reading the verification output and deciding to
  proceed — it does not happen as a side effect of a deploy.
- Rollback to the VM database available throughout a grace period by reverting
  configuration alone, with that database left intact and holding its data.
- Provisioning expressed as infrastructure-as-code alongside the existing
  templates, not clicked together in a portal.
- Credentials supplied by secret and never committed (NFR-CC-7).
- The actual cost confirmed before the instance is provisioned.

### Should have

- Local development and CI continue to run against a local database and are
  never able to reach the managed one by accident.
- A guard against the configuration seam being closed off again — the setting
  being fixed here is one that already exists and is currently overridden, and
  nothing today would catch it being overridden a second time.
- The instance sized to the smallest shape that serves the workload, so that
  free-tier eligibility is possible rather than precluded by over-provisioning.

### Won't have

- **Removal of the VM's Postgres container.** Keeping it running with its data
  intact *is* the rollback mechanism; removing it in the same change would
  reduce recovery from a configuration flip to a restore-from-dump. Teardown is
  deliberately deferred to a separate change once the grace period has passed.
- **The Discord bot, or any networking on its behalf.** That is P7, and P7 is
  the phase that knows what its own connectivity needs to look like.
- **Any schema or query change.** This phase moves data; it does not reshape
  it. The schema that lands on the managed instance is the schema that exists
  today.
- **Private networking (VNet integration / private endpoints).** A public
  endpoint restricted by IP allow-list is sufficient for one VM and, later, one
  Function, and the networking mode is fixed at creation time on Flexible
  Server — choosing the more elaborate option here would be irreversible for no
  present benefit.
- **Microsoft Entra authentication.** Password authentication supplied by
  secret reuses the credential path the deploy already has; Entra would be a
  better end state but is a separate concern from moving the data.
- **High availability, geo-redundant backup, or read replicas.** A single-user
  project with a daily batch cadence does not justify them, and each one pushes
  the instance out of the free-tier shape.
- **Connection pooling changes.** The application already holds an `asyncpg`
  pool; the managed instance's built-in pooler solves a problem this workload
  does not have.
- **Migration tooling.** The schema is idempotent `CREATE … IF NOT EXISTS`
  applied on startup, which is exactly what is needed to stand up a fresh
  instance. Introducing a migration framework to perform one move would be
  scope this phase has no use for.

---

## Proposed Approach

A fresh managed instance is provisioned and validated while the existing
database keeps serving; the data is copied across and checked; and only then,
as a deliberate human step, is the pipeline pointed at the new instance. The
old database stays alive and untouched behind it.

**The instance.** A Burstable-tier Azure Database for PostgreSQL Flexible
Server on the smallest available compute, with a modest fixed storage
allocation, no high availability, and locally-redundant backups. The major
version is pinned to match the container the data is coming from, so the copy
is a same-major move rather than an upgrade. This shape is chosen not only
because it fits the workload but because it is the shape a free allowance
would cover — over-provisioning would forfeit that possibility.

**The extension.** pgvector is not available by default on a managed instance
the way it is in the container image. The extension must first be added to the
server's extension allow-list as a server parameter, and only then can it be
created in the database. This is a step with no counterpart in the current
setup and is easy to overlook, because the schema's own
`CREATE EXTENSION IF NOT EXISTS` will simply fail against a server that has not
allow-listed it. Once allow-listed, the existing schema application needs no
change.

**Reachability.** The instance takes a public endpoint restricted by an
IP allow-list. The VM has a static public address, so a single rule covers the
pipeline. Nothing else is granted access in this phase.

**The configuration seam is a deletion.** The application already reads its
connection string from a single setting, opens one connection pool from it, and
the deploy already renders that setting from a secret onto the VM. The reason
that secret currently has no effect is that the container definition pins the
same variable inline, and an inline value takes precedence over the rendered
file. Removing that one pinned line is the entire repoint mechanism — the
secret path it uncovers has been in place all along. The connection library in
use already understands TLS parameters supplied in the connection string, so
encryption in transit is likewise a configuration matter and not a code change.

Because that line is a shadow rather than a genuine setting, its removal is
invisible in normal operation and could be reintroduced by anyone adding an
environment block back. A cheap automated check pins the fix in place.

**Moving the data.** A logical dump of the existing database restored into the
new one, ownership and privilege statements stripped since the administrative
role on a managed instance differs from the container's. The operation runs
from the VM rather than from CI: the VM's address is already allow-listed and
static, whereas CI runners draw from rotating address ranges and would require
opening the instance far wider to accomplish the same thing. Verification is a
side-by-side row count per table, plus an explicit count of resources that
still carry an embedding — the vector column is the one part of the copy whose
failure would be silent rather than loud.

**The cutover, and what makes it reversible.** Provisioning, migration, and
verification all happen while the pipeline is still writing to the old
database, so none of them can break anything. The switch itself is a single
change to the stored connection secret followed by a redeploy, confirmed by
running one full cycle and checking that its output lands on the new instance
and renders as expected. Reversing it is the same change in the other
direction. This is what the sign-off gate in the umbrella PRS buys: the
one-way door is only walked through once a human has looked at the numbers.

**What stays behind.** The container definition for the local database remains,
because local development and CI still need a real database and must never
reach the managed one. On the VM the same container keeps running, holding the
data it already has, serving no traffic — it is the rollback target, and
retiring it is out of scope here.

**Cost, before anything exists.** The instance is not created until its actual
price on this subscription has been confirmed. The free allowance that covers
this shape is documented for one class of subscription, and whether it extends
to the subscription in use here is not something to assume. If it turns out to
carry a charge, that is a decision to bring back rather than absorb.

**A latency assumption changes quietly.** Retrieval currently reaches a
database on the same host; afterwards it crosses a network with TLS on every
query. NFR-CC-2's sub-100 ms budget is still comfortably met — the corpus is
small, the pre-filter is selective, and the instance sits in the same region as
the VM — but the budget was written against a same-host assumption that no
longer holds, and the pipeline issues many queries per run rather than one.
Recorded so that a future latency surprise is diagnosed rather than
rediscovered.

**Dependencies.** This phase depends on Stage 1 being complete and signed off.
It touches no Stage 1 behaviour: the schema, the queries, the retriever, the
aggregator, the tip stage, and the report all continue to work exactly as they
do, against a different endpoint. P7 depends on this phase.

**Corrections this phase makes to the umbrella PRS.** Three points where the
PRS's description of P6 is incomplete, to be carried into it as amendments
rather than silently diverged from: it names four tables to migrate where the
foreign-key-connected set is six; it does not mention that pgvector requires
an allow-list step before it can be created; and NFR-CC-2's latency budget was
written against a same-host database, as above.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Stop deallocating the VM, leaving the existing container always reachable | Requires no migration at all and is the smallest possible change, but it makes the VM run 24/7 — the exact cost the deallocation cycle exists to avoid, and considerably more than a small managed instance. It also leaves the system of record on a single unmanaged disk with no backups. |
| Reconfigure the existing container's database in place onto managed infrastructure | Not a real option: a container-hosted database and a managed service are different products, so "in place" would still be a dump and restore, only without the ability to validate the target first. |
| A free managed Postgres outside Azure (Neon, Supabase) | Genuinely free with no expiry cliff, and adequate on capability — both support pgvector, and this workload is bursty enough that scale-to-zero with a fast wake would satisfy the availability requirement as well as always-on does. Rejected on coherence rather than capability: it puts the system of record outside the subscription that holds every other piece of infrastructure, adds a second credential domain, and its storage ceiling is tight against a listings table that grows daily. Recorded here because it remains the fallback if the Azure instance proves to carry unacceptable cost. |
| The umbrella PRS's own contingency — no database move, with on-demand queries served from the already-published static dashboard data | Free and simple, and it does make *something* answerable while the VM is down. But answers become read-only and only as fresh as the last morning's run, which reduces the interactive phase to a restatement of the dashboard. Retained in the PRS as a contingency, not chosen. |
| Managed migration tooling (Database Migration Service, logical replication) | Built for large databases and minimal-downtime cutovers. This database is small and the pipeline runs once a day, so there is a natural window in which nothing is writing; a plain dump and restore is simpler, inspectable, and has fewer moving parts to get wrong. |
| Start fresh on the new instance without copying anything | Removes the entire migration step and the risk that comes with it. Rejected because the run history is what the dashboard's history page displays, and the corpus was accumulated by weekly aggregation runs that cost GitHub API budget and LLM tagging spend to produce — discarding both to save one dump command is a bad trade. |
| Run the migration from CI rather than from the VM | Keeps the whole operation in one automated place. Rejected because CI runners have rotating addresses, so allow-listing them means opening the instance to a very wide range — a permanent weakening of the access rules to save one SSH invocation. |
| Automate the cutover end to end, failing the deploy if verification fails | Least manual effort, and the verification is mechanical enough to encode. Rejected because it moves a one-way door behind an unattended script: a verification that passes for the wrong reason would repoint the system of record with nobody having looked. |
| Do nothing | The data stays unreachable whenever the VM is down, which is most of the time. Stage 2 cannot be built at all, and FR-CC-13 is unsatisfiable by definition. |

---

## Open Questions

| Question | Who decides | Blocks planning? |
|----------|-------------|------------------|
| Whether this subscription qualifies for the free allowance covering this instance shape, or whether it will be billed | human | No — the plan is the same either way. It gates *execution*: provisioning stops and returns for a decision if a charge appears. |
| How long the grace period runs before the VM's database is retired | human | No — retirement is a separate change, and the grace period can be as long as wanted. |
| Whether transport encryption should later be tightened from encrypt-only to full certificate verification | human | No — encryption in transit is satisfied either way; verification strictness is a hardening step with no bearing on the migration. |
| Whether authentication should later move from password to Entra identity | human | No — explicitly out of scope here, and a change to how the pipeline authenticates rather than to where the data lives. |
| How P7's Function will be granted access, given that Consumption-plan outbound addresses are not fixed | human / P7 | No — deliberately left to P7, which is the phase that knows its own hosting shape. |

> No question blocks planning. The first materially gates execution and is the
> first task of the plan.

---

## Amendments *(only after approval — never silently edit approved content)*

### A1 — The instance is Neon, not Azure Database for PostgreSQL *(2026-07-29)*

Execution stopped at the cost gate, which is what the gate was for. Measured
against this subscription rather than assumed:

| Item | Rate | Monthly |
|------|------|---------|
| `Standard_B1ms` compute | $0.02730/hr × 730 h | $19.93 |
| Storage, 32 GiB (the floor) | $0.14490/GB/month | $4.64 |
| Backup up to provisioned size | included | $0.00 |
| | | **$24.57 USD/month** |

Region and SKU were fine — `newzealandnorth` serves `Standard_B1ms`, version 16,
32 GiB minimum, exactly the shape the approach described. The problem is the
allowance. This subscription is **Azure for Students**: a one-off $100 credit,
not the Azure free account that the 12-month free B1ms offer attaches to. A
`Compute - Free vCore` meter exists at $0.00, but it is the meter that offer
bills against, not something a subscription elects into. At $24.57/month
against a credit that also funds the VM, the runway is roughly four months,
after which the project stops rather than degrades.

The Alternatives table already recorded the response: *"a free managed Postgres
outside Azure (Neon, Supabase) … remains the fallback if the Azure instance
proves to carry unacceptable cost."* This is that case, and Neon is chosen over
Supabase — it is Postgres and nothing else, where Supabase bundles auth,
storage and a REST API we would not use, and its free projects pause after
about a week of inactivity where Neon scales to zero and wakes in about a
second. The coherence objection recorded against this alternative still stands
and is now simply accepted: the system of record moves outside the subscription
holding the rest of the infrastructure, and gains a second credential domain.

### A2 — Reachability is no longer restricted by IP allow-list *(2026-07-29)*

The approach specified "a public endpoint restricted by an IP allow-list … a
single rule covers the pipeline." Neon's **IP Allow is a Scale-plan feature**,
absent from Free and from Launch; private networking likewise. Supabase gates
its equivalent behind a paid plan too, so this is a consequence of choosing a
free tier rather than of choosing Neon.

Access control therefore degrades from *one permitted IP address* to *whoever
holds the connection string*. **Accepted risk**, mitigated only by: TLS is
mandatory and non-negotiable on Neon (a stronger guarantee than the
`sslmode=require` the Azure design opted into); the password is high-entropy
and supplied by secret (NFR-CC-7); and rotation is the response to any
suspected leak. Recorded rather than solved — the thing that solves it is
paying, which is the decision this amendment exists to avoid.

Sources: [Neon plans](https://neon.com/docs/introduction/plans),
[IP Allow](https://neon.com/docs/introduction/ip-allow).

### A3 — Provisioning is a committed API script, not a Bicep template *(2026-07-29)*

The Must-have "provisioning expressed as infrastructure-as-code alongside the
existing templates, not clicked together in a portal" **stands**, but cannot be
met with Bicep against a non-Azure provider. It is satisfied instead by a
committed, idempotent provisioning script driven by the Neon API, invoked from
`infra-provision.yml` beside the existing Bicep deployments.

Terraform's Neon provider was considered and rejected for this phase: its value
is state-based drift detection, and buying that means introducing a toolchain
the repo does not have plus a remote state backend to provision and secure —
infrastructure work to enable infrastructure work, for one project holding one
database.

### A4 — The pgvector allow-list step does not apply *(2026-07-29)*

The approach devoted a paragraph to `azure.extensions`: pgvector had to be
allow-listed as a server parameter before `CREATE EXTENSION` could succeed, and
this was called out as easy to overlook. That is an Azure Flexible Server
constraint with no Neon equivalent — `CREATE EXTENSION vector` works directly,
so `scout/shared/schema.sql` needs nothing special.

This changes what P6 owes the umbrella PRS. The correction listed as "the PRS
does not mention that pgvector requires an allow-list step" is withdrawn; in
its place, D-CC-8's naming of "Azure DB for PostgreSQL Flexible Server
(Burstable)" is itself now wrong and is what needs amending there.

### A5 — Sizing is replaced by the Neon Free plan's limits *(2026-07-29)*

"Sized to the smallest shape that serves the workload, so that free-tier
eligibility is possible" no longer describes a choice — the Free plan is a
fixed shape: **0.5 GB storage per project, 100 CU-hours per month**, with
compute scaling to zero when idle.

Compute is comfortable: a daily cycle active for ten to fifteen minutes is
roughly 7 CU-hours a month, leaving ample headroom for P7's queries. **Storage
is the new ceiling risk.** 0.5 GB is far tighter than 32 GiB, and `listings`
holds a description per row and grows every day. The spec's own note that the
storage ceiling "is tight against a listings table that grows daily" was
recorded against this alternative and is now live. Measuring the current
database size becomes the first task of the revised phase 2, and headroom must
be re-checked before this is treated as settled.

Consequently the Won't-haves for high availability, geo-redundant backup, read
replicas and private networking are moot rather than chosen — none exist on
this plan.

### A6 — The latency note is strengthened, not merely retained *(2026-07-29)*

The approach recorded that retrieval stops being same-host and starts crossing
a network with TLS, while arguing NFR-CC-2's sub-100 ms budget still holds
because the instance "sits in the same region as the VM". That premise is gone:
Neon is a different cloud in a different region from `newzealandnorth`, and
scale-to-zero means the first query after an idle period pays a cold start of
roughly a second before any work happens.

Neither is expected to break the pipeline — a batch run issues many queries and
only the first pays the wake, and the corpus is small — but the budget is now
being asserted against a materially weaker set of assumptions than when it was
written. Region selection should minimise the distance from the VM, and this
should be measured rather than assumed once the instance exists.

### A7 — The `resources` corpus is empty, which weakens this spec's own reasoning *(2026-07-29)*

Measuring the database for A5's storage question turned up something the spec
had assumed away: **`resources` holds 0 rows and 0 embeddings.** The whole
database is 12 MB, of which `listings` is 3.5 MB across 880 rows; `runs` holds
8 rows spanning 2026-07-22 to 2026-07-29.

Three claims in the approved text are affected:

- The Alternatives table rejected "start fresh on the new instance without
  copying anything" partly because "the corpus was accumulated by weekly
  aggregation runs that cost GitHub API budget and LLM tagging spend to
  produce." **There is no corpus.** The other half of that reasoning — the run
  history is what the dashboard's history page displays — still holds, and is
  reason enough to migrate rather than start fresh.
- The Success Criterion "every resource in the corpus is still retrievable with
  its embedding intact" is satisfiable only vacuously.
- The Must-have "with vector embeddings preserved … verified by comparing row
  counts" likewise. The embedding count check in phase 3 was singled out in the
  plan as the one part of the copy whose failure would be silent; against an
  empty table it compares 0 to 0 and proves nothing. It is kept, because it
  costs nothing and becomes meaningful the moment the corpus fills.

This is recorded, not fixed. It means P6 delivers the *reachability* half of
FR-CC-13 while the resource half stays unanswerable until aggregation actually
populates the corpus — which P7's `/resources <skill>` will need. Human
decision on 2026-07-29 was to continue: an empty table migrates fine, and the
aggregator will write to whichever database is current.
