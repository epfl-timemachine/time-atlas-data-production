"""
europeana_uuid_generator.py

Standalone helper that reproduces the historical-record UUID produced by
``produce_europe_postcards_data_v2.py`` for a given Europeana postcard
``record_id``.

Equivalent pipeline in the main script:

    uuid_mgr = UUIDManager("https://timemachine.epfl.ch/europe/europeana_postcards")
    seed     = seed_from_row(row, ["record_id"])   # → "{record_id}\\n"
    hr_uuid  = uuid_mgr._generate_uuid(seed)       # → uuid5(namespace, seed)

Both steps use UUIDv5:
  1. namespace UUID = uuid5(uuid.NAMESPACE_URL, NAMESPACE_URL)
  2. result         = uuid5(namespace, record_id + "\\n")

The trailing newline comes from pandas ``Series.to_csv()`` (no header, no
index), which appends a line terminator after every value.
"""

import uuid

# Matches ``data_config["UUID_NAMESPACE"]`` in dataproduction_config.json
_NAMESPACE_URL: str = "https://timemachine.epfl.ch/europe/europeana_postcards"

# Mirrors ``UUIDManager.__init__`` when given a URL string
_NAMESPACE: uuid.UUID = uuid.uuid5(uuid.NAMESPACE_URL, _NAMESPACE_URL)


def generate_hr_uuid(record_id: str) -> str:
    """Return the deterministic historical-record UUID for a postcard record_id.

    Args:
        record_id: The raw ``record_id`` string extracted from the WAM
                   annotation (e.g. ``"item_ABCDE12345"``).

    Returns:
        A UUID string (e.g. ``"f3a1b2c3-..."``).
    """
    # pandas to_csv appends a newline — must be reproduced exactly
    seed = f"{record_id}\n"
    return str(uuid.uuid5(_NAMESPACE, seed))


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <record_id>")
        sys.exit(1)

    print(generate_hr_uuid(sys.argv[1]))
