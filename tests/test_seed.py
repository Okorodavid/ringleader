"""G2: seeding is idempotent and the live graph holds the generated counts after two consecutive loads."""
from app import seed


def test_two_loads_leave_same_counts(dataset, live_graph):
    expected = dataset.counts()
    first = seed.load(dataset)
    second = seed.load(dataset)
    assert second["nodes_created"] == 0
    assert second["relationships_created"] == 0
    for key, value in expected.items():
        assert first["counts"][key] == value, key
        assert second["counts"][key] == value, key


def test_no_ground_truth_labels_or_properties(live_graph):
    labels = {r[0] for r in live_graph.ro_query("CALL db.labels() YIELD label RETURN label").result_set}
    assert labels <= {"Account", "Device", "Phone", "Address", "Card", "IP", "Merchant", "Transaction", "Case", "Action", "Finding"}
    props = {r[0] for r in live_graph.ro_query("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey").result_set}
    assert not ({"ring", "ring_name", "is_fraud", "truth"} & props)
