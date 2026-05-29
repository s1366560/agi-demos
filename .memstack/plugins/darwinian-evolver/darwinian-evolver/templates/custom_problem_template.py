"""Template for a custom darwinian_evolver problem.

Copy this file, fill in the organism, evaluator, mutator, and initial artifact,
then run it from an upstream darwinian_evolver checkout.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from darwinian_evolver.cli_common import (
    build_hyperparameter_config_from_args,
    parse_learning_log_view_type,
    register_hyperparameter_args,
)
from darwinian_evolver.evolve_problem_loop import EvolveProblemLoop
from darwinian_evolver.problem import (
    EvaluationFailureCase,
    EvaluationResult,
    Evaluator,
    Mutator,
    Organism,
    Problem,
)
from openai import OpenAI

if TYPE_CHECKING:
    from darwinian_evolver.learning_log import LearningLogEntry

DEFAULT_MODEL = os.environ.get("EVOLVER_MODEL", "openai/gpt-4o-mini")
DEFAULT_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_LLM_RETRIES = int(os.environ.get("EVOLVER_LLM_RETRIES", "3"))


def _client() -> OpenAI:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    return OpenAI(api_key=key, base_url=DEFAULT_BASE_URL)


def _prompt_llm(prompt: str, max_tokens: int = 1024) -> str:
    attempts = max(1, DEFAULT_LLM_RETRIES)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = _client().chat.completions.create(
                model=DEFAULT_MODEL,
                max_tokens=max_tokens,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.25 * attempt)

    assert last_error is not None
    return f"<LLM_ERROR: {type(last_error).__name__}: {last_error}>"


class MyOrganism(Organism):
    artifact: str

    def run(self, *inputs: object) -> str:
        raise NotImplementedError


class MyFailureCase(EvaluationFailureCase):
    input: str
    expected: str
    actual: str


class MyEvaluator(Evaluator[MyOrganism, EvaluationResult, MyFailureCase]):
    trainable: ClassVar[list[tuple[str, str]]] = []
    holdout: ClassVar[list[tuple[str, str]]] = []

    def evaluate(self, organism: MyOrganism) -> EvaluationResult:
        trainable_failures: list[MyFailureCase] = []
        holdout_failures: list[MyFailureCase] = []
        for index, (input_value, expected) in enumerate(self.trainable):
            actual = organism.run(input_value)
            if actual != expected:
                trainable_failures.append(
                    MyFailureCase(
                        input=input_value,
                        expected=expected,
                        actual=actual,
                        data_point_id=f"trainable_{index}",
                    )
                )
        for index, (input_value, expected) in enumerate(self.holdout):
            actual = organism.run(input_value)
            if actual != expected:
                holdout_failures.append(
                    MyFailureCase(
                        input=input_value,
                        expected=expected,
                        actual=actual,
                        data_point_id=f"holdout_{index}",
                    )
                )
        total = len(self.trainable) + len(self.holdout)
        passed = total - len(trainable_failures) - len(holdout_failures)
        return EvaluationResult(
            score=passed / total if total else 0.0,
            trainable_failure_cases=trainable_failures,
            holdout_failure_cases=holdout_failures,
            is_viable=True,
        )


class MyMutator(Mutator[MyOrganism, MyFailureCase]):
    prompt = """
The current artifact is:
```
{artifact}
```

On this input:
```
{input}
```
it produced:
```
{actual}
```
but we wanted:
```
{expected}
```

Diagnose what went wrong, then propose an improved artifact. Put the new
version in the last triple-backtick block of your response.
""".strip()

    def mutate(
        self,
        organism: MyOrganism,
        failure_cases: list[MyFailureCase],
        learning_log_entries: list[LearningLogEntry],
    ) -> list[MyOrganism]:
        if not failure_cases:
            return []
        failure = failure_cases[0]
        response = _prompt_llm(
            self.prompt.format(
                artifact=organism.artifact,
                input=failure.input,
                actual=failure.actual,
                expected=failure.expected,
                learning_log_entries=learning_log_entries,
            )
        )
        artifact = _extract_artifact(response)
        if not artifact:
            return []
        return [MyOrganism(artifact=artifact)]


def make_problem() -> Problem:
    initial = MyOrganism(artifact="TODO: starting artifact here")
    return Problem[MyOrganism, EvaluationResult, MyFailureCase](
        evaluator=MyEvaluator(),
        mutators=[MyMutator()],
        initial_organism=initial,
    )


def _extract_artifact(response: str) -> str | None:
    fenced_blocks = re.findall(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)```", response, re.DOTALL)
    candidates = [block.strip() for block in fenced_blocks]
    if not candidates:
        tag_match = re.search(
            r"<artifact>\s*(.*?)\s*</artifact>",
            response,
            re.DOTALL | re.IGNORECASE,
        )
        if tag_match:
            candidates.append(tag_match.group(1).strip())
    return candidates[-1] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser()
    register_hyperparameter_args(parser.add_argument_group("hyperparameters"))
    parser.add_argument("--num_iterations", type=int, default=3)
    parser.add_argument("--mutator_concurrency", type=int, default=2)
    parser.add_argument("--evaluator_concurrency", type=int, default=2)
    parser.add_argument("--output_dir", type=str, required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshots").mkdir(exist_ok=True)

    hyperparameters = build_hyperparameter_config_from_args(args)
    loop = EvolveProblemLoop(
        problem=make_problem(),
        learning_log_view_type=parse_learning_log_view_type(hyperparameters.learning_log_view_type),
        num_parents_per_iteration=hyperparameters.num_parents_per_iteration,
        mutator_concurrency=args.mutator_concurrency,
        evaluator_concurrency=args.evaluator_concurrency,
        fixed_midpoint_score=hyperparameters.fixed_midpoint_score,
        midpoint_score_percentile=hyperparameters.midpoint_score_percentile,
        sharpness=hyperparameters.sharpness,
        novelty_weight=hyperparameters.novelty_weight,
        batch_size=hyperparameters.batch_size,
        should_verify_mutations=hyperparameters.verify_mutations,
    )

    print("Evaluating initial organism...")
    for snapshot in loop.run(num_iterations=args.num_iterations):
        (output_dir / "snapshots" / f"iteration_{snapshot.iteration}.pkl").write_bytes(
            snapshot.snapshot
        )
        _, best_eval = snapshot.best_organism_result
        print(
            f"iter={snapshot.iteration} pop={snapshot.population_size} "
            f"best_score={best_eval.score:.3f}"
        )

    print(f"\nDone. Results in: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
