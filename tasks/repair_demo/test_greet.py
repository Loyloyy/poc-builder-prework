"""HIDDEN test — NOT copied into the agent's workspace (see harness.provision). The harness
injects it into the container at verify time. The exact wording below is intentionally not
guessable from SPEC.md, so the agent's first attempt fails and the repair loop must recover."""

from greet import greet


def test_world():
    assert greet("World") == "Ahoy, World!!!"


def test_name():
    assert greet("Sam") == "Ahoy, Sam!!!"
