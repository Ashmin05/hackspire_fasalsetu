import uuid

from pydantic import BaseModel


class NewsArticleResponse(BaseModel):
    title: str
    description: str | None
    url: str
    source: str
    image_url: str | None
    published_at: str


class FarmNewsResponse(BaseModel):
    farm_id: uuid.UUID
    location: str
    articles: list[NewsArticleResponse]
    is_configured: bool
