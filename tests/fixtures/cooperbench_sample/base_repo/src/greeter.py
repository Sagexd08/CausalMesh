"""Greeting helpers. SYNTHETIC fixture content, not real CooperBench data."""

GREETINGS = {
    "casual": "Hi",
}


def greet(name, style="casual"):
    """Return a greeting for name in the given style."""
    return f"{GREETINGS[style]}, {name}!"
