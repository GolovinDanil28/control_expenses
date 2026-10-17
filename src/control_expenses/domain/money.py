"""Денежный value object.

В базе суммы хранятся целыми копейками, в домене считаются на ``Decimal``.
``float`` запрещён (``project.md``): он теряет точность на копейках.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

KOPECK = Decimal("0.01")
KOPECKS_PER_RUBLE = Decimal(100)


def _as_decimal(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


@dataclass(frozen=True, order=True)
class Money:
    """Сумма в рублях, всегда кратная копейке."""

    rubles: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "rubles", self.rubles.quantize(KOPECK, rounding=ROUND_HALF_UP))

    @classmethod
    def zero(cls) -> Money:
        """Нулевая сумма."""
        return cls(Decimal(0))

    @classmethod
    def from_kopecks(cls, kopecks: int) -> Money:
        """Собрать сумму из целых копеек (формат хранения в БД)."""
        return cls(Decimal(kopecks) / KOPECKS_PER_RUBLE)

    @classmethod
    def from_rubles(cls, value: Decimal | int | str) -> Money:
        """Собрать сумму из рублей."""
        return cls(_as_decimal(value))

    @property
    def kopecks(self) -> int:
        """Сумма в целых копейках."""
        return int(self.rubles * KOPECKS_PER_RUBLE)

    @property
    def is_zero(self) -> bool:
        return self.kopecks == 0

    @property
    def is_negative(self) -> bool:
        return self.rubles < 0

    def __add__(self, other: Money) -> Money:
        return Money(self.rubles + other.rubles)

    def __sub__(self, other: Money) -> Money:
        return Money(self.rubles - other.rubles)

    def __neg__(self) -> Money:
        return Money(-self.rubles)

    def __floordiv__(self, divisor: int) -> Money:
        """Деление с округлением вниз до копейки.

        Дневная норма округляется вниз: лучше разрешить потратить на копейку
        меньше, чем пообещать невозможное (``design.md``).
        """
        if divisor <= 0:
            raise ValueError("divisor must be positive")
        return Money.from_kopecks(self.kopecks // divisor)

    def format_ru(self) -> str:
        """Человекочитаемая запись: «1 250 ₽ 50 коп» либо «250 ₽»."""
        total = self.kopecks
        sign = "-" if total < 0 else ""
        rubles, kopecks = divmod(abs(total), 100)
        grouped = f"{rubles:,}".replace(",", " ")
        if kopecks:
            return f"{sign}{grouped} ₽ {kopecks:02d} коп"
        return f"{sign}{grouped} ₽"
