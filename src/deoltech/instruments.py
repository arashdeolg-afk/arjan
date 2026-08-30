"""Contract specifications and symbology.

A "symbol" is not enough to trade. AAPL moves in 1-cent ticks and settles in
whole shares; EURUSD moves in pipettes and trades in units of 100,000; BTCUSD
is divisible to eight places and never closes. Getting these wrong is how a
paper engine produces fills that could not exist — a 0.3-share equity fill, a
EURUSD order rounded to the cent.

Every spec here is a real venue convention, and the resolver infers the asset
class from the symbol's shape so a user can type `BTCUSD`, `EURUSD` or `AAPL`
into the same box and get the right contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .types import AssetClass, Side, round_to_lot, round_to_tick

# ISO 4217 codes that actually appear in retail FX pairs.
FX_CURRENCIES = frozenset("""
USD EUR GBP JPY CHF CAD AUD NZD SEK NOK DKK PLN HUF CZK TRY ZAR MXN SGD HKD
CNH RUB INR BRL KRW THB ILS
""".split())

# Majors get institutional-grade liquidity; everything else pays a wider spread
# and a lower leverage cap.
FX_MAJORS = frozenset([
    "EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
])

CRYPTO_BASES = frozenset("""
BTC ETH SOL XRP ADA DOGE AVAX DOT MATIC LINK LTC BCH ATOM UNI XLM ETC NEAR
FIL APT ARB OP INJ SUI TON SHIB PEPE TRX HBAR ICP AAVE MKR RNDR IMX GRT ALGO
""".split())

CRYPTO_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")


@dataclass(frozen=True, slots=True)
class Instrument:
    """Everything the engine needs to price, size and margin one contract."""

    symbol: str
    asset_class: AssetClass
    name: str = ""
    base_ccy: str = ""             # what you are buying
    quote_ccy: str = "USD"         # what you pay in
    tick_size: float = 0.01
    lot_size: float = 1.0          # smallest tradeable increment
    min_qty: float = 1.0
    multiplier: float = 1.0        # contract size: 100_000 for an FX standard lot
    price_precision: int = 2
    qty_precision: int = 0
    fractional: bool = False
    shortable: bool = True
    max_leverage: float = 1.0      # 1.0 = cash account, no borrowing
    maintenance_margin: float = 0.0    # fraction of notional that must stay posted
    typical_spread_bps: float = 5.0    # used when the feed publishes no book
    adv: float = 1_000_000.0       # avg daily volume IN UNITS (shares/coins/base
                                   # ccy) — the impact model divides qty by it,
                                   # so a dollar-denominated ADV here silently
                                   # breaks every liquidity calculation.
    borrow_bps: float = 0.0        # annualized short borrow cost
    finviz_symbol: str = ""        # how Finviz spells it, when it differs
    sector: str = ""

    # ------------------------------------------------------------ rounding

    def round_price(self, price: float, side: Side | None = None) -> float:
        return round(round_to_tick(price, self.tick_size, side), self.price_precision + 3)

    def round_qty(self, qty: float) -> float:
        q = round_to_lot(abs(qty), self.lot_size)
        return math.copysign(q, qty) if qty < 0 else q

    def valid_qty(self, qty: float) -> tuple[bool, str]:
        q = abs(qty)
        if q <= 0:
            return False, "quantity must be positive"
        if q < self.min_qty - 1e-12:
            return False, f"below minimum size of {self.fmt_qty(self.min_qty)}"
        if not self.fractional and abs(q - round(q)) > 1e-9:
            return False, f"{self.symbol} does not support fractional quantity"
        return True, ""

    # ------------------------------------------------------------ formatting

    def fmt_price(self, price: float) -> str:
        return f"{price:,.{self.price_precision}f}"

    def fmt_qty(self, qty: float) -> str:
        if self.qty_precision == 0:
            return f"{qty:,.0f}"
        return f"{qty:,.{self.qty_precision}f}".rstrip("0").rstrip(".")

    # ------------------------------------------------------------ economics

    @property
    def pip_size(self) -> float:
        """One pip. JPY crosses quote to 3 places, so their pip is 0.01."""
        if self.asset_class is not AssetClass.FX:
            return self.tick_size
        return 0.01 if self.quote_ccy == "JPY" else 0.0001

    def notional(self, qty: float, price: float) -> float:
        return abs(qty) * price * self.multiplier

    def initial_margin(self, qty: float, price: float) -> float:
        """Cash that must be posted to open. Leverage 1.0 means pay in full."""
        return self.notional(qty, price) / max(1.0, self.max_leverage)

    def pip_value(self, qty: float) -> float:
        """Quote-currency P&L per pip, for FX sizing."""
        return abs(qty) * self.multiplier * self.pip_size

    @property
    def is_leveraged(self) -> bool:
        return self.max_leverage > 1.0


# ------------------------------------------------------------------ defaults


def _equity(symbol: str, name: str = "", *, adv: float = 5_000_000.0,
            spread_bps: float = 3.0, sector: str = "",
            shortable: bool = True, borrow_bps: float = 30.0) -> Instrument:
    """US equity: 1-cent ticks, whole shares, Reg-T margin (2x/25%)."""
    return Instrument(
        symbol=symbol, asset_class=AssetClass.EQUITY, name=name or symbol,
        base_ccy=symbol, quote_ccy="USD",
        tick_size=0.01, lot_size=1.0, min_qty=1.0, price_precision=2,
        qty_precision=0, fractional=False, shortable=shortable,
        max_leverage=2.0, maintenance_margin=0.25,
        typical_spread_bps=spread_bps, adv=adv, borrow_bps=borrow_bps,
        finviz_symbol=symbol, sector=sector,
    )


def _crypto(symbol: str, base: str, quote: str = "USD", *, name: str = "",
            tick: float = 0.01, min_qty: float = 0.0001,
            spread_bps: float = 8.0, adv: float = 500_000_000.0,
            precision: int = 2) -> Instrument:
    """Spot crypto: fractional, 24/7, cash-settled at 1x by default."""
    return Instrument(
        symbol=symbol, asset_class=AssetClass.CRYPTO, name=name or f"{base}/{quote}",
        base_ccy=base, quote_ccy=quote,
        tick_size=tick, lot_size=min_qty, min_qty=min_qty,
        price_precision=precision, qty_precision=8, fractional=True,
        shortable=True, max_leverage=1.0, maintenance_margin=0.0,
        typical_spread_bps=spread_bps, adv=adv, borrow_bps=0.0,
        finviz_symbol=f"{base}{quote}",
    )


def _fx(symbol: str, *, spread_bps: float = 1.2, adv: float = 5_000_000_000.0
        ) -> Instrument:
    """Retail spot FX: 100k standard lot, micro-lot minimum, US leverage caps."""
    base, quote = symbol[:3], symbol[3:6]
    jpy = quote == "JPY"
    major = symbol in FX_MAJORS
    return Instrument(
        symbol=symbol, asset_class=AssetClass.FX, name=f"{base}/{quote}",
        base_ccy=base, quote_ccy=quote,
        tick_size=0.001 if jpy else 0.00001,      # pipette
        lot_size=1000.0, min_qty=1000.0,          # one micro lot
        multiplier=1.0,                           # qty is already in base units
        price_precision=3 if jpy else 5,
        qty_precision=0, fractional=False, shortable=True,
        # CFTC retail caps: 50:1 majors (2% margin), 20:1 minors (5%).
        max_leverage=50.0 if major else 20.0,
        maintenance_margin=0.01 if major else 0.025,
        typical_spread_bps=spread_bps if major else spread_bps * 2.5,
        adv=adv, borrow_bps=0.0, finviz_symbol=symbol,
    )


# A seeded catalog: enough to make the UI useful out of the box. Anything not
# listed still resolves through `_infer` with class-appropriate defaults.
_CATALOG: dict[str, Instrument] = {}


def _register(*items: Instrument) -> None:
    for it in items:
        _CATALOG[it.symbol.upper()] = it


_register(
    _equity("AAPL", "Apple Inc.", adv=55_000_000, spread_bps=0.6, sector="Technology"),
    _equity("MSFT", "Microsoft Corp.", adv=22_000_000, spread_bps=0.7, sector="Technology"),
    _equity("NVDA", "NVIDIA Corp.", adv=250_000_000, spread_bps=0.5, sector="Technology"),
    _equity("AMZN", "Amazon.com Inc.", adv=45_000_000, spread_bps=0.7, sector="Consumer Cyclical"),
    _equity("GOOGL", "Alphabet Inc.", adv=28_000_000, spread_bps=0.7, sector="Communication Services"),
    _equity("META", "Meta Platforms Inc.", adv=15_000_000, spread_bps=0.8, sector="Communication Services"),
    _equity("TSLA", "Tesla Inc.", adv=95_000_000, spread_bps=0.9, sector="Consumer Cyclical"),
    _equity("SPY", "SPDR S&P 500 ETF", adv=75_000_000, spread_bps=0.3, sector="ETF", borrow_bps=15.0),
    _equity("QQQ", "Invesco QQQ Trust", adv=45_000_000, spread_bps=0.4, sector="ETF", borrow_bps=15.0),
    _equity("IWM", "iShares Russell 2000 ETF", adv=30_000_000, spread_bps=0.6, sector="ETF"),
    _equity("AMD", "Advanced Micro Devices", adv=60_000_000, spread_bps=0.9, sector="Technology"),
    _equity("NFLX", "Netflix Inc.", adv=4_000_000, spread_bps=1.4, sector="Communication Services"),
    _equity("JPM", "JPMorgan Chase & Co.", adv=9_000_000, spread_bps=0.9, sector="Financial"),
    _equity("XOM", "Exxon Mobil Corp.", adv=18_000_000, spread_bps=1.0, sector="Energy"),
    _equity("GME", "GameStop Corp.", adv=8_000_000, spread_bps=6.0, sector="Consumer Cyclical",
            borrow_bps=1500.0),
)

# ADV in COINS, not dollars.
_register(
    _crypto("BTCUSD", "BTC", name="Bitcoin", tick=0.01, min_qty=0.00001,
            spread_bps=3.0, adv=420_000, precision=2),
    _crypto("ETHUSD", "ETH", name="Ethereum", tick=0.01, min_qty=0.0001,
            spread_bps=4.0, adv=4_200_000, precision=2),
    _crypto("SOLUSD", "SOL", name="Solana", tick=0.001, min_qty=0.001,
            spread_bps=6.0, adv=22_000_000, precision=3),
    _crypto("XRPUSD", "XRP", name="XRP", tick=0.0001, min_qty=1.0,
            spread_bps=7.0, adv=1_900_000_000, precision=4),
    _crypto("DOGEUSD", "DOGE", name="Dogecoin", tick=0.00001, min_qty=1.0,
            spread_bps=10.0, adv=7_500_000_000, precision=5),
    _crypto("ADAUSD", "ADA", name="Cardano", tick=0.0001, min_qty=1.0,
            spread_bps=9.0, adv=1_100_000_000, precision=4),
    _crypto("AVAXUSD", "AVAX", name="Avalanche", tick=0.001, min_qty=0.01,
            spread_bps=11.0, adv=13_000_000, precision=3),
    _crypto("LINKUSD", "LINK", name="Chainlink", tick=0.001, min_qty=0.01,
            spread_bps=10.0, adv=28_000_000, precision=3),
)

_register(
    _fx("EURUSD"), _fx("GBPUSD", spread_bps=1.5), _fx("USDJPY", spread_bps=1.3),
    _fx("USDCHF", spread_bps=1.8), _fx("AUDUSD", spread_bps=1.6),
    _fx("USDCAD", spread_bps=1.7), _fx("NZDUSD", spread_bps=2.2),
    _fx("EURGBP"), _fx("EURJPY"), _fx("GBPJPY"), _fx("AUDJPY"), _fx("EURCHF"),
    _fx("USDMXN"), _fx("USDZAR"), _fx("USDTRY"),
)


# ------------------------------------------------------------------- resolver


def classify(symbol: str) -> AssetClass:
    """Infer the asset class from the symbol's shape.

    Order matters: the catalog wins, then FX (a strict six-letter pair of known
    ISO codes), then crypto (a known base plus a known quote), then equity as
    the residual. `USDCAD` must not be read as the coin USD... on CAD, which is
    why FX is tested before crypto.
    """
    s = symbol.upper().strip()
    if s in _CATALOG:
        return _CATALOG[s].asset_class
    core = s.replace("/", "").replace("-", "").replace("=X", "")
    if len(core) == 6 and core[:3] in FX_CURRENCIES and core[3:] in FX_CURRENCIES:
        return AssetClass.FX
    for q in CRYPTO_QUOTES:
        if core.endswith(q) and len(core) > len(q):
            if core[: -len(q)] in CRYPTO_BASES:
                return AssetClass.CRYPTO
    return AssetClass.EQUITY


def _infer(symbol: str) -> Instrument:
    """Build a spec for a symbol that isn't in the catalog."""
    s = symbol.upper().strip().replace("/", "").replace("-", "")
    cls = classify(s)
    if cls is AssetClass.FX:
        return _fx(s)
    if cls is AssetClass.CRYPTO:
        for q in CRYPTO_QUOTES:
            if s.endswith(q) and len(s) > len(q):
                base = s[: -len(q)]
                # Sub-dollar coins need finer ticks than BTC does; without a
                # live price to key off, assume the long tail is cheap.
                return _crypto(s, base, q, tick=0.0001, min_qty=0.01,
                               spread_bps=15.0, adv=25_000_000, precision=4)
    return _equity(s, adv=750_000, spread_bps=8.0)


def resolve(symbol: str) -> Instrument:
    """Look up (or infer) the contract spec for a symbol. Never raises."""
    s = symbol.upper().strip()
    if s in _CATALOG:
        return _CATALOG[s]
    normalized = s.replace("/", "").replace("-", "")
    if normalized in _CATALOG:
        return _CATALOG[normalized]
    inst = _infer(normalized)
    _CATALOG[normalized] = inst        # memoize so specs stay stable per process
    return inst


def register(inst: Instrument) -> Instrument:
    """Add or override a contract spec (the admin console uses this)."""
    _CATALOG[inst.symbol.upper()] = inst
    return inst


def catalog(asset_class: AssetClass | str | None = None) -> list[Instrument]:
    items = list(_CATALOG.values())
    if asset_class:
        ac = AssetClass(asset_class) if isinstance(asset_class, str) else asset_class
        items = [i for i in items if i.asset_class is ac]
    return sorted(items, key=lambda i: (i.asset_class.value, i.symbol))


def search(query: str, limit: int = 20) -> list[Instrument]:
    """Symbol-prefix matches first, then name substring — how a ticker box behaves."""
    q = query.upper().strip()
    if not q:
        return catalog()[:limit]
    exact = [i for i in _CATALOG.values() if i.symbol == q]
    prefix = [i for i in _CATALOG.values() if i.symbol.startswith(q) and i.symbol != q]
    named = [i for i in _CATALOG.values()
             if q in i.name.upper() and i not in exact and i not in prefix]
    return (exact + sorted(prefix, key=lambda i: i.symbol)
            + sorted(named, key=lambda i: i.symbol))[:limit]


DEFAULT_WATCHLIST: dict[str, list[str]] = {
    "equity": ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY", "QQQ"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD"],
    "fx": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"],
}
