"""CLI-agnostic domain helpers.

Pure logic and resolver utilities shared by the CLI and service layers.
Nothing here imports :mod:`mondo.cli`, so lower layers (``services``,
``cache``, ``api``) can reuse it without inverting the dependency arrow.
"""
