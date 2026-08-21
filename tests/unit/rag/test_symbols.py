from __future__ import annotations

from rag.symbols import MAX_SYMBOLS_PER_CHUNK, extract_symbols


def test_python_functions_and_classes() -> None:
    code = "class AuthService:\n    async def authenticate_user(self, token):\n        pass\n\ndef helper():\n    pass\n"
    symbols = extract_symbols(code, ".py")
    assert "authenticate_user" in symbols
    assert "AuthService" in symbols
    assert "helper" in symbols


def test_javascript_functions_classes_and_arrow_consts() -> None:
    code = "export function login(user) {}\nconst authenticateUser = async (token) => {}\nclass TokenService {}\n"
    symbols = extract_symbols(code, ".js")
    assert "login" in symbols
    assert "authenticateUser" in symbols
    assert "TokenService" in symbols


def test_typescript_reuses_javascript_patterns() -> None:
    symbols = extract_symbols("export class AuthGuard {}\n", ".ts")
    assert "AuthGuard" in symbols


def test_go_functions_and_structs() -> None:
    code = "func Authenticate(token string) bool {\n    return true\n}\ntype User struct {\n    Name string\n}\n"
    symbols = extract_symbols(code, ".go")
    assert "Authenticate" in symbols
    assert "User" in symbols


def test_rust_functions_and_structs() -> None:
    code = "pub fn authenticate(token: &str) -> bool {\n    true\n}\npub struct User {\n    name: String,\n}\n"
    symbols = extract_symbols(code, ".rs")
    assert "authenticate" in symbols
    assert "User" in symbols


def test_dart_class_and_method() -> None:
    code = "class AuthService {\n  Future<bool> authenticate(String token) {\n    return true;\n  }\n}\n"
    symbols = extract_symbols(code, ".dart")
    assert "AuthService" in symbols


def test_cpp_function_signature() -> None:
    code = "bool authenticate(std::string token) {\n    return true;\n}\n"
    symbols = extract_symbols(code, ".cpp")
    assert "authenticate" in symbols


def test_unsupported_extension_returns_empty() -> None:
    assert extract_symbols("whatever content", ".unknown") == []


def test_empty_content_returns_empty() -> None:
    assert extract_symbols("", ".py") == []


def test_symbol_count_is_bounded() -> None:
    code = "\n".join(f"def func_{i}():\n    pass" for i in range(50))
    symbols = extract_symbols(code, ".py")
    assert len(symbols) <= MAX_SYMBOLS_PER_CHUNK


def test_no_duplicate_symbols() -> None:
    code = "def foo():\n    pass\ndef foo():\n    pass\n"
    symbols = extract_symbols(code, ".py")
    assert symbols.count("foo") == 1
