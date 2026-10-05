"""Generate an Argon2id password hash without placing the password in shell history."""

from getpass import getpass

from argon2 import PasswordHasher
from argon2.low_level import Type

password = getpass("Новый пароль: ")
confirmation = getpass("Повторите пароль: ")
if not password or password != confirmation:
    raise SystemExit("Пароли пусты или не совпадают")
print(PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID).hash(password))
