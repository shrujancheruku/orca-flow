"""Shared library for the orca-flow scripts.

Pure modules (no I/O): routing, prices, transcripts, profiler, estimating.
I/O modules: config, github, orca. The Linear adapter lives apart, in
adapters/linear, and nothing here imports it.
"""

__version__ = "0.2.0"
