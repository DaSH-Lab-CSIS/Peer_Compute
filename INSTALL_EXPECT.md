# Installing Expect for ProxyJump Password Support

## Why Expect is Needed

When using ProxyJump with password authentication, `sshpass` doesn't work well because:
- ProxyJump requires authentication through the jumpnode first
- Then authentication to the target node
- `sshpass` can only handle one password prompt
- `expect` can handle multiple password prompts

## Installation

### On Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install expect
```

### On CentOS/RHEL:
```bash
sudo yum install expect
```

### On macOS:
```bash
brew install expect
```

## Verification

After installation, verify it works:
```bash
which expect
# Should output: /usr/bin/expect (or similar path)
```

## Usage

Once `expect` is installed, the scripts will automatically use it for ProxyJump password authentication. No configuration needed - just make sure your `.env` file has the correct passwords:

```
NODE_PASSWORD=your_password_here
```

The scripts will automatically detect `expect` and use it instead of `sshpass` when available.

