from enum import Enum

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import Field


class WinCondition(str, Enum):
    FLAG = 'flag'


class Benchmark(BaseModel):
    id: str = Field(..., description='The id of the benchmark')
    name: str = Field(..., description='The name of the benchmark')
    description: str = Field(
        ...,
        description='The description of the benchmark',
    )
    level: int = Field(..., description='The level of the benchmark')
    win_condition: WinCondition = Field(
        ...,
        description='The win condition of the benchmark',
    )
    tags: list[str] = Field(..., description='The tags of the benchmark')
    canaries: list[str] = Field(
        ...,
        description='The canaries of the benchmark',
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def points(self) -> int:
        points_map = {1: 200, 2: 300, 3: 500}
        return points_map.get(self.level, 0)
