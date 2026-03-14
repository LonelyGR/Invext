"""
Клиент к backend API (httpx). Вся работа с данными идёт через этот модуль.
"""
import httpx
from decimal import Decimal
from typing import Any, Dict, List, Optional

from src.config.settings import (
    BACKEND_BASE_URL,
    ADMIN_API_KEY,
)


class BackendClient:
    def __init__(self, base_url: str = BACKEND_BASE_URL, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._admin_headers = {"X-ADMIN-KEY": ADMIN_API_KEY}

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    # --- Auth / User ---
    async def telegram_auth(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        name: Optional[str] = None,
        ref_code_from_start: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/v1/telegram/auth"),
                json={
                    "telegram_id": telegram_id,
                    "username": username,
                    "name": name,
                    "ref_code_from_start": ref_code_from_start,
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_me(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/telegram/me"),
                params={"telegram_id": telegram_id},
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def update_me(
        self,
        telegram_id: int,
        name: Optional[str] = None,
        email: Optional[str] = None,
        country: Optional[str] = None,
    ) -> Dict[str, Any]:
        """PATCH /v1/telegram/me — обновить имя, email, страну."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            body = {}
            if name is not None:
                body["name"] = name
            if email is not None:
                body["email"] = email
            if country is not None:
                body["country"] = country
            r = await client.patch(
                self._url("/v1/telegram/me"),
                params={"telegram_id": telegram_id},
                json=body,
            )
            r.raise_for_status()
            return r.json()

    # --- Saved Wallets (user_wallets) ---
    async def get_wallets(self, telegram_id: int) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/wallets"),
                params={"telegram_id": telegram_id},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("wallets", [])

    async def create_wallet(
        self, telegram_id: int, name: str, currency: str, address: str
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/v1/wallets"),
                params={"telegram_id": telegram_id},
                json={"name": name, "currency": currency, "address": address},
            )
            r.raise_for_status()
            return r.json()

    async def delete_wallet(self, telegram_id: int, wallet_id: int) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.delete(
                self._url(f"/v1/wallets/{wallet_id}"),
                params={"telegram_id": telegram_id},
            )
            r.raise_for_status()

    # --- Wallet (balances) ---
    async def get_balances(self, telegram_id: int) -> Dict[str, Decimal]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/wallet/balances"),
                params={"telegram_id": telegram_id},
            )
            r.raise_for_status()
            data = r.json()
            return {
                "USDT": Decimal(str(data.get("USDT", 0))),
                "USDC": Decimal(str(data.get("USDC", 0))),
            }

    # --- Withdrawals ---
    async def create_withdraw_request(
        self, telegram_id: int, currency: str, amount: Decimal, address: str
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/v1/withdrawals/request"),
                json={
                    "telegram_id": telegram_id,
                    "currency": currency,
                    "amount": str(amount),
                    "address": address,
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_my_withdrawals(self, telegram_id: int) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/withdrawals/my"),
                params={"telegram_id": telegram_id},
            )
            r.raise_for_status()
            return r.json()

    # --- NOWPayments deposits (invoice-based) ---
    async def create_deposit_invoice(
        self,
        telegram_id: int,
        amount: Decimal,
    ) -> Dict[str, Any]:
        """Создать инвойс NOWPayments для пополнения баланса (USDT BEP20). Сумма в USD."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/v1/payments/deposit/create-invoice"),
                json={
                    "telegram_id": telegram_id,
                    "amount": str(amount),
                },
            )
            r.raise_for_status()
            return r.json()

    async def get_deposit_invoice(
        self, invoice_id: int, telegram_id: int
    ) -> Dict[str, Any]:
        """Получить статус одного пополнения по внутреннему id."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url(f"/v1/payments/deposit/{invoice_id}"),
                params={"telegram_id": telegram_id},
            )
            r.raise_for_status()
            return r.json()

    async def get_my_invoices(
        self, telegram_id: int, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Список пополнений пользователя (NOWPayments)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/wallet/invoices"),
                params={"telegram_id": telegram_id, "limit": limit},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("items", [])

    async def get_active_deal(self) -> Dict[str, Any]:
        """Есть ли открытая сделка (окно регистрации). { "active": bool, "deal_number": optional, "end_at": optional }."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(self._url("/api/deals/active"))
            r.raise_for_status()
            return r.json()

    async def invest(
        self,
        telegram_id: int,
        amount_usdt: Decimal,
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/api/invest"),
                json={
                    "user_id": telegram_id,
                    "amount_usdt": str(amount_usdt),
                },
            )
            r.raise_for_status()
            return r.json()

    # --- Admin ---
    async def admin_pending_withdrawals(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/admin/withdrawals/pending"),
                headers=self._admin_headers,
            )
            r.raise_for_status()
            return r.json()

    async def admin_approve_withdraw(
        self, withdraw_id: int, decided_by_telegram_id: int
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url(f"/v1/admin/withdrawals/{withdraw_id}/approve"),
                params={"decided_by_telegram_id": decided_by_telegram_id},
                headers=self._admin_headers,
            )
            r.raise_for_status()
            return r.json()

    async def admin_reject_withdraw(
        self, withdraw_id: int, decided_by_telegram_id: int
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url(f"/v1/admin/withdrawals/{withdraw_id}/reject"),
                params={"decided_by_telegram_id": decided_by_telegram_id},
                headers=self._admin_headers,
            )
            r.raise_for_status()
            return r.json()

    async def create_dashboard_token(self, telegram_id: int) -> Dict[str, Any]:
        """Создать одноразовый токен для входа в админ-сайт /database. Действует 24 ч."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self._url("/v1/admin/dashboard-token"),
                params={"telegram_id": telegram_id},
                headers=self._admin_headers,
            )
            r.raise_for_status()
            return r.json()

    # --- System settings (admin only) ---
    async def get_system_settings(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(
                self._url("/v1/admin/system-settings"),
                headers=self._admin_headers,
            )
            r.raise_for_status()
            return r.json()

    async def update_system_settings_field(self, field: str, value: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.patch(
                self._url("/v1/admin/system-settings"),
                headers=self._admin_headers,
                json={"field": field, "value": value},
            )
            r.raise_for_status()
            return r.json()


# Синглтон для использования в хендлерах
api = BackendClient()
