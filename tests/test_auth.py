"""Account creation, password verification, and the passwordless OTP account path."""

import pytest


class TestEmailValidation:
    @pytest.mark.parametrize("email", ["user@example.com", "first.last@sub.domain.co.uk", "a+tag@mail.io"])
    def test_accepts_valid_addresses(self, isolated_db, email):
        assert isolated_db.is_valid_email(email) is True

    @pytest.mark.parametrize("email", ["invalid-email", "", "no-at-sign.com", "trailing@dot.", "a@b"])
    def test_rejects_invalid_addresses(self, isolated_db, email):
        assert isolated_db.is_valid_email(email) is False

    def test_rejects_absurdly_long_addresses(self, isolated_db):
        assert isolated_db.is_valid_email("a" * 200 + "@example.com") is False


class TestPasswordHashing:
    def test_same_password_yields_different_hashes(self, isolated_db):
        """Each hash must carry its own random salt."""
        first, salt_a = isolated_db.hash_password("hunter2")
        second, salt_b = isolated_db.hash_password("hunter2")
        assert salt_a != salt_b
        assert first != second

    def test_hash_is_reproducible_from_its_salt(self, isolated_db):
        digest, salt = isolated_db.hash_password("hunter2")
        assert isolated_db.hash_password("hunter2", salt)[0] == digest

    def test_plaintext_is_never_stored(self, isolated_db):
        digest, _ = isolated_db.hash_password("hunter2")
        assert "hunter2" not in digest


class TestSignupAndLogin:
    def test_signup_then_login_succeeds(self, isolated_db):
        assert isolated_db.signup_user("user@example.com", "correct-horse")[0] is True
        assert isolated_db.login_user("user@example.com", "correct-horse")[0] is True

    def test_short_passwords_are_rejected(self, isolated_db):
        ok, message = isolated_db.signup_user("user@example.com", "123")
        assert ok is False
        assert "6 characters" in message

    def test_duplicate_signup_is_rejected(self, isolated_db):
        isolated_db.signup_user("user@example.com", "correct-horse")
        ok, message = isolated_db.signup_user("user@example.com", "another-one")
        assert ok is False
        assert "already exists" in message

    def test_wrong_password_is_rejected(self, isolated_db):
        isolated_db.signup_user("user@example.com", "correct-horse")
        assert isolated_db.login_user("user@example.com", "wrong")[0] is False

    def test_unknown_account_is_rejected(self, isolated_db):
        assert isolated_db.login_user("nobody@example.com", "whatever")[0] is False

    def test_email_is_case_insensitive(self, isolated_db):
        isolated_db.signup_user("User@Example.COM", "correct-horse")
        assert isolated_db.login_user("user@example.com", "correct-horse")[0] is True

    def test_user_count_tracks_signups(self, isolated_db):
        assert isolated_db.get_total_users() == 0
        isolated_db.signup_user("a@example.com", "correct-horse")
        isolated_db.signup_user("b@example.com", "correct-horse")
        assert isolated_db.get_total_users() == 2


class TestPasswordlessAccounts:
    """
    OTP-verified accounts previously shared one hardcoded password that was committed to
    the repository, so anyone could sign in as any of them. They now carry no usable
    password at all.
    """

    def test_ensure_user_creates_an_account(self, isolated_db):
        ok, _ = isolated_db.ensure_user("otp@example.com")
        assert ok is True
        assert isolated_db.get_total_users() == 1

    def test_ensure_user_is_idempotent(self, isolated_db):
        isolated_db.ensure_user("otp@example.com")
        ok, message = isolated_db.ensure_user("otp@example.com")
        assert ok is True
        assert "already exists" in message
        assert isolated_db.get_total_users() == 1

    def test_the_old_shared_password_no_longer_works(self, isolated_db):
        isolated_db.ensure_user("otp@example.com")
        ok, _ = isolated_db.login_user("otp@example.com", "OTP_VERIFIED_SECURE_AUTH")
        assert ok is False

    @pytest.mark.parametrize("attempt", ["", "!", "password", "OTP_VERIFIED_SECURE_AUTH", "a" * 100])
    def test_no_password_opens_a_passwordless_account(self, isolated_db, attempt):
        isolated_db.ensure_user("otp@example.com")
        assert isolated_db.login_user("otp@example.com", attempt)[0] is False

    def test_ensure_user_rejects_invalid_addresses(self, isolated_db):
        assert isolated_db.ensure_user("not-an-email")[0] is False

    def test_password_accounts_are_unaffected(self, isolated_db):
        isolated_db.ensure_user("otp@example.com")
        isolated_db.signup_user("pw@example.com", "correct-horse")
        assert isolated_db.login_user("pw@example.com", "correct-horse")[0] is True
