from pydantic import BaseModel, ConfigDict, Field


class PublisherSchema(BaseModel):
    id: str
    name: str
    aliases: list[str] | None = Field(default_factory=list)
    languages: list[str] | None = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
