"""Unit tests for user authentication and password hashing."""

import sqlite3
import pytest
from services.persistence.exercise_repository import (
    hash_password,
    verify_password,
)


def test_password_hashing_and_verification():
    """Verify PBKDF2 hashing and verification."""
    password = "secret_password_123"
    pw_hash, salt = hash_password(password)

    assert pw_hash != password
    assert len(salt) > 0
    assert verify_password(password, pw_hash, salt) is True
    assert verify_password("wrong_password", pw_hash, salt) is False


def test_unique_salts_for_identical_passwords():
    """Two identical passwords hashed separately must produce distinct hashes."""
    pw1 = "test_pass"
    pw2 = "test_pass"
    hash1, salt1 = hash_password(pw1)
    hash2, salt2 = hash_password(pw2)

    assert salt1 != salt2
    assert hash1 != hash2
