from sqlalchemy import BigInteger, Enum, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from volty.inverters import Brand
from volty.inverters.base import GridState

MAX_DISPLAY_NAME_LENGTH = 64


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    language: Mapped[str] = mapped_column(String(8))

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.telegram_id", ondelete="CASCADE"))
    brand: Mapped[Brand] = mapped_column(Enum(Brand, native_enum=False, length=32))
    region: Mapped[str] = mapped_column(String(16))
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary)
    needs_reauth: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship(back_populates="accounts")
    inverters: Mapped[list[Inverter]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Inverter(Base):
    __tablename__ = "inverters"
    __table_args__ = (UniqueConstraint("account_id", "serial"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    serial: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(MAX_DISPLAY_NAME_LENGTH))
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    group_chat_title: Mapped[str | None] = mapped_column(String(255))
    notifications_enabled: Mapped[bool] = mapped_column(default=True)
    grid_state: Mapped[GridState | None] = mapped_column(
        Enum(GridState, native_enum=False, length=16)
    )
    pending_grid_state: Mapped[GridState | None] = mapped_column(
        Enum(GridState, native_enum=False, length=16)
    )

    account: Mapped[Account] = relationship(back_populates="inverters")

    @property
    def label(self) -> str:
        return self.display_name or f"{self.model} ···{self.serial[-4:]}"
