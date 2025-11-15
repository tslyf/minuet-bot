import logging
import re
import json
import requests
import time
from datetime import date, datetime
from collections import defaultdict

EMAIL = "EMAIL"
PASSWORD = "PASSWORD"

TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
TELEGRAM_MESSAGE_THREAD_ID = None

TARGETS = [
    # {"teacher_id": 18, "car_id": 17},
    # {"teacher_id": 8, "car_id": 14},
    {"teacher_id": 16, "car_id": 8},  # Юзов
    {"teacher_id": 1, "car_id": 1},  # Сорокин
]
DATE_FROM = date(2025, 8, 27)
DATE_TO = date(2025, 10, 31)
CHECK_INTERVAL_SECONDS = 120

API_BASE_URL = "https://edu.automiet.ru/api/v1"

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s %(asctime)s] %(message)s",
    datefmt="%d.%m.%Y %H:%M:%S",
)


class AuthorizationFailed(Exception):
    """Исключение при ошибке авторизации."""

    pass


class DrivingSchoolAPI:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.student_id = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        })
        self.update_access_token()

        try:
            profile = self.get_profile()
            self.student_id = profile["studentDetails"]["id"]
            logging.info(f"Профиль успешно загружен. Student ID: {self.student_id}")
        except Exception as e:
            logging.error(f"Не удалось получить профиль студента: {e}")
            raise AuthorizationFailed(
                "Не удалось получить профиль студента после авторизации."
            )

    def update_access_token(self):
        logging.info("Обновление токена авторизации...")
        try:
            response = self.session.post(
                f"{API_BASE_URL}/auth/login",
                json={"email": self.email, "password": self.password},
                timeout=10,
            )
            try:
                data = response.json()
            except json.JSONDecodeError:
                raise requests.RequestException(
                    f"Не удалось получить данные от сервера: {response.text}"
                )
            if "meta" in data and "error" in data["meta"]:
                raise AuthorizationFailed(
                    f"Ошибка при обновлении токена: {data['meta']['error']}"
                )
            response.raise_for_status()
            token = data["result"]["token"]
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            logging.info("Токен успешно обновлен.")
        except requests.RequestException as e:
            logging.error(f"Критическая ошибка при обновлении токена: {e}")
            raise AuthorizationFailed from e

    def _call_api(
        self,
        method: str,
        json_payload: dict | None = None,
        request_method: str = "POST",
    ) -> dict:
        url = f"{API_BASE_URL}/{method}"
        try:
            resp = self.session.request(
                request_method, url, json=json_payload, timeout=10
            )
            if resp.status_code in (401, 403):
                logging.warning(
                    "Токен истек или недействителен. Попытка переавторизации..."
                )
                self.update_access_token()
                resp = self.session.request(
                    request_method, url, json=json_payload, timeout=10
                )

            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logging.error(f"Ошибка при вызове API {method}: {e}")
            raise

    def get_profile(self) -> dict:
        return self._call_api("auth/profile", request_method="GET")["result"]

    def get_car_info(self, car_id: int) -> dict:
        return self._call_api(f"car/{car_id}", request_method="GET")["result"]

    def get_available_slots(
        self, car_id: int, teacher_id: int, date_from: date, date_to: date
    ) -> list:
        payload = {
            "carId": car_id,
            "teacherId": teacher_id,
            "dateFrom": datetime.combine(date_from, datetime.min.time()).isoformat()
            + "+03:00",
            "dateTo": datetime.combine(date_to, datetime.min.time()).isoformat()
            + "+03:00",
        }
        logging.info(
            f"Проверка расписания с {date_from.strftime('%d.%m.%Y')} по {date_to.strftime('%d.%m.%Y')}"
        )
        response_data = self._call_api("driving-entry/search", json_payload=payload)
        slots = response_data.get("result", [])
        return [slot for slot in slots if slot.get("isFree") is True]

    def driving_signup(self, driving_id: int) -> bool:
        if not self.student_id:
            logging.error("Невозможно записаться: ID студента не определен.")
            return False

        logging.info(
            f"Попытка записи на занятие с ID: {driving_id} для студента {self.student_id}..."
        )
        try:
            response = self._call_api(
                f"driving-entry/{driving_id}/signup",
                json_payload={"studentId": self.student_id},
            )
            is_success = response.get("result", {}).get("status") == 1
            if is_success:
                logging.info(f"УСПЕШНАЯ ЗАПИСЬ на занятие ID: {driving_id}")
            else:
                logging.warning(
                    f"Не удалось записаться на занятие ID: {driving_id}. Ответ API: {response}"
                )
            return is_success
        except Exception as e:
            logging.error(f"Ошибка при записи на занятие ID {driving_id}: {e}")
            return False


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


def monitor_slots():
    try:
        api = DrivingSchoolAPI(EMAIL, PASSWORD)
        notifier = TelegramNotifier(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_MESSAGE_THREAD_ID
        )
    except AuthorizationFailed as e:
        logging.error(f"Не удалось запустить мониторинг: {e}")
        return

    known_free_slots_ids = set()
    try:
        car_names = {
            target["car_id"]: api.get_car_info(target["car_id"])["name"]
            for target in TARGETS
        }
        logging.info(f"Информация о машинах загружена: {car_names}")
    except Exception as e:
        logging.error(f"Не удалось получить информацию о машинах: {e}")
        return

    logging.info("--- Мониторинг запущен ---")
    is_first_run = True
    while True:
        try:
            all_current_slots = []
            for target in TARGETS:
                teacher_id, car_id = target["teacher_id"], target["car_id"]

                slots_for_target = api.get_available_slots(
                    car_id, teacher_id, DATE_FROM, DATE_TO
                )

                for slot in slots_for_target:
                    slot["car_id"] = car_id

                all_current_slots.extend(slots_for_target)

            current_free_slots_ids = {slot["id"] for slot in all_current_slots}

            if is_first_run:
                known_free_slots_ids = current_free_slots_ids
                logging.info(
                    f"Первоначальная проверка завершена. Найдено слотов: {len(known_free_slots_ids)}"
                )
                is_first_run = False
            else:
                newly_appeared_ids = current_free_slots_ids - known_free_slots_ids
                if newly_appeared_ids:
                    new_slots_data = [
                        slot
                        for slot in all_current_slots
                        if slot["id"] in newly_appeared_ids
                    ]

                    logging.info(
                        f"!!! НАЙДЕНЫ НОВЫЕ СВОБОДНЫЕ СЛОТЫ: {len(newly_appeared_ids)} шт. !!!"
                    )

                    grouped_for_telegram = defaultdict(list)
                    for slot in new_slots_data:
                        slot_time = datetime.fromisoformat(slot["drivingDate"])
                        group_key = (slot["car_id"], slot_time.date())
                        grouped_for_telegram[group_key].append(
                            slot_time.strftime("%H:%M")
                        )

                    for (car_id, day), times in sorted(grouped_for_telegram.items()):
                        times.sort()
                        car_name = notifier.escape_markdown(
                            car_names.get(car_id, f"Машина ID {car_id}")
                        )
                        day_str = notifier.escape_markdown(day.strftime("%d.%m.%Y"))
                        times_str = notifier.escape_markdown(", ".join(times))
                        link = f"[Записаться]({notifier.escape_markdown(f'https://edu.automiet.ru/cars/{car_id}?transmission=0')})"

                        message_text = (
                            f"🚗 *{car_name}*\n\n"
                            f"Доступные для записи занятия:\n\n"
                            f"📅 *Дата:* {day_str}\n"
                            f"⏰ *Время:* {times_str}\n\n"
                            f"{link}"
                        )
                        notifier.send_message(message_text)
                        time.sleep(1)

                    known_free_slots_ids.update(newly_appeared_ids)
                else:
                    logging.info("Новых свободных слотов не найдено.")

            known_free_slots_ids.intersection_update(current_free_slots_ids)

        except Exception as e:
            logging.error(
                f"В главном цикле произошла ошибка: {e}. Мониторинг продолжится через {CHECK_INTERVAL_SECONDS} сек."
            )

        finally:
            logging.info(f"Следующая проверка через {CHECK_INTERVAL_SECONDS} секунд.")
            time.sleep(CHECK_INTERVAL_SECONDS)


def driving_signup(driving_id: int) -> bool:
    api = DrivingSchoolAPI(EMAIL, PASSWORD)
    print(api.get_profile())
    # return api.driving_signup(driving_id)


if __name__ == "__main__":
    print(driving_signup(96535))
    # monitor_slots()
