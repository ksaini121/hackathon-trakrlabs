"""Block 1 gate: tenant isolation, schema setup and the idempotency-key constraint.

Run from the repo root:  .venv/bin/python -m scratch.isolation_check
"""
import time

from redis.exceptions import ResponseError

from backend.app.db import ensure_schema, get_client, get_tenant_graph

TENANTS = ("northside", "lakeview")


def wait_for_constraints(graph, timeout=10.0):
    # Constraints are built in the background; they only enforce once operational.
    deadline = time.time() + timeout
    while time.time() < deadline:
        constraints = graph.list_constraints()
        if constraints and all(c["status"] == "OPERATIONAL" for c in constraints):
            return
        time.sleep(0.2)
    raise TimeoutError("constraint did not become operational")


def main():
    client = get_client()

    # Start clean so reruns are repeatable.
    for tenant in TENANTS:
        graph = get_tenant_graph(client, tenant)
        try:
            graph.delete()
        except ResponseError:
            pass  # graph did not exist yet

    graphs = {tenant: get_tenant_graph(client, tenant) for tenant in TENANTS}
    for graph in graphs.values():
        ensure_schema(graph)
        ensure_schema(graph)  # second run must not fail
        wait_for_constraints(graph)
    print("schema ok on both tenants (and idempotent)")

    north, lake = graphs["northside"], graphs["lakeview"]
    find = "MATCH (s:Subject {id: $id}) RETURN s.name"

    north.query("CREATE (:Subject {id: $id, name: $name})", {"id": "p1", "name": "Asha"})
    assert len(north.query(find, {"id": "p1"}).result_set) == 1
    assert len(lake.query(find, {"id": "p1"}).result_set) == 0
    print("isolation ok: lakeview cannot see northside's p1")

    lake.query("CREATE (:Subject {id: $id, name: $name})", {"id": "p1", "name": "Ravi"})
    assert north.query(find, {"id": "p1"}).result_set == [["Asha"]]
    assert lake.query(find, {"id": "p1"}).result_set == [["Ravi"]]
    print("same id in both tenants stays separate")

    create_ep = "CREATE (:Episode {id: $id, idempotency_key: $key})"
    north.query(create_ep, {"id": "e1", "key": "k1"})
    try:
        north.query(create_ep, {"id": "e2", "key": "k1"})
        raise AssertionError("duplicate idempotency key was accepted")
    except ResponseError:
        print("duplicate idempotency key rejected by CREATE")

    merge_ep = "MERGE (e:Episode {idempotency_key: $key}) ON CREATE SET e.id = $id RETURN e.id"
    assert north.query(merge_ep, {"id": "e3", "key": "k1"}).result_set == [["e1"]]
    print("MERGE on the same key matches the existing episode")

    names = sorted(g for g in client.list_graphs() if g.startswith("t_"))
    print("tenant graphs:", names)


if __name__ == "__main__":
    main()
