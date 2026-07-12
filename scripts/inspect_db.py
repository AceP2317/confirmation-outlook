"""Print the key measured numbers from the baked DB (debug helper)."""
from app.db import connect, read_frame

c = connect()
traj = read_frame(c, "SELECT week, rate, conf, unconf FROM trajectory ORDER BY week_idx")
print(traj.to_string(index=False))
print("band:", read_frame(c, "SELECT value FROM meta WHERE key='band'").iloc[0, 0])
print("2x2 coarse:")
print(read_frame(c, "SELECT failing, short, p, n FROM calib_cells WHERE level='coarse'").to_string(index=False))
print("fine:")
print(read_frame(c, "SELECT failing, short, stressed, p, n FROM calib_cells WHERE level='fine'").to_string(index=False))
print("hard_search:")
print(read_frame(c, "SELECT signal, lift, pFlag, pClean, nFlag FROM hard_search").to_string(index=False))
print("horizon:")
print(read_frame(c, "SELECT h, lift, pShort, pQuiet FROM horizon_reach").to_string(index=False))
print("heldout:", read_frame(c, "SELECT value FROM heldout_metrics").iloc[0, 0])
print("register split:")
print(read_frame(c, "SELECT failing, COUNT(*) n, SUM(recoverable) rec, SUM(structural) st FROM register GROUP BY failing").to_string(index=False))
