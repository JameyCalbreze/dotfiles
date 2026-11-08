#!/usr/bin/env lua
-- Install shared dotfiles while preserving machine-local Codex configuration.
-- Requires Lua 5.4+ and standard Unix shell utilities; no Lua packages are needed.

local major, minor = _VERSION:match("Lua (%d+)%.(%d+)")
if not major or tonumber(major) < 5 or (tonumber(major) == 5 and tonumber(minor) < 4) then
  io.stderr:write("install: Lua 5.4 or newer is required\n")
  os.exit(1)
end

local function quote(s)
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function command(cmd)
  local ok, _, code = os.execute(cmd)
  if ok ~= true then error("command failed (" .. tostring(code) .. "): " .. cmd, 0) end
end

local function succeeds(cmd)
  return os.execute(cmd .. " >/dev/null 2>&1") == true
end

local function capture(cmd)
  local pipe, err = io.popen(cmd, "r")
  if not pipe then error(err, 0) end
  local output = pipe:read("*a")
  local ok, _, code = pipe:close()
  if not ok then error("command failed (" .. tostring(code) .. "): " .. cmd, 0) end
  return output:sub(1, -2) -- remove the one newline printed by the command
end

local function dirname(path)
  return path:match("^(.*)/[^/]*$") or "."
end

local function join(a, b)
  return a:gsub("/+$", "") .. "/" .. b
end

local cwd = capture("pwd -P")
local function absolute(path)
  if path:sub(1, 1) ~= "/" then path = join(cwd, path) end
  return path == "/" and path or path:gsub("/+$", "")
end

local script_dir = dirname(absolute(arg[0]))
local ROOT = capture("cd " .. quote(script_dir) .. " && pwd -P")
local toml = dofile(join(ROOT, "vendor/tinytoml.lua"))
local json = dofile(join(ROOT, "vendor/json.lua"))
local array_mt = toml.array_mt
local date_mt = { __toml_date = true }
local SOURCE_LINE = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.bash" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.bash"'
local OPTIONAL_SOURCE_LINE = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.bash" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.bash"'
local ZSH_SOURCE_LINE = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.zsh" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-shell.zsh"'
local ZSH_OPTIONAL_SOURCE_LINE = '[[ -f "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.zsh" ]] && source "${CODEX_HOME:-$HOME/.codex}/scripts/codex-openrouter-shell.zsh"'
local STATE_NAME = ".dotfiles-managed-config.json"

local function exists(path) return succeeds("test -e " .. quote(path)) end
local function is_link(path) return succeeds("test -L " .. quote(path)) end
local function is_dir(path) return succeeds("test -d " .. quote(path)) end
local function is_file(path) return succeeds("test -f " .. quote(path)) end

local function read_file(path)
  local file, err = io.open(path, "rb")
  if not file then error("cannot read " .. path .. ": " .. tostring(err), 0) end
  local text, read_err = file:read("*a")
  file:close()
  if not text then error("cannot read " .. path .. ": " .. tostring(read_err), 0) end
  return text
end

local function backup(path)
  local n, candidate = 1
  repeat
    candidate = path .. ".dotfiles-backup." .. n
    n = n + 1
  until not exists(candidate) and not is_link(candidate)
  if is_link(path) then
    command("ln -s " .. quote(capture("readlink " .. quote(path))) .. " " .. quote(candidate))
  else
    command("cp -p " .. quote(path) .. " " .. quote(candidate))
  end
  print("Backed up " .. path .. " to " .. candidate)
end

local function atomic_write(path, text, mode)
  local temp = capture("mktemp " .. quote(join(dirname(path), ".dotfiles.XXXXXX")))
  local ok, err = pcall(function()
    command("chmod " .. mode .. " " .. quote(temp))
    local file, open_err = io.open(temp, "wb")
    if not file then error(open_err, 0) end
    local wrote, write_err = file:write(text)
    local closed, close_err = file:close()
    if not wrote then error(write_err, 0) end
    if not closed then error(close_err, 0) end
    local renamed, rename_err = os.rename(temp, path)
    if not renamed then error(rename_err, 0) end
  end)
  if not ok then os.remove(temp); error(err, 0) end
end

local function is_array(value)
  return type(value) == "table" and getmetatable(value) == array_mt
end

local function is_date(value)
  return type(value) == "table" and getmetatable(value) == date_mt
end

local function is_dictionary(value)
  return type(value) == "table" and not is_array(value) and not is_date(value)
end

local function sorted_keys(value)
  local keys = {}
  for key in pairs(value) do keys[#keys + 1] = key end
  table.sort(keys)
  return keys
end

local function toml_quote(s)
  return '"' .. s:gsub('[%z\1-\31\127\\"]', function(c)
    if c == '\\' then return '\\\\' end
    if c == '"' then return '\\"' end
    return string.format('\\u%04X', c:byte())
  end) .. '"'
end

local function value_string(value)
  local kind = type(value)
  if kind == "string" then return toml_quote(value) end
  if kind == "boolean" then return tostring(value) end
  if kind == "number" then
    if value ~= value then return "nan" end
    if value == math.huge then return "inf" end
    if value == -math.huge then return "-inf" end
    if math.type(value) == "integer" then return tostring(value) end
    local s = string.format("%.17g", value)
    if not s:find("[.eE]") then s = s .. ".0" end
    return s
  end
  if is_date(value) then return value.raw end
  if is_array(value) then
    local result = {}
    for _, entry in ipairs(value) do result[#result + 1] = value_string(entry) end
    return "[" .. table.concat(result, ", ") .. "]"
  end
  if is_dictionary(value) then
    local result = {}
    for _, key in ipairs(sorted_keys(value)) do
      result[#result + 1] = toml_quote(key) .. " = " .. value_string(value[key])
    end
    return "{ " .. table.concat(result, ", ") .. " }"
  end
  error("unsupported TOML value: " .. kind, 0)
end

local function same_value(a, b)
  if type(a) ~= type(b) then return false end
  if type(a) == "number" then
    if math.type(a) ~= math.type(b) then return false end
    if a ~= a and b ~= b then return true end
  end
  if type(a) ~= "table" then return a == b end
  if getmetatable(a) ~= getmetatable(b) then return false end
  for key, value in pairs(a) do
    if b[key] == nil or not same_value(value, b[key]) then return false end
  end
  for key in pairs(b) do if a[key] == nil then return false end end
  return true
end

local function parse_toml(text)
  local function date(raw) return setmetatable({ raw = raw }, date_mt) end
  return toml.parse(text, { load_from_string = true, type_conversion = {
    ["datetime"] = date, ["datetime-local"] = date,
    ["date-local"] = date, ["time-local"] = date,
  } })
end

local function dump_toml(data)
  local lines = {}
  local function emit_table(node, path)
    if #path > 0 then
      local names = {}
      for _, name in ipairs(path) do names[#names + 1] = toml_quote(name) end
      lines[#lines + 1] = ""
      lines[#lines + 1] = "[" .. table.concat(names, ".") .. "]"
    end
    for _, key in ipairs(sorted_keys(node)) do
      if not is_dictionary(node[key]) then
        lines[#lines + 1] = toml_quote(key) .. " = " .. value_string(node[key])
      end
    end
    for _, key in ipairs(sorted_keys(node)) do
      if is_dictionary(node[key]) then
        path[#path + 1] = key
        emit_table(node[key], path)
        path[#path] = nil
      end
    end
  end
  emit_table(data, {})
  local text = table.concat(lines, "\n") .. "\n"
  if not same_value(parse_toml(text), data) then error("TOML serialization did not preserve the configuration", 0) end
  return text
end

local function read_toml(path)
  if exists(path) then return parse_toml(read_file(path)) end
  if is_link(path) then error("broken configuration symlink: " .. path, 0) end
  return {}
end

local function leaf_paths(data, prefix, result)
  for _, key in ipairs(sorted_keys(data)) do
    prefix[#prefix + 1] = key
    if is_dictionary(data[key]) then
      leaf_paths(data[key], prefix, result)
    else
      local path = {}
      for i, part in ipairs(prefix) do path[i] = part end
      result[#result + 1] = path
    end
    prefix[#prefix] = nil
  end
end

local function remove_leaf(data, path)
  local function remove(node, index)
    if not is_dictionary(node) then return end
    local key = path[index]
    if index == #path then
      node[key] = nil
    else
      local child = node[key]
      remove(child, index + 1)
      if is_dictionary(child) and next(child) == nil then node[key] = nil end
    end
  end
  remove(data, 1)
end

-- Fail closed if unmanaged legacy settings still mention the forbidden provider.
local function references_openrouter(value)
  if type(value) == "string" then return value:lower():find("open[_-]?router") ~= nil end
  if type(value) ~= "table" then return false end
  for key, child in pairs(value) do
    if references_openrouter(key) or references_openrouter(child) then return true end
  end
  return false
end

local function merge(target, shared, path)
  for _, key in ipairs(sorted_keys(shared)) do
    local value = shared[key]
    if is_dictionary(value) then
      if target[key] == nil then target[key] = {} end
      if not is_dictionary(target[key]) then error("expected a table at " .. path .. key, 0) end
      merge(target[key], value, path .. key .. ".")
    else
      target[key] = value
    end
  end
end

local function valid_array(value)
  if type(value) ~= "table" or getmetatable(value) ~= json.array_mt then return false end
  local n = #value
  for key in pairs(value) do
    if type(key) ~= "number" or key % 1 ~= 0 or key < 1 or key > n then return false end
  end
  for i = 1, n do if value[i] == nil then return false end end
  return true
end

local function prepare_configs(codex_home, include_openrouter)
  local state_file = join(codex_home, STATE_NAME)
  local state = exists(state_file) and json.decode(read_file(state_file)) or setmetatable({}, json.object_mt)
  if type(state) ~= "table" or getmetatable(state) ~= json.object_mt then error("invalid managed-config state: " .. state_file, 0) end
  local prepared, new_state = {}, {}
  for _, name in ipairs({ "config.toml", "granular.config.toml" }) do
    local shared_path = join(ROOT, "codex/" .. name)
    if not is_file(shared_path) then error("missing repository file: " .. shared_path, 0) end
    local shared = read_toml(shared_path)
    if include_openrouter and name == "config.toml" then
      local optional_path = join(ROOT, "codex/openrouter.config.toml")
      if not is_file(optional_path) then error("missing repository file: " .. optional_path, 0) end
      merge(shared, read_toml(optional_path), "")
    end
    if name == "granular.config.toml" then
      shared.permissions = shared.permissions or {}
      shared.permissions.granular = shared.permissions.granular or {}
      shared.permissions.granular.workspace_roots = shared.permissions.granular.workspace_roots or {}
      shared.permissions.granular.workspace_roots[codex_home] = true
    end
    local paths, lookup = {}, {}
    leaf_paths(shared, {}, paths)
    for _, path in ipairs(paths) do lookup[json.encode(path)] = true end
    local old_paths = state[name]
    if old_paths == nil then old_paths = setmetatable({}, json.array_mt) end
    if not valid_array(old_paths) then error("invalid managed paths for " .. name, 0) end
    for _, path in ipairs(old_paths) do
      if not valid_array(path) or #path == 0 then error("invalid managed paths for " .. name, 0) end
      for _, part in ipairs(path) do
        if type(part) ~= "string" then error("invalid managed paths for " .. name, 0) end
      end
    end
    local target = join(codex_home, name)
    local existing, merged = read_toml(target), read_toml(target)
    for _, path in ipairs(old_paths) do
      if not lookup[json.encode(path)] then remove_leaf(merged, path) end
    end
    merge(merged, shared, "")
    if not include_openrouter and references_openrouter(merged) then
      error("OpenRouter references remain in " .. target .. "; review and remove them or use --include-openrouter on an approved machine (existing configuration has not been changed)", 0)
    end
    local text = dump_toml(merged)
    prepared[#prepared + 1] = { target = target, changed = not same_value(existing, merged) or not exists(target), text = text }
    new_state[name] = paths
  end
  -- Stable ordering avoids rewriting metadata on every invocation.
  local state_text = '{\n  "config.toml": ' .. json.encode(new_state["config.toml"]) ..
    ',\n  "granular.config.toml": ' .. json.encode(new_state["granular.config.toml"]) .. '\n}\n'
  return prepared, state_file, state_text
end

local function install_link(source, target)
  command("mkdir -p " .. quote(dirname(target)))
  if is_link(target) and capture("readlink " .. quote(target)) == source then return end
  if exists(target) and is_dir(target) and not is_link(target) then error("refusing to replace directory: " .. target, 0) end
  if exists(target) or is_link(target) then
    backup(target)
    local ok, err = os.remove(target)
    if not ok then error(err, 0) end
  end
  command("ln -s " .. quote(source) .. " " .. quote(target))
  print("Linked " .. target .. " -> " .. source)
end

local function remove_source_line(text, source_line)
  local from = 1
  while true do
    local first, last = text:find(source_line, from, true)
    if not first then return text end
    local before = first == 1 or text:sub(first - 1, first - 1) == "\n"
    local after = last == #text or text:sub(last + 1, last + 1) == "\n"
    if before and after then
      if last < #text then last = last + 1 end
      text = text:sub(1, first - 1) .. text:sub(last + 1)
      from = first
    else
      from = last + 1
    end
  end
end

local function append_source_line(text, source_line)
  if #text > 0 and text:sub(-1) ~= "\n" then text = text .. "\n" end
  return text .. source_line .. "\n"
end

local function prepare_shell_file(path, common_line, optional_line, include_openrouter)
  local original = exists(path) and read_file(path) or ""
  local text = remove_source_line(original, optional_line)
  local has_common = false
  for line in (text .. "\n"):gmatch("(.-)\n") do
    if line == common_line then has_common = true; break end
  end
  if not has_common then text = append_source_line(text, common_line) end
  if include_openrouter then text = append_source_line(text, optional_line) end
  local mode = "644"
  if exists(path) then
    mode = capture("stat -L -c '%a' " .. quote(path) .. " 2>/dev/null || stat -L -f '%Lp' " .. quote(path) .. " 2>/dev/null")
    if not mode:match("^[0-7]+$") or #mode > 4 then error("invalid file mode for " .. path, 0) end
  end
  return { path = path, text = text, changed = text ~= original, mode = mode }
end

local function main()
  local include_openrouter = #arg == 1 and arg[1] == "--include-openrouter"
  if #arg == 1 and (arg[1] == "--help" or arg[1] == "-h") then
    print("Usage: lua install.lua [--include-openrouter]")
    return
  end
  if #arg ~= 0 and not include_openrouter then error("Usage: lua install.lua [--include-openrouter]", 0) end
  local home = os.getenv("HOME")
  if not home or home == "" then error("HOME must be set", 0) end
  home = absolute(home)
  local codex_home = os.getenv("CODEX_HOME")
  if not codex_home or codex_home == "" then codex_home = join(home, ".codex") end
  if codex_home == "~" then codex_home = home
  elseif codex_home:sub(1, 2) == "~/" then codex_home = join(home, codex_home:sub(3)) end
  codex_home = absolute(codex_home)
  local zdotdir = os.getenv("ZDOTDIR")
  if not zdotdir or zdotdir == "" then zdotdir = home end
  if zdotdir == "~" then zdotdir = home
  elseif zdotdir:sub(1, 2) == "~/" then zdotdir = join(home, zdotdir:sub(3)) end
  zdotdir = absolute(zdotdir)
  if not is_dir(zdotdir) then error("ZDOTDIR directory does not exist: " .. zdotdir, 0) end
  local links = {
    { join(ROOT, "codex/AGENTS.md"), join(codex_home, "AGENTS.md") },
    { join(ROOT, "bash/codex.bash"), join(codex_home, "scripts/codex-shell.bash") },
    { join(ROOT, "zsh/codex.zsh"), join(codex_home, "scripts/codex-shell.zsh") },
    { join(ROOT, "codex/scripts/pick-codex-model.sh"), join(codex_home, "scripts/pick-codex-model.sh") },
    { join(ROOT, "codex/scripts/codex-profile-config.lua"), join(codex_home, "scripts/codex-profile-config.lua") },
    { join(ROOT, "vendor/tinytoml.lua"), join(codex_home, "scripts/codex-toml.lua") },
  }
  local optional_links = {
    { join(ROOT, "bash/codex-openrouter.bash"), join(codex_home, "scripts/codex-openrouter-shell.bash") },
    { join(ROOT, "zsh/codex-openrouter.zsh"), join(codex_home, "scripts/codex-openrouter-shell.zsh") },
  }
  for _, name in ipairs({ "openrouter-model-families.txt", "openrouter-model-exceptions.json" }) do
    optional_links[#optional_links + 1] = { join(ROOT, "codex/" .. name), join(codex_home, name) }
  end
  for _, name in ipairs({ "pick-openrouter-model.sh", "refresh-openrouter-model-catalog.sh", "strip-model-system-prompts.sh" }) do
    optional_links[#optional_links + 1] = { join(ROOT, "codex/scripts/" .. name), join(codex_home, "scripts/" .. name) }
  end
  if include_openrouter then
    for _, link in ipairs(optional_links) do links[#links + 1] = link end
  end
  for _, link in ipairs(links) do
    if not is_file(link[1]) then error("missing repository file: " .. link[1], 0) end
    if exists(link[2]) and is_dir(link[2]) and not is_link(link[2]) then error("refusing to replace directory: " .. link[2], 0) end
  end
  local configs, state_file, state_text = prepare_configs(codex_home, include_openrouter)
  local shell_files = {
    prepare_shell_file(join(home, ".bashrc_local"), SOURCE_LINE, OPTIONAL_SOURCE_LINE, include_openrouter),
    prepare_shell_file(join(zdotdir, ".zshrc"), ZSH_SOURCE_LINE, ZSH_OPTIONAL_SOURCE_LINE, include_openrouter),
  }
  command("mkdir -p " .. quote(codex_home))
  for _, link in ipairs(links) do install_link(link[1], link[2]) end
  if not include_openrouter then
    for _, link in ipairs(optional_links) do
      local source, target = link[1], link[2]
      if is_link(target) and capture("readlink " .. quote(target)) == source then
        local ok, err = os.remove(target)
        if not ok then error(err, 0) end
        print("Removed previously managed optional link " .. target)
      elseif exists(target) or is_link(target) then
        io.stderr:write("install: leaving unmanaged optional file " .. target .. "; review it separately\n")
      end
    end
  end
  for _, config in ipairs(configs) do
    if config.changed then
      if exists(config.target) or is_link(config.target) then backup(config.target) end
      atomic_write(config.target, config.text, "600")
      print("Updated " .. config.target)
    end
  end
  if not exists(state_file) or read_file(state_file) ~= state_text then atomic_write(state_file, state_text, "600") end
  for _, shell_file in ipairs(shell_files) do
    if shell_file.changed then
      if exists(shell_file.path) or is_link(shell_file.path) then backup(shell_file.path) end
      atomic_write(shell_file.path, shell_file.text, shell_file.mode)
      print("Updated " .. shell_file.path)
    end
  end
  if include_openrouter then
    print("Done. OpenRouter integration installed. Restart Zsh or ensure ~/.bashrc sources ~/.bashrc_local.")
  else
    print("Done. OpenRouter integration omitted. Restart Zsh or ensure ~/.bashrc sources ~/.bashrc_local.")
  end
end

local ok, err = pcall(main)
if not ok then io.stderr:write("install: " .. tostring(err) .. "\n"); os.exit(1) end
