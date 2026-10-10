
class FakeBankClient:
    async def get_account(self, account_number: str):
        return {
            "ok": True,
            "account_number": account_number,
            "account_status": "ACTIVE",
            "beneficiary_name": "Example Trading Ltd",
        }

    async def get_balance(self, account_number: str):
        return {
            "ok": True,
            "account_number": account_number,
            "balance": 10000,
            "currency": "EUR",
        }

    async def get_bank_status(self, bic_code: str):
        return {
            "ok": True,
            "bic_code": bic_code,
            "status": "AVAILABLE",
        }
