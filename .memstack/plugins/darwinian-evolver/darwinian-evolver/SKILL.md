---
name: darwinian-evolver
description: Evolve prompts, regex, SQL, or code with an LLM loop.
version: 0.1.0
author: Bihruze (Asahi0x), Hermes Agent, MemStack
license: MIT
compatibility: Python 3.11+, git, uv, macOS or Linux
tools:
  - terminal
metadata:
  tags:
    - evolution
    - optimization
    - prompt-engineering
    - research
---

# Darwinian Evolver

Run Imbue's `darwinian_evolver`, an LLM-driven evolutionary search loop, to
optimize a prompt, regex, SQL query, or small code snippet against a measurable
fitness function.

This plugin is a thin wrapper around the upstream tool. It installs the upstream
repository into a cache directory, helps define a `Problem` made of an organism,
evaluator, and mutator, then runs either the upstream CLI or one of the shipped
driver scripts.

License boundary: the upstream tool is AGPL-3.0. The plugin only invokes it from
user-side scripts or the upstream CLI. Do not import upstream classes into
MemStack core runtime code.

## When To Use

- The user asks to optimize a prompt, evolve a regex, improve a SQL query, or
  search for a better small code artifact.
- There is a starting candidate and a measurable scorer such as exact match,
  regex pass rate, unit tests, runtime metric, or a tightly defined LLM judge.
- The run budget can tolerate tens to hundreds of LLM calls.

Do not use this when the target is differentiable, when only two or three manual
variants are needed, or when the fitness signal is purely subjective.

## Install

Use the terminal tool:

```bash
export DE_CACHE="${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}"
mkdir -p "$DE_CACHE"
cd "$DE_CACHE"
[ -d darwinian_evolver ] || git clone --depth 1 https://github.com/imbue-ai/darwinian_evolver.git
cd darwinian_evolver
uv sync
```

Verify:

```bash
cd "${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}/darwinian_evolver"
uv run darwinian_evolver --help | head -5
```

## OpenRouter Smoke Run

Use the shipped OpenRouter driver when the user has `OPENROUTER_API_KEY` and
wants provider flexibility. It defaults to `https://openrouter.ai/api/v1`; set
`OPENROUTER_BASE_URL` only for an OpenAI-compatible local test endpoint.

```bash
PLUGIN_DIR="$(pwd)/.memstack/plugins/darwinian-evolver"
DE_DIR="${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}/darwinian_evolver"

cd "$DE_DIR" && \
  EVOLVER_MODEL="${EVOLVER_MODEL:-openai/gpt-4o-mini}" \
  uv run --with openai python "$PLUGIN_DIR/darwinian-evolver/scripts/parrot_openrouter.py" \
    --num_iterations 3 \
    --num_parents_per_iteration 2 \
    --mutator_concurrency 2 \
    --evaluator_concurrency 2 \
    --output_dir /tmp/parrot_or
```

For a no-network local evaluation of the full evolution loop, use the fake
OpenAI-compatible monitor:

```bash
DE_DIR="${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}/darwinian_evolver"
PLUGIN_DIR="$(pwd)/.memstack/plugins/darwinian-evolver/darwinian-evolver"

uv run python "$PLUGIN_DIR/scripts/evaluate_local_parrot.py" \
  --de-dir "$DE_DIR" \
  --hermes-skill-dir /Users/tiejunsun/github/hermes-agent/optional-skills/research/darwinian-evolver
```

Expected result: the initial seed scores `0.0`, a mutated prompt reaches `1.0`,
the plugin snapshot reader exits `0`, and the Hermes reference snapshot reader
fails on the same snapshot because the pickled organism class was created under
the driver script's `__main__`.

Inspect a trusted snapshot:

```bash
cd "$DE_DIR" && \
  uv run --with openai python "$PLUGIN_DIR/darwinian-evolver/scripts/show_snapshot.py" \
  /tmp/parrot_or/snapshots/iteration_3.pkl \
  --i-trust-this-file
```

## Custom Problem

Copy `templates/custom_problem_template.py`, then define three things:

1. `Organism`: the artifact being evolved, such as `prompt_template`,
   `regex_pattern`, `sql_query`, or `code_block`.
2. `Evaluator`: returns an `EvaluationResult` with a score in `[0, 1]`,
   trainable failure cases, holdout failure cases, and `is_viable=True` unless
   the organism cannot run at all.
3. `Mutator`: uses failure cases and learning-log entries to produce improved
   organisms. Return an empty list on parse failure.

Run the custom driver from the upstream checkout:

```bash
cd "${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}/darwinian_evolver"
OPENROUTER_API_KEY=... EVOLVER_MODEL=openai/gpt-4o-mini \
  uv run --with openai python /path/to/custom_problem.py \
    --num_iterations 5 \
    --num_parents_per_iteration 2 \
    --output_dir /tmp/my_evolution
```

## Useful Hyperparameters

| flag | default | when to change |
| --- | --- | --- |
| `--num_iterations` | 3 | Increase after the evaluator is trusted. |
| `--num_parents_per_iteration` | 2 | Increase for broader exploration. |
| `--mutator_concurrency` | 2 | Keep low to avoid provider rate limits. |
| `--evaluator_concurrency` | 2 | Match provider and scorer capacity. |
| `--batch_size` | 1 | Raise only when the mutator handles multiple failures. |
| `--verify_mutations` | off | Enable when many mutations are invalid. |

## Pitfalls

- The initial organism must be viable. A zero-score organism is acceptable if it
  can still run and produce failure cases.
- `loop.run()` is a generator. Iterate over it or nothing happens.
- Provider content filters and rate limits should score a candidate as failed,
  not kill the run.
- Snapshot files are pickles. Only unpickle snapshots you created or otherwise
  fully trust.
- The upstream CLI defaults to Anthropic. Use the OpenRouter driver for other
  providers.
- Do not import the AGPL upstream library from MemStack core code.

## Completion Check

```bash
DE_DIR="${DARWINIAN_EVOLVER_CACHE_DIR:-$HOME/.memstack/cache/darwinian-evolver}/darwinian_evolver"
test -f "$DE_DIR/darwinian_evolver/lineage_visualizer.html" && \
cd "$DE_DIR" && uv run darwinian_evolver --help >/dev/null && \
echo "darwinian-evolver: OK"
```
