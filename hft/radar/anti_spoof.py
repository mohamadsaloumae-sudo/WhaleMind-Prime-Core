"""
hft/radar/anti_spoof.py
═══════════════════════════════════════════════════════════════════════
MODULE 1: ANTI-SPOOFING RADAR & MACRO GOVERNOR
- VPIN (Volume-Synchronized Probability of Informed Trading)
- Order Book Imbalance (OBI)
- Cumulative Volume Delta (CVD) slope analysis
- Liquidity Vacuum / Stop-Hunt detection
- Fuzzy Logic Adaptive Scoring Matrix (0–100)
- Macro Governor weight injection
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
import math
import statistics
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from hft.engine.context import (
    GCM, MarketRegime, OBLevel, OrderBookSnapshot,
    RadarOutput, SignalDirection, TickSnapshot,
)

log = logging.getLogger("hft.radar")

# ── Radar tunables ─────────────────────────────────────────────────────────────
VPIN_BUCKET_SIZE    = 50        # trades per VPIN bucket
VPIN_WINDOW         = 50        # buckets for rolling VPIN
VPIN_TOXIC_THRESHOLD= 0.65      # above = institutional toxic flow
OBI_IMBALANCE_GATE  = 0.35      # |OBI| > this = significant imbalance
CVD_WINDOW          = 30        # bars for slope regression
LIQ_POOL_PROXIMITY  = 0.008     # within 0.8% of price = pool nearby
SCORE_THRESHOLD     = 75.0      # composite score gate for signal validation
WALL_MIN_SIZE       = 40.0      # minimum notional for "significant wall"
STOP_HUNT_WICK_PCT  = 0.004     # 0.4% wick = potential stop hunt
RADAR_LOOP_HZ       = 100       # target 100 Hz radar loop


class VPINCalculator:
    """
    Volume-Synchronized Probability of Informed Trading (Easley et al.)
    Segments trade flow into equal-volume buckets, classifies buy/sell,
    computes order imbalance per bucket, rolling VPIN = avg(|OI|/V).
    """

    def __init__(self) -> None:
        self.bucket_buy_vol:  float = 0.0
        self.bucket_sell_vol: float = 0.0
        self.bucket_total:    float = 0.0
        self.bucket_imbalances: Deque[float] = deque(maxlen=VPIN_WINDOW)
        self._last_price:     float = 0.0

    def ingest_trade(self, price: float, size: float, aggressor: str) -> Optional[float]:
        """Feed one trade. Returns current VPIN once a bucket completes."""
        # Classify aggressor side using tick rule if not provided
        if aggressor == "buy":
            self.bucket_buy_vol  += size
        elif aggressor == "sell":
            self.bucket_sell_vol += size
        else:
            # tick rule
            if price > self._last_price:
                self.bucket_buy_vol  += size
            else:
                self.bucket_sell_vol += size

        self.bucket_total  += size
        self._last_price    = price

        if self.bucket_total >= VPIN_BUCKET_SIZE:
            imbalance = abs(self.bucket_buy_vol - self.bucket_sell_vol) / self.bucket_total
            self.bucket_imbalances.append(imbalance)
            # Reset bucket
            self.bucket_buy_vol  = 0.0
            self.bucket_sell_vol = 0.0
            self.bucket_total    = 0.0
            return self.current_vpin

        return None

    @property
    def current_vpin(self) -> float:
        if not self.bucket_imbalances:
            return 0.0
        return statistics.mean(self.bucket_imbalances)

    @property
    def is_toxic(self) -> bool:
        return self.current_vpin >= VPIN_TOXIC_THRESHOLD


class OBIAnalyzer:
    """
    Order Book Imbalance — weighted by distance from mid.
    OBI = (bid_notional - ask_notional) / (bid_notional + ask_notional)
    Range: -1 (full ask pressure) to +1 (full bid pressure).
    """

    def compute(self, ob: OrderBookSnapshot, depth: int = 10) -> float:
        if not ob.bids or not ob.asks:
            return 0.0
        mid = ob.mid
        bid_notional = sum(
            b.size * b.price * math.exp(-abs(mid - b.price) / mid)
            for b in ob.bids[:depth]
        )
        ask_notional = sum(
            a.size * a.price * math.exp(-abs(a.price - mid) / mid)
            for a in ob.asks[:depth]
        )
        total = bid_notional + ask_notional
        return (bid_notional - ask_notional) / total if total > 0 else 0.0

    def detect_spoofing(self, ob: OrderBookSnapshot, min_wall: float = 200.0) -> Tuple[bool, str]:
        """
        Spoof pattern: massive wall far from mid that appears/vanishes.
        Here we flag walls >5% from mid with size > min_wall.
        """
        mid = ob.mid
        if not mid:
            return False, ""
        for b in ob.bids:
            if b.size >= min_wall and abs(mid - b.price) / mid > 0.05:
                return True, f"Spoofed BID wall {b.price:.2f} × {b.size:.0f}"
        for a in ob.asks:
            if a.size >= min_wall and abs(a.price - mid) / mid > 0.05:
                return True, f"Spoofed ASK wall {a.price:.2f} × {a.size:.0f}"
        return False, ""


class CVDAnalyzer:
    """
    Cumulative Volume Delta — running sum of (buy_vol - sell_vol).
    Slope computed via linear regression over CVD_WINDOW bars.
    Positive slope = buyers dominating. Negative = sellers.
    """

    def __init__(self) -> None:
        self._series: Deque[float] = deque(maxlen=CVD_WINDOW + 1)
        self._cumulative: float = 0.0

    def update(self, buy_vol: float, sell_vol: float) -> float:
        self._cumulative += buy_vol - sell_vol
        self._series.append(self._cumulative)
        return self._cumulative

    @property
    def slope(self) -> float:
        """Returns slope of CVD via least-squares regression."""
        n = len(self._series)
        if n < 3:
            return 0.0
        x = list(range(n))
        y = list(self._series)
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)
        num   = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        denom = sum((xi - x_mean) ** 2 for xi in x)
        return num / denom if denom else 0.0

    @property
    def acceleration(self) -> float:
        """Second derivative — detects momentum explosion."""
        if len(self._series) < 4:
            return 0.0
        recent = list(self._series)[-4:]
        slopes = [recent[i + 1] - recent[i] for i in range(3)]
        return slopes[-1] - slopes[0]


class LiquidityVacuumDetector:
    """
    Maps high-density derivative liquidation pools.
    Suppresses entries until stop-hunt completes + organic walls form.
    """

    def __init__(self) -> None:
        self._recent_wicks: Deque[Tuple[float, float, float]] = deque(maxlen=20)
        # (ts, high_wick_pct, low_wick_pct)

    def update(self, open_: float, high: float, low: float, close: float) -> None:
        candle_range = high - low if high > low else 1e-9
        high_wick = (high - max(open_, close)) / candle_range
        low_wick  = (min(open_, close) - low)  / candle_range
        self._recent_wicks.append((time.time(), high_wick, low_wick))

    def detect_stop_hunt(self, direction: SignalDirection, current_price: float,
                         liq_above: float, liq_below: float) -> Tuple[bool, str]:
        """Returns (suppressed, reason)."""
        if not self._recent_wicks:
            return False, ""

        _, hw, lw = self._recent_wicks[-1]

        if direction == SignalDirection.LONG:
            # Long entry after a low-wick spike = stop-hunt of longs below
            if lw > STOP_HUNT_WICK_PCT * 10 and liq_below > 0:
                if abs(current_price - liq_below) / current_price < LIQ_POOL_PROXIMITY:
                    return True, f"LIQ_VACUUM: Price near liq pool {liq_below:.2f}; awaiting flush"
        elif direction == SignalDirection.SHORT:
            if hw > STOP_HUNT_WICK_PCT * 10 and liq_above > 0:
                if abs(liq_above - current_price) / current_price < LIQ_POOL_PROXIMITY:
                    return True, f"LIQ_VACUUM: Price near liq pool {liq_above:.2f}; awaiting flush"
        return False, ""

    def estimate_pools(self, price: float, ob: OrderBookSnapshot) -> Tuple[float, float]:
        """Estimate liquidation pool levels from largest OB clusters."""
        liq_above = 0.0
        liq_below = 0.0
        ask_wall = ob.largest_ask_wall(WALL_MIN_SIZE)
        bid_wall = ob.largest_bid_wall(WALL_MIN_SIZE)
        if ask_wall:
            liq_above = ask_wall.price
        if bid_wall:
            liq_below = bid_wall.price
        return liq_above, liq_below


class FuzzyScoreMatrix:
    """
    Adaptive Fuzzy Logic Scoring — no hard if/else thresholds.
    Aggregates 4 primary dimensions into a composite 0–100 score.
    A signal validates if score > SCORE_THRESHOLD even when one
    variable is sub-optimal (riding the whale's wave).
    """

    # Fuzzy membership breakpoints per dimension
    def _obi_score(self, obi: float, direction: SignalDirection) -> float:
        """OBI contribution: 0–25 points."""
        signed = obi if direction == SignalDirection.LONG else -obi
        if signed >= 0.5:   return 25.0
        if signed >= 0.3:   return 20.0
        if signed >= 0.1:   return 14.0
        if signed >= -0.1:  return 8.0
        if signed >= -0.3:  return 3.0
        return 0.0

    def _cvd_score(self, slope: float, direction: SignalDirection) -> float:
        """CVD slope contribution: 0–25 points."""
        signed_slope = slope if direction == SignalDirection.LONG else -slope
        cap = 25.0
        # Normalise slope to ±500 range
        normalised = max(-1.0, min(1.0, signed_slope / 500.0))
        return round(max(0.0, normalised * cap), 2)

    def _macro_score(self, macro: Dict[str, float]) -> float:
        """Macro contribution: 0–25 points."""
        score = 12.5   # neutral base
        fg = macro.get("fear_greed", 50.0)
        dxy = macro.get("dxy_volatility", 0.0)
        # Fear & Greed: extreme fear (0-20) or greed (80-100) = 5 pts
        if fg < 20 or fg > 80:
            score += 5.0
        elif fg < 35 or fg > 65:
            score += 2.5
        # DXY volatility: high = tighten crypto
        if dxy > 1.5:
            score -= 5.0
        elif dxy > 0.8:
            score -= 2.0
        return max(0.0, min(25.0, score))

    def _vpin_score(self, vpin: float, direction: SignalDirection, cvd_slope: float) -> float:
        """
        VPIN contribution: 0–25 points.
        VPIN > 0.65 is toxic — but toxic flow aligned WITH direction = bonus.
        VPIN > 0.65 aligned AGAINST direction = large penalty.
        """
        if vpin < 0.4:
            return 15.0   # low toxicity, clean tape
        if vpin < VPIN_TOXIC_THRESHOLD:
            return 10.0
        # Toxic flow — check alignment with direction
        flow_aligned = (
            (direction == SignalDirection.LONG  and cvd_slope > 0) or
            (direction == SignalDirection.SHORT and cvd_slope < 0)
        )
        return 22.0 if flow_aligned else 0.0   # riding whale = bonus, fighting = zero

    def compute(
        self,
        direction: SignalDirection,
        obi: float,
        cvd_slope: float,
        vpin: float,
        macro: Dict[str, float],
        macro_weight: float = 1.0,
    ) -> float:
        s_obi   = self._obi_score(obi, direction)
        s_cvd   = self._cvd_score(cvd_slope, direction)
        s_macro = self._macro_score(macro) * macro_weight
        s_vpin  = self._vpin_score(vpin, direction, cvd_slope)
        raw     = s_obi + s_cvd + s_macro + s_vpin
        return round(min(100.0, raw), 2)

    def determine_regime(self, obi: float, cvd_slope: float, vpin: float,
                         velocity: float) -> MarketRegime:
        if vpin > 0.75 and abs(obi) > 0.5:
            return MarketRegime.STOP_HUNT
        if abs(velocity) > 200:
            return MarketRegime.HIGH_VOLATILITY
        if abs(cvd_slope) < 5 and abs(obi) < 0.1:
            return MarketRegime.RANGE_BOUND
        if abs(obi) < 0.05 and vpin > 0.5:
            return MarketRegime.LIQUIDITY_VACUUM
        if cvd_slope > 20 and obi > 0.2:
            return MarketRegime.TRENDING_BULL
        if cvd_slope < -20 and obi < -0.2:
            return MarketRegime.TRENDING_BEAR
        return MarketRegime.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# ANTI-SPOOF RADAR — main async loop
# ══════════════════════════════════════════════════════════════════════════════

class AntiSpoofRadar:
    """
    Central radar. Runs at target 100 Hz.
    Writes RadarOutput into GCM on every cycle.
    """

    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol     = symbol
        self.vpin_calc  = VPINCalculator()
        self.obi_calc   = OBIAnalyzer()
        self.cvd_calc   = CVDAnalyzer()
        self.liq_det    = LiquidityVacuumDetector()
        self.fuzzy      = FuzzyScoreMatrix()
        self._running   = False
        self._prev_price= 0.0
        self._prev_ts   = 0.0

    def feed_trade(self, price: float, size: float, aggressor: str) -> None:
        """Called by the WebSocket ingestor for every matched trade."""
        buy_vol  = size if aggressor == "buy"  else 0.0
        sell_vol = size if aggressor == "sell" else 0.0
        self.vpin_calc.ingest_trade(price, size, aggressor)
        self.cvd_calc.update(buy_vol, sell_vol)

    def feed_candle(self, open_: float, high: float, low: float, close: float) -> None:
        self.liq_det.update(open_, high, low, close)

    def _compute_direction(self, obi: float, cvd_slope: float) -> SignalDirection:
        """Preliminary direction from OBI + CVD agreement."""
        if obi > OBI_IMBALANCE_GATE and cvd_slope > 0:
            return SignalDirection.LONG
        if obi < -OBI_IMBALANCE_GATE and cvd_slope < 0:
            return SignalDirection.SHORT
        return SignalDirection.FLAT

    def _compute_velocity(self, current_price: float, now: float) -> float:
        dt = now - self._prev_ts if self._prev_ts else 1.0
        v  = (current_price - self._prev_price) / dt if dt > 0 else 0.0
        self._prev_price = current_price
        self._prev_ts    = now
        return v

    def _macro_weight(self) -> float:
        macro = GCM.macro
        dxy   = macro.get("dxy_volatility", 0.0)
        btcd  = macro.get("btc_dominance", 50.0)
        # Weight contracts when DXY is volatile or BTC dominance extreme
        w = 1.0
        if dxy > 1.5:   w -= 0.25
        if btcd > 65:   w -= 0.10
        if btcd < 35:   w += 0.10
        return max(0.5, min(1.5, w))

    async def tick(self) -> RadarOutput:
        """Single radar evaluation cycle."""
        tick = GCM.get_tick(self.symbol)
        ob   = GCM.get_ob(self.symbol)
        if not tick or not ob:
            return GCM.radar

        now      = time.time()
        price    = tick.last
        velocity = self._compute_velocity(price, now)

        obi      = self.obi_calc.compute(ob)
        cvd_slope= self.cvd_calc.slope
        vpin     = self.vpin_calc.current_vpin
        macro_w  = self._macro_weight()

        direction = self._compute_direction(obi, cvd_slope)

        # Estimate liquidation pool levels
        liq_above, liq_below = self.liq_det.estimate_pools(price, ob)

        # Score
        score = self.fuzzy.compute(
            direction, obi, cvd_slope, vpin, GCM.macro, macro_w
        )

        # Override from admin
        if GCM.ai_score_override is not None:
            score = GCM.ai_score_override

        regime = self.fuzzy.determine_regime(obi, cvd_slope, vpin, velocity)

        # ── Suppression checks ────────────────────────────────────────────────
        suppressed     = False
        suppress_reason= ""

        # 1. Admin kill-switch
        if GCM.radar_suppressed:
            suppressed, suppress_reason = True, "ADMIN_OVERRIDE: Radar manually suppressed"

        # 2. VPIN toxic flow AGAINST signal direction
        elif vpin > VPIN_TOXIC_THRESHOLD:
            flow_against = (
                (direction == SignalDirection.LONG  and cvd_slope < 0) or
                (direction == SignalDirection.SHORT and cvd_slope > 0)
            )
            if flow_against:
                suppressed     = True
                suppress_reason= f"VPIN_TOXIC: {vpin:.3f} flow against {direction.value}"

        # 3. Liquidity vacuum / stop-hunt
        if not suppressed and direction != SignalDirection.FLAT:
            suppressed, suppress_reason = self.liq_det.detect_stop_hunt(
                direction, price, liq_above, liq_below
            )

        # 4. OBI spoof detection
        if not suppressed:
            spoofed, spoof_reason = self.obi_calc.detect_spoofing(ob)
            if spoofed:
                suppressed, suppress_reason = True, f"SPOOF_DETECT: {spoof_reason}"

        # Final signal gate
        final_signal = SignalDirection.FLAT
        if not suppressed and direction != SignalDirection.FLAT and score >= SCORE_THRESHOLD:
            final_signal = direction

        out = RadarOutput(
            ts               = now,
            composite_score  = score,
            vpin             = vpin,
            obi              = obi,
            cvd_slope        = cvd_slope,
            macro_weight     = macro_w,
            btc_dominance    = GCM.macro.get("btc_dominance", 50.0),
            dxy_volatility   = GCM.macro.get("dxy_volatility", 0.0),
            regime           = regime,
            signal           = final_signal,
            suppressed       = suppressed,
            suppress_reason  = suppress_reason,
            liq_pool_above   = liq_above,
            liq_pool_below   = liq_below,
            feature_densities= {
                "obi":       round(obi, 4),
                "cvd_slope": round(cvd_slope, 4),
                "vpin":      round(vpin, 4),
                "velocity":  round(velocity, 4),
                "score":     round(score, 2),
            },
        )

        await GCM.update_radar(out)

        if final_signal != SignalDirection.FLAT:
            GCM.enqueue_tg({
                "type":    "RADAR_SIGNAL",
                "signal":  final_signal.value,
                "score":   score,
                "vpin":    vpin,
                "regime":  regime.value,
                "symbol":  self.symbol,
            })

        return out

    async def run(self) -> None:
        """Main radar loop — targets 100 Hz."""
        self._running = True
        interval = 1.0 / RADAR_LOOP_HZ
        log.info("AntiSpoofRadar started for %s @ %d Hz", self.symbol, RADAR_LOOP_HZ)
        while self._running and GCM.running:
            t0 = time.perf_counter()
            try:
                await self.tick()
            except Exception as exc:
                log.exception("Radar tick error: %s", exc)
            elapsed = time.perf_counter() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    def stop(self) -> None:
        self._running = False
