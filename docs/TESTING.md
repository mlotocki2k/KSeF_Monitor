# Testing Guide

Complete guide for testing your KSeF Invoice Monitor installation.

## Pre-Deployment Tests

Run these tests BEFORE deploying to production.

### Test 1: Configuration Validation

```bash
# Validate JSON syntax
cat config.json | python3 -m json.tool

# Should output formatted JSON without errors
```

**Expected:** Clean JSON output
**On Error:** Fix JSON syntax errors

### Test 2: Environment Variables

```bash
# Check .env file exists and is secure
ls -la .env

# Should show: -rw------- (600 permissions)
```

**Expected:** File exists with 600 permissions
**On Error:** Run `chmod 600 .env`

### Test 3: Docker Build

```bash
# Build the image
docker-compose build

# Should complete without errors
```

**Expected:** "Successfully built" message
**On Error:** Check Dockerfile and requirements.txt

### Test 4: Import Check

```bash
# Test imports work
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient, PushoverNotifier, InvoiceMonitor
print('✓ All imports successful')
"
```

**Expected:** "✓ All imports successful"
**On Error:** Check app/__init__.py and module files

## Component Tests

Test each component individually.

### Test 5: Configuration Loading

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager
config = ConfigManager('/data/config.json')
print('✓ Config loaded')
print('Environment:', config.get('ksef', 'environment'))
print('NIP:', config.get('ksef', 'nip'))
print('Interval:', config.get('monitoring', 'check_interval'))
"
```

**Expected:**
```
✓ Config loaded
Environment: test
NIP: 1234567890
Interval: 300
```

**On Error:** Check config.json and secrets

### Test 6: Secrets Loading

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager
config = ConfigManager('/data/config.json')
has_ksef = bool(config.get('ksef', 'token'))
has_pushover_user = bool(config.get('pushover', 'user_key'))
has_pushover_api = bool(config.get('pushover', 'api_token'))
print('✓ Secrets check')
print(f'KSeF token present: {has_ksef}')
print(f'Pushover user key present: {has_pushover_user}')
print(f'Pushover API token present: {has_pushover_api}')
"
```

**Expected:** All three should be True
**On Error:** Check .env file or Docker secrets

### Test 7: Pushover Connection

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager, PushoverNotifier
config = ConfigManager('/data/config.json')
notifier = PushoverNotifier(config)
result = notifier.test_connection()
print('✓ Test notification sent:', result)
"
```

**Expected:** 
- "✓ Test notification sent: True"
- Notification on your device

**On Error:** 
- Check Pushover credentials
- Verify device has Pushover app installed

### Test 8: KSeF Authentication

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient
config = ConfigManager('/data/config.json')
client = KSeFClient(config)
result = client.authenticate()
print('✓ KSeF authentication:', 'SUCCESS' if result else 'FAILED')
"
```

**Expected:** "✓ KSeF authentication: SUCCESS"

**On Error:**
- Check KSeF token is valid
- Verify NIP is correct
- Ensure correct environment (test/prod)
- Check network connectivity

### Test 9: Invoice Query (Requires Authentication)

```bash
docker-compose run --rm ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient
from datetime import datetime, timedelta
config = ConfigManager('/data/config.json')
client = KSeFClient(config)
client.authenticate()
now = datetime.now()
invoices = client.get_invoices_metadata(now - timedelta(days=1), now)
print('✓ Query successful')
print(f'Found {len(invoices)} invoice(s)')
"
```

**Expected:** Query completes (may find 0 invoices if none exist)
**On Error:** Check authentication and network

## Integration Tests

Test the complete workflow.

### Test 10: Full Startup

```bash
# Start the monitor
docker-compose up -d

# Wait a few seconds
sleep 5

# Check logs
docker-compose logs --tail=50
```

**Expected logs:**
```
✓ Configuration loaded
✓ KSeF client initialized
✓ Pushover notifier initialized
✓ Invoice monitor initialized
Checking for new invoices...
```

**On Error:** Check component tests above

### Test 11: Monitoring Loop

```bash
# Let it run for 1 minute
docker-compose logs -f

# Should see:
# - Initial check
# - "Waiting X seconds until next check..."
# - Another check after interval
```

**Expected:** Regular check cycles
**On Error:** Check monitor configuration

### Test 12: State Persistence

```bash
# Check state file created
docker-compose exec ksef-monitor ls -la /data/last_check.json

# View state
docker-compose exec ksef-monitor cat /data/last_check.json
```

**Expected:** JSON file with last_check and seen_invoices
**On Error:** Check volume mounts

### Test 13: Restart Persistence

```bash
# Stop monitor
docker-compose down

# Start again
docker-compose up -d

# Check it remembers state
docker-compose exec ksef-monitor cat /data/last_check.json
```

**Expected:** Same state as before restart
**On Error:** Check data volume mount

## Error Handling Tests

Test how the system handles errors.

### Test 14: Invalid Token

```bash
# Temporarily set wrong token
docker-compose run --rm -e KSEF_TOKEN=invalid ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient
config = ConfigManager('/data/config.json')
client = KSeFClient(config)
result = client.authenticate()
print('Auth with bad token:', result)
"
```

**Expected:** "Auth with bad token: False"
**On Error:** Error handling not working

### Test 15: Network Failure Simulation

```bash
# Start monitor without network
docker-compose run --rm --network none ksef-monitor python3 -c "
from app import ConfigManager, KSeFClient
config = ConfigManager('/data/config.json')
client = KSeFClient(config)
try:
    client.authenticate()
except Exception as e:
    print('✓ Network error handled:', type(e).__name__)
"
```

**Expected:** Error handled gracefully
**On Error:** Improve error handling

### Test 16: Missing Configuration

```bash
# Try to run without config
docker-compose run --rm -v /dev/null:/data/config.json ksef-monitor python3 main.py

# Should exit with error message
```

**Expected:** Clear error message about missing config
**On Error:** Improve error messages

## Performance Tests

### Test 17: Response Time

```bash
docker-compose run --rm ksef-monitor python3 -c "
import time
from app import ConfigManager, KSeFClient
from datetime import datetime, timedelta

config = ConfigManager('/data/config.json')
client = KSeFClient(config)

# Test auth time
start = time.time()
client.authenticate()
auth_time = time.time() - start

# Test query time
start = time.time()
now = datetime.now()
client.get_invoices_metadata(now - timedelta(hours=1), now)
query_time = time.time() - start

print(f'Auth time: {auth_time:.2f}s')
print(f'Query time: {query_time:.2f}s')
"
```

**Expected:** 
- Auth: < 10 seconds
- Query: < 5 seconds

**On Error:** Check network or API issues

### Test 18: Memory Usage

```bash
# Start monitor
docker-compose up -d

# Check memory usage
docker stats ksef-invoice-monitor --no-stream
```

**Expected:** < 100MB memory usage
**On Error:** Check for memory leaks

## Security Tests

### Test 19: File Permissions

```bash
# Check config file permissions
ls -la config.json
ls -la .env

# Both should be 600 or 640
```

**Expected:** Restricted permissions
**On Error:** Run `chmod 600 config.json .env`

### Test 20: Secrets Not Logged

```bash
# Check logs don't contain secrets
docker-compose logs | grep -i "token\|password\|secret" | grep -v "loaded from"

# Should not show actual secret values
```

**Expected:** No secrets in logs
**On Error:** Review logging code

### Test 21: Container Security

```bash
# Check container runs as non-root
docker-compose exec ksef-monitor whoami
```

**Expected:** Not "root"
**On Error:** Update Dockerfile

## Production Readiness Tests

Before deploying to production, verify:

### Checklist

```bash
# 1. Using Docker Secrets (not .env)
docker secret ls

# 2. Log rotation enabled
grep -A 3 "logging:" docker-compose.yml

# 3. Restart policy set
grep "restart:" docker-compose.yml

# 4. Production environment
grep '"environment"' config.json

# 5. Appropriate check interval
grep '"check_interval"' config.json

# 6. Security measures
chmod 600 config.json
ls -la .env  # Should not exist in production
```

## Automated Test Script

Save this as `run_tests.sh`:

```bash
#!/bin/bash

echo "=== KSeF Monitor Test Suite ==="

tests_passed=0
tests_failed=0

run_test() {
    echo ""
    echo "Running: $1"
    if eval "$2"; then
        echo "✓ PASS"
        ((tests_passed++))
    else
        echo "✗ FAIL"
        ((tests_failed++))
    fi
}

# Run tests
run_test "Config validation" "cat config.json | python3 -m json.tool > /dev/null"
run_test "Docker build" "docker-compose build > /dev/null 2>&1"
run_test "Import test" "docker-compose run --rm ksef-monitor python3 -c 'from app import ConfigManager' 2>/dev/null"

echo ""
echo "=== Test Results ==="
echo "Passed: $tests_passed"
echo "Failed: $tests_failed"

if [ $tests_failed -eq 0 ]; then
    echo "✓ All tests passed!"
    exit 0
else
    echo "✗ Some tests failed"
    exit 1
fi
```

## Continuous Monitoring

### Health Check Script

Create `healthcheck.sh`:

```bash
#!/bin/bash
# Check if monitor is healthy

# Check container is running
if ! docker-compose ps | grep -q "Up"; then
    echo "✗ Container not running"
    exit 1
fi

# Check last log entry is recent (within 10 minutes)
last_log=$(docker-compose logs --tail=1 --timestamps | awk '{print $1}')
now=$(date +%s)
log_time=$(date -d "$last_log" +%s 2>/dev/null || echo 0)
diff=$((now - log_time))

if [ $diff -gt 600 ]; then
    echo "✗ No recent activity (${diff}s ago)"
    exit 1
fi

echo "✓ Monitor is healthy"
exit 0
```

## Test Results Logging

Log test results:

```bash
# Run tests and save results
./run_tests.sh 2>&1 | tee test_results_$(date +%Y%m%d_%H%M%S).log
```

## Troubleshooting Failed Tests

### Configuration Tests Fail
- Verify JSON syntax
- Check file exists
- Verify secrets are set

### Authentication Tests Fail
- Check token validity
- Verify NIP format
- Test network connectivity
- Check environment matches token

### Notification Tests Fail
- Verify Pushover credentials
- Check device has app installed
- Test from Pushover website

### Performance Tests Fail
- Check network speed
- Verify API status
- Consider increasing timeouts

---

**Run these tests before each deployment to ensure reliability!**
