"""polymkt — a read-only Polymarket client for research and monitoring.

Polymarket exposes prediction-market prices, which are probabilities you
can read off a live order book. This package makes those readable from a
terminal and stores snapshots locally so you can see how a probability
*moved*, not just where it sits right now.

Scope is deliberately read-only: discovery (Gamma), live prices and books
(CLOB), and account/market activity (Data). Placing orders needs EIP-712
signing, which needs a crypto dependency, and this repo is stdlib-only.
See docs/POLYMARKET.md for why that line is drawn where it is.
"""

__version__ = "0.1.0"
