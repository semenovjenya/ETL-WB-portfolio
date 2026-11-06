"""Скрипт для получения цен и скидок товаров WB из API list/goods/filter (content-api)."""
import json
import logging
import os
import time
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import requests
from config import Config
from database import PricesDatabase
from wb_api_support import (
    TOKEN_MODE_BASE,
    extract_rate_limit_snapshot,
    resolve_wb_token_mode,
)

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


class PricesFetcher:
    """Выгрузка цен и скидок товаров WB (API content-api list/goods/filter)."""

    def __init__(self):
        Config.validate()
        self.db = PricesDatabase()
        os.makedirs(Config.JSON_OUTPUT_DIR, exist_ok=True)
        self.token_mode = resolve_wb_token_mode(Config.WB_API_TOKEN, Config.WB_API_TOKEN_MODE)
        self.retry_delay_429 = (
            float(Config.BASE_TOKEN_RETRY_DELAY_429)
            if self.token_mode == TOKEN_MODE_BASE
            else float(Config.RETRY_DELAY_429)
        )

    def _get_headers(self) -> Dict[str, str]:
        token = (Config.WB_API_TOKEN or "").strip()
        headers = {"Authorization": token, "Content-Type": "application/json"}
        client_secret = (Config.WB_API_CLIENT_SECRET or "").strip()
        if client_secret:
            headers["X-Client-Secret"] = client_secret
        return headers

    def _retry_wait_for_429(self, resp: requests.Response, attempt: int) -> float:
        snapshot = extract_rate_limit_snapshot(resp.headers)
        if snapshot.wait_hint is not None:
            return snapshot.wait_hint
        return max(self.retry_delay_429, (attempt + 1) * Config.RETRY_DELAY * 2)

    @staticmethod
    def _progress_path() -> Path:
        return Path(Config.PROGRESS_FILE)

    def _load_progress_state(self, snapshot_date: date) -> Optional[dict[str, int]]:
        path = self._progress_path()
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("snapshot_date") != snapshot_date.isoformat():
            return None
        offset = int(payload.get("offset", 0) or 0)
        page = int(payload.get("page", 0) or 0)
        total_items = int(payload.get("total_items", 0) or 0)
        if offset < 0 or page < 0 or total_items < 0:
            return None
        return {"offset": offset, "page": page, "total_items": total_items}

    def _save_progress_state(
        self,
        snapshot_date: date,
        snapshot_hour: datetime,
        *,
        offset: int,
        page: int,
        total_items: int,
    ) -> None:
        path = self._progress_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshot_date": snapshot_date.isoformat(),
            "snapshot_hour": snapshot_hour.isoformat(),
            "offset": offset,
            "page": page,
            "total_items": total_items,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_progress_state(self) -> None:
        path = self._progress_path()
        if path.exists():
            path.unlink()

    def fetch_page(self, offset: int, retry_count: int = None) -> Optional[List[Dict[str, Any]]]:
        """Один запрос к API: товары с ценами (limit=1000, offset)."""
        if retry_count is None:
            retry_count = Config.RETRY_COUNT
        url = Config.WB_API_BASE_URL
        headers = self._get_headers()
        params = {"limit": Config.PRICES_LIMIT, "offset": offset}

        for attempt in range(retry_count):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=120)
                if resp.status_code == 429:
                    rate_limit = extract_rate_limit_snapshot(resp.headers)
                    wait = self._retry_wait_for_429(resp, attempt)
                    logger.warning(
                        "429 Too Many Requests, ожидание %.1f сек... "
                        "(mode=%s, retry=%s, reset=%s, remaining=%s, limit=%s, retry_after=%s)",
                        wait,
                        self.token_mode,
                        rate_limit.retry,
                        rate_limit.reset,
                        rate_limit.remaining,
                        rate_limit.limit,
                        rate_limit.retry_after,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    logger.warning(f"Ожидался объект, получен: {type(data)}")
                    return []
                inner = data.get("data") or {}
                list_goods = inner.get("listGoods") if isinstance(inner, dict) else None
                if not isinstance(list_goods, list):
                    logger.warning("В ответе нет data.listGoods")
                    return []
                logger.info(f"Получено строк цен: {len(list_goods)} (offset={offset})")
                return list_goods
            except requests.exceptions.RequestException as e:
                logger.warning(f"Попытка {attempt + 1}/{retry_count} не удалась: {e}")
                if attempt == retry_count - 1:
                    logger.error(f"Все попытки исчерпаны: {e}")
                    return None
                time.sleep((attempt + 1) * Config.RETRY_DELAY)
        return None

    def save_to_json(
        self,
        items: List[Dict[str, Any]],
        offset: int,
        page: int,
    ) -> str:
        """Сохранить одну страницу в JSON."""
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(
            Config.JSON_OUTPUT_DIR,
            f"prices_p{page}_offset{offset}_{ts}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "offset": offset,
                    "page": page,
                    "total_items": len(items),
                    "timestamp": ts,
                    "data": items,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"Сохранён JSON: {filename} ({len(items)} записей)")
        return filename

    def run(self, snapshot_hour: Optional[datetime] = None) -> None:
        """Полная выгрузка цен с пагинацией по offset."""
        logger.info("Начало выгрузки цен list/goods/filter")

        try:
            self.db.connect()
            self.db.create_tables()
        except Exception as e:
            logger.error(f"Подключение к БД: {e}")
            raise

        try:
            snapshot_hour = resolve_snapshot_hour(snapshot_hour)
            snapshot_date = snapshot_hour.date()
            progress_state = self._load_progress_state(snapshot_date)
            total_items = progress_state["total_items"] if progress_state else 0
            offset = progress_state["offset"] if progress_state else 0
            page = progress_state["page"] if progress_state else 0
            logger.info(
                "Срез цен: date=%s, hour=%s, token_mode=%s, resume_offset=%s, resume_page=%s",
                snapshot_date,
                snapshot_hour.isoformat(),
                self.token_mode,
                offset,
                page,
            )

            while True:
                page += 1
                chunk = self.fetch_page(offset)
                if chunk is None:
                    raise RuntimeError(
                        f"Не удалось получить страницу цен: page={page}, offset={offset}"
                    )
                if not chunk:
                    logger.info("Пустой ответ — все товары выгружены")
                    break

                self.save_to_json(chunk, offset, page)
                count = self.db.upsert_prices(chunk, snapshot_date, snapshot_hour)
                total_items += count
                offset += len(chunk)
                self._save_progress_state(
                    snapshot_date,
                    snapshot_hour,
                    offset=offset,
                    page=page,
                    total_items=total_items,
                )

                logger.info(f"Страница {page}: обработано {len(chunk)} строк, всего за запуск {total_items}")

                if len(chunk) < Config.PRICES_LIMIT:
                    logger.info("Получено меньше limit — конец выгрузки")
                    break

                logger.info(f"Пауза {Config.REQUEST_INTERVAL} сек перед следующим запросом...")
                time.sleep(Config.REQUEST_INTERVAL)

            if total_items == 0:
                raise RuntimeError(
                    "Выгрузка цен завершилась без записей. "
                    "Проверьте WB API token/endpoint и доступность данных."
                )

            self._clear_progress_state()
            logger.info(f"Выгрузка цен завершена. Всего записей: {total_items}")
        finally:
            self.db.close()


def main():
    fetcher = PricesFetcher()
    fetcher.run()


if __name__ == "__main__":
    main()
