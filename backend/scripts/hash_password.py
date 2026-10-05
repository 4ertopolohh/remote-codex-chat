"""Generate an Argon2id password hash without placing the password in shell history."""

from getpass import getpass

from argon2 import PasswordHasher
from argon2.low_level import Type

password = getpass("New password: ")
confirmation = getpass("Repeat password: ")
if not password or password != confirmation:
    raise SystemExit("Passwords are empty or do not match")
print(PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID).hash(password))
