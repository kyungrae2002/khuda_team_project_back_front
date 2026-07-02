"""Extracts travel-planning slots (destination/date/budget/...) from a parsed
KakaoTalk conversation using OpenAI, with evidence tracking back to the
source ChatMessage.order_index values."""

from typing import Sequence

import openai

from app.models.chat_message import ChatMessage
from app.schemas.slot_extraction import SlotExtractionResult
from app.services.llm_client import LLMCallError, call_structured, default_client

DEFAULT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_RETRIES = 2

_SYSTEM_PROMPT = """당신은 단체 여행 채팅 대화에서 여행 계획에 필요한 신호(슬롯)를 추출하는 전문가입니다.

입력은 order_index가 붙은 카카오톡 대화입니다. 각 줄은 "[순번] 발신자: 메시지" 형식입니다.

추출 대상 필드(field): destination(목적지), date(날짜), budget(예산), headcount(인원),
transport(교통수단), constraint(제약사항), wishlist(먹킷리스트/하고싶은 것).

반드시 지켜야 할 규칙:
1. evidence_message_ids는 모든 슬롯 항목에 반드시 포함해야 하며, 절대 빈 배열이 되어서는 안
   됩니다. 반드시 대화에 실제로 등장한 순번([번호])만 참조하세요.
2. 농담이나 웃음 표현(ㅋㅋ, ㅎㅎ, 반어법 등)이 섞인 발화를 진심으로 오독하지 마세요.
   예: "하와이 가자 ㅋㅋ"는 농담일 가능성이 높습니다. 이런 경우 status를 confirmed로 올리지
   말고 undecided로 두거나, 확신이 전혀 없다면 해당 슬롯을 아예 결과에 포함시키지 마세요.
3. 아무도 명시적으로 말하지 않은 값을 추측해서 채우지 마세요. 대화에 없는 내용을 지어내면
   안 됩니다.
4. 대화 중간에 값이 번복된 경우(예: 처음엔 "부산"이라고 했다가 나중에 "제주"로 바뀜),
   최신 발화의 값을 우선시하되 이전 값도 버리지 말고 같은 field로 별도의 슬롯 항목을 만들어
   함께 포함하세요. 최신 값에는 명확한 status(confirmed 등)를, 이전 값에는 undecided를
   부여해 번복되었음을 나타내세요.
5. 여러 발화자의 말이 섞여 누가 한 말인지, 혹은 값 자체가 서로 충돌해 확정할 수 없는 경우
   status를 conflict로 표시하세요.
6. confidence는 0.0~1.0 사이의 실수로, 추출 확신도를 나타냅니다.

반드시 주어진 JSON 스키마에 맞는 형식으로만 응답하세요."""


class SlotExtractionError(RuntimeError):
    """Raised when slot extraction fails after exhausting all retries."""


def _format_conversation(messages: Sequence[ChatMessage]) -> str:
    lines = [
        f"[{message.order_index}] {message.sender}: {message.text}"
        for message in messages
        if not message.is_media
    ]
    return "\n".join(lines)


class SlotExtractor:
    def __init__(
        self,
        client: openai.OpenAI | None = None,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._client = client or default_client()
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    def extract(self, messages: Sequence[ChatMessage]) -> SlotExtractionResult:
        conversation = _format_conversation(messages)

        try:
            return call_structured(
                self._client,
                model=self._model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=conversation,
                output_model=SlotExtractionResult,
                schema_name="slot_extraction",
                max_tokens=self._max_tokens,
                max_retries=self._max_retries,
                retry_delay_seconds=self._retry_delay_seconds,
            )
        except LLMCallError as exc:
            raise SlotExtractionError(str(exc)) from exc


slot_extractor = SlotExtractor()
