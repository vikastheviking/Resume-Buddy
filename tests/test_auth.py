"""
Unit tests for auth.py
"""

from engine.auth import init_db, signup_user, login_user, is_valid_email, get_total_users

def run_tests():
    print("=== Testing Authentication Module ===")
    init_db()

    # 1. Test email validation
    assert is_valid_email("user@example.com") is True
    assert is_valid_email("invalid-email") is False
    assert is_valid_email("") is False
    print("[OK] Email validation tests passed.")

    # 2. Test short password rejection
    success, msg = signup_user("testuser@resumeai.com", "123")
    assert success is False
    assert "at least 6 characters" in msg
    print("[OK] Password length enforcement passed.")

    # 3. Test successful signup
    import time
    test_email = f"tester_{int(time.time())}@resumeai.com"
    test_pw = "SecurePass123"
    
    # Try logging in before signup
    success, msg = login_user(test_email, test_pw)
    assert success is False
    assert "No account found" in msg

    # Signup
    success, msg = signup_user(test_email, test_pw)
    assert success is True
    print("[OK] User signup passed.")

    # 4. Test duplicate signup rejection
    success, msg = signup_user(test_email, "AnotherPass")
    assert success is False
    assert "already exists" in msg
    print("[OK] Duplicate email rejection passed.")

    # 5. Test successful login
    success, msg = login_user(test_email, test_pw)
    assert success is True
    print("[OK] User login with valid credentials passed.")

    # 6. Test wrong password
    success, msg = login_user(test_email, "WrongPassword")
    assert success is False
    assert "Incorrect password" in msg
    print("[OK] Wrong password rejection passed.")

    print(f"[OK] Total registered users: {get_total_users()}")
    print("\nALL AUTHENTICATION TESTS PASSED!")

if __name__ == "__main__":
    run_tests()
