"""Build the demo database end to end: generate -> write -> bake -> selfcheck.

Run: python -m app.build_db
Used verbatim inside the Docker build; a failed selfcheck fails the image.
"""
from __future__ import annotations

import sys
import time

from . import bake, generate, selfcheck
from .db import DB_PATH, connect, create_schema, write_frame


def main() -> int:
    t0 = time.time()
    print(f"generating synthetic world (seed {generate.CONFIG['seed']}) ...")
    frames = generate.generate()
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect(DB_PATH, ro=False)
    create_schema(conn)
    for table, df in frames.items():
        write_frame(conn, table, df)
    conn.commit()
    print(f"wrote {len(frames)} raw tables ({len(frames['order_lines'])} order lines)")
    result = bake.bake(conn)
    conn.close()
    print(f"baked warm state: {result['register_rows']} register rows, "
          f"{result['weeks']} weeks, band {result['band']['lo']}-{result['band']['hi']}")
    rc = selfcheck.run(DB_PATH)
    print(f"build_db done in {time.time() - t0:.1f}s")
    return rc


if __name__ == "__main__":
    sys.exit(main())
