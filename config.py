from datetime import date
from typing import TypedDict

from dotenv import load_dotenv
from pydantic import EmailStr, Field, HttpUrl
from pydantic_settings import BaseSettings


class TargetConfig(TypedDict):
    teacher_id: int
    car_id: int


class Settings(BaseSettings, env_parse_none_str="None"):
    EMAIL: EmailStr
    PASSWORD: str = Field(min_length=1)
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    TELEGRAM_MESSAGE_THREAD_ID: int | None = None

    API_BASE_URL: HttpUrl = HttpUrl("https://edu.automiet.ru/api/v1")
    CHECK_INTERVAL_SECONDS: int = 120

    TARGETS: list[TargetConfig] = [
        {"teacher_id": 16, "car_id": 8},  # Юзов
        {"teacher_id": 1, "car_id": 1},  # Сорокин
    ]

    DATE_FROM: date = date(2025, 8, 27)
    DATE_TO: date = date(2025, 10, 31)


load_dotenv()
settings = Settings()  # type: ignore
