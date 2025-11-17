import logging
import re
import time

import requests


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str | int, thread_id: int | None):
        self.token = token
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    @staticmethod
    def escape_markdown(text: str) -> str:
        escape_chars = r"[_*\[\]()~`>#\+\-=|{}.!]"
        return re.sub(f"({escape_chars})", r"\\\1", text)

    def send_message(self, text: str):
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        if self.thread_id:
            payload["message_thread_id"] = self.thread_id

        last_error = None
        for attempt in range(5):
            try:
                response = requests.post(self.api_url, json=payload, timeout=10)
                response.raise_for_status()
                logging.info(
                    f"Уведомление успешно отправлено в чат {self.chat_id}/{self.thread_id}."
                )
                return
            except requests.RequestException as e:
                last_error = e
                logging.error(
                    f"Ошибка при отправке уведомления (попытка {attempt + 1}/5): {e}"
                )
                time.sleep(3)
        logging.error(
            f"Не удалось отправить уведомление после 5 попыток. Последняя ошибка: {last_error}"
        )
