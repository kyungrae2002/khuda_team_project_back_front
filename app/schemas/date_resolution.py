from pydantic import BaseModel, ConfigDict


class DateResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    could_resolve: bool
    # ISO 형식(YYYY-MM-DD). could_resolve가 false면 빈 문자열.
    resolved_date: str
