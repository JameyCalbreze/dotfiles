#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PICKER="$ROOT/scripts/pick-codex-model.sh"
BASHRC="$ROOT/../bash/codex.bash"
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
original_path=$PATH
bash_bin=$(command -v bash)
jq_bin=$(command -v jq)
mkdir -p "$work/bin" "$work/project with spaces" "$work/catalog with spaces"
catalog="$work/catalog with spaces/models.json"
cp "$ROOT/tests/fixtures/codex-model-picker.json" "$catalog"
cp "$catalog" "$work/catalog.before.json"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
assert_jq() { jq -e "$1" "$2" >/dev/null || fail "assertion failed: $1 ($2)"; }

cat >"$work/bin/fzf" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=0
[[ ! -f $STUB_WORK/count ]] || count=$(<"$STUB_WORK/count")
count=$((count + 1))
printf '%s' "$count" >"$STUB_WORK/count"
rows=$(cat)
printf '%s\n' "$rows" >"$STUB_WORK/rows.$count"
jq -n --args '$ARGS.positional' -- "$@" >"$STUB_WORK/fzf-args.$count.json"
printf '%s|%s' "${FZF_DEFAULT_OPTS-unset}" "${FZF_DEFAULT_OPTS_FILE-unset}" >"$STUB_WORK/fzf-env.$count"
if ((count == 1)); then
  status=${STUB_MODEL_STATUS:-0}
  wanted=${STUB_MODEL_SLUG:-}
else
  status=${STUB_EFFORT_STATUS:-0}
  wanted=${STUB_EFFORT:-}
fi
((status == 0)) || exit "$status"
if [[ ${STUB_INVALID_SELECTION:-0} == 1 ]]; then
  printf '999\tinvented\n'
  exit 0
fi
if [[ -z $wanted ]]; then
  printf '%s\n' "${rows%%$'\n'*}"
else
  while IFS= read -r row; do
    fields=${row#*$'\t'}
    value=${fields%%$'\t'*}
    if [[ $value == "$wanted" ]]; then
      printf '%s\n' "$row"
      exit 0
    fi
  done <<< "$rows"
  exit 1
fi
EOF

cat >"$work/bin/codex" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
jq -n --args '$ARGS.positional' -- "$@" >"$STUB_WORK/argv.json"
printf '%s' "$PWD" >"$STUB_WORK/cwd"
jq -n --arg editor "${EDITOR:-}" --arg router "${OPEN_ROUTER_KEY:-}" \
  --arg bedrock "${BEDROCK_API_KEY:-}" --arg foundry "${FOUNDRY_KIMIK_KEY:-}" \
  '{editor:$editor, router:$router, bedrock:$bedrock, foundry:$foundry}' >"$STUB_WORK/env.json"
if [[ ${STUB_READ_STDIN:-0} == 1 ]]; then
  cat >"$STUB_WORK/stdin"
fi
exit "${STUB_CODEX_STATUS:-0}"
EOF
chmod +x "$work/bin/fzf" "$work/bin/codex"
export PATH="$work/bin:$original_path"
export STUB_WORK="$work"
export EDITOR=test-editor OPEN_ROUTER_KEY=fake-router-key BEDROCK_API_KEY=fake-bedrock-key
export FZF_DEFAULT_OPTS='--multi --print-query --filter=wrong'
export FZF_DEFAULT_OPTS_FILE="$work/nonexistent-options-file"

reset_case() {
  rm -f "$work/count" "$work/argv.json" "$work/cwd" "$work/env.json" \
    "$work/rows.1" "$work/rows.2" "$work/fzf-args.1.json" "$work/fzf-args.2.json" \
    "$work/fzf-env.1" "$work/fzf-env.2" "$work/stdin"
  unset STUB_MODEL_SLUG STUB_EFFORT STUB_MODEL_STATUS STUB_EFFORT_STATUS \
    STUB_INVALID_SELECTION STUB_CODEX_STATUS STUB_READ_STDIN
}
run_picker() {
  "$PICKER" --catalog "$catalog" --codex-bin "$work/bin/codex" "$@" \
    >"$work/stdout" 2>"$work/stderr"
}
expect_failure() {
  local expected=$1 status=0
  shift
  run_picker "$@" || status=$?
  [[ $status == "$expected" ]] || fail "expected exit $expected, got $status: $(cat "$work/stderr")"
  [[ ! -f $work/argv.json ]] || fail 'failure launched Codex'
}
assert_no_picker() { [[ ! -f $work/count ]] || fail 'invalid arguments opened the picker'; }
assert_clean_catalog() { cmp -s "$catalog" "$work/catalog.before.json" || fail 'launcher modified catalogue'; }

# Default effort is first despite being second in the catalogue; exact slug is retained.
reset_case
run_picker -- --profile granular -C "$work/project with spaces" 'a prompt with "quotes" and spaces'
assert_jq '.[0:8] == ["--model", "anthropic/claude-test:batch", "-c", "model_reasoning_effort=\"high\"", "-c", "model_provider=\"open_router\"", "-c", .[7]]' "$work/argv.json"
assert_jq '.[8:] == ["--profile", "granular", "-C", .[11], "a prompt with \"quotes\" and spaces"]' "$work/argv.json"
jq -e --arg expected "model_catalog_json=\"$catalog\"" '.[7] == $expected' "$work/argv.json" >/dev/null || fail 'incorrect catalogue override'
jq -e --arg dir "$work/project with spaces" '.[11] == $dir' "$work/argv.json" >/dev/null || fail 'directory argument split'
[[ $(head -n 1 "$work/rows.2") == $'0\thigh\t(default)' ]] || fail 'default effort was not first'
[[ $(cat "$work/fzf-env.1") == '|' && $(cat "$work/fzf-env.2") == '|' ]] || fail 'inherited fzf options were not cleared'
assert_jq 'index("--no-multi") != null and index("--with-nth=2..") != null and index("--nth=2..") == null' "$work/fzf-args.1.json"
assert_jq 'index("--no-sort") != null' "$work/fzf-args.2.json"
assert_jq '.editor == "test-editor" and .router == "fake-router-key" and .bedrock == "fake-bedrock-key"' "$work/env.json"
[[ ! -s $work/stdout ]] || fail 'launcher printed to stdout'
assert_clean_catalog

reset_case
export STUB_EFFORT=max
run_picker
assert_jq '.[3] == "model_reasoning_effort=\"max\""' "$work/argv.json"
[[ $(wc -l <"$work/rows.2") == 3 ]] || fail 'effort screen added or removed supported efforts'

reset_case
export STUB_MODEL_SLUG=openai/no-reasoning-test
run_picker
[[ $(cat "$work/count") == 1 ]] || fail 'single-effort model opened effort screen'
assert_jq '.[1] == "openai/no-reasoning-test" and .[3] == "model_reasoning_effort=\"none\""' "$work/argv.json"

# Exception routing uses a fixed EU provider and leaves the catalog unchanged.
reset_case
jq '.models[0].slug = "openai/eu-routing-test" | .models[0].openrouter_region = "eu"' "$catalog" >"$work/eu-catalog.json"
cp "$work/eu-catalog.json" "$work/eu-catalog.before.json"
export STUB_MODEL_SLUG=openai/eu-routing-test
run_picker --catalog "$work/eu-catalog.json" -- --profile granular
assert_jq '.[1] == "openai/eu-routing-test" and .[5] == "model_provider=\"open_router_eu_exception\""' "$work/argv.json"
assert_jq '.[8:] == ["-c", "model_providers.open_router_eu_exception={name=\"OpenRouter EU exception\",base_url=\"https://eu.openrouter.ai/api/v1\",env_key=\"OPEN_ROUTER_KEY\",wire_api=\"responses\"}", "--profile", "granular"]' "$work/argv.json"
grep -q '\[EU routing\]' "$work/rows.1" || fail 'EU routing label absent'
grep -q 'EU-only routing' "$work/stderr" || fail 'EU routing warning absent'
cmp -s "$work/eu-catalog.json" "$work/eu-catalog.before.json" || fail 'EU launch modified catalog'
# Non-exception models in the same catalog retain normal routing.
reset_case
export STUB_MODEL_SLUG=openai/no-reasoning-test
run_picker --catalog "$work/eu-catalog.json"
assert_jq 'length == 8 and .[5] == "model_provider=\"open_router\""' "$work/argv.json"

# Display control characters cannot create rows; metadata is independent of display text.
reset_case
export STUB_MODEL_SLUG=openai/quoted-name-test
run_picker
[[ $(wc -l <"$work/rows.1") == 3 ]] || fail 'display name created extra rows'
assert_jq '.[1] == "openai/quoted-name-test" and .[3] == "model_reasoning_effort=\"xhigh\""' "$work/argv.json"

# Picker input must not replace Codex stdin or change its working directory.
reset_case
export STUB_READ_STDIN=1
(
  cd "$work/project with spaces"
  printf 'original stdin\n' | run_picker -- -- '--model is prompt text'
)
[[ $(cat "$work/cwd") == "$work/project with spaces" ]] || fail 'working directory changed'
[[ $(cat "$work/stdin") == 'original stdin' ]] || fail 'stdin was consumed'
assert_jq '.[8:] == ["--", "--model is prompt text"]' "$work/argv.json"

# Ordinary configuration overrides and option values are forwarded verbatim.
reset_case
run_picker -- -c 'approval_policy="never"' --config=tui.status_line_use_colors=false \
  -C --model --profile=granular
assert_jq '.[8:] == ["-c", "approval_policy=\"never\"", "--config=tui.status_line_use_colors=false", "-C", "--model", "--profile=granular"]' "$work/argv.json"

reset_case
export STUB_CODEX_STATUS=37
status=0
run_picker || status=$?
[[ $status == 37 && -f $work/argv.json ]] || fail 'Codex exit status not propagated'

# Cancellation, no match, fzf errors, and invalid output never launch Codex.
for stage in model effort; do
  for code in 130 1 2; do
    reset_case
    if [[ $stage == model ]]; then export STUB_MODEL_STATUS=$code
    else export STUB_EFFORT_STATUS=$code; fi
    expect_failure "$code"
    assert_clean_catalog
  done
done
reset_case
export STUB_INVALID_SELECTION=1
expect_failure 1

# Reject separate, attached, long, short-cluster, and quoted protected keys.
for option in --model=x -mx --oss --local-provider=x --remote=ws://example.invalid \
  --config=model=x '-cmodel_reasoning_effort="low"' \
  '--config= model_provider = "other"' "--config='model_catalog_json'=\"elsewhere\"" \
  '--config="model"="other"' -hmx \
  '--config=model_providers.open_router_eu_exception.base_url="https://example.invalid"' \
  '--config=model_providers={}' '--config=openai_base_url="https://example.invalid"'; do
  reset_case
  expect_failure 2 -- "$option"
  assert_no_picker
done
for option in --model -m --local-provider --remote; do
  reset_case
  expect_failure 2 -- "$option" x
  assert_no_picker
done
for option in -c --config; do
  reset_case
  expect_failure 2 -- "$option" 'model = "other"'
  assert_no_picker
  reset_case
  expect_failure 2 -- "$option"
  assert_no_picker
done
reset_case
expect_failure 2 --catalog
reset_case
expect_failure 2 --unknown
reset_case
expect_failure 1 --codex-bin "$work/missing-codex"
assert_no_picker
reset_case
expect_failure 1 --catalog "$work/missing-catalog"
assert_no_picker

# The standalone launcher discovers Codex on PATH or accepts CODEX_BIN.
reset_case
CODEX_HOME="$work/catalog with spaces" "$PICKER" >"$work/stdout" 2>"$work/stderr"
assert_jq '.[1] == "anthropic/claude-test:batch"' "$work/argv.json"
reset_case
CODEX_BIN="$work/bin/codex" CODEX_HOME="$work/catalog with spaces" "$PICKER" >"$work/stdout" 2>"$work/stderr"
assert_jq '.[1] == "anthropic/claude-test:batch"' "$work/argv.json"

# Standalone defaults respect CODEX_HOME, and relative paths become absolute
# without changing Codex's working directory.
reset_case
CODEX_HOME="$work/catalog with spaces" "$PICKER" --codex-bin "$work/bin/codex" \
  >"$work/stdout" 2>"$work/stderr"
jq -e --arg expected "model_catalog_json=\"$catalog\"" '.[7] == $expected' "$work/argv.json" >/dev/null || fail 'CODEX_HOME default ignored'
reset_case
(
  cd "$work/project with spaces"
  run_picker --catalog '../catalog with spaces/models.json'
)
jq -e --arg expected "model_catalog_json=\"$catalog\"" '.[7] == $expected' "$work/argv.json" >/dev/null || fail 'relative catalogue path not resolved'
[[ $(cat "$work/cwd") == "$work/project with spaces" ]] || fail 'relative catalogue changed working directory'
reset_case
quoted_catalog="$work/catalog with spaces/a\"quoted-models.json"
cp "$catalog" "$quoted_catalog"
run_picker --catalog "$quoted_catalog"
expected=$(jq -Rn --arg value "$quoted_catalog" '"model_catalog_json=" + ($value | tojson)')
jq -e --argjson expected "$expected" '.[7] == $expected' "$work/argv.json" >/dev/null || fail 'catalogue path not TOML-quoted'

# Smoke-test the current local catalogue when present, without launching real
# Codex or accessing any credentials. The fixture remains the portable baseline.
if [[ -f $ROOT/models.json ]]; then
  reset_case
  run_picker --catalog "$ROOT/models.json"
  local_slug=$(jq -r '.models[0].slug' "$ROOT/models.json")
  local_effort=$(jq -r '.models[0].default_reasoning_level' "$ROOT/models.json")
  jq -e --arg slug "$local_slug" --arg effort "model_reasoning_effort=\"$local_effort\"" \
    '.[1] == $slug and .[3] == $effort' "$work/argv.json" >/dev/null || fail 'local catalogue launch metadata incorrect'
fi

# Invalid catalogue fixtures are constructed by persistent test code.
for expression in \
  '.models = []' \
  '.models = {}' \
  '.models[0].slug = ""' \
  '.models[0].slug = "bad\nslug"' \
  '.models[1].slug = .models[0].slug' \
  '.models[0].supported_reasoning_levels = []' \
  '.models[0].supported_reasoning_levels = [{"effort": "high"}, {"effort": "high"}]' \
  '.models[0].supported_reasoning_levels = [{"effort": 7}]' \
  '.models[0].default_reasoning_level = "unsupported"' \
  '.models[0].display_name = 7' \
  '.models[0].openrouter_region = "us"' \
  '.models[0].openrouter_region = null' \
  '.models[0] = null'; do
  reset_case
  jq "$expression" "$catalog" >"$work/invalid.json"
  cp "$work/invalid.json" "$work/invalid.before.json"
  expect_failure 1 --catalog "$work/invalid.json"
  assert_no_picker
  cmp -s "$work/invalid.json" "$work/invalid.before.json" || fail 'invalid catalogue changed'
done
for content in '{broken' 'null' '{"models": []} {"models": []}'; do
  reset_case
  printf '%s\n' "$content" >"$work/invalid.json"
  expect_failure 1 --catalog "$work/invalid.json"
  assert_no_picker
done

# Missing dependency cases use a confined PATH, not the host package installation.
for missing in jq fzf; do
  reset_case
  dep_bin="$work/missing-$missing"
  mkdir -p "$dep_bin"
  ln -s "$bash_bin" "$dep_bin/bash"
  ln -s "$(command -v dirname)" "$dep_bin/dirname"
  if [[ $missing == jq ]]; then ln -s "$work/bin/fzf" "$dep_bin/fzf"
  else ln -s "$jq_bin" "$dep_bin/jq"; fi
  status=0
  PATH="$dep_bin" "$bash_bin" "$PICKER" --catalog "$catalog" \
    --codex-bin "$work/bin/codex" >"$work/stdout" 2>"$work/stderr" || status=$?
  [[ $status == 1 ]] || fail "missing $missing did not fail"
  grep -q "$missing is required" "$work/stderr" || fail "missing $missing lacks actionable error"
  [[ ! -f $work/argv.json ]] || fail 'missing dependency launched Codex'
done
reset_case
run_picker --help
grep -q 'Usage:' "$work/stdout" || fail 'help text missing'
assert_no_picker

# Exercise the real shared Bash integration with an isolated HOME and stubs.
mkdir -p "$work/home/.secrets" "$work/codex-home/scripts"
printf '%s' mocked-router >"$work/home/.secrets/openrouter"
printf '%s' mocked-bedrock >"$work/home/.secrets/bedrock"
printf '%s' mocked-foundry >"$work/home/.secrets/kimik.foundry"
cat >"$work/codex-home/scripts/pick-codex-model.sh" <<'PICK'
#!/usr/bin/env bash
jq -n --args '$ARGS.positional' -- "$@" >"$STUB_WORK/routed.json"
exec "$STUB_WORK/bin/codex" "$@"
PICK
cat >"$work/codex-home/scripts/refresh-openrouter-model-catalog.sh" <<'REFRESH'
#!/usr/bin/env bash
jq -n --arg key "${OPEN_ROUTER_KEY:-}" --args '{key:$key,args:$ARGS.positional}' -- "$@" >"$STUB_WORK/refresh.json"
REFRESH
chmod +x "$work/codex-home/scripts/"*.sh
run_bash_function() {
  env -u OPEN_ROUTER_KEY -u BEDROCK_API_KEY -u FOUNDRY_KIMIK_KEY \
    HOME="$work/home" CODEX_HOME="$work/codex-home" BASHRC="$BASHRC" \
    "$bash_bin" -c 'source "$BASHRC"; "$@"' bash "$@"
}
reset_case
run_bash_function codex pick -C 'directory with spaces' 'test prompt'
jq -e --arg bin "$work/bin/codex" '.[0:3] == ["--codex-bin", $bin, "--"] and .[3:] == ["--profile", "granular", "-C", "directory with spaces", "test prompt"]' "$work/routed.json" >/dev/null || fail 'picker routing failed'
assert_jq '.editor == "micro" and .router == "mocked-router" and .bedrock == "mocked-bedrock" and .foundry == "mocked-foundry"' "$work/env.json"
for invocation in bare args; do
  reset_case
  rm -f "$work/routed.json"
  if [[ $invocation == bare ]]; then
    run_bash_function codex
    assert_jq '. == ["--profile", "granular"]' "$work/argv.json"
  else
    run_bash_function codex exec 'a prompt'
    assert_jq '. == ["--profile", "granular", "exec", "a prompt"]' "$work/argv.json"
  fi
  [[ ! -f $work/routed.json ]] || fail 'ordinary invocation routed to picker'
done
run_bash_function codex-openrouter-models --target 'path with spaces'
assert_jq '.key == "mocked-router" and .args == ["--target", "path with spaces"]' "$work/refresh.json"
# Existing environment overrides files; absent credentials do not prevent invocation.
env HOME="$work/home" CODEX_HOME="$work/codex-home" BASHRC="$BASHRC" OPEN_ROUTER_KEY=from-env \
  "$bash_bin" -c 'source "$BASHRC"; codex-openrouter-models --test'
assert_jq '.key == "from-env" and .args == ["--test"]' "$work/refresh.json"
rm -f "$work/home/.secrets/"*
reset_case
run_bash_function codex exec 'no credentials'
assert_jq '.router == "" and .bedrock == "" and .foundry == ""' "$work/env.json"
# The helper runs in a subshell and does not leave loaded secrets in the shell.
printf '%s' secret >"$work/home/.secrets/openrouter"
env -u OPEN_ROUTER_KEY HOME="$work/home" CODEX_HOME="$work/codex-home" BASHRC="$BASHRC" \
  "$bash_bin" -c 'source "$BASHRC"; codex; [[ -z ${OPEN_ROUTER_KEY+x} ]]' || fail 'credential leaked into parent shell'

assert_clean_catalog
printf 'PASS: Codex model picker, Bash routing, and refresh wrapper\n'
