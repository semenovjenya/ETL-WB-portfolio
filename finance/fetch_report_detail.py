"""Скрипт для получения финансовых отчетов из API Wildberries."""
import json
import logging
import os
import time
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import ReportDetailDatabase

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def today_moscow() -> date:
    return datetime.now(MOSCOW_TZ).date()


def build_report_detail_intervals(
    start_date: date,
    end_date: date,
    interval_days: int = Config.INTERVAL_DAYS,
) -> List[Tuple[date, date]]:
    """Разбить диапазон на chunk-окна report_detail длиной до interval_days."""
    intervals: List[Tuple[date, date]] = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=interval_days - 1), end_date)
        intervals.append((chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return intervals


def build_missing_report_detail_intervals(
    start_date: date,
    end_date: date,
    completed_dates: Set[date],
    interval_days: int = Config.INTERVAL_DAYS,
) -> List[Tuple[date, date]]:
    """Вернуть интервалы подряд идущих отсутствующих daily-дат."""
    missing_dates = build_missing_report_detail_dates(start_date, end_date, completed_dates)
    return build_report_detail_intervals_from_dates(
        missing_dates,
        interval_days=interval_days,
    )


def build_missing_report_detail_dates(
    start_date: date,
    end_date: date,
    completed_dates: Set[date],
) -> List[date]:
    """Построить список отсутствующих daily-дат внутри рабочего окна."""
    missing_dates: List[date] = []
    current_date = start_date
    while current_date <= end_date:
        if current_date not in completed_dates:
            missing_dates.append(current_date)
        current_date += timedelta(days=1)
    return missing_dates


def build_report_detail_intervals_from_dates(
    report_dates: List[date],
    interval_days: int = Config.INTERVAL_DAYS,
) -> List[Tuple[date, date]]:
    """Сжать sorted/unsorted daily-даты в интервалы длиной не больше interval_days."""
    if interval_days <= 0:
        raise ValueError("interval_days must be positive")

    intervals: List[Tuple[date, date]] = []
    current_start: Optional[date] = None
    current_end: Optional[date] = None

    for report_date in sorted(set(report_dates)):
        if current_start is None or current_end is None:
            current_start = current_end = report_date
            continue

        is_next_day = report_date == current_end + timedelta(days=1)
        current_length = (current_end - current_start).days + 1
        if is_next_day and current_length < interval_days:
            current_end = report_date
            continue

        intervals.append((current_start, current_end))
        current_start = current_end = report_date

    if current_start is not None and current_end is not None:
        intervals.append((current_start, current_end))

    return intervals


def iter_report_detail_dates(start_date: date, end_date: date) -> List[date]:
    """Вернуть все daily-даты в интервале включительно."""
    return build_missing_report_detail_dates(start_date, end_date, set())


def get_default_report_detail_window(
    today: date,
    rolling_window_days: int = Config.ROLLING_WINDOW_DAYS,
) -> Tuple[date, date]:
    """Вернуть дефолтное окно report_detail: последние rolling_window_days до вчера."""
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=rolling_window_days - 1)
    floor_start = datetime.strptime(Config.START_DATE, "%Y-%m-%d").date()
    return max(start_date, floor_start), end_date


class ReportDetailFetcher:
    """Класс для получения данных финансовых отчетов из API Wildberries."""
    
    def __init__(self):
        """Инициализация класса."""
        Config.validate()
        self.db = ReportDetailDatabase()
        
        # Создаем директорию для JSON файлов
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
    
    def load_progress(self) -> Optional[date]:
        """Загрузка прогресса из БД/таблицы/файла с приоритетом на фактически загруженные данные."""
        progress_candidates: List[date] = []
        last_loaded_date: Optional[date] = None
        already_connected = self.db.conn is not None and not getattr(self.db.conn, "closed", False)

        try:
            if not already_connected:
                self.db.connect()
            last_progress_date = self.db.get_last_processed_date()
            if last_progress_date:
                progress_candidates.append(last_progress_date)

            last_loaded_date = self.db.get_last_loaded_date()
            if last_loaded_date:
                progress_candidates.append(last_loaded_date)
        except Exception as e:
            logger.warning(f"Не удалось загрузить прогресс из БД/таблицы: {e}")
        finally:
            if not already_connected and self.db.conn:
                self.db.close()

        if os.path.exists(Config.PROGRESS_FILE):
            try:
                with open(Config.PROGRESS_FILE, "r", encoding="utf-8") as f:
                    progress_data = json.load(f)
                    last_date_str = progress_data.get("last_processed_date")
                    if last_date_str:
                        last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                        progress_candidates.append(last_date)
            except (json.JSONDecodeError, IOError, ValueError) as e:
                logger.warning(f"Ошибка при загрузке прогресса из файла: {e}")

        if last_loaded_date is not None:
            freshest_progress = max(progress_candidates) if progress_candidates else last_loaded_date
            safe_progress_date = min(freshest_progress, last_loaded_date)
            if progress_candidates and safe_progress_date != freshest_progress:
                logger.warning(
                    "Прогресс опережает фактически загруженные данные: "
                    "used=%s, candidates=%s",
                    safe_progress_date,
                    sorted(progress_candidates),
                )
            logger.info(f"Выбрана безопасная дата прогресса по загруженным данным: {safe_progress_date}")
            return safe_progress_date

        if progress_candidates:
            freshest_date = max(progress_candidates)
            logger.warning(
                "Фактически загруженные данные не найдены, используется только progress=%s",
                freshest_date,
            )
            return freshest_date

        logger.info("Прогресс не найден, будет использована начальная дата")
        return None
    
    def save_progress(self, processed_date: date) -> None:
        """Сохранение прогресса в БД и файл."""
        # Сохраняем в БД
        try:
            if not self.db.conn:
                self.db.connect()
            self.db.update_progress(processed_date)
        except Exception as e:
            logger.error(f"Ошибка при сохранении прогресса в БД: {e}")
            raise
        
        # Сохраняем в файл
        try:
            progress_data = {
                "last_processed_date": processed_date.strftime("%Y-%m-%d"),
                "updated_at": datetime.now().isoformat()
            }
            with open(Config.PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Прогресс сохранен в файл: {processed_date}")
        except IOError as e:
            logger.error(f"Ошибка при сохранении прогресса в файл: {e}")
            # Не прерываем выполнение, если не удалось сохранить в файл

    def save_progress_range(self, start_date: date, end_date: date) -> None:
        """Сохранить progress для каждой daily-даты успешного интервала."""
        processed_dates = iter_report_detail_dates(start_date, end_date)
        if not processed_dates:
            return

        try:
            if not self.db.conn:
                self.db.connect()
            self.db.update_progress_dates(processed_dates)
        except Exception as e:
            logger.error(f"Ошибка при сохранении диапазона прогресса в БД: {e}")
            raise

        try:
            progress_data = {
                "last_processed_date": end_date.strftime("%Y-%m-%d"),
                "updated_at": datetime.now().isoformat()
            }
            with open(Config.PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
            logger.info("Прогресс сохранен для диапазона: %s — %s", start_date, end_date)
        except IOError as e:
            logger.error(f"Ошибка при сохранении progress.json для диапазона: {e}")

    @staticmethod
    def _max_loaded_date_from_batch(report_data: List[Dict[str, Any]], fallback_date: date) -> date:
        """Определяет максимальную фактически загруженную дату в батче API."""
        max_loaded = fallback_date
        for item in report_data:
            for raw in (
                item.get("sale_dt"),
                item.get("saleDt"),
                item.get("date_to"),
                item.get("dateTo"),
            ):
                if not raw:
                    continue
                try:
                    loaded_date = datetime.strptime(str(raw).split("T")[0], "%Y-%m-%d").date()
                except ValueError:
                    continue
                if loaded_date > max_loaded:
                    max_loaded = loaded_date
        return max_loaded
    
    def _get_headers(self) -> Dict[str, str]:
        """Получение заголовков для API запросов."""
        token = Config.WB_API_TOKEN.strip() if Config.WB_API_TOKEN else ""
        return {
            "Authorization": token,
            "Content-Type": "application/json"
        }
    
    def fetch_report_for_period(
        self, date_from: date, date_to: date, retry_count: int = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Получение отчета за период из API (интервал до INTERVAL_DAYS дней)."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT

        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")
        payload = {
            "dateFrom": date_from_str,
            "dateTo": date_to_str,
            "limit": Config.API_LIMIT,
            "period": Config.WB_REPORT_PERIOD,
        }

        logger.info(f"Запрос отчета за период {date_from_str} — {date_to_str}")
        
        # API reportDetailByPeriod принимает только GET (документация WB)
        for attempt in range(retry_count):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=payload,
                    timeout=120
                )
                
                if response.status_code == 429:
                    # Too Many Requests - ждем дольше
                    wait_time = (attempt + 1) * Config.RETRY_DELAY * 2
                    logger.warning(
                        f"Получен 429 (Too Many Requests), попытка {attempt + 1}/{retry_count}. "
                        f"Ожидание {wait_time} секунд..."
                    )
                    time.sleep(wait_time)
                    continue

                if response.status_code == 204:
                    logger.info(
                        "WB API вернул 204 No Content за период %s — %s "
                        "(daily-режим, данных нет)",
                        date_from_str,
                        date_to_str,
                    )
                    return []
                
                if response.status_code != 200:
                    logger.warning(f"Ответ API: {response.status_code} - {response.text[:500]}")
                
                response.raise_for_status()
                data = response.json()
                
                # API может возвращать данные в разных форматах
                if isinstance(data, list):
                    report_items = data
                elif isinstance(data, dict):
                    # Проверяем различные возможные ключи
                    report_items = (
                        data.get("data", []) or
                        data.get("report", []) or
                        data.get("items", []) or
                        []
                    )
                else:
                    logger.error(f"Неожиданный тип данных от API: {type(data)}")
                    return None

                logger.info(
                    f"За период {date_from_str} — {date_to_str} за раз выгружено строк: {len(report_items)}"
                )
                return report_items

            except requests.exceptions.HTTPError as e:
                error_detail = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = e.response.text
                        logger.warning(
                            f"Попытка {attempt + 1}/{retry_count} не удалась: "
                            f"{e.response.status_code} - {error_detail[:200]}"
                        )
                    except:
                        logger.warning(
                            f"Попытка {attempt + 1}/{retry_count} не удалась: {e}"
                        )
                else:
                    logger.warning(
                        f"Попытка {attempt + 1}/{retry_count} не удалась: {e}"
                    )
                
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки запроса исчерпаны: {error_detail}")
                    return None
                
                # Ожидание перед повтором
                wait_time = (attempt + 1) * Config.RETRY_DELAY
                logger.info(f"Ожидание {wait_time} секунд перед повтором...")
                time.sleep(wait_time)
                continue
                
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Попытка {attempt + 1}/{retry_count} не удалась: {e}"
                )
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки запроса исчерпаны: {e}")
                    return None
                
                wait_time = (attempt + 1) * Config.RETRY_DELAY
                time.sleep(wait_time)
                continue
        
        return None
    
    def save_to_json(
        self,
        report_data: List[Dict[str, Any]],
        date_from: date,
        date_to: Optional[date] = None,
    ) -> str:
        """Сохранение данных в JSON файл (один день или период)."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        if date_to is None or date_from == date_to:
            name_part = date_from.strftime("%Y-%m-%d")
        else:
            name_part = f"{date_from.strftime('%Y-%m-%d')}_{date_to.strftime('%Y-%m-%d')}"
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"report_detail_{name_part}_{timestamp}.json"
        )
        period_label = f"{date_from}" if date_to is None or date_from == date_to else f"{date_from} — {date_to}"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "date_from": date_from.strftime("%Y-%m-%d"),
                        "date_to": (date_to or date_from).strftime("%Y-%m-%d"),
                        "timestamp": timestamp,
                        "total_items": len(report_data),
                        "data": report_data,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info(f"Данные сохранены в JSON: {filename} ({len(report_data)} записей за {period_label})")
            return filename
        except IOError as e:
            logger.error(f"Ошибка при сохранении JSON: {e}")
            raise
    
    def process_intervals(self, intervals: List[Tuple[date, date]]) -> Dict[str, Any]:
        """Обработка заданного списка interval windows для report_detail."""
        results = {
            "processed": 0,
            "failed": 0,
            "total_items": 0,
            "last_successful_date": None,
        }

        total_intervals = len(intervals)
        for index, (chunk_start, chunk_end) in enumerate(intervals, start=1):
            logger.info(
                "Обработка интервала %s/%s: %s — %s (%s дн.)",
                index,
                total_intervals,
                chunk_start,
                chunk_end,
                Config.INTERVAL_DAYS,
            )

            report_data = self.fetch_report_for_period(chunk_start, chunk_end)
            if report_data is None:
                logger.error(f"Не удалось получить данные за период {chunk_start} — {chunk_end}")
                results["failed"] += 1
                continue

            try:
                self.save_to_json(report_data, chunk_start, chunk_end)
            except Exception as e:
                logger.error(f"Ошибка при сохранении JSON для периода {chunk_start} — {chunk_end}: {e}")

            try:
                if not self.db.conn:
                    self.db.connect()
                items_count = self.db.upsert_report_data(report_data, chunk_start)
                results["total_items"] += items_count
            except Exception as e:
                logger.error(f"Ошибка при сохранении в БД для периода {chunk_start} — {chunk_end}: {e}")
                results["failed"] += 1
                continue

            progress_date = chunk_end
            if not report_data:
                safe_empty_until = today_moscow() - timedelta(days=2)
                progress_date = min(chunk_end, safe_empty_until)
                logger.info(
                    "За интервал %s — %s нет строк, пустые daily-даты подтверждаем только до %s",
                    chunk_start,
                    chunk_end,
                    progress_date,
                )

            if progress_date >= chunk_start:
                self.save_progress_range(chunk_start, progress_date)
            else:
                logger.warning(
                    "Интервал %s — %s вернул пустой ответ слишком рано; progress не обновлён",
                    chunk_start,
                    chunk_end,
                )
                results["failed"] += 1
                continue
            results["processed"] += 1
            results["last_successful_date"] = progress_date
            logger.info(
                "Успешно обработан интервал %s — %s: выгружено %s строк, "
                "в БД записано %s, подтвержденная дата прогресса %s",
                chunk_start,
                chunk_end,
                len(report_data),
                items_count,
                progress_date,
            )

            if index < total_intervals:
                logger.info(f"Ожидание {Config.REQUEST_INTERVAL} сек. перед следующим запросом...")
                time.sleep(Config.REQUEST_INTERVAL)

        return results

    def process_date_range(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Обработка диапазона дат интервалами по INTERVAL_DAYS дней."""
        return self.process_intervals(
            build_report_detail_intervals(
                start_date,
                end_date,
                interval_days=Config.INTERVAL_DAYS,
            )
        )
    
    def run(self, start_date: Optional[date] = None, end_date: Optional[date] = None) -> None:
        """Основной метод для запуска процесса получения отчетов."""
        logger.info("Начало получения финансовых отчетов из API Wildberries")
        
        db_connected = False
        try:
            # Подключаемся к базе данных
            try:
                self.db.connect()
                self.db.create_tables()
                db_connected = True
                logger.info("Подключение к PostgreSQL установлено")
            except Exception as e:
                logger.error(
                    f"Не удалось подключиться к PostgreSQL: {e}. "
                    "Работа невозможна без подключения к БД."
                )
                raise
            
            explicit_range = start_date is not None or end_date is not None

            # Определяем диапазон дат
            if start_date is None and explicit_range:
                # Загружаем прогресс или используем начальную дату
                last_processed = self.load_progress()
                if last_processed:
                    start_date = last_processed + timedelta(days=1)
                    logger.info(f"Продолжение с даты: {start_date}")
                else:
                    start_date = datetime.strptime(Config.START_DATE, "%Y-%m-%d").date()
                    logger.info(f"Начало с начальной даты: {start_date}")
            elif start_date is None:
                start_date, computed_end_date = get_default_report_detail_window(today_moscow())
                if end_date is None:
                    end_date = computed_end_date
                logger.info(
                    "Дефолтный режим report_detail: проверяем пропущенные интервалы в rolling window %s дней: %s — %s",
                    Config.ROLLING_WINDOW_DAYS,
                    start_date,
                    end_date,
                )
            
            if end_date is None:
                # По умолчанию до вчерашнего дня (данные за сегодня могут быть неполными)
                end_date = today_moscow() - timedelta(days=1)
            
            logger.info(f"Диапазон дат для обработки: {start_date} - {end_date}")
            
            if start_date > end_date:
                logger.info("Нет новых дат для обработки")
                return

            if not explicit_range:
                completed_dates = self.db.get_completed_report_dates(
                    start_date,
                    end_date,
                )
                missing_intervals = build_missing_report_detail_intervals(
                    start_date,
                    end_date,
                    completed_dates,
                    interval_days=Config.INTERVAL_DAYS,
                )
                logger.info(
                    "Целевое окно report_detail: %s — %s, завершённых дат: %s, пропущено интервалов: %s",
                    start_date,
                    end_date,
                    len(completed_dates),
                    len(missing_intervals),
                )
                if not missing_intervals:
                    logger.info("Пропущенных интервалов report_detail не найдено")
                    return

                logger.info(
                    "Будут дозагружены интервалы report_detail: %s",
                    ", ".join(
                        f"{chunk_start} — {chunk_end}"
                        for chunk_start, chunk_end in missing_intervals[:10]
                    ) + (" ..." if len(missing_intervals) > 10 else ""),
                )
                results = self.process_intervals(missing_intervals)
            else:
                # Для ручного диапазона сохраняем прежнее поведение: пройти сплошным окном.
                results = self.process_date_range(start_date, end_date)
            
            logger.info("=" * 50)
            logger.info("Результаты обработки:")
            logger.info(f"  Обработано дат: {results['processed']}")
            logger.info(f"  Ошибок: {results['failed']}")
            logger.info(f"  Всего записей: {results['total_items']}")
            if results['last_successful_date']:
                logger.info(f"  Последняя успешная дата: {results['last_successful_date']}")
            logger.info("=" * 50)

            if results["failed"] > 0:
                raise RuntimeError(
                    "Получение финансовых отчетов завершилось с ошибками: "
                    f"failed={results['failed']}, processed={results['processed']}, "
                    f"total_items={results['total_items']}"
                )

            if results["processed"] == 0:
                raise RuntimeError(
                    "Получение финансовых отчетов не обработало ни одного интервала "
                    f"(processed={results['processed']}, total_items={results['total_items']})"
                )
            
            logger.info("Процесс завершен успешно")
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            raise
        finally:
            if db_connected:
                self.db.close()


def main():
    """Точка входа в скрипт."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Получение финансовых отчетов из API Wildberries"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Дата начала (формат: YYYY-MM-DD). По умолчанию: последняя обработанная дата + 1"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="Дата окончания (формат: YYYY-MM-DD). По умолчанию: вчера"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Полная перезагрузка с начальной даты (игнорирует прогресс)"
    )
    
    args = parser.parse_args()
    
    fetcher = ReportDetailFetcher()
    
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    
    if args.full:
        start_date = datetime.strptime(Config.START_DATE, "%Y-%m-%d").date()
        logger.info("Режим полной перезагрузки")
    
    fetcher.run(start_date=start_date, end_date=end_date)


if __name__ == "__main__":
    main()
