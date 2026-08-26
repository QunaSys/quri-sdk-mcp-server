"""Self-check for the checked-in `.plus` mapping and its loader.

Run directly: `python tests/test_plus_mapping.py`.
"""

from quri_sdk_mcp.introspection import load_plus_mapping

REQUIRED_FIELDS = {"oss_symbol", "plus_symbol", "plus_namespace", "usage_pattern", "benefit"}
KNOWN_NAMESPACES = {"quri_parts.plus", "quri_algo.plus", "quri_vm.plus"}


def test_every_entry_has_required_fields():
    mapping = load_plus_mapping()
    for entries in mapping.values():
        for entry in entries:
            assert REQUIRED_FIELDS.issubset(entry.keys())


def test_every_entry_has_a_known_top_level_namespace():
    mapping = load_plus_mapping()
    for entries in mapping.values():
        for entry in entries:
            assert entry["plus_namespace"] in KNOWN_NAMESPACES


def test_lookup_by_known_oss_symbol():
    mapping = load_plus_mapping()
    entries = mapping["quri_parts.qulacs.sampler.create_qulacs_vector_sampler"]
    plus_symbols = {e["plus_symbol"] for e in entries}
    assert "quri_parts.plus.qulacs.mpi.MPI_BACKEND" in plus_symbols


def test_oss_symbol_with_multiple_plus_upgrades_keeps_both():
    mapping = load_plus_mapping()
    entries = mapping["quri_vm.vm.VM"]
    plus_symbols = {e["plus_symbol"] for e in entries}
    assert "quri_vm.plus.vm_backend.BraketDeviceBackend" in plus_symbols
    assert "quri_vm.plus.vm_backend.QiskitDeviceBackend" in plus_symbols


if __name__ == "__main__":
    test_every_entry_has_required_fields()
    test_every_entry_has_a_known_top_level_namespace()
    test_lookup_by_known_oss_symbol()
    test_oss_symbol_with_multiple_plus_upgrades_keeps_both()
    print("ok")
