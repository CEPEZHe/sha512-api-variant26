"""Find a shrunk, multi-operation counterexample for an injected API bug."""

from hypothesis import HealthCheck, settings
from hypothesis.stateful import run_state_machine_as_test

from tests.test_mbt import BaseMachine


class MutationMachine(BaseMachine):
    """Run the same independent model against an intentionally broken API."""

    backend = "sqlite"
    mutation = True


def main():
    """Print the Hypothesis counterexample and fail if no bug is found."""
    config = settings(
        max_examples=150,
        stateful_step_count=30,
        deadline=None,
        derandomize=True,
        suppress_health_check=[HealthCheck.too_slow],
    )
    try:
        run_state_machine_as_test(MutationMachine, settings=config)
    except AssertionError:
        print("EXPECTED: Hypothesis found the injected tag-propagation bug")
        print("A failed run is the intended outcome of this experiment.")
        print("See the Falsifying example in the traceback below.")
        raise
    raise RuntimeError("No mutation counterexample was generated")


if __name__ == "__main__":
    main()
