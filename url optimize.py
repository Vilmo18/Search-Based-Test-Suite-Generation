from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
from pymoo.algorithms.soo.nonconvex.ga import GA, comp_by_cv_and_fitness
from pymoo.algorithms.soo.nonconvex.random_search import RandomSearch
from pymoo.config import Config
from pymoo.operators.selection.rnd import RandomSelection
from pymoo.operators.selection.tournament import TournamentSelection
from pymoo.optimize import minimize

from poly_sbst.sampling.abstract_sampling import AbstractSampling
from tp3.shared import ensure_dir, get_random_seed
from tp3.url import (
    UrlTestSuiteCrossover,
    UrlTestSuiteGenerator,
    UrlTestSuiteMutation,
    UrlTestSuiteProblem,
    make_executor,
)

Config.warnings["not_compiled"] = False


def _pad_history(history: list[float], *, length: int) -> np.ndarray:
    if not history:
        return np.zeros(length, dtype=float)
    if len(history) >= length:
        return np.asarray(history[:length], dtype=float)
    tail = np.full(length - len(history), history[-1], dtype=float)
    return np.concatenate([np.asarray(history, dtype=float), tail])


def _write_suite(path: Path, suite) -> None:
    if suite is None:
        lines: list[str] = []
    else:
        lines = [str(s) for s in suite]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _run_once(*, algo, budget: int, seed: int, verbose: bool):
    random.seed(seed)
    np.random.seed(seed)
    generator = UrlTestSuiteGenerator()
    executor = make_executor()
    problem = UrlTestSuiteProblem(executor)

    res = minimize(
        problem,
        algo(generator),
        termination=("n_eval", budget),
        seed=seed,
        verbose=verbose,
        eliminate_duplicates=False,
        save_history=False,
    )

    return res, problem


def _ga_tournament(pop_size: int):
    def make(generator: UrlTestSuiteGenerator):
        return GA(
            pop_size=pop_size,
            n_offsprings=pop_size,
            sampling=AbstractSampling(generator),
            selection=TournamentSelection(func_comp=comp_by_cv_and_fitness),
            mutation=UrlTestSuiteMutation(generator=generator),
            crossover=UrlTestSuiteCrossover(generator=generator),
            eliminate_duplicates=False,
        )

    return make


def _ga_random(pop_size: int):
    def make(generator: UrlTestSuiteGenerator):
        return GA(
            pop_size=pop_size,
            n_offsprings=pop_size,
            sampling=AbstractSampling(generator),
            selection=RandomSelection(),
            mutation=UrlTestSuiteMutation(generator=generator),
            crossover=UrlTestSuiteCrossover(generator=generator),
            eliminate_duplicates=False,
        )

    return make


def _random_search(points_per_iter: int):
    def make(generator: UrlTestSuiteGenerator):
        return RandomSearch(
            n_points_per_iteration=points_per_iter,
            sampling=AbstractSampling(generator),
        )

    return make


def main() -> int:
    parser = argparse.ArgumentParser(description="TP3 - Optimize test suites for urllib.parse.urlparse")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--budget", type=int, default=5000)
    parser.add_argument("--pop-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0, help="0 => random seed per run")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "urlparse")
    parser.add_argument("--plot", type=Path, default=ROOT / "plots" / "urlparse_convergence.png")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.budget <= 0 or args.runs <= 0:
        raise SystemExit("--budget and --runs must be > 0")

    out_dir = ensure_dir(args.out)

    configs = [
        ("GA+Tournament", _ga_tournament(args.pop_size)),
        ("GA+RandomSel", _ga_random(args.pop_size)),
        ("RandomSearch", _random_search(args.pop_size)),
    ]

    histories: dict[str, list[np.ndarray]] = {name: [] for name, _ in configs}
    best_ratios: dict[str, list[float]] = {name: [] for name, _ in configs}
    run_results: list[dict] = []

    for config_name, algo_factory in configs:
        for run in range(args.runs):
            seed = (args.seed + run) if args.seed else get_random_seed()
            res, problem = _run_once(algo=algo_factory, budget=args.budget, seed=seed, verbose=args.verbose)

            histories[config_name].append(_pad_history(problem.best_history, length=args.budget))
            best_ratios[config_name].append(problem.best.ratio if problem.best is not None else float("-inf"))

            suite_path = out_dir / f"{config_name}_run{run+1}_best_suite.txt"
            _write_suite(suite_path, problem.best_suite)

            best = problem.best
            run_results.append(
                {
                    "config": config_name,
                    "run": run + 1,
                    "seed": seed,
                    "budget": args.budget,
                    "pop_size": args.pop_size,
                    "best_ratio": float(best.ratio) if best is not None else None,
                    "best_lines": int(best.lines) if best is not None else None,
                    "best_tests": int(best.tests) if best is not None else None,
                    "exceptions": int(best.exceptions) if best is not None else None,
                    "exec_time_s": float(best.exec_time_s) if best is not None else None,
                    "suite_file": str(suite_path),
                    "res_F": float(res.F[0]) if hasattr(res, "F") and res.F is not None else None,
                }
            )

            if args.verbose:
                print(f"[{config_name} run {run+1}] best ratio={best_ratios[config_name][-1]:.4f} res.F={res.F}")

    xs = np.arange(1, args.budget + 1, dtype=int)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for config_name, _ in configs:
        data = np.stack(histories[config_name], axis=0)
        mean = data.mean(axis=0)
        std = data.std(axis=0)
        ax.plot(xs, mean, linewidth=2.0, label=f"{config_name} (mean)")
        ax.fill_between(xs, mean - std, mean + std, alpha=0.18)

    ax.set_title(f"Best nl/nt over evaluations (urlparse) — runs={args.runs}, budget={args.budget}")
    ax.set_xlabel("Evaluations")
    ax.set_ylabel("Best ratio nl/nt")
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.35)
    ax.legend(frameon=False)
    fig.tight_layout()
    ensure_dir(args.plot.parent)
    fig.savefig(args.plot, dpi=300)
    plt.close(fig)

    summary = "\n".join(
        f"{name}: best(max)={max(vals):.4f} mean(best)={np.mean(vals):.4f} std(best)={np.std(vals):.4f}"
        for name, vals in best_ratios.items()
    )
    print(summary)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "sut": "urllib.parse.urlparse",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "args": {
                    "runs": args.runs,
                    "budget": args.budget,
                    "pop_size": args.pop_size,
                    "seed": args.seed,
                },
                "by_config": {
                    name: {
                        "best_max": float(max(vals)),
                        "best_mean": float(np.mean(vals)),
                        "best_std": float(np.std(vals)),
                    }
                    for name, vals in best_ratios.items()
                },
                "runs": run_results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote suites under: {out_dir}")
    print(f"Wrote plot: {args.plot}")
    print(f"Wrote summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
