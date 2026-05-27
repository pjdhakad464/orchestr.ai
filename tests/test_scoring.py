from app.models import EntityCandidate, EntityQuery
from app.services.scoring import HeuristicScoringEngine


def test_profile_scoring_rewards_exact_name_match():
    engine = HeuristicScoringEngine()
    query = EntityQuery(name="Nintendo", entity_type="company")
    entity = EntityCandidate(
        candidate_id="1",
        label="Nintendo",
        canonical_name="Nintendo",
        description="Japanese video game company",
        source_url="https://en.wikipedia.org/wiki/Nintendo",
        source_domain="en.wikipedia.org",
        score=80,
    )
    raw_candidates = [
        {
            "url": "https://www.youtube.com/@NintendoAmerica",
            "display_name": "Nintendo",
            "handle": "@NintendoAmerica",
            "title": "Nintendo - YouTube",
            "snippet": "Official brand channel for Nintendo",
            "account_labels": ["brand channel"],
            "negative_hints": [],
        }
    ]

    result = engine.score_profile_candidates(query, entity, "YouTube", raw_candidates)
    assert result.primary is not None
    assert result.primary.confidence_score >= 60
    assert result.status == "found"


def test_entity_scoring_prefers_trusted_reference_results():
    engine = HeuristicScoringEngine()
    query = EntityQuery(name="Avatar", entity_type="movie")
    candidates = [
        EntityCandidate(
            candidate_id="1",
            label="Avatar",
            canonical_name="Avatar",
            description="2009 epic science fiction film",
            source_url="https://www.imdb.com/title/tt0499549/",
            source_domain="www.imdb.com",
            score=8,
        ),
        EntityCandidate(
            candidate_id="2",
            label="Avatar Fan Zone",
            canonical_name="Avatar Fan Zone",
            description="Community fan site",
            source_url="https://avatarfans.example.com",
            source_domain="avatarfans.example.com",
            score=8,
        ),
    ]

    ranked = engine.score_entity_candidates(query, candidates)
    assert ranked[0].candidate_id == "1"


def test_entity_scoring_penalizes_short_partial_brand_matches():
    engine = HeuristicScoringEngine()
    query = EntityQuery(name="Nickelodeon Animated Shorts", entity_type="tv_show")
    candidates = [
        EntityCandidate(
            candidate_id="1",
            label="Nickelodeon Animated Shorts",
            canonical_name="Nickelodeon Animated Shorts",
            description="Animated shorts television series",
            source_url="https://en.wikipedia.org/wiki/Nickelodeon_Animated_Shorts",
            source_domain="en.wikipedia.org",
            score=8,
        ),
        EntityCandidate(
            candidate_id="2",
            label="Nickelodeon",
            canonical_name="Nickelodeon",
            description="American pay television channel",
            source_url="https://en.wikipedia.org/wiki/Nickelodeon",
            source_domain="en.wikipedia.org",
            score=8,
        ),
    ]

    ranked = engine.score_entity_candidates(query, candidates)
    assert ranked[0].candidate_id == "1"


def test_profile_scoring_penalizes_regional_variants_without_country_hint():
    engine = HeuristicScoringEngine()
    query = EntityQuery(name="Sony Pictures", entity_type="company")
    entity = EntityCandidate(
        candidate_id="1",
        label="Sony Pictures",
        canonical_name="Sony Pictures",
        description="American entertainment company",
        source_url="https://en.wikipedia.org/wiki/Sony_Pictures",
        source_domain="en.wikipedia.org",
        score=90,
    )
    raw_candidates = [
        {
            "url": "https://facebook.com/SonyPicturesAUS",
            "display_name": "Sony Pictures",
            "handle": "SonyPicturesAUS",
            "title": "Sony Pictures - Facebook",
            "snippet": "Official page for Sony Pictures Australia",
            "account_labels": ["official", "official page"],
            "negative_hints": [],
        },
        {
            "url": "https://facebook.com/SonyPictures",
            "display_name": "Sony Pictures",
            "handle": "SonyPictures",
            "title": "Sony Pictures - Facebook",
            "snippet": "Official page for Sony Pictures",
            "account_labels": ["official", "official page"],
            "negative_hints": [],
        },
    ]

    result = engine.score_profile_candidates(query, entity, "Facebook", raw_candidates)
    assert result.primary is not None
    assert result.primary.handle == "SonyPictures"
