import pytest

from app.schemas.decision import Band, Thresholds
from app.services.policy import PolicyEngine


@pytest.fixture
def policy():
    return PolicyEngine(Thresholds(step_up=300, review=650, decline=850))


@pytest.mark.parametrize(
    "score, band",
    [
        (0, Band.APPROVE),
        (299, Band.APPROVE),
        (300, Band.STEP_UP),
        (649, Band.STEP_UP),
        (650, Band.REVIEW),
        (849, Band.REVIEW),
        (850, Band.DECLINE),
        (1000, Band.DECLINE),
    ],
)
def test_band_boundaries(policy, score, band):
    assert policy.band_for(score) == band


def test_tighten_shifts_all_bands_down_and_reset_restores(policy):
    old, new = policy.tighten(75)
    assert (old.step_up, old.review, old.decline) == (300, 650, 850)
    assert (new.step_up, new.review, new.decline) == (225, 575, 775)
    assert policy.band_for(775) == Band.DECLINE
    assert policy.band_for(224) == Band.APPROVE
    policy.reset()
    assert policy.thresholds == policy.base


def test_classify_returns_thresholds_used(policy):
    band, used = policy.classify(700)
    assert band == Band.REVIEW
    assert used == Thresholds(step_up=300, review=650, decline=850)


def test_invalid_thresholds_rejected():
    with pytest.raises(ValueError):
        PolicyEngine(Thresholds(step_up=700, review=650, decline=850))
