# Benchmarks

> Admin access required

## What Are Benchmarks?

Benchmarks let you compare different AI models against the same document. Run the same review with Sonnet 4, Haiku, or any Bedrock model and compare quality scores, finding counts, token usage, and cost side by side.

## Creating a Benchmark

1. Go to the **Benchmarks** page (admin-only nav link)
2. Click **+ New Benchmark**
3. Select a completed project as the source document
4. Choose which agent type to benchmark (e.g., architecture, security)
5. Add two or more configurations, each with:
   - **Label** — human-readable name (e.g., "Sonnet 4")
   - **Model ID** — Bedrock model identifier (e.g., `us.anthropic.claude-sonnet-4-20250514-v1:0`)
   - **Depth** — quick, standard, or thorough
6. Click **Create Benchmark**

## Running a Benchmark

Click **Run Benchmark** on the detail page. The system:

1. Loads the document from the source project
2. Invokes the review agent once per configuration using the specified model
3. Runs the quality judge on each set of findings
4. Stores results with quality scores and token metrics

Execution is parallel — all configurations run simultaneously. Typical runtime is 1–3 minutes depending on document size and model speed. The page auto-refreshes while running.

## Reading Results

Each configuration shows:

- **Quality Score** — overall score with completeness/specificity/actionability breakdown
- **Finding Count** — total findings broken down by severity
- **Token Usage** — input, output, and total tokens consumed
- **Duration** — total execution time and model latency
- **Estimated Cost** — approximate cost based on token usage (when available)

## Cost Awareness

Benchmarks invoke models multiple times in parallel. A benchmark with 3 configurations against a large document at thorough depth could consume significant tokens. Monitor the metrics to understand the cost/quality tradeoff.
