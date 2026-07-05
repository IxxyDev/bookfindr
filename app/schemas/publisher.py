from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PublisherSchema(BaseModel):
    id: str
    name: str
    aliases: Optional[List[str]] = Field(default_factory=list)
    languages: Optional[List[str]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
