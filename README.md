# AKPsi Connections

A chapter-internal recruiting tool for **Alpha Kappa Psi at Columbia**. It turns the
chapter's existing alumni database and big/little Linktrees into a queryable knowledge
graph, so an underclassman prepping for a coffee chat can type **"Evercore"** and instantly see:

- which **alumni currently work there**,
- which **current brothers have a warm path** to them through their lineage
  (big → big's big → …), and
- **request an intro** that routes *through the alum first*, rather than through a
  self-claimed connection.

The value is fast, ranked answers to *"who can get me into this firm,"* not eye candy —
so it prioritizes a clean searchable directory and the chapter's real family-tree over the
generic force-directed graph that similar projects default to.

## How it works

**Postgres is the system of record** (alumni, firms, groups, intro requests, claim tokens).
**Neo4j is a derived projection** used only for the multi-hop traversal through the
big/little chain — it's rebuilt from Postgres, never edited directly.

```
xlsx ──extract──> canonicalize ──load──> Postgres ──sync──> Neo4j
                       │                    │                 │
                  review CLI           FastAPI API      multi-hop lineage
                   (human)                  │            traversal
                                       Next.js (Vercel)
                                            ▲
                          ┌─────────────────┴─────────────────┐
                          │   Claude agents (Claude Agent SDK)  │
                          │   enrichment · search · intro draft │
                          └─────────────────────────────────────┘
```

A **magic-link claim flow** puts alumni in control of their own profile and contact
preferences: an alum follows a one-time link, verifies, and owns what's shown and how
intros reach them.

## AI agents

Agents are the engine that keeps the graph fresh and turns it into ranked answers. They're
built on the **[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk)** with the
**Claude API** (Opus / Sonnet), and reach the data exclusively through **tool use** —
specifically **MCP servers** that expose Postgres (SQL) and Neo4j (Cypher) as tools, plus a
web-search tool for the enrichment agent. Every agent writes back through the same
human-in-the-loop review surfaces the rest of the system already uses (confidence levels,
`source` tags, the review CLI), so nothing an agent proposes goes live unverified.

| Agent | Where it plugs in | Tools (via MCP / tool use) | Output |
|-------|-------------------|----------------------------|--------|
| **Enrichment agent** | `alumni_pipeline/research.py` (today a hand-curated dict — the agent automates exactly this) | web search + Postgres MCP | proposes `worked_at` rows with `source='research'` + `confidence`, queued for review |
| **Search / "who-can-get-me-in" agent** | behind the FastAPI search endpoint | Postgres MCP (firm/alumni lookup) + Neo4j MCP (lineage traversal) | interprets free-text ("Evercore", "growth equity in SF"), returns **ranked warm paths** with reasoning |
| **Intro-draft agent** | the intro-request flow | Postgres MCP (requester, target alum, lineage path) | drafts the personalized intro message that **routes through the alum first** |

The recurring pattern is **Claude Agent SDK + tool use + MCP over the Postgres/Neo4j system
of record** — agents never get their own database, they operate on the canonical one through
typed tools and leave an audit trail.

## Status

This is being built toward the vision above. Where things stand:

| Step | What | Status |
|------|------|--------|
| 1 | **Alumni → Postgres.** Parse the Alumni Master Key, canonicalize messy firm strings, load `persons / firms / groups / worked_at`. `research.py` seeds the (hand-curated) enrichment that the **enrichment agent** will automate. | ✅ **Done** (agent: planned) |
| 2 | **Big/little → `relationships`.** Parse the Lin Trees Linktrees, resolve names to people (fuzzy-match + review), populate the lineage edges. | 🔜 Planned |
| 3 | **Neo4j projection.** `sync_to_neo4j.py` — full rebuild (truncate + batched MERGE) from Postgres. | 🔜 Planned |
| 4 | **FastAPI API + magic-link claim flow.** Search, ranked "who-can-get-me-in" paths (**search agent**), intro requests (**intro-draft agent**), `claim_tokens`. | 🔜 Planned |
| 5 | **Next.js frontend on Vercel.** Searchable directory + family-tree view. | 🔜 Planned |

## Run it (local)

Local dev mirrors the Railway services via docker-compose.

```bash
cp .env.example .env
docker compose up -d                  # Postgres + Neo4j (schema auto-loads)
pip install -r requirements.txt

python -m alumni_pipeline.load        # extract → canonicalize → load Postgres
python -m alumni_pipeline.review_cli  # (optional) resolve ambiguous firm matches
```

`load` is an idempotent full rebuild — safe to run repeatedly.

> **Note:** Postgres is mapped to host port **5433** (not 5432) to avoid clashing with a
> native Postgres install. Connection strings use `127.0.0.1`, not `localhost`, to dodge
> IPv6 surprises. See `docker-compose.yml`.

## How firm canonicalization works

Each `POST GRAD` cell is parsed (`firmparse.py`) into employment stints, splitting:

| raw | becomes |
|-----|---------|
| `Carlyle (Prev. GS)` | current **Carlyle** + prior **Goldman Sachs** |
| `TPG (Prev. KKR & GS)` | current **TPG** + prior **KKR** + prior **Goldman Sachs** |
| `Litmus (YC 26)` | current **Y Combinator**, group **Litmus** |
| `Bank of America - ECM` | current **Bank of America**, group **ECM** |
| `Wharton (Prev. Amazon)` | current **Wharton** (school) + prior **Amazon** |

Each firm token then resolves to a canonical firm (`canonicalize.py`):

1. **Curated seed** (`aliases.py`) — abbreviations & synonyms fuzzy matching can't get
   (`GS`→Goldman Sachs, `AWS`→Amazon/AWS, `Facebook`→Meta). Deliberate non-merges too
   (`Citi` ≠ `Citadel`, `Bain & Company` ≠ `Bain Capital`).
2. **Persisted review decisions** (`data/firm_review.json`).
3. **Exact** normalized match.
4. **Fuzzy** (`rapidfuzz.token_sort_ratio`): ≥92 auto-merge, 80–92 → review queue, else new.

Every raw→canonical decision is recorded in the `firm_aliases` table for audit.

## Deployment (Railway + Vercel)

Code is 12-factor: it reads `DATABASE_URL`, `NEO4J_URI/USER/PASSWORD`, and `ANTHROPIC_API_KEY`
from the environment. Locally those come from `docker-compose.yml` / `.env`; on Railway the
data ones are injected by the managed **Postgres** and **Neo4j AuraDB** plugins. The Next.js
frontend deploys to **Vercel**. Nothing is host-specific.

**Tech stack:** FastAPI · Postgres (system of record) · Neo4j AuraDB (graph projection) ·
**Claude API + Claude Agent SDK** (agents) · **MCP** (Postgres/Neo4j exposed as agent tools) ·
Next.js on Vercel · Railway.

## Schema

`db/schema.sql` is the source of truth:

- **`firms`** — canonical organizations; `org_type` (company/school/government/…) so
  schools and startups in the POST GRAD column aren't mislabeled.
- **`groups`** — divisions within a firm (IBD, ECM, a YC startup, …).
- **`persons`** — alumni and current brothers; `is_alumnus = FALSE` for lin-tree-only
  undergrads (Step 2).
- **`worked_at`** — employment/education history; `seq 0` = current, `1..` = prior.
- **`relationships`** — big/little lineage edges (Step 2).
- **`firm_aliases`** — audit trail of every raw → canonical firm decision.

`intro_requests` and `claim_tokens` land with Step 4.
