"""Модуль для работы с PostgreSQL для финансовых отчетов."""
import logging
import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Set
import psycopg2
from psycopg2.extras import execute_values
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config import Config
from wb_schemas import execute_ddl_bundle, execute_sql, executemany_sql, rewrite_reports_sql

logger = logging.getLogger(__name__)


class ReportDetailDatabase:
    """Класс для работы с базой данных PostgreSQL для финансовых отчетов."""
    
    def __init__(self):
        """Инициализация подключения к базе данных."""
        self.conn = None
        self.cursor = None
    
    def connect(self) -> None:
        """Подключение к базе данных."""
        try:
            self.conn = psycopg2.connect(Config.get_db_connection_string())
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            logger.info("Успешное подключение к базе данных PostgreSQL")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise
    
    def close(self) -> None:
        """Закрытие подключения к базе данных."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Подключение к базе данных закрыто")
    
    def create_tables(self) -> None:
        """Создание таблиц в базе данных."""
        try:
            execute_ddl_bundle(self.cursor, "schema_report_detail.sql")
            logger.info("Таблицы успешно созданы или уже существуют")
        except FileNotFoundError:
            logger.warning("Файл schema_report_detail.sql не найден, создание таблиц пропущено")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при создании таблиц: {e}")
            raise
    
    def get_last_processed_date(self) -> Optional[date]:
        """Получение последней обработанной даты из БД."""
        try:
            query = """
                SELECT last_processed_date 
                FROM reports.wb_report_detail_progress 
                ORDER BY last_processed_date DESC 
                LIMIT 1
            """
            execute_sql(self.cursor, query)
            result = self.cursor.fetchone()
            
            if result:
                last_date = result[0]
                logger.info(f"Последняя обработанная дата из БД: {last_date}")
                return last_date
            else:
                logger.info("В БД нет записей о прогрессе")
                return None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при получении последней обработанной даты: {e}")
            return None

    def get_last_loaded_date(self) -> Optional[date]:
        """Получение максимальной даты из уже загруженных данных отчета."""
        try:
            query = "SELECT MAX(date_to) FROM reports.wb_report_detail_daily"
            execute_sql(self.cursor, query)
            result = self.cursor.fetchone()
            if result and result[0]:
                last_date = result[0]
                logger.info(f"Последняя дата в wb_report_detail_daily: {last_date}")
                return last_date
            logger.info("В wb_report_detail_daily нет записей")
            return None
        except psycopg2.Error as e:
            logger.error(f"Ошибка при получении max(date_to) из wb_report_detail_daily: {e}")
            return None

    def get_completed_interval_end_dates(self, start_date: date, end_date: date) -> Set[date]:
        """
        Вернуть множество завершённых report_detail дат внутри диапазона.

        Источники completion:
        - фактически загруженные строки wb_report_detail_daily (distinct date_to).
        - progress-таблица wb_report_detail_progress только для пустых дней,
          подтверждённых не раньше чем через 2 московских дня после отчётной даты.
        """
        completed_dates: Set[date] = set()

        try:
            query = """
                SELECT last_processed_date
                FROM reports.wb_report_detail_progress
                WHERE last_processed_date BETWEEN %s AND %s
                  AND (updated_at AT TIME ZONE 'Europe/Moscow')::date >= last_processed_date + 2
            """
            execute_sql(self.cursor, query, (start_date, end_date))
            completed_dates.update(
                row[0] for row in self.cursor.fetchall() if row and row[0] is not None
            )
        except psycopg2.Error as e:
            logger.warning(
                "Ошибка при чтении progress-дат для report_detail: %s",
                e,
            )

        try:
            query = """
                SELECT DISTINCT date_to
                FROM reports.wb_report_detail_daily
                WHERE date_to BETWEEN %s AND %s
            """
            execute_sql(self.cursor, query, (start_date, end_date))
            completed_dates.update(
                row[0] for row in self.cursor.fetchall() if row and row[0] is not None
            )
        except psycopg2.Error as e:
            logger.warning(
                "Ошибка при чтении фактически загруженных interval end dates для report_detail: %s",
                e,
            )

        logger.info(
            "Найдено завершённых дат report_detail за %s — %s: %s",
            start_date,
            end_date,
            len(completed_dates),
        )
        return completed_dates

    def get_completed_report_dates(self, start_date: date, end_date: date) -> Set[date]:
        """
        Вернуть множество завершённых daily-дат внутри диапазона.

        Дата считается завершённой, если она есть в фактических данных date_to
        или явно отмечена в progress с задержкой. Progress закрывает только
        дни, где WB API вернул успешный пустой ответ уже после периода
        возможной задержки генерации daily-отчёта.
        """
        return self.get_completed_interval_end_dates(start_date, end_date)
    
    def update_progress(self, processed_date: date) -> None:
        """Обновление прогресса в БД."""
        try:
            query = """
                INSERT INTO reports.wb_report_detail_progress (last_processed_date, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                ON CONFLICT (last_processed_date) 
                DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """
            execute_sql(self.cursor, query, (processed_date,))
            logger.info(f"Прогресс обновлен в БД: {processed_date}")
        except psycopg2.Error as e:
            logger.error(f"Ошибка при обновлении прогресса: {e}")
            raise

    def update_progress_dates(self, processed_dates: List[date]) -> None:
        """Обновление progress сразу для набора daily-дат."""
        if not processed_dates:
            return
        try:
            query = """
                INSERT INTO reports.wb_report_detail_progress (last_processed_date, updated_at)
                VALUES (%s, CURRENT_TIMESTAMP)
                ON CONFLICT (last_processed_date)
                DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """
            executemany_sql(self.cursor, query, [(processed_date,) for processed_date in processed_dates])
            logger.info(
                "Прогресс обновлен в БД для %s дат: %s — %s",
                len(processed_dates),
                min(processed_dates),
                max(processed_dates),
            )
        except psycopg2.Error as e:
            logger.error(f"Ошибка при массовом обновлении прогресса: {e}")
            raise
    
    def parse_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Парсинг даты из различных форматов."""
        if not date_str:
            return None
        try:
            # Пробуем разные форматы
            for fmt in [
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d",
                "%Y-%m-%d %H:%M:%S"
            ]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            logger.warning(f"Не удалось распарсить дату: {date_str}")
            return None
        except Exception as e:
            logger.warning(f"Ошибка парсинга даты {date_str}: {e}")
            return None
    
    def parse_date(self, date_str: Optional[str]) -> Optional[date]:
        """Парсинг даты без времени."""
        if not date_str:
            return None
        try:
            for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    dt = datetime.strptime(date_str.split('T')[0], "%Y-%m-%d")
                    return dt.date()
                except ValueError:
                    continue
            return None
        except Exception as e:
            logger.warning(f"Ошибка парсинга даты {date_str}: {e}")
            return None
    
    @staticmethod
    def _get_any(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """Берёт значение по первому из ключей (snake_case или camelCase от API WB)."""
        for k in keys:
            if k in item:
                return item[k]
        return default

    @staticmethod
    def _deduplicate_valid_data(valid_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Убирает дубли по rrd_id внутри батча, оставляя последнюю запись."""
        deduped_by_rrd_id: Dict[Any, Dict[str, Any]] = {}
        for item in valid_data:
            deduped_by_rrd_id[item["rrd_id"]] = item

        return list(deduped_by_rrd_id.values())

    def normalize_report_data(self, report_item: Dict[str, Any], report_date: date) -> Dict[str, Any]:
        """Нормализация данных детального отчета для вставки в БД."""
        get_ = lambda *keys, default=None: self._get_any(report_item, *keys, default=default)
        # Парсим даты (API может отдавать dateFrom/dateTo в camelCase)
        date_from = self.parse_date(get_("date_from", "dateFrom"))
        date_to = self.parse_date(get_("date_to", "dateTo"))
        create_dt = self.parse_datetime(get_("create_dt", "createDt"))
        order_dt = self.parse_datetime(get_("order_dt", "orderDt"))
        sale_dt = self.parse_datetime(get_("sale_dt", "saleDt"))
        rr_dt = self.parse_date(get_("rr_dt", "rrDt"))
        fix_tariff_date_from = self.parse_date(get_("fix_tariff_date_from", "fixTariffDateFrom"))
        fix_tariff_date_to = self.parse_date(get_("fix_tariff_date_to", "fixTariffDateTo"))

        rrd_id = get_("rrd_id", "rrdId")
        srid_raw = get_("srid")
        srid = (srid_raw or "").strip() or None

        normalized = {
            # Идентификаторы
            "rrd_id": rrd_id,
            "realizationreport_id": get_("realizationreport_id", "realizationreportId"),
            "srid": srid,

            # Даты периода отчета
            "date_from": date_from or report_date,
            "date_to": date_to or report_date,
            "create_dt": create_dt,

            # Валюта и контракт
            "currency_name": get_("currency_name", "currencyName"),
            "suppliercontract_code": get_("suppliercontract_code", "suppliercontractCode"),

            # Товар
            "gi_id": get_("gi_id", "giId"),
            "nm_id": get_("nm_id", "nmId"),
            "subject_name": get_("subject_name", "subjectName"),
            "brand_name": get_("brand_name", "brandName"),
            "sa_name": get_("sa_name", "saName"),
            "ts_name": get_("ts_name", "tsName"),
            "barcode": get_("barcode"),

            # Документ и суммы (API часто отдаёт camelCase — иначе в БД 0)
            "doc_type_name": get_("doc_type_name", "docTypeName"),
            "quantity": get_("quantity", default=0),

            # prices и суммы
            "retail_price": get_("retail_price", "retailPrice"),
            "retail_amount": get_("retail_amount", "retailAmount"),
            "sale_percent": get_("sale_percent", "salePercent"),
            "commission_percent": get_("commission_percent", "commissionPercent"),
            "retail_price_withdisc_rub": get_("retail_price_withdisc_rub", "retailPriceWithdiscRub"),
            "product_discount_for_report": get_("product_discount_for_report", "productDiscountForReport"),

            # Склад и операции
            "office_name": get_("office_name", "officeName"),
            "supplier_oper_name": get_("supplier_oper_name", "supplierOperName"),

            # Даты операций
            "order_dt": order_dt,
            "sale_dt": sale_dt,
            "rr_dt": rr_dt,

            # Логистика
            "shk_id": get_("shk_id", "shkId"),
            "delivery_amount": get_("delivery_amount", "deliveryAmount"),
            "return_amount": get_("return_amount", "returnAmount"),
            "delivery_rub": get_("delivery_rub", "deliveryRub"),
            "gi_box_type_name": get_("gi_box_type_name", "giBoxTypeName"),
            "delivery_method": get_("delivery_method", "deliveryMethod"),

            # Промо и скидки
            "supplier_promo": get_("supplier_promo", "supplierPromo"),
            "ppvz_spp_prc": get_("ppvz_spp_prc", "ppvzSppPrc"),
            "ppvz_kvw_prc_base": get_("ppvz_kvw_prc_base", "ppvzKvwPrcBase"),
            "ppvz_kvw_prc": get_("ppvz_kvw_prc", "ppvzKvwPrc"),
            "sup_rating_prc_up": get_("sup_rating_prc_up", "supRatingPrcUp"),
            "seller_promo_id": get_("seller_promo_id", "sellerPromoId"),
            "seller_promo_discount": get_("seller_promo_discount", "sellerPromoDiscount"),
            "loyalty_id": get_("loyalty_id", "loyaltyId"),
            "loyalty_discount": get_("loyalty_discount", "loyaltyDiscount"),
            "uuid_promocode": get_("uuid_promocode", "uuidPromocode"),
            "sale_price_promocode_discount_prc": get_("sale_price_promocode_discount_prc", "salePricePromocodeDiscountPrc"),
            "wibes_wb_discount_percent": get_("wibes_wb_discount_percent", "wibesWbDiscountPercent"),

            # Комиссии и платежи
            "ppvz_sales_commission": get_("ppvz_sales_commission", "ppvzSalesCommission"),
            "ppvz_for_pay": get_("ppvz_for_pay", "ppvzForPay"),
            "ppvz_reward": get_("ppvz_reward", "ppvzReward"),
            "acquiring_fee": get_("acquiring_fee", "acquiringFee"),
            "acquiring_percent": get_("acquiring_percent", "acquiringPercent"),
            "payment_processing": get_("payment_processing", "paymentProcessing"),
            "acquiring_bank": get_("acquiring_bank", "acquiringBank"),
            "ppvz_vw": get_("ppvz_vw", "ppvzVw"),
            "ppvz_vw_nds": get_("ppvz_vw_nds", "ppvzVwNds"),
            
            # ПВЗ информация
            "ppvz_office_name": get_("ppvz_office_name", "ppvzOfficeName"),
            "ppvz_office_id": get_("ppvz_office_id", "ppvzOfficeId"),
            "ppvz_supplier_id": get_("ppvz_supplier_id", "ppvzSupplierId"),
            "ppvz_supplier_name": get_("ppvz_supplier_name", "ppvzSupplierName"),
            "ppvz_inn": get_("ppvz_inn", "ppvzInn"),

            # Дополнительная информация
            "declaration_number": get_("declaration_number", "declarationNumber"),
            "bonus_type_name": get_("bonus_type_name", "bonusTypeName"),
            "sticker_id": get_("sticker_id", "stickerId"),
            "site_country": get_("site_country", "siteCountry"),
            "srv_dbs": get_("srv_dbs", "srvDbs"),

            # Штрафы и доплаты
            "penalty": get_("penalty"),
            "additional_payment": get_("additional_payment", "additionalPayment"),
            "rebill_logistic_cost": get_("rebill_logistic_cost", "rebillLogisticCost"),
            "rebill_logistic_org": get_("rebill_logistic_org", "rebillLogisticOrg"),
            "storage_fee": get_("storage_fee", "storageFee"),
            "deduction": get_("deduction"),
            "acceptance": get_("acceptance"),

            # Дополнительные поля
            "assembly_id": get_("assembly_id", "assemblyId"),
            "kiz": get_("kiz"),
            "report_type": get_("report_type", "reportType"),
            "is_legal_entity": get_("is_legal_entity", "isLegalEntity"),
            "is_kgvp_v2": get_("is_kgvp_v2", "isKgvpV2"),
            "trbx_id": get_("trbx_id", "trbxId"),
            "installment_cofinancing_amount": get_("installment_cofinancing_amount", "installmentCofinancingAmount"),
            "cashback_amount": get_("cashback_amount", "cashbackAmount"),
            "cashback_discount": get_("cashback_discount", "cashbackDiscount"),
            "cashback_commission_change": get_("cashback_commission_change", "cashbackCommissionChange"),
            "order_uid": get_("order_uid", "orderUid"),
            "payment_schedule": get_("payment_schedule", "paymentSchedule"),
            "dlv_prc": get_("dlv_prc", "dlvPrc"),
            "fix_tariff_date_from": fix_tariff_date_from,
            "fix_tariff_date_to": fix_tariff_date_to,
        }
        
        return normalized
    
    def upsert_report_data(self, report_data: List[Dict[str, Any]], report_date: date) -> int:
        """Вставка или обновление детальных данных отчета в БД."""
        if not report_data:
            logger.warning(f"Нет данных для вставки за {report_date}")
            return 0
        
        normalized_data = [
            self.normalize_report_data(item, report_date) 
            for item in report_data
        ]
        
        # Фильтруем записи без rrd_id (они не могут быть сохранены)
        valid_data = [item for item in normalized_data if item.get("rrd_id")]
        if len(valid_data) < len(normalized_data):
            logger.warning(
                f"Отфильтровано {len(normalized_data) - len(valid_data)} записей без rrd_id"
            )
        
        if not valid_data:
            logger.warning(f"Нет валидных данных для вставки за {report_date}")
            return 0

        deduped_data = self._deduplicate_valid_data(valid_data)
        if len(deduped_data) < len(valid_data):
            logger.warning(
                "Удалено дублей внутри батча report_detail: %s",
                len(valid_data) - len(deduped_data),
            )

        insert_query = """
            INSERT INTO reports.wb_report_detail_daily (
                rrd_id, realizationreport_id, srid,
                date_from, date_to, create_dt,
                currency_name, suppliercontract_code,
                gi_id, nm_id, subject_name, brand_name, sa_name, ts_name, barcode,
                doc_type_name, quantity,
                retail_price, retail_amount, sale_percent, commission_percent,
                retail_price_withdisc_rub, product_discount_for_report,
                office_name, supplier_oper_name,
                order_dt, sale_dt, rr_dt,
                shk_id, delivery_amount, return_amount, delivery_rub,
                gi_box_type_name, delivery_method,
                supplier_promo, ppvz_spp_prc, ppvz_kvw_prc_base, ppvz_kvw_prc,
                sup_rating_prc_up, seller_promo_id, seller_promo_discount,
                loyalty_id, loyalty_discount, uuid_promocode,
                sale_price_promocode_discount_prc, wibes_wb_discount_percent,
                ppvz_sales_commission, ppvz_for_pay, ppvz_reward,
                acquiring_fee, acquiring_percent, payment_processing, acquiring_bank,
                ppvz_vw, ppvz_vw_nds,
                ppvz_office_name, ppvz_office_id, ppvz_supplier_id,
                ppvz_supplier_name, ppvz_inn,
                declaration_number, bonus_type_name, sticker_id, site_country, srv_dbs,
                penalty, additional_payment, rebill_logistic_cost, rebill_logistic_org,
                storage_fee, deduction, acceptance,
                assembly_id, kiz, report_type, is_legal_entity, is_kgvp_v2,
                trbx_id, installment_cofinancing_amount,
                cashback_amount, cashback_discount, cashback_commission_change,
                order_uid, payment_schedule, dlv_prc,
                fix_tariff_date_from, fix_tariff_date_to,
                last_synced_at
            ) VALUES (
                %(rrd_id)s, %(realizationreport_id)s, %(srid)s,
                %(date_from)s, %(date_to)s, %(create_dt)s,
                %(currency_name)s, %(suppliercontract_code)s,
                %(gi_id)s, %(nm_id)s, %(subject_name)s, %(brand_name)s, %(sa_name)s, %(ts_name)s, %(barcode)s,
                %(doc_type_name)s, %(quantity)s,
                %(retail_price)s, %(retail_amount)s, %(sale_percent)s, %(commission_percent)s,
                %(retail_price_withdisc_rub)s, %(product_discount_for_report)s,
                %(office_name)s, %(supplier_oper_name)s,
                %(order_dt)s, %(sale_dt)s, %(rr_dt)s,
                %(shk_id)s, %(delivery_amount)s, %(return_amount)s, %(delivery_rub)s,
                %(gi_box_type_name)s, %(delivery_method)s,
                %(supplier_promo)s, %(ppvz_spp_prc)s, %(ppvz_kvw_prc_base)s, %(ppvz_kvw_prc)s,
                %(sup_rating_prc_up)s, %(seller_promo_id)s, %(seller_promo_discount)s,
                %(loyalty_id)s, %(loyalty_discount)s, %(uuid_promocode)s,
                %(sale_price_promocode_discount_prc)s, %(wibes_wb_discount_percent)s,
                %(ppvz_sales_commission)s, %(ppvz_for_pay)s, %(ppvz_reward)s,
                %(acquiring_fee)s, %(acquiring_percent)s, %(payment_processing)s, %(acquiring_bank)s,
                %(ppvz_vw)s, %(ppvz_vw_nds)s,
                %(ppvz_office_name)s, %(ppvz_office_id)s, %(ppvz_supplier_id)s,
                %(ppvz_supplier_name)s, %(ppvz_inn)s,
                %(declaration_number)s, %(bonus_type_name)s, %(sticker_id)s, %(site_country)s, %(srv_dbs)s,
                %(penalty)s, %(additional_payment)s, %(rebill_logistic_cost)s, %(rebill_logistic_org)s,
                %(storage_fee)s, %(deduction)s, %(acceptance)s,
                %(assembly_id)s, %(kiz)s, %(report_type)s, %(is_legal_entity)s, %(is_kgvp_v2)s,
                %(trbx_id)s, %(installment_cofinancing_amount)s,
                %(cashback_amount)s, %(cashback_discount)s, %(cashback_commission_change)s,
                %(order_uid)s, %(payment_schedule)s, %(dlv_prc)s,
                %(fix_tariff_date_from)s, %(fix_tariff_date_to)s,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (rrd_id) DO UPDATE SET
                realizationreport_id = EXCLUDED.realizationreport_id,
                srid = EXCLUDED.srid,
                date_from = EXCLUDED.date_from,
                date_to = EXCLUDED.date_to,
                create_dt = EXCLUDED.create_dt,
                currency_name = EXCLUDED.currency_name,
                suppliercontract_code = EXCLUDED.suppliercontract_code,
                gi_id = EXCLUDED.gi_id,
                nm_id = EXCLUDED.nm_id,
                subject_name = EXCLUDED.subject_name,
                brand_name = EXCLUDED.brand_name,
                sa_name = EXCLUDED.sa_name,
                ts_name = EXCLUDED.ts_name,
                barcode = EXCLUDED.barcode,
                doc_type_name = EXCLUDED.doc_type_name,
                quantity = EXCLUDED.quantity,
                retail_price = EXCLUDED.retail_price,
                retail_amount = EXCLUDED.retail_amount,
                sale_percent = EXCLUDED.sale_percent,
                commission_percent = EXCLUDED.commission_percent,
                retail_price_withdisc_rub = EXCLUDED.retail_price_withdisc_rub,
                product_discount_for_report = EXCLUDED.product_discount_for_report,
                office_name = EXCLUDED.office_name,
                supplier_oper_name = EXCLUDED.supplier_oper_name,
                order_dt = EXCLUDED.order_dt,
                sale_dt = EXCLUDED.sale_dt,
                rr_dt = EXCLUDED.rr_dt,
                shk_id = EXCLUDED.shk_id,
                delivery_amount = EXCLUDED.delivery_amount,
                return_amount = EXCLUDED.return_amount,
                delivery_rub = EXCLUDED.delivery_rub,
                gi_box_type_name = EXCLUDED.gi_box_type_name,
                delivery_method = EXCLUDED.delivery_method,
                supplier_promo = EXCLUDED.supplier_promo,
                ppvz_spp_prc = EXCLUDED.ppvz_spp_prc,
                ppvz_kvw_prc_base = EXCLUDED.ppvz_kvw_prc_base,
                ppvz_kvw_prc = EXCLUDED.ppvz_kvw_prc,
                sup_rating_prc_up = EXCLUDED.sup_rating_prc_up,
                seller_promo_id = EXCLUDED.seller_promo_id,
                seller_promo_discount = EXCLUDED.seller_promo_discount,
                loyalty_id = EXCLUDED.loyalty_id,
                loyalty_discount = EXCLUDED.loyalty_discount,
                uuid_promocode = EXCLUDED.uuid_promocode,
                sale_price_promocode_discount_prc = EXCLUDED.sale_price_promocode_discount_prc,
                wibes_wb_discount_percent = EXCLUDED.wibes_wb_discount_percent,
                ppvz_sales_commission = EXCLUDED.ppvz_sales_commission,
                ppvz_for_pay = EXCLUDED.ppvz_for_pay,
                ppvz_reward = EXCLUDED.ppvz_reward,
                acquiring_fee = EXCLUDED.acquiring_fee,
                acquiring_percent = EXCLUDED.acquiring_percent,
                payment_processing = EXCLUDED.payment_processing,
                acquiring_bank = EXCLUDED.acquiring_bank,
                ppvz_vw = EXCLUDED.ppvz_vw,
                ppvz_vw_nds = EXCLUDED.ppvz_vw_nds,
                ppvz_office_name = EXCLUDED.ppvz_office_name,
                ppvz_office_id = EXCLUDED.ppvz_office_id,
                ppvz_supplier_id = EXCLUDED.ppvz_supplier_id,
                ppvz_supplier_name = EXCLUDED.ppvz_supplier_name,
                ppvz_inn = EXCLUDED.ppvz_inn,
                declaration_number = EXCLUDED.declaration_number,
                bonus_type_name = EXCLUDED.bonus_type_name,
                sticker_id = EXCLUDED.sticker_id,
                site_country = EXCLUDED.site_country,
                srv_dbs = EXCLUDED.srv_dbs,
                penalty = EXCLUDED.penalty,
                additional_payment = EXCLUDED.additional_payment,
                rebill_logistic_cost = EXCLUDED.rebill_logistic_cost,
                rebill_logistic_org = EXCLUDED.rebill_logistic_org,
                storage_fee = EXCLUDED.storage_fee,
                deduction = EXCLUDED.deduction,
                acceptance = EXCLUDED.acceptance,
                assembly_id = EXCLUDED.assembly_id,
                kiz = EXCLUDED.kiz,
                report_type = EXCLUDED.report_type,
                is_legal_entity = EXCLUDED.is_legal_entity,
                is_kgvp_v2 = EXCLUDED.is_kgvp_v2,
                trbx_id = EXCLUDED.trbx_id,
                installment_cofinancing_amount = EXCLUDED.installment_cofinancing_amount,
                cashback_amount = EXCLUDED.cashback_amount,
                cashback_discount = EXCLUDED.cashback_discount,
                cashback_commission_change = EXCLUDED.cashback_commission_change,
                order_uid = EXCLUDED.order_uid,
                payment_schedule = EXCLUDED.payment_schedule,
                dlv_prc = EXCLUDED.dlv_prc,
                fix_tariff_date_from = EXCLUDED.fix_tariff_date_from,
                fix_tariff_date_to = EXCLUDED.fix_tariff_date_to,
                last_synced_at = CURRENT_TIMESTAMP
        """
        
        try:
            executemany_sql(self.cursor, insert_query, deduped_data)
            inserted_count = len(deduped_data)
            logger.info(f"Успешно обработано {inserted_count} записей за {report_date}")
            return inserted_count
        except psycopg2.Error as e:
            logger.error(f"Ошибка при вставке данных: {e}")
            raise
