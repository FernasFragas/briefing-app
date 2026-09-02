"""Factor certificate / knock-out leverage guard.

A daily-reset product does not return `L x` the underlying's move over more than one
day. The reset compounds the leveraged daily return, so a round trip in the underlying
leaves the certificate below where it started. This module quantifies that drag and
enforces the three hard rules from `trading ideas.md` Stage 6:

- No leveraged expression on an Estimated catalyst.
- No leveraged expression without a stop, a measured range, and a drag figure.
- A name whose *routine* daily move approaches `1 / L` is not a candidate at that
  leverage on any multi-day hold - the knock-out barrier is inside normal noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Fraction of the `1 / L` barrier a routine daily move may reach before the leverage
#: is refused. 0.5 means "half the barrier is already too close".
DEFAULT_KNOCKOUT_BUFFER: float = 0.5


class LeverageError(ValueError):
    """Raised when a drag simulation is asked for impossible inputs."""


@dataclass(frozen=True)
class DragSimulation:
    """Deterministic daily-reset path simulation over the holding window.

    The path alternates `+v` / `-v` daily shocks around a drift solved so the
    underlying lands exactly on `total_move_pct`. That is the cheapest honest way to
    show the reset cost of a given routine daily move: no randomness, no seed, same
    answer every run, and it reproduces the closed-form variance drag as `days` grows.
    """

    leverage: float
    daily_vol_pct: float
    days: int
    underlying_return_pct: float
    naive_return_pct: float
    simulated_return_pct: float
    drag_pct: float
    max_drawdown_pct: float
    worst_daily_return_pct: float

    @property
    def is_total_loss(self) -> bool:
        """The certificate path reached zero: a knock-out on any real product."""
        return self.simulated_return_pct <= -100.0


@dataclass(frozen=True)
class LeverageCheck:
    """Verdict for one leveraged expression, with the numbers behind it."""

    leverage: float
    allowed: bool
    knockout_move_pct: float
    daily_vol_pct: float
    knockout_buffer: float
    simulation: DragSimulation | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    inputs_checked: tuple[str, ...] = field(default=("catalyst", "stop", "range", "drag"))

    @property
    def drag_pct(self) -> float | None:
        return self.simulation.drag_pct if self.simulation is not None else None

    def summary(self) -> str:
        if self.allowed:
            drag = self.drag_pct
            drag_text = f"{drag:+.2f}% drag" if drag is not None else "drag unavailable"
            return (
                f"{self.leverage:g}x cleared: {drag_text} over "
                f"{self.simulation.days if self.simulation else 0}d, knock-out at "
                f"{self.knockout_move_pct:.2f}% vs {self.daily_vol_pct:.2f}% routine daily move"
            )
        return f"{self.leverage:g}x refused: " + "; ".join(self.blockers)

    def to_dict(self) -> dict[str, object]:
        return {
            "leverage": self.leverage,
            "allowed": self.allowed,
            "knockout_move_pct": self.knockout_move_pct,
            "daily_vol_pct": self.daily_vol_pct,
            "knockout_buffer": self.knockout_buffer,
            "drag_pct": self.drag_pct,
            "simulated_return_pct": (
                self.simulation.simulated_return_pct if self.simulation else None
            ),
            "naive_return_pct": self.simulation.naive_return_pct if self.simulation else None,
            "max_drawdown_pct": self.simulation.max_drawdown_pct if self.simulation else None,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def knockout_move_pct(leverage: float) -> float:
    """The one-day underlying move that takes a daily-reset product to zero: `1 / L`."""
    if leverage <= 0.0:
        raise LeverageError("leverage must be positive")
    return 100.0 / leverage


def simulate_daily_reset(
    leverage: float,
    daily_vol_pct: float,
    days: int,
    total_move_pct: float = 0.0,
) -> DragSimulation:
    """Compound a leveraged daily-reset path and report the drag against `L x move`.

    `daily_vol_pct` and `total_move_pct` are percentages of the underlying. The drift
    is solved by bisection so the simulated underlying path ends exactly on
    `total_move_pct`, which keeps the drag attributable to the reset rather than to a
    path that quietly went somewhere else.
    """

    if leverage <= 0.0:
        raise LeverageError("leverage must be positive")
    if daily_vol_pct < 0.0:
        raise LeverageError("daily_vol_pct must not be negative")
    if days <= 0:
        raise LeverageError("days must be positive")
    if total_move_pct <= -100.0:
        raise LeverageError("total_move_pct must be greater than -100")

    vol = daily_vol_pct / 100.0
    target = total_move_pct / 100.0
    drift = _solve_drift(vol, days, target)

    certificate = 1.0
    underlying = 1.0
    peak = 1.0
    max_drawdown = 0.0
    worst_daily = 0.0

    for day in range(days):
        daily_return = drift + (vol if day % 2 == 0 else -vol)
        worst_daily = min(worst_daily, daily_return)
        underlying *= 1.0 + daily_return
        # The reset: today's leveraged return applies to yesterday's certificate value.
        certificate = max(0.0, certificate * (1.0 + (leverage * daily_return)))
        peak = max(peak, certificate)
        if peak > 0.0:
            max_drawdown = min(max_drawdown, (certificate / peak) - 1.0)
        if certificate == 0.0:
            break

    underlying_return = (underlying - 1.0) * 100.0
    simulated_return = (certificate - 1.0) * 100.0
    naive_return = leverage * underlying_return
    return DragSimulation(
        leverage=leverage,
        daily_vol_pct=daily_vol_pct,
        days=days,
        underlying_return_pct=underlying_return,
        naive_return_pct=naive_return,
        simulated_return_pct=simulated_return,
        drag_pct=simulated_return - naive_return,
        max_drawdown_pct=max_drawdown * 100.0,
        worst_daily_return_pct=worst_daily * 100.0,
    )


def check_leverage(
    *,
    leverage: float,
    daily_vol_pct: float | None,
    days: int,
    total_move_pct: float = 0.0,
    catalyst_confirmed: bool,
    has_stop: bool,
    has_measured_range: bool,
    knockout_buffer: float = DEFAULT_KNOCKOUT_BUFFER,
    max_window_drag_pct: float | None = None,
) -> LeverageCheck:
    """Run every leverage precondition and return one verdict.

    All blockers are collected, not just the first, so the rejected-setup line says
    everything that was wrong with the expression instead of one symptom at a time.
    """

    blockers: list[str] = []
    warnings: list[str] = []

    if not catalyst_confirmed:
        blockers.append("no confirmed dated catalyst: an Estimated date never authorises leverage")
    if not has_stop:
        blockers.append("no stop level: a leveraged expression needs an explicit invalidation")
    if not has_measured_range:
        blockers.append("no measured sigma range: routine daily move is unquantified")

    barrier = knockout_move_pct(leverage)
    simulation: DragSimulation | None = None

    if daily_vol_pct is None:
        blockers.append("no daily volatility estimate: drag simulation cannot run")
    else:
        simulation = simulate_daily_reset(leverage, daily_vol_pct, days, total_move_pct)
        if daily_vol_pct >= barrier:
            blockers.append(
                f"routine daily move {daily_vol_pct:.2f}% is at or beyond the "
                f"{barrier:.2f}% knock-out move (1/{leverage:g})"
            )
        elif daily_vol_pct >= barrier * knockout_buffer:
            blockers.append(
                f"routine daily move {daily_vol_pct:.2f}% approaches the {barrier:.2f}% "
                f"knock-out move (1/{leverage:g}) at a {knockout_buffer:g} buffer"
            )
        if simulation.is_total_loss:
            blockers.append("simulated daily-reset path reaches zero inside the holding window")
        if max_window_drag_pct is not None and -simulation.drag_pct > max_window_drag_pct:
            blockers.append(
                f"daily-reset drag {simulation.drag_pct:+.2f}% over {days}d exceeds the "
                f"{max_window_drag_pct:.2f}% budget"
            )
        elif simulation.drag_pct < 0.0:
            warnings.append(
                f"daily-reset drag {simulation.drag_pct:+.2f}% over {days}d at "
                f"{daily_vol_pct:.2f}% daily vol"
            )

    return LeverageCheck(
        leverage=leverage,
        allowed=not blockers,
        knockout_move_pct=barrier,
        daily_vol_pct=daily_vol_pct if daily_vol_pct is not None else float("nan"),
        knockout_buffer=knockout_buffer,
        simulation=simulation,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def _solve_drift(vol: float, days: int, target: float) -> float:
    """Bisect the per-day drift that lands the alternating path on `target`."""
    def terminal(drift: float) -> float:
        value = 1.0
        for day in range(days):
            value *= 1.0 + drift + (vol if day % 2 == 0 else -vol)
        return value - 1.0

    low, high = -0.9 + vol, 0.9
    if terminal(low) > target or terminal(high) < target:
        raise LeverageError("total_move_pct is unreachable at this daily volatility")
    for _ in range(200):
        mid = (low + high) / 2.0
        if terminal(mid) < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0
