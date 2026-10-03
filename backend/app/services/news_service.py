from app.integrations.news_client import NewsClient, NewsNotConfiguredError, NewsRequestError
from app.models.farm import Farm
from app.schemas.news import FarmNewsResponse, NewsArticleResponse


class NewsServiceError(Exception):
    """Raised when a live NewsAPI fetch fails -- safe to return as a 503."""


class NewsService:
    def __init__(self, news_client: NewsClient) -> None:
        self.news_client = news_client

    async def get_farm_news(self, farm: Farm) -> FarmNewsResponse:
        """Recent farming news for `farm`'s district/state. Returns an empty
        feed (not an error) when NEWS_API_KEY isn't configured, so the
        dashboard can show a clean "not set up" state instead of a 503."""
        location = ", ".join(part for part in [farm.district, farm.state] if part)

        if not self.news_client.configured or not location:
            return FarmNewsResponse(farm_id=farm.id, location=location, articles=[], is_configured=self.news_client.configured)

        try:
            articles = await self.news_client.get_farming_news(location=location)
        except NewsNotConfiguredError:
            return FarmNewsResponse(farm_id=farm.id, location=location, articles=[], is_configured=False)
        except NewsRequestError as exc:
            raise NewsServiceError(str(exc)) from exc

        return FarmNewsResponse(
            farm_id=farm.id,
            location=location,
            articles=[
                NewsArticleResponse(
                    title=a.title,
                    description=a.description,
                    url=a.url,
                    source=a.source,
                    image_url=a.image_url,
                    published_at=a.published_at,
                )
                for a in articles
            ],
            is_configured=True,
        )
