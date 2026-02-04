# ADR 004: Centralized Constants Module

## Status
Accepted

## Context
Before the constants module, taskflows had magic numbers scattered throughout the codebase:
- API timeouts hardcoded as `10` in multiple places
- HMAC window as `300` without explanation
- Port numbers, buffer sizes, retry counts all duplicated
- No single source of truth for configuration values
- Difficult to find and update related constants

## Decision
Created a centralized `taskflows/constants.py` module organizing all magic numbers into logical classes.

## Structure

```python
from typing import Final

class API:
    """API server configuration constants."""
    DEFAULT_PORT: Final[int] = 7777
    DEFAULT_TIMEOUT: Final[int] = 10
    MAX_RESPONSE_SIZE: Final[int] = 8000
    MAX_TRACEBACK_LINES: Final[int] = 40

class Security:
    """Security and authentication constants."""
    HMAC_WINDOW_SECONDS: Final[int] = 300  # 5 minutes
    JWT_EXPIRATION_SECONDS: Final[int] = 3600  # 1 hour
    BCRYPT_ROUNDS: Final[int] = 12

class Service:
    """Service management constants."""
    DEFAULT_RESTART_DELAY: Final[int] = 10
    DEFAULT_STOP_TIMEOUT: Final[int] = 120
    MAX_SERVICE_NAME_LENGTH: Final[int] = 255

class Logging:
    """Logging configuration constants."""
    DEFAULT_LOG_LEVEL: Final[str] = "INFO"
    MAX_LOG_MESSAGE_SIZE: Final[int] = 10000
    LOG_ROTATION_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB

class Metrics:
    """Prometheus metrics configuration."""
    NAMESPACE: Final[str] = "taskflows"
    DURATION_BUCKETS: Final[tuple] = (
        0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0
    )
    TASK_DURATION: Final[str] = "task_duration_seconds"
    SERVICE_STATE: Final[str] = "service_state"
    API_REQUEST_DURATION: Final[str] = "api_request_duration_seconds"

class Docker:
    """Docker-related constants."""
    DEFAULT_NETWORK: Final[str] = "bridge"
    DEFAULT_STOP_TIMEOUT: Final[int] = 10
    MAX_CONTAINER_NAME_LENGTH: Final[int] = 63
```

## Design Principles

### 1. Logical Grouping
Constants are grouped by domain (API, Security, Service, etc.) not by type. This makes it easy to find related constants.

### 2. Type Safety
All constants use `Final` type hint to:
- Indicate immutability
- Enable mypy to catch reassignment
- Serve as documentation

### 3. Self-Documenting Names
Names clearly indicate:
- What the constant represents
- Units when applicable (e.g., `_SECONDS`, `_BYTES`)
- Context (e.g., `DEFAULT_`, `MAX_`, `MIN_`)

### 4. Comments for Non-Obvious Values
Values that aren't self-explanatory get inline comments:
```python
HMAC_WINDOW_SECONDS: Final[int] = 300  # 5 minutes
```

### 5. Calculated Constants
Related constants can reference each other:
```python
MAX_LOG_FILE_SIZE: Final[int] = 10 * 1024 * 1024  # 10 MB
LOG_RETENTION_SIZE: Final[int] = MAX_LOG_FILE_SIZE * 10
```

## Rationale

### Advantages Over Magic Numbers

**Before** (Magic Numbers):
```python
# admin/security.py
if time_diff > 300:  # What's 300?
    raise SecurityError("Expired")

# api.py
resp = requests.get(url, timeout=10)  # Why 10?

# service.py
restart_sec=10  # Same as API timeout? Coincidence?
```

**After** (Named Constants):
```python
from taskflows.constants import Security, API, Service

# admin/security.py
if time_diff > Security.HMAC_WINDOW_SECONDS:
    raise SecurityError("HMAC timestamp expired")

# api.py
resp = requests.get(url, timeout=API.DEFAULT_TIMEOUT)

# service.py
restart_sec=Service.DEFAULT_RESTART_DELAY
```

### Benefits

1. **Single Source of Truth**: Change once, effect everywhere
2. **Searchability**: Easy to find all uses of a constant
3. **Documentation**: Names explain purpose
4. **Type Safety**: mypy catches misuse
5. **Maintainability**: Clear what values are related
6. **Testability**: Easy to mock/override in tests

## Alternatives Considered

### Environment Variables
```python
HMAC_WINDOW = int(os.getenv("HMAC_WINDOW", "300"))
```
- ✅ Runtime configurability
- ❌ No type safety
- ❌ Scattered across files
- ❌ Hard to discover all options

**Decision**: Use constants for invariants, environment variables for deployment-specific config.

### Config Files (YAML/JSON)
```yaml
security:
  hmac_window_seconds: 300
```
- ✅ Centralized
- ❌ Runtime parsing overhead
- ❌ No type checking
- ❌ Overkill for simple constants

**Decision**: Save config files for user-facing configuration.

### Enums
```python
class Timeouts(IntEnum):
    API = 10
    SERVICE = 120
```
- ✅ Type safe
- ❌ Less readable (`Timeouts.API` vs `API.DEFAULT_TIMEOUT`)
- ❌ Constraints on value types

**Decision**: Use Enums for related options, constants for values.

## Migration Process

### Phase 1: Create Module (Completed)
- Identify all magic numbers
- Group into logical classes
- Add type hints and comments

### Phase 2: Update Imports (Completed in Phases 1-5)
- Replace magic numbers in new modules
- Update security, metrics, API modules

### Phase 3: Gradual Adoption (Ongoing)
- Update remaining modules as they're modified
- No rush to change working code

## Usage Guidelines

### When to Add a Constant
Add to constants module when value is:
- Used in multiple files
- Has domain significance (not arbitrary)
- Might change as requirements evolve
- Non-obvious without context

### When NOT to Add a Constant
Don't add when value is:
- Local to single function
- Truly arbitrary (e.g., random seed)
- Changes frequently per-deployment

## Consequences

### Positive
- ✅ Eliminated ~50 magic numbers
- ✅ Improved code readability
- ✅ Easier to adjust timeouts/limits
- ✅ mypy catches misuse
- ✅ grep finds all uses

### Negative
- Extra import statement
- Slightly more verbose (API.DEFAULT_PORT vs 7777)
- Need discipline to use consistently

### Neutral
- Not all numbers should be constants
- Balance between reusability and over-abstraction

## Examples

### Security Hardening
Adjusting HMAC window affects all auth checks:
```python
# Tighten security: 5 min → 2 min
HMAC_WINDOW_SECONDS: Final[int] = 120
```

### Performance Tuning
Increase API timeout for slow endpoints:
```python
# Before: Multiple files with timeout=10
# After: One change
DEFAULT_TIMEOUT: Final[int] = 30
```

### Feature Toggle
Add new constant for feature gating:
```python
class Features:
    ENABLE_METRICS: Final[bool] = True
    ENABLE_CACHING: Final[bool] = False
```

## References
- [Google Python Style Guide - Constants](https://google.github.io/styleguide/pyguide.html#s3.16-naming)
- [PEP 591 - Adding a final qualifier](https://www.python.org/dev/peps/pep-0591/)
