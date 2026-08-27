"""Deol Tech — a professional paper trading platform for stocks, crypto and forex.

Market data comes from Finviz. Execution is simulated by a matching engine that
models the things that actually decide whether a strategy survives contact with
a broker: the spread it must cross, the liquidity available at the touch, the
slippage of size, commissions and regulatory fees, margin, and stops that gap
through rather than filling politely at their trigger.

Nothing here places a real order or touches real money.

    python -m deoltech admin create     create the first administrator
    python -m deoltech serve            start the web platform
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
