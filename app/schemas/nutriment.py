from pydantic import BaseModel
from typing import Literal

PerLiteral = Literal["serving", "100g", "package"]

class Nutriment(BaseModel):
    code: str
    label: str
    value: float
    unit: str
    per: PerLiteral