"""Number-grounding eval harness for the merchant analyst agent.

Two layers:

1. Grounding: every number mentioned in an answer must be traceable to a tool
   result (exactly, rounded, as a percentage of a rate, scaled with k/M, or as
   a simple derivation of two tool numbers).
2. Golden: for selected cases, the answer must contain the values a direct
   tool call returns for explicit arguments.
"""

__all__ = ["golden", "grounding", "numbers", "report", "run"]
