"""
run_compliance_evals.py
--------------------------
The pass^k evaluation harness for the REAL production Compliance Agent
(app.agents.compliance.run_compliance_agent - real pgvector retrieval +
real Claude Sonnet reasoning).

WHAT "pass^k" MEANS HERE (and why not "pass@k")
--------------------------------------------------
"pass@k" (common in code-generation evals) asks: across k attempts, did
AT LEAST ONE succeed? That is the wrong question for a compliance/safety
gate - a guest doesn't get to retry until the AI happens to get it right.
"pass^k" asks the stricter, correct question for this use case: across k
INDEPENDENT attempts at the same case, did EVERY SINGLE ONE succeed? A
compliance agent that gets a case right 2 times out of 3 is not reliable
enough to trust in production, even though it would "pass@k" easily.

This matters specifically because Claude Sonnet's reasoning is not
perfectly deterministic between calls - the whole point of running each
case k times is to catch that inconsistency, not just to sample luck.

WHAT COUNTS AS "PASSING" A SINGLE ATTEMPT
--------------------------------------------
An attempt passes if:
  1. The verdict matches the case's `expected_verdict`, AND
  2. For REJECTED cases with a `must_mention` string, that substring
     (case-insensitive) appears in the corrected `guest_message` - proving
     the correction is actually grounded in the real policy fact, not
     just "any rejection would do."

COST WARNING
-------------
This makes REAL calls to Voyage AI (embeddings) and Claude Sonnet
(reasoning) - it is not free, and is not run as part of the normal
`pytest` suite (see tests/test_compliance_agent_real.py for the free,
mocked orchestration tests that DO run in CI). Run this manually, or on
a schedule, not on every commit.

Run with:
    cd backend
    python evals/run_compliance_evals.py --k 3
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from app.agents.compliance import run_compliance_agent
from evals.eval_cases import EVAL_CASES, EvalCase


@dataclass
class CaseResult:
    case: EvalCase
    attempts_passed: int
    k: int
    attempt_details: list[str]

    @property
    def passed_all(self) -> bool:
        return self.attempts_passed == self.k


def _attempt_passes(case: EvalCase, guest_message: str, verdict: str) -> tuple[bool, str]:
    if verdict != case.expected_verdict:
        return (
            False,
            f"verdict={verdict!r}, expected={case.expected_verdict!r}, "
            f"guest_message={guest_message!r}",
        )

    if case.expected_verdict == "REJECTED" and case.must_mention:
        if case.must_mention.lower() not in guest_message.lower():
            return False, f"guest_message did not mention required fact '{case.must_mention}': {guest_message!r}"

    return True, "ok"


def run_case(case: EvalCase, k: int) -> CaseResult:
    attempts_passed = 0
    attempt_details: list[str] = []

    for attempt_number in range(1, k + 1):
        state = {
            "guest_id": f"eval-{case.case_id}",
            "user_message": case.user_message,
            "draft_response": case.draft_response,
        }
        result = run_compliance_agent(state)
        compliance_status = result["compliance_status"]
        verdict = compliance_status["status"].value
        guest_message = compliance_status["guest_message"]

        passed, detail = _attempt_passes(case, guest_message, verdict)
        attempt_details.append(f"attempt {attempt_number}/{k}: {'PASS' if passed else 'FAIL'} ({detail})")
        if passed:
            attempts_passed += 1

    return CaseResult(case=case, attempts_passed=attempts_passed, k=k, attempt_details=attempt_details)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pass^k evals against the real Compliance Agent.")
    parser.add_argument("--k", type=int, default=3, help="Number of independent attempts per case (default: 3).")
    parser.add_argument(
        "--case", type=str, default=None,
        help="Run only the eval case with this case_id, instead of the full suite.",
    )
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent.parent.parent / ".env")

    cases = EVAL_CASES
    if args.case:
        cases = [c for c in EVAL_CASES if c.case_id == args.case]
        if not cases:
            print(f"No eval case found with case_id={args.case!r}")
            return 1

    print(f"Running pass^{args.k} evals against the REAL Compliance Agent ({len(cases)} case(s))...")
    print("(This makes real Voyage AI + Claude Sonnet API calls and will incur real cost.)")
    print()

    results: list[CaseResult] = []
    for case in cases:
        result = run_case(case, args.k)
        results.append(result)
        status = "PASS" if result.passed_all else "FAIL"
        print(f"[{status}] {case.case_id}: {result.attempts_passed}/{result.k} attempts passed")
        if not result.passed_all:
            for detail in result.attempt_details:
                print(f"    {detail}")

    print()
    passed_cases = sum(1 for r in results if r.passed_all)
    total_cases = len(results)
    print(f"pass^{args.k} score: {passed_cases}/{total_cases} cases passed ALL {args.k} attempts")

    return 0 if passed_cases == total_cases else 1


if __name__ == "__main__":
    sys.exit(main())