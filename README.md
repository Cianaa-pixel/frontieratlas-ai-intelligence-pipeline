# FrontierAtlas AI Intelligence Pipeline

Production-oriented AI intelligence ingestion pipeline for collecting,
normalizing, enriching, and resolving AI ecosystem data.

## Pipeline

Sources
  ↓
Async Crawlers
  ↓
Raw Data Validation
  ↓
Date Normalization
  ↓
LLM Extraction
  ↓
Entity Resolution
  ↓
Enrichment
  ↓
CSV / Google Sheets
  ↓
Analytics / Intelligence Graph

## Current Output

### Research Papers
- 1,000 research papers collected from arXiv
- GitHub repository enrichment
- Current GitHub star counts
- ISO-8601 publication timestamps
- Source URLs retained for traceability

Current enrichment:
- 1,000 papers
- 46 GitHub repositories detected
- 30 repositories with non-zero GitHub star counts

## Architecture

### Crawling

Python asyncio + aiohttp is used for concurrent network operations.

Concurrency is controlled using asyncio semaphores to prevent
uncontrolled request bursts.

### Reliability

The pipeline is designed around:

- asynchronous requests
- bounded concurrency
- retry handling
- exponential backoff
- jitter
- request timeouts
- source-level error isolation
- checkpointable outputs

### LLM Extraction

The extraction layer is designed as a provider fallback chain:

1. Gemini Flash
2. Groq Llama
3. DeepSeek

LLM output is validated against Pydantic schemas before persistence.

LLMs are used for extraction and normalization only.
Source URLs remain the authoritative origin of every record.

### 413 Handling

Large documents are cleaned and divided into semantic chunks before
LLM processing.

Priority is given to:

1. title
2. metadata
3. headings
4. main content
5. relevant surrounding context

Payload size is bounded before provider submission.

### 429 Handling

Rate limits are handled with exponential backoff and jitter.

Requests are retried only for retryable failures, with bounded
maximum attempts.

### Entity Resolution

Raw organization/product names are normalized before matching.

Examples:

OpenAI
Open AI
OpenAI, Inc.

are normalized toward the same canonical entity.

RapidFuzz is used for similarity matching against the canonical seed
entity list.

### Freshness

News and job records contain normalized publication timestamps.

Records are filtered against the ingestion timestamp so that only
records published within the required 24-hour window are accepted.

### Traceability

Every record retains its original source URL.

No unsupported fields are generated from assumptions.

## Scale Strategy

The crawler is horizontally scalable.

For 500,000+ records:

- partition URLs into batches
- distribute batches across workers
- use bounded async concurrency per worker
- checkpoint completed URLs
- persist raw and normalized records independently
- retry failed partitions
- use centralized deduplication

The application code remains unchanged while worker capacity is
increased.

## Storage

CSV is used for the demonstration output.

A production deployment can use:

- PostgreSQL for canonical entities and structured records
- Redis for queues, rate limiting, and distributed locks
- object storage for raw HTML
- PostgreSQL pgvector or a dedicated vector database for embeddings
- Neo4j or another graph database for startup/product/research
  relationships

## Reproducibility

```bash
python -m venv .venv
pip install -r requirements.txt