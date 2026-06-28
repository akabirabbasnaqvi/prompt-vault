# PromptVault

## How to run and test

The test configuration in this repository already enables coverage reporting through `pytest.ini`, so running `pytest` is enough to execute the suite and generate HTML coverage in `htmlcov/`.

### Run all tests with coverage

```bash
pytest
```

### Run only unit tests

```bash
pytest tests/unit/ -v
```

### Run only integration tests

```bash
pytest tests/integration/ -v
```

### Run a single test file

```bash
pytest tests/unit/test_schemas.py -v
```

### Run a single test

```bash
pytest tests/unit/test_schemas.py::TestWorkspaceCreateSchema::test_valid_workspace_create -v
```

### Open the HTML coverage report

After running `pytest`, open:

```text
D:\PromptVault(Project)\htmlcov\index.html
```

Note: the current test fixtures still initialize a dedicated test database, so the unit test folder is not fully database-free yet.