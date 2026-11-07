#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REFRESH="$ROOT/scripts/refresh-openrouter-model-catalog.sh"
SANITIZER="$ROOT/scripts/strip-model-system-prompts.sh"
export CODEX_HOME="$ROOT"
FIXTURE="$ROOT/tests/fixtures/openrouter-models.json"
EU_FIXTURE="$ROOT/tests/fixtures/openrouter-models-eu.json"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_jq() {
  local expression=$1 file=$2
  jq -e "$expression" "$file" >/dev/null || fail "assertion failed: $expression"
}

mkdir -p "$work/bin" "$work/catalog"
cat >"$work/bin/curl" <<EOF
#!/usr/bin/env bash
if [[ " \$* " == *" malformed "* ]]; then
  printf '%s\n' '{"data":{}}'
elif [[ " \$* " == *" eu-fixture "* ]]; then
  [[ " \$* " != *"Authorization:"* ]] || exit 91
  cat "$EU_FIXTURE"
else
  cat "$FIXTURE"
fi
EOF
chmod +x "$work/bin/curl"
printf '%s\n' '{"exceptions":[]}' >"$work/no-exceptions.json"

cat >"$work/families.txt" <<'EOF'
# Intended coding families
openai/
anthropic/
EOF
cat >"$work/catalog/models.json" <<'EOF'
{"models":[{"base_instructions":"do not retain this","slug":"old"}]}
EOF

chmod 640 "$work/catalog/models.json"

PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --exceptions "$work/no-exceptions.json" \
  --families "$work/families.txt" \
  --target "$work/catalog/models.json" \
  --endpoint https://example.invalid/models >/dev/null

catalog="$work/catalog/models.json"
assert_jq '.models | length == 2' "$catalog"
assert_jq '[.models[].slug] == ["anthropic/claude-test", "openai/gpt-test"]' "$catalog"
assert_jq 'all(.models[]; .base_instructions == "" and has("base_instructions"))' "$catalog"
assert_jq '(.models[] | select(.slug == "openai/gpt-test") | .context_window == 200000 and .default_reasoning_level == "high")' "$catalog"
assert_jq '(.models[] | select(.slug == "anthropic/claude-test") | .default_reasoning_level == "none")' "$catalog"

backup=$(find "$work/catalog" -maxdepth 1 -name 'models.json.*.bak' -print -quit)
[[ -n "$backup" ]] || fail "refresh did not create a backup"
assert_jq '.models[0].base_instructions == "" and has("models")' "$backup"
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"; }
[[ $(mode "$catalog") == 640 && $(mode "$backup") == 640 ]] || fail 'refresh did not preserve catalog modes'

cat >"$work/sanitize.json" <<'EOF'
{"models":[{"base_instructions":"sensitive", "slug":"one"}]}
EOF
chmod 640 "$work/sanitize.json"
"$SANITIZER" --target "$work/sanitize.json" >/dev/null
[[ $(mode "$work/sanitize.json") == 640 ]] || fail 'sanitizer did not preserve catalog mode'
assert_jq '.models[0] | has("base_instructions") and .base_instructions == ""' "$work/sanitize.json"

# Preserve the referent's mode, not a symlink's often-permissive 777 mode.
cat >"$work/symlink-referent.json" <<'EOF'
{"models":[{"base_instructions":"sensitive", "slug":"one"}]}
EOF
chmod 640 "$work/symlink-referent.json"
ln -s "$work/symlink-referent.json" "$work/symlink-catalog.json"
"$SANITIZER" --target "$work/symlink-catalog.json" >/dev/null
[[ ! -L $work/symlink-catalog.json && $(mode "$work/symlink-catalog.json") == 640 ]] || fail 'sanitizer did not preserve symlink referent mode'
assert_jq '.models[0].base_instructions == "sensitive"' "$work/symlink-referent.json"

cat >"$work/invalid.json" <<'EOF'
{"models":[{"slug":"missing"}]}
EOF
cp "$work/invalid.json" "$work/invalid.before.json"
if "$SANITIZER" --target "$work/invalid.json" >/dev/null 2>&1; then
  fail "sanitizer accepted a missing base_instructions field"
fi
cmp -s "$work/invalid.json" "$work/invalid.before.json" || fail "sanitizer changed invalid input"

printf 'unknown/\n' >"$work/no-match.txt"
cp "$catalog" "$work/catalog.before.json"
if PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --exceptions "$work/no-exceptions.json" \
  --families "$work/no-match.txt" \
  --target "$catalog" \
  --endpoint https://example.invalid/models >/dev/null 2>&1; then
  fail "refresh accepted a family with no models"
fi
cmp -s "$catalog" "$work/catalog.before.json" || fail "refresh changed catalog after no-match failure"

if PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --exceptions "$work/no-exceptions.json" \
  --families "$work/families.txt" \
  --target "$catalog" \
  --endpoint malformed >/dev/null 2>&1; then
  fail "refresh accepted a malformed OpenRouter response"
fi
cmp -s "$catalog" "$work/catalog.before.json" || fail "refresh changed catalog after malformed-response failure"

if PATH="$work/bin:$PATH" env -u OPEN_ROUTER_KEY "$REFRESH" \
  --exceptions "$work/no-exceptions.json" \
  --families "$work/families.txt" \
  --target "$catalog" >/dev/null 2>&1; then
  fail "refresh accepted a missing OPEN_ROUTER_KEY"
fi

# Explicit EU exceptions are imported even when absent from the authenticated
# response or excluded by family prefixes; only exact IDs are imported.
cat >"$work/exceptions.json" <<'EOF'
{"exceptions":[{"id":"openai/eu-exception-test","region":"eu"}]}
EOF
PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --families "$work/families.txt" --exceptions "$work/exceptions.json" \
  --exceptions-endpoint eu-fixture --endpoint regular-fixture \
  --target "$catalog" >/dev/null
assert_jq '.models | length == 3' "$catalog"
assert_jq '(.models[] | select(.slug == "openai/eu-exception-test") | .openrouter_region == "eu" and .context_window == 1050000 and .default_reasoning_level == "medium")' "$catalog"
assert_jq 'all(.models[] | select(.slug != "openai/eu-exception-test"); has("openrouter_region") | not)' "$catalog"

# Explicit IDs intentionally bypass family selection, but do not import the
# rest of the public catalog. Invalid EU responses still preserve the target.
printf 'unknown/\n' >"$work/exception-families.txt"
PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --families "$work/exception-families.txt" --exceptions "$work/exceptions.json" \
  --exceptions-endpoint eu-fixture --endpoint regular-fixture \
  --target "$work/catalog/exception-only.json" >/dev/null
assert_jq '.models | length == 1 and .[0].slug == "openai/eu-exception-test" and .[0].openrouter_region == "eu"' "$work/catalog/exception-only.json"
[[ $(mode "$work/catalog/exception-only.json") == 600 ]] || fail 'new catalog is not private'
cp "$catalog" "$work/exception.before.json"
if PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --families "$work/families.txt" --exceptions "$work/exceptions.json" \
  --exceptions-endpoint malformed --endpoint regular-fixture \
  --target "$catalog" >/dev/null 2>&1; then
  fail 'refresh accepted malformed EU catalog'
fi
cmp -s "$catalog" "$work/exception.before.json" || fail 'invalid EU response changed catalog'

# If the authenticated list later includes an exception, replace its metadata
# rather than duplicating it, and preserve the EU routing marker.
printf '%s\n' '{"exceptions":[{"id":"openai/gpt-test","region":"eu"}]}' >"$work/exceptions.json"
PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
  --families "$work/families.txt" --exceptions "$work/exceptions.json" \
  --exceptions-endpoint eu-fixture --endpoint regular-fixture \
  --target "$catalog" >/dev/null
assert_jq '[.models[] | select(.slug == "openai/gpt-test")] | length == 1 and .[0].openrouter_region == "eu" and .[0].context_window == 300000' "$catalog"

# A missing/non-chat EU exception and invalid configuration fail atomically.
cp "$catalog" "$work/exception.before.json"
for content in \
  '{"exceptions":[{"id":"openai/missing","region":"eu"}]}' \
  '{"exceptions":[{"id":"openai/image-test","region":"eu"}]}' \
  '{"exceptions":[{"id":"openai/gpt-test","region":"us"}]}' \
  '{"exceptions":[{"id":"openai/gpt-test","region":"eu"},{"id":"openai/gpt-test","region":"eu"}]}' \
  '{"exceptions":null}' '{broken' 'null'; do
  printf '%s\n' "$content" >"$work/exceptions.json"
  if PATH="$work/bin:$PATH" OPEN_ROUTER_KEY=test-key "$REFRESH" \
    --families "$work/families.txt" --exceptions "$work/exceptions.json" \
    --exceptions-endpoint eu-fixture --endpoint regular-fixture \
    --target "$catalog" >/dev/null 2>&1; then
    fail "refresh accepted invalid exception: $content"
  fi
  cmp -s "$catalog" "$work/exception.before.json" || fail 'invalid exception changed catalog'
done

printf 'PASS: model catalog scripts\n'
