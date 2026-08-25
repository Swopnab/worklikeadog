"""
browser/fillers/__init__.py
Form filler registry and factory.
"""
from browser.detect import ATSPlatform
from browser.fillers.base import BaseFormFiller, FillResult
from browser.fillers.greenhouse import GreenhouseFiller
from browser.fillers.lever import LeverFiller
from browser.fillers.ashby import AshbyFiller
from browser.fillers.workday import WorkdayFiller
from browser.fillers.taleo import TaleoFiller
from browser.fillers.generic import GenericFormFiller

FILLERS = {
    ATSPlatform.GREENHOUSE: GreenhouseFiller,
    ATSPlatform.LEVER: LeverFiller,
    ATSPlatform.ASHBY: AshbyFiller,
    ATSPlatform.WORKDAY: WorkdayFiller,
    ATSPlatform.GENERIC: GenericFormFiller,
    ATSPlatform.UNKNOWN: GenericFormFiller,
}


def get_form_filler(platform: ATSPlatform) -> BaseFormFiller:
    """Returns the specialized form filler instance for the given ATS platform."""
    cls = FILLERS.get(platform, GenericFormFiller)
    return cls()
