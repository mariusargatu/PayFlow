"""Composition root.

This is the one place in the domain layer that wires concrete persistence into
the ports the service depends on. The API layer calls ``build_service`` and never
touches infrastructure itself, which keeps the ``api -> domain -> infrastructure``
layering intact.
"""

from __future__ import annotations

from ..config import Config
from ..infrastructure.db import Database
from ..infrastructure.ledger.core import CorrectLedgerWriter, SplitCommitLedgerWriter
from .idempotency import AtomicIdempotency, CheckThenActIdempotency
from .models import (
    ACCT_EXTERNAL_SETTLEMENT,
    ACCT_HOLDS,
    ACCT_PLATFORM_FEES,
    Account,
    AccountType,
)
from .repositories import (
    AccountsRepository,
    IdempotencyRepository,
    IntentsRepository,
    LedgerRepository,
)
from .seams import SystemClock, UuidIdGenerator
from .service import PaymentService

_SYSTEM_ACCOUNTS = (
    (ACCT_EXTERNAL_SETTLEMENT, "External settlement", AccountType.EXTERNAL_SETTLEMENT),
    (ACCT_PLATFORM_FEES, "Platform fees", AccountType.PLATFORM_FEES),
    (ACCT_HOLDS, "Holds", AccountType.HOLDS),
)


def build_service(config: Config) -> PaymentService:
    db = Database(config.db_path)
    clock = SystemClock()
    id_generator = UuidIdGenerator()

    backend = SplitCommitLedgerWriter() if config.bug == "fm_c" else CorrectLedgerWriter()
    ledger = LedgerRepository(backend, clock, id_generator)

    accounts = AccountsRepository()
    intents = IntentsRepository()
    idem_store = IdempotencyRepository(clock)

    if config.bug == "fm_a":
        idempotency = CheckThenActIdempotency(db, idem_store)
    else:
        idempotency = AtomicIdempotency(db, idem_store)

    _seed_system_accounts(db, accounts, clock)

    return PaymentService(
        db=db,
        accounts=accounts,
        intents=intents,
        ledger=ledger,
        idempotency=idempotency,
        clock=clock,
        id_generator=id_generator,
        capture_fee=config.capture_fee,
    )


def _seed_system_accounts(db: Database, accounts: AccountsRepository, clock: SystemClock) -> None:
    now = clock.now().isoformat()
    with db.transaction() as conn:
        for account_id, name, account_type in _SYSTEM_ACCOUNTS:
            accounts.insert_if_absent(
                conn, Account(id=account_id, name=name, type=account_type, created_at=now)
            )
