# Mini Project Report: Lakehouse Research Assistant

**Asit Kar** · Post Graduate Program in AI and Machine Learning, weeks 35–36 · Notebook: [`MiniProject_solution.ipynb`](MiniProject_solution.ipynb)

## 1. Domain and corpus
I built a research assistant for **data engineering and lakehouse architecture**. My day job is designing Databricks lakehouse platforms, and design reviews regularly come down to "why does Delta Lake (or Spark, or Photon) do it this way?". The primary sources answer those questions, but nobody has time to reread them. The assistant answers from the papers with page-level citations, goes to the web when the papers are out of date, and produces a structured report.

**Corpus:** 13 peer-reviewed systems papers, 167 pages and about 970k characters. They are MapReduce, GFS, Bigtable, Dremel, RDD/Spark, Spark SQL, Structured Streaming, Deequ, Delta Lake, Lakehouse (CIDR '21), Photon, LHBench and a data-lake survey. All are free PDFs from the authors' or venues' sites, downloaded at run time.

## 2. Architecture decisions
| Decision | Choice | Why |
|---|---|---|
| Chunking | `RecursiveCharacterTextSplitter` 1000/200 → 1,266 chunks, ~197 tokens each | Strategy B (400/80) gave 3,223 chunks of ~72 tokens that often split an argument mid-paragraph, and was slightly worse on paraphrased retrieval (MRR 0.95 vs 1.00) |
| Embeddings | `all-MiniLM-L6-v2` (384-d, normalised, cosine) | Free and fast on a GPU. The median chunk fits its 256-word-piece window |
| Vector store | Chroma, persisted | Embedding runs once (15 s on a T4), and the store is 32 MB for both chunkings |
| Retriever | Similarity, k = 4 | Both retrievers hit the right paper first on 20/20 questions. MMR filled ranks 2–4 with other papers, which dilutes context for single-paper questions |
| LLMs | `qwen2.5:7b` generates, `llama3.1:8b` judges (both via Ollama on a free Colab T4) | Evidence-driven, see below |

**Model choice was the most important decision, and it changed during the project.** The first full run used Llama 3.1 8B for everything. As an agent it never escalated to web search and stated a wrong Apache Iceberg version from memory. It also broke the report JSON on long outputs, and as a judge it gave itself 5/5 almost everywhere. A model-by-prompt comparison (Task 10) showed Qwen 2.5 7B handling all four query types. Llama 3.1 8B was kept as the **judge**, so the generator never grades itself, after a calibration test showed it catches an injected false claim and scores an off-topic answer 1/5 for relevance.

## 3. Prompt engineering findings
On five test questions, judged on accuracy, groundedness and clarity (1–5): **role-based 4.80** > chain-of-thought 4.73 > baseline 4.60. The "principal data architect" persona made answers more precise and more likely to use the papers' own terminology. Groundedness was identical (4.6) because all three prompts share the same context and citation instruction. With five questions and one 8B judge these gaps are small, so this is a preference, not a proof.

**Few-shot made the bigger difference, to format.** Two worked examples raised bullet-point use from 0% to 90% and the "Key points" structure from 0% to 90%, with citations staying at 100%. One lesson: with single-source examples, Llama merged pages into one tag (`Page: 12, 4`) and the citation rate *fell* from 90% to 70%. Adding an example that cites two sources on separate lines fixed it.

## 4. Multi-agent design
A LangGraph `StateGraph` with a **supervisor node** and conditional edges. The order is Research Agent → (Web Search Agent only if `needs_web_search`) → Report Writer → Verifier → END, and every agent returns to the supervisor.
- **Research Agent:** calls `search_documents`, then makes a structured decision: are the passages *about the asked-for system*, do they fully answer the question, and is the web needed. Off-topic passages are dropped before writing.
- **Web Search Agent:** writes a focused query, calls `search_web` (metasearch with a Wikipedia fallback) and summarises only the relevant results.
- **Report Writer:** produces a validated `ResearchReport` (Pydantic). Truncated or invalid JSON is repaired, and citation tags are normalised.
- **Review gate:** `interrupt_before=["report_writer"]` with a `MemorySaver` checkpointer.
  - *yes* resumes the graph.
  - *add more context* writes the text into state and re-enters **as the supervisor**, which re-runs the Research Agent.
  - *change query* restarts on a new thread.
  - The notebook demonstrates an approval cycle, a revision cycle and a query change.
- **Guardrails:** a verifier marks unsupported key findings `[UNVERIFIED]` and lowers confidence. When neither source has relevant evidence, a deterministic fallback returns a report with confidence 0.15 and explicit knowledge gaps.

**What I would change:**
1. Treat reviewer text as retrieval guidance only. In the revision cycle it surfaced as a "finding".
2. Add an ambiguity check before research.
3. Make the web decision partly rule-based (any question about versions, dates or "latest" goes to the web) instead of relying entirely on an 8B model's judgement.

## 5. Evaluation results
**End-to-end (Task 15, 10 questions, full system with the review gate auto-approved):**

| Retrieval hit | Faithfulness | Relevance | Citation accuracy | Latency | Tokens (in / out) | Cost |
|---|---|---|---|---|---|---|
| 10 / 10 | 4.82 / 5 | 5.0 / 5 | 100% (9 reports with citations) | 58 s avg (35–100 s) | 2.7k / 1.3k per query | $0 local; ≈ $0.0012 per query at gpt-4o-mini prices |

- **Best (Q2 GFS chunk size, Q3 RDD lineage):** all evidence came from one paper, and every claim and citation checks out.
- **Worst:**
  - **Q10 (Photon):** one finding came from the paper's general knowledge rather than the retrieved chunks, and was correctly marked `[UNVERIFIED]`.
  - **Q4 (Catalyst):** the longest answer hit the 2,048-token writer cap. JSON repair saved the report but lost the citations, and the report mixed in Structured Streaming's planning stages from a neighbouring chunk.
- Relevance is at the ceiling, so the 8B judge is good at catching fabrications but too lenient to rank close systems.

**Ablation (Task 16, 5 queries):**

| Configuration | Faithfulness | Relevance | Latency | Tokens |
|---|---|---|---|---|
| Baseline RAG (similarity) | 4.68 | 4.4 | 6.4 s | 1.1k |
| RAG + MMR | 4.68 | 4.4 | 6.0 s | 1.1k |
| ReAct agent | 4.84 | 5.0 | 11.5 s | 3.1k |
| Full system | 4.73 | 5.0 | 42.6 s | 3.7k |

All four configurations do well on corpus questions. The query about features added to Delta Lake after 2020 separates them: plain RAG can only paraphrase the 2020 paper (relevance 2), while the agent and the full system search the web (relevance 5). MMR changed nothing on this small corpus. The full system costs about 7× the latency of plain RAG without a higher judge score. What it buys is auditability: a structured, cited, verified report, a human approval step and an honest low-confidence fallback. In practice I would use RAG for quick lookups, ReAct for questions that may need fresh information, and the full pipeline for reports someone will rely on.

## 6. Failure analysis
1. **Ambiguous entity, silently merged.** "How does *the system from Google* handle stragglers?" retrieved Dremel, GFS and MapReduce, and merged them into one confident answer (confidence 0.90). The verifier returned no checks and the pipeline treated that as a pass. *Mitigation:* an ambiguity check that asks a clarifying question, and treating an empty verifier result as "unverified".
2. **Right numbers, wrong benchmark.** Asked for Photon's speed-up on **TPC-DS**, the system reported the paper's **TPC-H** figures (23× maximum, 4× average, 8 nodes) as the answer. The verifier passed them because they *are* in the source. *Mitigation:* tie each data point to its entity or benchmark, and add a verifier check that data points refer to what was asked.
3. **Tool-choice errors in the free-form agent.** Llama 3.1 answered "latest Iceberg release" from memory with a wrong version, and Qwen with prompt v2 skipped the web on the Delta Lake "newer features" question. *Mitigation:* a stronger tool-calling model, a structured escalation decision (as in the graph), and a post-check that forces a web search when an answer states a version or date without a web citation.

Two further problems were caught and fixed during development: citation-tag drift (accuracy 11% → 100% after normalisation) and truncated report JSON (fixed with a larger token budget plus `json_repair`).

## 7. Production considerations
- **Latency:** about 58 s per report on a T4 is too slow for interactive use. Stream the report as it is written, run the verifier asynchronously, use a hosted model or vLLM with batching, and cache answers to repeated questions.
- **Cost:** a local model costs $0 per token but needs a GPU running all the time. At these token volumes a hosted mini model would cost about $1–2 per 1,000 reports, so the trade-off is hosting cost against data control.
- **Data privacy:** this corpus is public. For internal design documents, keep embeddings and the LLM inside the VPC (Ollama or vLLM on private GPUs, or a private endpoint), apply document-level access control at retrieval time, and send **no** internal text to a public web-search API. Web queries should be generated from the question only.
- **Staleness:** papers are static, but product documentation is not. Add incremental ingestion keyed by document hash and `date_ingested`, re-embed on change, version the vector store, and show source dates in reports. The web agent covers recent facts, but needs a reliable search API: free metasearch engines often failed from Colab, so production should use a paid API such as Tavily.
- **Monitoring:**
  - Trace every run (LangSmith or OpenTelemetry).
  - Track tool usage, the web-escalation rate, verifier flag rate, fallback rate, latency and tokens.
  - Run the 20-question evaluation set as a regression test on every prompt or model change.
  - Use a stronger judge, and sample human spot checks.
