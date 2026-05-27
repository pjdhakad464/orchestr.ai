from app.platforms.facebook import FacebookAdapter
from app.platforms.imdb import ImdbAdapter
from app.platforms.instagram import InstagramAdapter
from app.platforms.twitter import TwitterAdapter
from app.platforms.wikipedia import WikipediaAdapter
from app.platforms.youtube import YouTubeAdapter


def get_platform_adapters():
    return [
        FacebookAdapter(),
        InstagramAdapter(),
        YouTubeAdapter(),
        TwitterAdapter(),
        WikipediaAdapter(),
        ImdbAdapter(),
    ]
