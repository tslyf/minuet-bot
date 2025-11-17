import logging
import time
from collections import defaultdict
from datetime import datetime

from .api_client import AuthorizationFailed, DrivingSchoolAPI
from .config import settings
from .notifier import TelegramNotifier


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s %(asctime)s] %(message)s",
        datefmt="%d.%m.%Y %H:%M:%S",
    )


def run_monitoring():
    try:
        api = DrivingSchoolAPI(
            email=settings.EMAIL,
            password=settings.PASSWORD,
            base_url=str(settings.API_BASE_URL),
        )

        notifier = TelegramNotifier(
            token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            thread_id=settings.TELEGRAM_MESSAGE_THREAD_ID,
        )

    except AuthorizationFailed:
        logging.critical("Ошибка авторизации при старте", exc_info=True)
        return

    except Exception:
        logging.critical("Не удалось инициализировать компоненты", exc_info=True)
        return

    known_free_slots_ids = set()
    car_names = {}
    car_ids = {target["car_id"] for target in settings.TARGETS}

    try:
        for car_id in car_ids:
            info = api.get_car_info(car_id)
            car_names[car_id] = info.get("name", f"Unknown Car {car_id}")
        logging.info(f"Информация о машинах загружена: {car_names}")

    except Exception:
        logging.exception("Не удалось получить информацию о машинах")

    logging.info(
        f"--- Мониторинг запущен (Интервал: {settings.CHECK_INTERVAL_SECONDS} сек) ---"
    )
    is_first_run = True

    while True:
        try:
            all_current_slots = []

            for target in settings.TARGETS:
                teacher_id = target["teacher_id"]
                car_id = target["car_id"]

                try:
                    slots_for_target = api.get_available_slots(
                        car_id=car_id,
                        teacher_id=teacher_id,
                        date_from=settings.DATE_FROM,
                        date_to=settings.DATE_TO,
                    )

                    for slot in slots_for_target:
                        slot["_car_id"] = car_id

                    all_current_slots.extend(slots_for_target)

                except Exception:
                    logging.exception(
                        f"Ошибка при получении слотов (T:{teacher_id}/C:{car_id})"
                    )
                    time.sleep(1)

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
                    logging.info(
                        f"!!! НАЙДЕНЫ НОВЫЕ СВОБОДНЫЕ СЛОТЫ: {len(newly_appeared_ids)} шт. !!!"
                    )

                    new_slots_data = [
                        slot
                        for slot in all_current_slots
                        if slot["id"] in newly_appeared_ids
                    ]

                    # { (car_id, date): [time1, time2] }
                    grouped_for_telegram = defaultdict(list)
                    for slot in new_slots_data:
                        slot_dt = datetime.fromisoformat(slot["drivingDate"])
                        group_key = (slot["_car_id"], slot_dt.date())
                        grouped_for_telegram[group_key].append(
                            slot_dt.strftime("%H:%M")
                        )

                    for (g_car_id, g_date), times_list in sorted(
                        grouped_for_telegram.items()
                    ):
                        times_list.sort()

                        safe_car_name = notifier.escape_markdown(
                            car_names.get(g_car_id, f"Машина {g_car_id}")
                        )
                        safe_date = notifier.escape_markdown(
                            g_date.strftime("%d.%m.%Y")
                        )
                        safe_times = notifier.escape_markdown(", ".join(times_list))

                        safe_url = notifier.escape_markdown(
                            f"https://edu.automiet.ru/cars/{g_car_id}?transmission=0"
                        )
                        link_text = f"[Записаться]({safe_url})"

                        message_text = (
                            f"🚗 *{safe_car_name}*\n\n"
                            f"Доступные для записи занятия:\n\n"
                            f"📅 *Дата:* {safe_date}\n"
                            f"⏰ *Время:* {safe_times}\n\n"
                            f"{link_text}"
                        )

                        notifier.send_message(message_text)
                        time.sleep(1)

                    known_free_slots_ids.update(newly_appeared_ids)
                else:
                    logging.info("Новых свободных слотов не найдено.")

            known_free_slots_ids.intersection_update(current_free_slots_ids)

        except KeyboardInterrupt:
            logging.info("Остановка мониторинга пользователем.")
            break

        except Exception:
            logging.exception(
                "Критическая ошибка в цикле мониторинга. "
                f"Повтор через {settings.CHECK_INTERVAL_SECONDS} сек."
            )

        time.sleep(settings.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    setup_logging()
    run_monitoring()
