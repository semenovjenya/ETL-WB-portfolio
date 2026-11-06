"""Скрипт для получения тарифов WB из API common-api (wb-tariffs)."""
import json
import logging
import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import TariffsDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def resolve_snapshot_hour(snapshot_hour: Optional[datetime]) -> datetime:
    if snapshot_hour is None:
        snapshot_hour = datetime.now(MOSCOW_TZ)
    elif snapshot_hour.tzinfo is None:
        snapshot_hour = snapshot_hour.replace(tzinfo=MOSCOW_TZ)
    return snapshot_hour.astimezone(MOSCOW_TZ).replace(minute=0, second=0, microsecond=0)


class TariffsFetcher:
    """Выгрузка тарифов WB (API common-api: commission, box, pallet, return, acceptance)."""

    def __init__(self):
        Config.validate()
        self.db = TariffsDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
        self.base_url = Config.WB_API_BASE_URL.rstrip("/")

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        return {"Authorization": token, "Content-Type": "application/json"}

    def _request(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        retry_count: Optional[int] = None,
    ) -> Optional[Any]:
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = f"{self.base_url}{path}"
        headers = self._get_headers()
        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, params=params or {}, timeout=60)
                if resp.status_code == 429:
                    wait = (attempt + 1) * Config.RETRY_DELAY * 2
                    logger.warning(f"429 Too Many Requests, ожидание {wait} сек...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def _save_json(self, name: str, payload: Any) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(Config.JSON_OUTPUT_DIR, f"tariffs_{name}_{ts}.json")
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранён JSON: {filename}")
        return filename

    def fetch_commission(self, locale: str = "ru") -> Optional[List[Dict[str, Any]]]:
        """GET /api/v1/tariffs/commission."""
        data = self._request("/api/v1/tariffs/commission", params={"locale": locale})
        if data is None:
            return None
        report = data.get("report") if isinstance(data, dict) else None
        if not isinstance(report, list):
            logger.warning("В ответе commission нет report")
            return []
        return report

    def fetch_box(self, tariff_date: date) -> Optional[Dict[str, Any]]:
        """GET /api/v1/tariffs/box?date=YYYY-MM-DD."""
        data = self._request(
            "/api/v1/tariffs/box",
            params={"date": tariff_date.isoformat()},
        )
        if data is None:
            return None
        response = data.get("response") if isinstance(data, dict) else data
        inner = response.get("data") if isinstance(response, dict) else response
        return inner if isinstance(inner, dict) else response

    def fetch_pallet(self, tariff_date: date) -> Optional[Dict[str, Any]]:
        """GET /api/v1/tariffs/pallet?date=YYYY-MM-DD."""
        data = self._request(
            "/api/v1/tariffs/pallet",
            params={"date": tariff_date.isoformat()},
        )
        if data is None:
            return None
        response = data.get("response") if isinstance(data, dict) else data
        inner = response.get("data") if isinstance(response, dict) else response
        return inner if isinstance(inner, dict) else response

    def fetch_return(self, tariff_date: date) -> Optional[Dict[str, Any]]:
        """GET /api/v1/tariffs/return?date=YYYY-MM-DD."""
        data = self._request(
            "/api/v1/tariffs/return",
            params={"date": tariff_date.isoformat()},
        )
        if data is None:
            return None
        response = data.get("response") if isinstance(data, dict) else data
        inner = response.get("data") if isinstance(response, dict) else response
        return inner if isinstance(inner, dict) else response

    def fetch_acceptance(self, warehouse_ids: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """GET /api/tariffs/v1/acceptance/coefficients (опционально warehouseIDs)."""
        params = {}
        if warehouse_ids:
            params["warehouseIDs"] = warehouse_ids
        data = self._request("/api/tariffs/v1/acceptance/coefficients", params=params or None)
        if data is None:
            return None
        if isinstance(data, list):
            return data
        logger.warning("Ожидался массив в acceptance/coefficients")
        return []

    def run(self, snapshot_hour: Optional[datetime] = None) -> None:
        """Полная выгрузка всех тарифов на сегодня."""
        logger.info("Начало выгрузки тарифов WB")
        snapshot_hour = resolve_snapshot_hour(snapshot_hour)
        snapshot_date = snapshot_hour.date()

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        try:
            # 1. Commission (1 req/min)
            report = self.fetch_commission()
            if report is not None:
                self._save_json("commission", {"report": report})
                self.db.upsert_commission(report, snapshot_date, snapshot_hour)
            time.sleep(Config.REQUEST_INTERVAL)

            # 2. Box
            box_data = self.fetch_box(snapshot_date)
            if box_data is not None:
                self._save_json("box", box_data)
                self.db.upsert_box(box_data, snapshot_date, snapshot_hour)
            time.sleep(Config.REQUEST_INTERVAL)

            # 3. Pallet
            pallet_data = self.fetch_pallet(snapshot_date)
            if pallet_data is not None:
                self._save_json("pallet", pallet_data)
                self.db.upsert_pallet(pallet_data, snapshot_date, snapshot_hour)
            time.sleep(Config.REQUEST_INTERVAL)

            # 4. Return
            return_data = self.fetch_return(snapshot_date)
            if return_data is not None:
                self._save_json("return", return_data)
                self.db.upsert_return(return_data, snapshot_date, snapshot_hour)
            time.sleep(Config.REQUEST_INTERVAL)

            # 5. Acceptance coefficients (6 req / 10 sec)
            acceptance_data = self.fetch_acceptance()
            if acceptance_data is not None:
                self._save_json("acceptance_coefficients", acceptance_data)
                self.db.upsert_acceptance(acceptance_data, snapshot_date, snapshot_hour)

            logger.info("Выгрузка тарифов завершена")
        finally:
            self.db.close()


def main():
    fetcher = TariffsFetcher()
    fetcher.run()


if __name__ == "__main__":
    main()
