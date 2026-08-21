"""Deterministic workspace/repository intelligence.

Everything here is plain, testable Python over the filesystem — no LLM
call ever decides what a project *is*; the model only ever interprets the
structured result these modules produce. This is what lets the Planner
receive a genuine understanding of an existing project instead of relying
on the LLM to "just know" the repository.
"""
