from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from poly_sbst.common.abstract_executor import AbstractExecutor
from poly_sbst.common.abstract_grammar import AbstractGrammar
from poly_sbst.generators.abstract_generator import AbstractGenerator
from poly_sbst.mutation.abstract_mutation import AbstractMutation
from poly_sbst.crossover.abstract_crossover import AbstractCrossover
from poly_sbst.problems.abstract_problem import AbstractProblem


def _coerce_suite(x) -> np.ndarray:
    if x is None:
        return np.array([], dtype=object)
    if isinstance(x, np.ndarray):
        return x.astype(object, copy=False)
    return np.array(list(x), dtype=object)


def _stable_unique(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def get_random_seed() -> int:
    t = int(time.time() * 1000)
    return (
        ((t & 0xFF000000) >> 24)
        + ((t & 0x00FF0000) >> 8)
        + ((t & 0x0000FF00) << 8)
        + ((t & 0x000000FF) << 24)
    )


@dataclass(frozen=True)
class SuiteEval:
    ratio: float
    lines: int
    tests: int
    exceptions: int
    exec_time_s: float


class GrammarSuiteGenerator(AbstractGenerator):
    def __init__(
        self,
        *,
        name: str,
        grammar: dict[str, list[str]],
        seeds: Sequence[str],
        min_suite_len: int,
        max_suite_len: int,
        suite_length_exponent: float = 6.0,
        max_input_len: int,
        max_nonterminals: int,
        post_process: Callable[[str], str] | None = None,
        p_seed: float = 0.20,
    ) -> None:
        super().__init__()
        self._name = name
        self.grammar = AbstractGrammar(grammar)
        self.seeds = list(seeds)
        self.min_length = int(min_suite_len)
        self.max_length = int(max_suite_len)
        self.suite_length_exponent = float(suite_length_exponent)
        self.max_input_len = int(max_input_len)
        self.max_nonterminals = int(max_nonterminals)
        self.post_process = post_process
        self.p_seed = float(p_seed)

    def cmp_func(self, x: np.ndarray, y: np.ndarray) -> float:
        sx = set(_coerce_suite(x))
        sy = set(_coerce_suite(y))
        if not sx and not sy:
            return 1.0
        denom = len(sx | sy) or 1
        return len(sx & sy) / denom

    def _generate_one(self) -> str:
        if self.seeds and random.random() < self.p_seed:
            s = random.choice(self.seeds)
        else:
            for _ in range(25):
                s = self.grammar.generate_input(max_nonterminals=self.max_nonterminals)
                if len(s) <= self.max_input_len:
                    break
            s = s[: self.max_input_len]
        if self.post_process is not None:
            s = self.post_process(s)
        return s

    def generate_random_test(self) -> np.ndarray:
        span = max(0, self.max_length - self.min_length)
        if span == 0:
            n = self.min_length
        else:
            exp = max(1.0, self.suite_length_exponent)
            frac = random.random() ** exp
            n = self.min_length + min(int(frac * (span + 1)), span)
        suite = _stable_unique([self._generate_one() for _ in range(n)])
        while len(suite) < self.min_length:
            suite.append(self._generate_one())
        if len(suite) > self.max_length:
            suite = suite[: self.max_length]
        return np.array(suite, dtype=object)


class RatioCoverageProblem(AbstractProblem):
    def __init__(self, executor: AbstractExecutor, *, name: str):
        super().__init__(executor, n_var=1, n_obj=1, n_ieq_constr=0, xl=None, xu=None)
        self._name = name
        self.best: SuiteEval | None = None
        self.best_suite: np.ndarray | None = None
        self.best_coverage: set[int] | None = None
        self.best_history: list[float] = []

    def _evaluate(self, x, out, *args, **kwargs):
        suite = _coerce_suite(x[0])

        self.executor._full_coverage = []
        self.executor._coverage = set()
        self.executor._previous_line = 0
        self.executor._trace_pairs = set()

        exceptions_total = 0
        exec_time_total = 0.0
        for test in suite:
            exceptions, exec_time, _ = self.executor._execute_input(str(test))
            exceptions_total += int(exceptions)
            exec_time_total += float(exec_time)

        coverage = self.executor._coverage
        nl = int(len(coverage))
        nt = int(len(suite))
        ratio = float(nl / nt) if nt > 0 else 0.0

        current = SuiteEval(
            ratio=ratio,
            lines=nl,
            tests=nt,
            exceptions=exceptions_total,
            exec_time_s=exec_time_total,
        )

        if self.best is None:
            improved = True
        else:
            improved = (
                (current.ratio > self.best.ratio + 1e-12)
                or (
                    abs(current.ratio - self.best.ratio) <= 1e-12
                    and (current.lines, -current.tests) > (self.best.lines, -self.best.tests)
                )
            )

        if improved:
            self.best = current
            self.best_suite = suite.copy()
            self.best_coverage = set(coverage)

        self.best_history.append(self.best.ratio if self.best is not None else ratio)

        self.execution_data[self.n_evals] = {
            "ratio": ratio,
            "lines": nl,
            "tests": nt,
            "exceptions": exceptions_total,
            "exec_time_s": exec_time_total,
        }
        self.n_evals += 1

        out["F"] = -ratio


class SuiteMutation(AbstractMutation):
    def __init__(
        self,
        *,
        generator: GrammarSuiteGenerator,
        string_mutators: Sequence[Callable[[str], str]],
        mut_rate: float = 0.50,
    ):
        super().__init__(mut_rate=mut_rate, generator=generator)
        self._string_mutators = list(string_mutators)

    def _do_mutation(self, x) -> np.ndarray:
        suite = _coerce_suite(x)

        operations = [
            self._delete_test,
            self._insert_test,
            self._replace_test,
            self._mutate_string,
            self._shuffle_suite,
            self._dedup_suite,
        ]
        weights = [0.18, 0.14, 0.22, 0.34, 0.06, 0.06]
        op = random.choices(operations, weights=weights, k=1)[0]
        suite = op(suite)

        suite = np.array(_stable_unique([str(s) for s in suite]), dtype=object)
        while len(suite) < self.generator.min_length:
            suite = np.append(suite, self.generator._generate_one())
        if len(suite) > self.generator.max_length:
            suite = suite[: self.generator.max_length]
        return suite

    def _delete_test(self, suite: np.ndarray) -> np.ndarray:
        if len(suite) <= self.generator.min_length:
            return suite
        idx = random.randrange(len(suite))
        return np.delete(suite, idx)

    def _insert_test(self, suite: np.ndarray) -> np.ndarray:
        if len(suite) >= self.generator.max_length:
            return suite
        new_test = self.generator._generate_one()
        idx = random.randrange(len(suite) + 1)
        return np.insert(suite, idx, new_test)

    def _replace_test(self, suite: np.ndarray) -> np.ndarray:
        if len(suite) == 0:
            return np.array([self.generator._generate_one()], dtype=object)
        idx = random.randrange(len(suite))
        suite = suite.copy()
        suite[idx] = self.generator._generate_one()
        return suite

    def _mutate_string(self, suite: np.ndarray) -> np.ndarray:
        if len(suite) == 0:
            return np.array([self.generator._generate_one()], dtype=object)
        idx = random.randrange(len(suite))
        mut = random.choice(self._string_mutators) if self._string_mutators else (lambda s: s)
        s = str(suite[idx])
        suite = suite.copy()
        suite[idx] = mut(s)[: self.generator.max_input_len]
        return suite

    def _shuffle_suite(self, suite: np.ndarray) -> np.ndarray:
        if len(suite) <= 1:
            return suite
        suite = suite.copy()
        np.random.shuffle(suite)
        return suite

    def _dedup_suite(self, suite: np.ndarray) -> np.ndarray:
        return np.array(_stable_unique([str(s) for s in suite]), dtype=object)


class OnePointSuiteCrossover(AbstractCrossover):
    def __init__(self, *, generator: GrammarSuiteGenerator, cross_rate: float = 0.90):
        super().__init__(cross_rate=cross_rate)
        self.generator = generator

    def _do_crossover(self, problem, a, b) -> tuple:
        a_suite = _coerce_suite(a)
        b_suite = _coerce_suite(b)

        cut_a = random.randrange(len(a_suite) + 1) if len(a_suite) else 0
        cut_b = random.randrange(len(b_suite) + 1) if len(b_suite) else 0

        off1 = np.concatenate([a_suite[:cut_a], b_suite[cut_b:]]) if len(b_suite) else a_suite.copy()
        off2 = np.concatenate([b_suite[:cut_b], a_suite[cut_a:]]) if len(a_suite) else b_suite.copy()

        off1 = np.array(_stable_unique([str(s) for s in off1]), dtype=object)
        off2 = np.array(_stable_unique([str(s) for s in off2]), dtype=object)

        off1 = self._repair(off1)
        off2 = self._repair(off2)
        return off1, off2

    def _repair(self, suite: np.ndarray) -> np.ndarray:
        suite = _coerce_suite(suite)
        while len(suite) < self.generator.min_length:
            suite = np.append(suite, self.generator._generate_one())
        if len(suite) > self.generator.max_length:
            suite = suite[: self.generator.max_length]
        return suite


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
