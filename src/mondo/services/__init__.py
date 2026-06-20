"""Service layer: behavior-neutral business logic extracted from the CLI.

Modules here hold the query-building, validation, and response-shaping logic
that the Typer command callbacks in :mod:`mondo.cli` delegate to. Functions
take plain arguments, return plain data, and raise domain errors from
:mod:`mondo.api.errors`; the CLI layer owns argument parsing, emission, and
exit-code mapping.
"""
