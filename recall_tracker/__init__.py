"""Recall campaign tracker.

The tool pipeline reads the accepted SQLite rows into one affected list, runs
notification and repair checks, and saves reports and decisions. The
contract package defines the shared records the checks and UI use.

Run ``python -m recall_tracker --help`` for the CLI and local report API.
"""
