"""`mondo schema` — print the GraphQL selection set for each resource.

Built so an agent can answer "what fields can I project with `-q` on
`mondo board get`?" without trial and error. Pure renderer over the
`extract_selected_fields(...)` data already in `mondo.cli._field_sets`,
so there is no separate source of truth.
"""

from __future__ import annotations

import typer

from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts


def schema_command(
    ctx: typer.Context,
    resource: str | None = typer.Argument(
        None,
        metavar="[RESOURCE]",
        help=(
            "Restrict to one resource (board, item, group, update, column, "
            "folder, workspace, user, team, doc, subitem). Omit to list every "
            "resource."
        ),
    ),
) -> None:
    """Print the GraphQL fields each `mondo *` read command selects.

    Use this to plan JMESPath `-q` projections without guessing — every
    field listed here projects to a real value, every field absent will
    trigger the Phase 2.1 `warning: field 'X' is not in the GraphQL
    selection set` line.
    """
    from mondo.cli._field_sets import all_resource_schemas

    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    schemas = all_resource_schemas()

    if resource is None:
        opts.emit(schemas)
        return

    if resource not in schemas:
        typer.secho(
            f"unknown resource '{resource}'. "
            f"Known: {', '.join(sorted(schemas))}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    opts.emit(schemas[resource])


# Used by the lazy-loader in `mondo.cli.main` to attach an epilog.
EPILOG = epilog_for("schema")
