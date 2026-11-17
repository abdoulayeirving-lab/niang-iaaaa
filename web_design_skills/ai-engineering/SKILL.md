---
name: ai-engineering
description: Design and evaluate applications using LLMs, local models, tool calling, RAG, embeddings, vector retrieval, or multi-agent orchestration. Use when software features depend on AI behavior or model integration.
---

# AI engineering

## Identity and objective
Build AI features with explicit data boundaries, measurable behavior, and
predictable failure handling.

## When to use / when not to use
Use for model calls, RAG, tool calling, evaluation, or agent workflows. Do not
send private data to a provider, use paid APIs, or install a model/service
without explicit approval.

## Method
1. Define the user outcome and a non-AI baseline.
2. Classify data, provider, retention, cost, latency, and network requirements.
3. Design a minimal prompt/tool contract and validate all model outputs.
4. For RAG, define source provenance, chunking, permissions, freshness, and
   retrieval evaluation.
5. Add timeouts, rate/cost bounds, cancellation, and explicit unavailable
   states.
6. Evaluate with a representative, privacy-safe dataset and record limitations.

## Architecture and practices
- Treat model output and retrieved documents as untrusted input.
- Enforce tool permissions in host code, not in prompt text.
- Apply access control before retrieval and avoid cross-user data leakage.
- Do not allow arbitrary tool, shell, or filesystem execution.
- Keep secrets outside prompts, logs, embeddings, and client bundles.
- Provide deterministic fallbacks only when they are truthful and clearly
  labelled.

## Tools and technologies
Prefer local, already-installed models when required. Consult the selected
provider's official API documentation and
[Ollama documentation](https://docs.ollama.com/) for local runtime behavior.
Do not assume model capabilities from a model name alone; test tool calling.

## Execution instructions
Use mocks for unit tests. Run local or provider-backed demonstrations only
when configured and authorized. Never use a paid endpoint or transmit workspace
contents externally without explicit user approval.

## Quality example
An agent proposal is schema-validated, each requested action is checked by a
host allowlist, and a provider outage is surfaced as an error rather than
returning fabricated content.

## Common errors
- Treating prompt instructions as a security boundary.
- Trusting model JSON without schema and semantic validation.
- Claiming RAG answers are grounded without source evidence.
- Ignoring token, latency, privacy, and cost limits.

## Validation criteria
Measure task success, invalid-output handling, retrieval relevance, tool
denials, latency, cancellation, and data leakage risk. Separate mock results
from real-model results.

## Final checklist
- [ ] Data/provider/cost boundary is approved
- [ ] Model output and tool input are validated
- [ ] Host enforces permissions independently of prompts
- [ ] Failure, timeout, cancellation, and unavailable states are tested
- [ ] Model-backed claims are supported by an actual authorized run

## References
- [Ollama documentation](https://docs.ollama.com/)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
