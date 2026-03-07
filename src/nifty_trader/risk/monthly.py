"""Monthly risk management for VENOM strategy."""

from dataclasses import dataclass


@dataclass
class MonthlyMode:
    stopped: bool = False
    stop_days: int = 0
    size_reduction: float = 0.0
    only_a_plus: bool = False
    resume_size_reduction: float = 0.0


class MonthlyManager:
    def __init__(self, max_daily_loss: float = 3000, max_weekly_loss: float = 8000,
                 consecutive_loss_limit: int = 3, mtd_protection_threshold: float = 12000,
                 mtd_protection_size_reduction: float = 0.30,
                 mtd_stop_threshold: float = -5000, mtd_stop_days: int = 3,
                 mtd_resume_size_reduction: float = 0.50):
        self.max_daily_loss = max_daily_loss
        self.max_weekly_loss = max_weekly_loss
        self.consecutive_loss_limit = consecutive_loss_limit
        self.mtd_protection_threshold = mtd_protection_threshold
        self.mtd_protection_size_reduction = mtd_protection_size_reduction
        self.mtd_stop_threshold = mtd_stop_threshold
        self.mtd_stop_days = mtd_stop_days
        self.mtd_resume_size_reduction = mtd_resume_size_reduction

    def can_trade_today(self, daily_pnl: float) -> bool:
        return daily_pnl > -self.max_daily_loss

    def can_trade_this_week(self, weekly_pnl: float) -> bool:
        return weekly_pnl > -self.max_weekly_loss

    def can_trade_after_streak(self, consecutive_losses: int) -> bool:
        return consecutive_losses < self.consecutive_loss_limit

    def get_monthly_mode(self, mtd_pnl: float, day_of_month: int) -> MonthlyMode:
        if day_of_month <= 15 and mtd_pnl <= self.mtd_stop_threshold:
            return MonthlyMode(stopped=True, stop_days=self.mtd_stop_days,
                               resume_size_reduction=self.mtd_resume_size_reduction)
        if day_of_month <= 15 and mtd_pnl >= self.mtd_protection_threshold:
            return MonthlyMode(size_reduction=self.mtd_protection_size_reduction,
                               only_a_plus=True)
        return MonthlyMode()

    def compute_consecutive_losses(self, recent_pnls: list[float]) -> int:
        count = 0
        for pnl in reversed(recent_pnls):
            if pnl < 0:
                count += 1
            else:
                break
        return count
