"""Central orchestration: validation -> Telegram -> Fragment -> verdict.

The decision matrix is deliberately conservative:

===========================  ==============================================
Telegram ``exists``          verdict
===========================  ==============================================
True                         ``taken``
False (clearly not           Fragment listing? -> ``fragment_collectible``.
resolving)                   Fragment "taken" badge? -> conflict -> ``unknown``.
                             Fragment page found but unparsable -> ``unknown``.
                             Fragment lookup failed -> ``unknown``.
                             Fragment has no page AND no errors -> ``available``.
None (indeterminate or       Fragment collectible/listing -> ``fragment_collectible``.
errored)                     Fragment "taken" badge -> ``taken``
                             (a bare t.me user page is consistent with that).
                             Anything else -> ``unknown``.
===========================  ==============================================

A username is only ever reported ``available`` when **both** sources give a
clean negative. Network failures, rate limits, timeouts, anti-bot pages or
unrecognized upstream responses always degrade to ``unknown`` — never to
``available``.
"""

from __future__ import annotations

import asyncio
import logging

from .cache import TTLCache
from .config import settings
from .fragment import FragmentAdapter
from .http import HttpManager
from .models import (
    BulkRequest,
    BulkResponse,
    CheckResponse,
    EntityType,
    FragmentListingState,
    FragmentResult,
    HeuristicScore,
    OverallStatus,
    ReportResponse,
    ResultSummary,
    TelegramResult,
    UsernameCharacteristics,
    ValidationResult,
)
from .telegram import TelegramAdapter
from .validators import validate_username

logger = logging.getLogger(__name__)


class UsernameChecker:
    def __init__(self, http: HttpManager) -> None:
        self.telegram = TelegramAdapter(http)
        self.fragment = FragmentAdapter(http)
        self._cache: TTLCache[CheckResponse] = TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries)
        self._bulk_semaphore = asyncio.Semaphore(settings.bulk_concurrency)

    # ------------------------------------------------------------------
    # single check
    # ------------------------------------------------------------------
    async def check_username(self, raw: str) -> CheckResponse:
        validation = validate_username(raw)
        if not validation.valid:
            return self._invalid_response(validation)

        username = validation.normalized or ""
        cached = self._cache.get(username)
        if cached is not None:
            value, _age = cached
            return value.model_copy(update={"cached": True})

        response = await self._perform_check(validation)
        # Only persist trustworthy results: never cache responses where an
        # upstream failed, so transient problems are re-checked quickly.
        trustworthy = response.telegram.error is None and response.fragment.error is None
        if trustworthy:
            self._cache.set(username, response)
        else:
            self._cache.set(username, response, ttl=min(settings.cache_ttl_seconds, 30))
        return response

    async def _perform_check(self, validation: ValidationResult) -> CheckResponse:
        username = validation.normalized or ""

        # --- Telegram lookup ------------------------------------------------
        if validation.telegram_eligible:
            telegram = await self.telegram.check(username)
        else:
            telegram = TelegramResult(
                checked=False,
                exists=None,
                public_url="",
                evidence=["Telegram check skipped: the username does not satisfy Telegram's eligibility rules"],
            )

        # --- Fragment lookup ------------------------------------------------
        fragment: FragmentResult
        if validation.fragment_eligible and telegram.exists is not True:
            fragment = await self.fragment.check(username)
        elif validation.fragment_eligible and telegram.exists is True:
            fragment = FragmentResult(checked=False)
            fragment.evidence.append("not queried: the username already resolves on Telegram")
        else:
            fragment = FragmentResult(checked=False)
            if not validation.fragment_eligible:
                fragment.evidence.append("Fragment check skipped: the username does not satisfy Fragment's eligibility rules")
            else:
                fragment.evidence.append("not queried: the username already resolves on Telegram")

        summary = self._decide(telegram, fragment)

        return CheckResponse(
            success=True,
            username=username,
            validation=validation,
            telegram=telegram,
            fragment=fragment,
            result=summary,
        )

    # ------------------------------------------------------------------
    # decisive logic
    # ------------------------------------------------------------------
    @staticmethod
    def _decide(telegram: TelegramResult, fragment: FragmentResult) -> ResultSummary:
        # 1. Telegram positively resolves -> taken.
        if telegram.exists is True:
            entity = telegram.entity_type.value if telegram.entity_type else "unknown entity"
            return ResultSummary(
                status=OverallStatus.TAKEN,
                explanation=f"@{telegram.public_url.rsplit('/', 1)[-1]} currently resolves on Telegram (public {entity} page).",
            )

        fragment_collectible = fragment.found is True and fragment.status in {
            FragmentListingState.ON_AUCTION,
            FragmentListingState.FOR_SALE,
            FragmentListingState.AVAILABLE,
            FragmentListingState.SOLD,
            FragmentListingState.UNAVAILABLE,
        }

        # 2. Fragment shows a tradable/held collectible.
        if fragment_collectible or (fragment.found is True and fragment.collectible is True):
            state = fragment.status.value.replace("_", " ") if fragment.status else "listed"
            price_note = ""
            if fragment.price is not None:
                price_note = f" Publicly displayed price: {fragment.price.amount} {fragment.price.currency}."
            return ResultSummary(
                status=OverallStatus.FRAGMENT_COLLECTIBLE,
                explanation=(
                    f"The username is tracked by Fragment (status: {state}).{price_note} "
                    "It is not freely claimable."
                ),
            )

        # 3. Fragment says "taken on Telegram".
        if fragment.status == FragmentListingState.TAKEN:
            if telegram.exists is False:
                return ResultSummary(
                    status=OverallStatus.UNKNOWN,
                    explanation=(
                        "Conflicting public signals: Telegram serves no page for this handle, while Fragment "
                        "reports it as already claimed on Telegram. Treated as unknown."
                    ),
                )
            return ResultSummary(
                status=OverallStatus.TAKEN,
                explanation="Fragment reports this username as already claimed on Telegram (not minted as a collectible).",
            )

        # 4. Telegram clearly does not resolve.
        if telegram.exists is False:
            if fragment.error is not None or fragment.found is None:
                return ResultSummary(
                    status=OverallStatus.UNKNOWN,
                    explanation=(
                        "Telegram does not resolve this handle, but the Fragment lookup was inconclusive "
                        f"({fragment.error.code.value if fragment.error else 'no usable response'}), so availability cannot be confirmed."
                    ),
                )
            if fragment.found is True:
                return ResultSummary(
                    status=OverallStatus.UNKNOWN,
                    explanation=(
                        "Telegram does not resolve this handle, but its Fragment page could not be interpreted "
                        "reliably. Availability is not confirmed."
                    ),
                )
            # telegram negative + fragment negative, both clean:
            return ResultSummary(
                status=OverallStatus.AVAILABLE,
                explanation=(
                    "Public evidence indicates this username does not currently resolve on Telegram and has no "
                    "listing on Fragment. Availability can still change at any moment and Telegram may reserve "
                    "some handles; claim it in the official Telegram app to confirm."
                ),
            )

        # 5. Telegram indeterminate (bare page, deep link, errors...) or
        #    not checked (skipped due to Telegram eligibility rules).
        if not telegram.checked:
            # Telegram was skipped (e.g. too short).  Fragment already
            # handled in case 2/3 above; if we land here Fragment found
            # nothing useful either.
            if fragment.found is False:
                fragment_note = "Fragment has no listing for this handle"
            elif fragment.error is not None:
                fragment_note = f"the Fragment lookup also failed ({fragment.error.code.value})"
            else:
                fragment_note = "Fragment returned no usable information"
            return ResultSummary(
                status=OverallStatus.UNKNOWN,
                explanation=(
                    f"The username does not satisfy Telegram's eligibility rules so it was not checked there, "
                    f"and {fragment_note}. Neither availability nor ownership can be confirmed."
                ),
            )

        detail = telegram.page_kind.value if telegram.page_kind else "no response"
        if fragment.error is not None:
            fragment_note = f"the Fragment lookup also failed ({fragment.error.code.value})"
        elif fragment.found is False:
            fragment_note = "Fragment has no listing for this handle"
        else:
            fragment_note = "Fragment returned no usable information"
        return ResultSummary(
            status=OverallStatus.UNKNOWN,
            explanation=(
                f"Telegram's public signals are inconclusive ({detail}) and {fragment_note}. "
                "Telegram renders identical bare pages for private-profile users and unclaimed handles, "
                "so neither availability nor ownership can be confirmed publicly."
            ),
        )

    # ------------------------------------------------------------------
    # invalid fast path
    # ------------------------------------------------------------------
    @staticmethod
    def _invalid_response(validation: ValidationResult) -> CheckResponse:
        telegram = TelegramResult(
            checked=False,
            public_url="",
            evidence=["not checked: the username failed local validation, no external request was made"],
        )
        fragment = FragmentResult(
            checked=False,
            evidence=["not checked: the username failed local validation, no external request was made"],
        )
        return CheckResponse(
            success=True,
            username=validation.normalized,
            validation=validation,
            telegram=telegram,
            fragment=fragment,
            result=ResultSummary(
                status=OverallStatus.INVALID,
                explanation=f"Invalid username: {validation.reason}",
            ),
        )

    # ------------------------------------------------------------------
    # detailed report
    # ------------------------------------------------------------------
    async def report_username(self, raw: str) -> ReportResponse:
        check = await self.check_username(raw)
        characteristics: UsernameCharacteristics | None = None
        heuristic: HeuristicScore | None = None
        if check.validation.valid and check.username:
            characteristics = build_characteristics(check.username)
            heuristic = build_heuristic_score(check.username)

        signals = list(check.telegram.evidence) + list(check.fragment.evidence)
        return ReportResponse(
            success=check.success,
            username=check.username,
            validation=check.validation,
            telegram=check.telegram,
            fragment=check.fragment,
            result=check.result,
            characteristics=characteristics,
            heuristic_score=heuristic,
            signals=signals,
            cached=check.cached,
        )

    # ------------------------------------------------------------------
    # bulk
    # ------------------------------------------------------------------
    async def check_bulk(self, request: BulkRequest) -> BulkResponse:
        entries = list(request.usernames)
        # In-flight deduplication by normalized form so duplicates in the same
        # bulk request cause at most one upstream lookup.
        in_flight: dict[str, asyncio.Task[CheckResponse]] = {}
        immediate: dict[int, CheckResponse] = {}
        task_for_index: dict[int, asyncio.Task[CheckResponse]] = {}

        for index, raw in enumerate(entries):
            validation = validate_username(raw)
            if not validation.valid:
                immediate[index] = self._invalid_response(validation)
                continue
            key = validation.normalized or raw
            if key not in in_flight:
                in_flight[key] = asyncio.create_task(self._throttled_check(raw))
            task_for_index[index] = in_flight[key]

        results: list[CheckResponse] = []
        for index in range(len(entries)):
            if index in immediate:
                results.append(immediate[index])
            else:
                results.append(await task_for_index[index])
        in_flight.clear()

        return BulkResponse(success=True, total=len(entries), results=results)

    async def _throttled_check(self, raw: str) -> CheckResponse:
        async with self._bulk_semaphore:
            try:
                return await self.check_username(raw)
            except Exception as exc:  # defensive: one bad item must not break the bulk
                logger.exception("bulk item failed unexpectedly")
                validation = validate_username(raw)
                response = self._invalid_response(validation)
                response.validation.valid = validation.valid
                response.result = ResultSummary(
                    status=OverallStatus.UNKNOWN,
                    explanation=f"internal error while checking: {exc.__class__.__name__}",
                )
                return response


# ---------------------------------------------------------------------------
# characteristics & heuristic scoring
# ---------------------------------------------------------------------------


def build_characteristics(username: str) -> UsernameCharacteristics:
    digits = sum(ch.isdigit() for ch in username)
    underscores = username.count("_")
    alpha = sum(ch.isalpha() for ch in username)

    max_run = 1
    run = 1
    for prev, cur in zip(username, username[1:]):
        run = run + 1 if cur == prev else 1
        max_run = max(max_run, run)

    return UsernameCharacteristics(
        length=len(username),
        digit_count=digits,
        underscore_count=underscores,
        alpha_count=alpha,
        starts_with_letter=username[0].isalpha(),
        ends_with_letter_or_digit=username[-1].isalnum(),
        has_digits=digits > 0,
        has_underscores=underscores > 0,
        only_letters=alpha == len(username),
        max_repeated_char_run=max_run,
        unique_characters=len(set(username)),
    )


def build_heuristic_score(username: str) -> HeuristicScore:
    """Objective-trait heuristic (0-100). NOT a market valuation — short,
    clean usernames merely tend to be in higher demand on marketplaces."""
    score = 50
    notes: list[str] = []

    length = len(username)
    if length == 5:
        score += 20
        notes.append("minimum possible length (5) — short handles are scarce")
    elif length == 6:
        score += 12
        notes.append("very short (6 characters)")
    elif length <= 8:
        score += 6
        notes.append("short (7-8 characters)")
    elif length >= 20:
        score -= 8
        notes.append("very long (20+ characters)")

    if "_" not in username:
        score += 12
        notes.append("contains no underscores")
    else:
        score -= 6
        notes.append(f"contains {username.count('_')} underscore(s)")

    if username.isalpha():
        score += 12
        notes.append("letters only")
    digits = sum(ch.isdigit() for ch in username)
    if digits > 0:
        score -= min(4 * digits, 14)
        notes.append(f"contains {digits} digit(s)")

    if len(set(username)) == len(username):
        notes.append("all characters unique")

    score = max(0, min(100, score))
    return HeuristicScore(score=score, factor_notes=notes)
