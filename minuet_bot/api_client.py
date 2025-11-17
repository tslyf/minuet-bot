import json
import logging
from datetime import date, datetime

import requests


class AuthorizationFailed(Exception):
    """Исключение при ошибке авторизации."""

    pass


class DrivingSchoolAPI:
    def __init__(self, email: str, password: str, base_url: str):
        self.email = email
        self.password = password
        self.student_id = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        })
        self.base_url = base_url
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
                f"{self.base_url}/auth/login",
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
            logging.exception("Критическая ошибка при обновлении токена")
            raise AuthorizationFailed from e

    def _call_api(
        self,
        method: str,
        json_payload: dict | None = None,
        request_method: str = "POST",
    ) -> dict:
        url = f"{self.base_url}/{method}"
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

        except requests.RequestException:
            logging.exception(f"Ошибка при вызове API {method}")
            raise

    def get_profile(self) -> dict:
        """Получает данные профиля пользователя."""
        return self._call_api("auth/profile", request_method="GET")["result"]

    def get_car_info(self, car_id: int) -> dict:
        """Получает информацию о машине и инструкторе."""
        return self._call_api(f"car/{car_id}", request_method="GET")["result"]

    def get_available_slots(
        self, car_id: int, teacher_id: int, date_from: date, date_to: date
    ) -> list:
        """Получает список свободных слотов для записи."""
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
        """Выполняет запись на занятие по его ID."""
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

        except Exception:
            logging.exception(f"Ошибка при записи на занятие ID {driving_id}")
            return False
