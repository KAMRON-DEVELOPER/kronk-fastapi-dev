from pydantic import BaseModel


class StatisticsSchema(BaseModel):
    weekly: dict[str, int]
    monthly: dict[str, int]
    yearly: dict[str, int]
    total: int
