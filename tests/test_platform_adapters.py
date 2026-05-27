from app.platforms.facebook import FacebookAdapter
from app.platforms.instagram import InstagramAdapter
from app.platforms.tiktok import TikTokAdapter
from app.platforms.twitter import TwitterAdapter
from app.platforms.youtube import YouTubeAdapter


def test_instagram_rejects_reels():
    adapter = InstagramAdapter()
    assert not adapter.is_valid_profile_url("https://www.instagram.com/reel/ABC123/")
    assert adapter.is_valid_profile_url("https://www.instagram.com/nasa/")


def test_youtube_extracts_handle_from_at_urls():
    adapter = YouTubeAdapter()
    assert adapter.extract_handle("https://www.youtube.com/@TaylorSwift") == "@TaylorSwift"


def test_twitter_rejects_status_urls():
    adapter = TwitterAdapter()
    assert not adapter.is_valid_profile_url("https://x.com/nasa/status/123")
    assert adapter.is_valid_profile_url("https://x.com/nasa")


def test_facebook_extracts_profile_id():
    adapter = FacebookAdapter()
    assert adapter.extract_handle("https://www.facebook.com/profile.php?id=12345") == "12345"


def test_facebook_rejects_blocked_page_paths():
    adapter = FacebookAdapter()
    assert not adapter.is_valid_profile_url("https://www.facebook.com/p/example")
    assert not adapter.is_valid_profile_url("https://www.facebook.com/page/example")
    assert not adapter.is_valid_profile_url("https://www.facebook.com/pages/example/123")
    assert not adapter.is_valid_profile_url("https://www.facebook.com/profile.php?id=12345")
    assert adapter.is_valid_profile_url("https://www.facebook.com/nasa")


def test_tiktok_adapter_accepts_profile_urls_only():
    adapter = TikTokAdapter()
    assert adapter.is_valid_profile_url("https://www.tiktok.com/@barbiethemovie")
    assert not adapter.is_valid_profile_url("https://www.tiktok.com/tag/barbie")
    assert adapter.extract_handle("https://www.tiktok.com/@barbiethemovie") == "@barbiethemovie"
