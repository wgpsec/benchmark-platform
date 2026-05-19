from enum import Enum

from pydantic import BaseModel
from pydantic import computed_field
from pydantic import Field


class WinCondition(str, Enum):
    FLAG = 'flag'


class FlagDef(BaseModel):
    id: str = Field(..., description='Unique flag identifier within challenge')
    route: str = Field(default="/", description='Route path for this flag')
    description: str = Field(default="", description='Scenario description (no spoilers)')
    hint: str = Field(default="", description='Technical hint, only revealed on request')


class Requirements(BaseModel):
    arch: str | None = Field(default=None, description='Required CPU architecture: x86_64 or aarch64')
    kvm: bool = Field(default=False, description='Requires /dev/kvm hardware virtualization')


class Benchmark(BaseModel):
    id: str = Field(..., description='The id of the benchmark')
    name: str = Field(..., description='The name of the benchmark')
    description: str = Field(
        ...,
        description='The description of the benchmark',
    )
    hint: str = Field(default="", description='Technical hint for solving, revealed on request')
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
    flags: list[FlagDef] = Field(
        default_factory=list,
        description='Multi-flag definitions (empty = legacy single-flag)',
    )
    requires: Requirements | None = Field(
        default=None,
        description='Hardware/environment requirements (null = no special requirements)',
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def points(self) -> int:
        points_map = {1: 200, 2: 300, 3: 500, 4: 1000}
        return points_map.get(self.level, 0)
