import os

from falkordb import FalkorDB, Graph
from redis.exceptions import ResponseError

# Properties indexed on every tenant graph: lookups by id are on every query path.
ID_INDEXED_LABELS = ("Subject", "Episode", "Fact", "Task")


def get_client() -> FalkorDB:
    return FalkorDB(
        host=os.getenv("FALKORDB_HOST", "localhost"),
        port=int(os.getenv("FALKORDB_PORT", "6379")),
    )


def tenant_graph_name(tenant_id: str) -> str:
    # Graph names are built here, from a server-side tenant id. Callers never pick one.
    return f"t_{tenant_id}"


def get_tenant_graph(client: FalkorDB, tenant_id: str) -> Graph:
    return client.select_graph(tenant_graph_name(tenant_id))


def _ignore_already_exists(create) -> None:
    try:
        create()
    except ResponseError as err:
        if "already" not in str(err).lower():
            raise


def ensure_schema(graph: Graph) -> None:
    """Create indexes and constraints on a tenant graph. Safe to run more than once."""
    for label in ID_INDEXED_LABELS:
        _ignore_already_exists(lambda label=label: graph.create_node_range_index(label, "id"))

    # A unique constraint needs an index on the same property first.
    _ignore_already_exists(
        lambda: graph.create_node_range_index("Episode", "idempotency_key")
    )
    # Makes retries of the same episode safe: the key can exist only once per tenant.
    _ignore_already_exists(
        lambda: graph.create_node_unique_constraint("Episode", "idempotency_key")
    )
