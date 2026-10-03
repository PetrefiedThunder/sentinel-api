============================= test session starts ==============================
platform darwin -- Python 3.13.14, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/sellers/Projects/qa-sweep-2026-10-02/sentinel-api
configfile: pyproject.toml
plugins: platformdirs-4.12.2, hypothesis-6.168.3, cov-7.1.0, socket-0.8.1, asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 4 items

tests/test_qa_dx.py ...x                                                 [100%]

=========================== short test summary info ============================
XFAIL tests/test_qa_dx.py::test_contributing_single_file_test_example_exists - UX-002: CONTRIBUTING names a nonexistent test file
========================= 3 passed, 1 xfailed in 0.07s =========================
All checks passed!
