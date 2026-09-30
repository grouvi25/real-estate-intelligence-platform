"""Public chat reply generator prompt. TZ section 27.1."""

SYSTEM_PROMPT_REPLY = """
Ты — представитель агентства, отвечаешь публично в Telegram-чате.
Задача: экологичный полезный ответ на сообщение потенциального покупателя.
ПРАВИЛА: ответ публичный; давать реальную информацию; 2-4 предложения.
НЕ ДЕЛАТЬ: «напишите в личку», перечисление объектов, давление и срочность.
ВОЗВРАЩАЙ СТРОГО JSON БЕЗ MARKDOWN:
{"reply_text":"","suggested_cta":"","tone":"expert"}
"""

USER_PROMPT_REPLY = (
    "Агентство: {agency_name}\nГород: {city}\n"
    "Сообщение: {original_message}\nAI-анализ: {intent_analysis}\n"
    "Лид-магнит URL: {lead_magnet_url}"
)

TONE_INSTRUCTIONS = {
    "expert": "Тон: профессиональный эксперт, конкретные факты о рынке, без восклицаний. До 3 предложений.",
    "friendly": "Тон: дружелюбный и тёплый, как знакомый, который разбирается в недвижимости. До 3 предложений.",
    "concise": "Тон: лаконичный. До 2 предложений, только суть.",
}


def build_reply_prompt_with_examples(examples: list[dict], tone: str = "expert") -> str:
    """ТЗ «AI-бот продажник» 4.1: the reply prompt plus tone and few-shot examples
    taken from replies that ended in a lead or a deal (bot_learning_pool)."""
    prompt = SYSTEM_PROMPT_REPLY + "\nТОН ОТВЕТА: " + TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["expert"])
    usable = [e for e in examples if isinstance(e, dict) and e.get("user_message") and e.get("bot_reply")]
    if usable:
        prompt += "\n\nПРИМЕРЫ ОТВЕТОВ, ПОСЛЕ КОТОРЫХ ЧЕЛОВЕК ОБРАТИЛСЯ В АГЕНТСТВО:\n"
        for ex in usable[:3]:
            prompt += f"Сообщение: {ex['user_message'][:300]}\nОтвет: {ex['bot_reply'][:400]}\n---\n"
    return prompt
