# Week 1 - LLM Data Pipeline

This folder is pulled in from the team repository
[Automatic28m/Advance-AI-RAG](https://github.com/Automatic28m/Advance-AI-RAG)
with `git subtree`, from my own feature branch `feature-paphawit`.

The team splits the LLM data pipeline into stages, one per member.
**My part is stage 5, Embedding.** Everything else is here because my stage
reads its output, not because I wrote it.

## What is mine

| File | What it does |
|---|---|
| [`Pipeline/embedding.py`](Pipeline/embedding.py) | The stage as a library: providers, batching, retry with backoff, an on-disk cache, and the output checks |
| [`Pipeline/05_embedding.py`](Pipeline/05_embedding.py) | The runner: reads `outputs/metadata_*.json`, writes `outputs/embeddings_*.json`, prints the checks and a nearest-neighbour sample |
| [`Pipeline/.env.example`](Pipeline/.env.example) | Where the API key goes. The real `.env` is ignored and never committed |

## What came from the team

| Stage | File | Author |
|---|---|---|
| 1 Collection | `Pipeline/01_data_collection.ipynb` | Phanlop Boonleua |
| 2 Cleaning | `Pipeline/02_data_cleaning.py`, `cleaning.py` | Pitchakorn Phuadkhunthod |
| 3 Chunking | `Pipeline/03_data_chunking.py`, `chunking.py` | Prapakorn Phithamma |
| 4 Metadata | `Pipeline/04_metadata.py` | Saran Thanyawikai |
| **5 Embedding** | **`Pipeline/05_embedding.py`, `embedding.py`** | **Paphawit Kaewrak (me)** |

Stages 1-4 are input to my stage. I did not modify any of them.

## What the Embedding stage does

Every chunk from stage 4 becomes one vector.

**The text that gets embedded is not the chunk body alone.** A short header
built from the chunk's own `retrieval_metadata` is prepended first:

```
Senior Frontend Software Engineer, Home Experience
Reddit | USA

Reddit is a community of communities. It's built on shared interests...
```

Without it, a chunk cut from the middle of a posting is a paragraph of
requirements naming neither the job nor the company, and a query like
"frontend role at Reddit" cannot reach it. The body itself is passed through
untouched, since stage 2 already cleaned and normalized it.

**Every vector keeps its provenance.** Each output record carries `chunk_id`,
`id`, `source`, `source_file`, `chunk_index` and `chunk_count`, plus the whole
`retrieval_metadata` block for filtering later. `id` on its own is not a key:
Jobicy numbers its postings and AIDevBoard uses UUIDs, so the two id spaces can
collide. `(source, id)` is the real pair, and `chunk_id` is that pair plus the
chunk index.

**Two providers behind one interface**, `gemini-embedding-001` by default and
OpenAI `text-embedding-3-*` with `--provider openai`. Both go over `urllib`, so
this stage adds nothing to `requirements.txt`. The output width is a parameter
and defaults to 1536, which is the width the Vector Store stage indexes on - a
mismatch there is a failed upsert, not a quality problem.

**Rate limits are handled by pacing rather than by retrying.** A free-tier key
is metered at 30k tokens per minute, and a 100-chunk batch of this corpus is
about 45k tokens, so the first full run was refused outright. Batches are now
capped on estimated tokens as well as on count, and requests wait for room in a
rolling minute. Exponential backoff is still there for the transient failures.

**Re-runs cost almost nothing.** Every vector is cached on disk under a key
covering the exact text, provider, model and dimension, so a second run sends
only what actually changed.

## Running it

The metadata stage's output is not committed, so run stage 4 first:

```
pip install -r requirements.txt
python Pipeline/04_metadata.py
python Pipeline/05_embedding.py
```

Put the API key in `Pipeline/.env` (copy `Pipeline/.env.example`). It is read
through `os.environ` only, never hardcoded, and never printed or written to the
output.

Useful flags:

```
python Pipeline/05_embedding.py --limit 20                  a cheap trial run
python Pipeline/05_embedding.py --provider openai           the other provider
python Pipeline/05_embedding.py --dimension 768             a narrower index
python Pipeline/05_embedding.py --tokens-per-minute 0       no pacing, paid key
```

## Result on the current corpus

518 chunks from 180 job postings across 4 files:

```
checks passed: 518 vectors over 4 files, each 1536 wide
               carrying its id + source + chunk_index
```

The checks refuse a run where a vector lost its id or its source, came back the
wrong width, or where the vectors do not cover exactly the chunks that came in,
so no chunk can be silently dropped or embedded twice.

The vectors were also checked for meaning, not only for shape. Nearest
neighbours of one Anthropic reinforcement-learning posting:

```
0.954  the same posting, chunk 1
0.939  the same posting, chunk 2
0.904  Staff Software Engineer, Code RL - Anthropic
0.888  Research Lead, Training Insights - Anthropic
0.883  Staff Software Engineer, Environments Infrastructure - Anthropic
```

Other chunks of the same posting rank highest, then related roles at the same
company, which is what a working embedding should do.
