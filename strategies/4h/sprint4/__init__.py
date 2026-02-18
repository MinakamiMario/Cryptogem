"""Sprint 4 -- DC-Compatible Entry Mining.

Generates entries that mimic DualConfirm's geometric properties:
  - Entry at price-structure LOW (bottom of recent range)
  - Entry BELOW dc_mid (ensures DC TARGET is profitable)
  - Entry BELOW bb_mid (ensures BB TARGET is profitable)
  - RSI has room to recover (ensures RSI RECOVERY exit is reachable)
  - Volume/momentum confirmation (ensures bounce has power)

Sprint 3 proved that arbitrary entries + DC exits = 0 GO.
DualConfirm is an indivisible system: entry and exit are co-dependent.
Sprint 4 tests whether entries that MIMIC DC geometry can unlock DC exits.
"""
