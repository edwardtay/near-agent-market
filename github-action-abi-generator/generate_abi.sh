#!/usr/bin/env bash
set -euo pipefail

CONTRACT_PATH="${1:-.}"
OUTPUT_PATH="${2:-abi.json}"
NEAR_SDK_VERSION="${3:-}"

# Resolve to absolute path
CONTRACT_PATH="$(cd "$CONTRACT_PATH" && pwd)"
OUTPUT_DIR="$(dirname "$OUTPUT_PATH")"
mkdir -p "$OUTPUT_DIR"

echo "=== NEAR ABI Generator ==="
echo "Contract path: $CONTRACT_PATH"
echo "Output path:   $OUTPUT_PATH"

# ── Verify this is a NEAR contract ──────────────────────────────────────────

if [ ! -f "$CONTRACT_PATH/Cargo.toml" ]; then
  echo "ERROR: No Cargo.toml found at $CONTRACT_PATH"
  exit 1
fi

if ! grep -q 'near-sdk' "$CONTRACT_PATH/Cargo.toml"; then
  echo "ERROR: Cargo.toml does not depend on near-sdk. Not a NEAR contract."
  exit 1
fi

DETECTED_SDK_VERSION=$(grep 'near-sdk' "$CONTRACT_PATH/Cargo.toml" \
  | head -1 \
  | sed -n 's/.*version\s*=\s*"\([^"]*\)".*/\1/p')
SDK_VERSION="${NEAR_SDK_VERSION:-$DETECTED_SDK_VERSION}"
echo "near-sdk version: ${SDK_VERSION:-unknown}"

# ── Try cargo-near first (produces the most accurate ABI) ───────────────────

if command -v cargo-near &> /dev/null; then
  echo "Attempting ABI generation via cargo-near..."
  if (cd "$CONTRACT_PATH" && cargo near abi 2>/dev/null); then
    # cargo-near outputs to target/near/<name>_abi.json
    CARGO_ABI=$(find "$CONTRACT_PATH/target/near" -name '*_abi.json' -type f 2>/dev/null | head -1)
    if [ -n "$CARGO_ABI" ] && [ -f "$CARGO_ABI" ]; then
      cp "$CARGO_ABI" "$OUTPUT_PATH"
      METHOD_COUNT=$(python3 -c "
import json, sys
with open('$OUTPUT_PATH') as f:
    abi = json.load(f)
methods = abi.get('body', {}).get('functions', abi.get('methods', []))
print(len(methods))
" 2>/dev/null || echo "0")
      echo "cargo-near succeeded. Methods found: $METHOD_COUNT"
      echo "method_count=$METHOD_COUNT" >> "${GITHUB_OUTPUT:-/dev/null}"
      exit 0
    fi
  fi
  echo "cargo-near did not produce output. Falling back to source parser."
fi

# ── Fallback: parse Rust source files directly ──────────────────────────────

echo "Parsing Rust source files for NEAR annotations..."

RUST_FILES=$(find "$CONTRACT_PATH/src" -name '*.rs' -type f 2>/dev/null)
if [ -z "$RUST_FILES" ]; then
  echo "ERROR: No .rs files found in $CONTRACT_PATH/src"
  exit 1
fi

# Use Python for reliable JSON generation and Rust parsing
python3 << 'PYEOF'
import json
import re
import sys
import os
from pathlib import Path

contract_path = os.environ.get("CONTRACT_PATH", ".")
output_path = os.environ.get("OUTPUT_PATH", "abi.json")
sdk_version = os.environ.get("SDK_VERSION", "")
github_output = os.environ.get("GITHUB_OUTPUT", "")

src_dir = Path(contract_path) / "src"
rust_files = sorted(src_dir.rglob("*.rs"))

if not rust_files:
    print("ERROR: No Rust source files found", file=sys.stderr)
    sys.exit(1)

# Read all source content
all_source = ""
for rf in rust_files:
    all_source += rf.read_text(errors="replace") + "\n"

methods = []
structs = []

# ── Extract contract struct name ────────────────────────────────────────
# Matches #[near(contract_state)] or #[near_bindgen] before a struct
contract_struct_pattern = re.compile(
    r'#\[near(?:_bindgen)?\s*(?:\([^)]*contract_state[^)]*\))?\s*\]\s*'
    r'(?:#\[[^\]]*\]\s*)*'
    r'pub\s+struct\s+(\w+)',
    re.DOTALL
)
contract_structs = contract_struct_pattern.findall(all_source)
contract_name = contract_structs[0] if contract_structs else "Contract"

# ── Extract impl blocks for contract ────────────────────────────────────
# Find #[near] or #[near_bindgen] impl blocks
impl_pattern = re.compile(
    r'#\[near(?:_bindgen)?\b[^\]]*\]\s*impl\s+(\w+)\s*\{',
    re.DOTALL
)

def find_matching_brace(text, start):
    """Find the position of the matching closing brace."""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text)

def parse_params(param_str):
    """Parse function parameters, skipping self variants."""
    params = []
    if not param_str.strip():
        return params

    # Split by comma but respect angle brackets and parentheses
    depth = 0
    current = ""
    for ch in param_str:
        if ch in ('<', '(', '[', '{'):
            depth += 1
            current += ch
        elif ch in ('>', ')', ']', '}'):
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            params.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        params.append(current.strip())

    result = []
    for p in params:
        p = p.strip()
        # Skip self parameters
        if p in ('self', '&self', '&mut self', 'mut self'):
            continue
        # Parse "name: Type"
        if ':' in p:
            parts = p.split(':', 1)
            name = parts[0].strip().lstrip('_')
            # Remove mut keyword from name
            name = re.sub(r'^\s*mut\s+', '', name)
            typ = parts[1].strip()
            result.append({"name": name, "type_schema": typ})
    return result

def parse_return_type(ret_str):
    """Parse a return type string."""
    ret_str = ret_str.strip()
    if not ret_str or ret_str == '()':
        return None
    return ret_str

# Find all impl blocks with NEAR annotations
for match in impl_pattern.finditer(all_source):
    struct_name = match.group(1)
    brace_start = match.end() - 1
    brace_end = find_matching_brace(all_source, brace_start)
    impl_body = all_source[brace_start + 1:brace_end]

    # Find public functions within the impl block
    fn_pattern = re.compile(
        r'(?:#\[(?:init|payable|private|handle_result|result_serializer\([^)]*\))\]\s*)*'
        r'pub\s+fn\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^{]+?))?\s*\{',
        re.DOTALL
    )

    for fn_match in fn_pattern.finditer(impl_body):
        fn_name = fn_match.group(1)
        fn_params_raw = fn_match.group(2)
        fn_return_raw = fn_match.group(3) or ""

        params = parse_params(fn_params_raw)
        return_type = parse_return_type(fn_return_raw)

        # Determine if the method is a view or call
        # Check for &self (view) vs &mut self (call/change)
        is_view = '&self' in fn_params_raw and '&mut self' not in fn_params_raw
        # init methods are calls that don't take self
        is_init = bool(re.search(r'#\[init\b', impl_body[:fn_match.start()].split('\n')[-5:] and impl_body[max(0,fn_match.start()-200):fn_match.start()]))

        # Check nearby annotations
        preceding = impl_body[max(0, fn_match.start() - 300):fn_match.start()]
        is_init = '#[init' in preceding.split('\n')[-1] if preceding else False
        is_payable = '#[payable' in preceding.split('\n')[-1] if preceding else False

        # Look back through preceding lines for annotations
        preceding_lines = preceding.strip().split('\n')
        annotations = []
        for line in reversed(preceding_lines[-5:]):
            line = line.strip()
            if line.startswith('#['):
                if 'init' in line:
                    is_init = True
                    annotations.append('init')
                if 'payable' in line:
                    is_payable = True
                    annotations.append('payable')
                if 'private' in line:
                    annotations.append('private')
            elif line and not line.startswith('//'):
                break

        if is_init:
            kind = "init"
        elif is_view:
            kind = "view"
        else:
            kind = "call"

        method_entry = {
            "name": fn_name,
            "kind": kind,
            "params": params,
        }
        if return_type:
            method_entry["return_type"] = return_type
        if is_payable:
            method_entry["is_payable"] = True
        if annotations:
            method_entry["annotations"] = annotations

        methods.append(method_entry)

# ── Extract event types (#[near(event_standard(...))] or NearEvent) ─────
event_pattern = re.compile(
    r'#\[near\s*\(\s*event_standard\s*\([^)]*\)\s*\)\s*\]\s*'
    r'(?:#\[[^\]]*\]\s*)*'
    r'pub\s+enum\s+(\w+)',
    re.DOTALL
)
events = event_pattern.findall(all_source)

# ── Build ABI output ───────────────────────────────────────────────────
abi = {
    "schema_version": "0.4.0",
    "metadata": {
        "name": contract_name,
        "build": {
            "compiler": "rustc",
            "builder": "near-abi-generator-action"
        }
    },
    "body": {
        "functions": methods,
        "root_schema": {}
    }
}

if sdk_version:
    abi["metadata"]["build"]["near_sdk_version"] = sdk_version

if events:
    abi["body"]["events"] = [{"name": e} for e in events]

with open(output_path, 'w') as f:
    json.dump(abi, f, indent=2)

method_count = len(methods)
print(f"Generated ABI: {method_count} methods from {len(rust_files)} source files")
print(f"Contract: {contract_name}")
for m in methods:
    param_str = ", ".join(p["name"] + ": " + p["type_schema"] for p in m["params"])
    ret_str = f" -> {m['return_type']}" if m.get("return_type") else ""
    print(f"  [{m['kind']}] {m['name']}({param_str}){ret_str}")

if github_output:
    with open(github_output, 'a') as f:
        f.write(f"method_count={method_count}\n")

PYEOF

echo "ABI written to: $OUTPUT_PATH"
