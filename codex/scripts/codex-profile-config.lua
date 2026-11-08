#!/usr/bin/env lua
-- Translate a Codex V2 profile into dotted -c assignments for app-server.
-- Each output line is one TOML assignment; strings are escaped onto one line.
local profile, parser_path = arg[1], arg[2]
if not profile or not parser_path or arg[3] then
  io.stderr:write('Usage: lua codex-profile-config.lua PROFILE TOML_PARSER\n')
  os.exit(1)
end
local ok, err = pcall(function()
  local toml = dofile(parser_path)
  local date_mt = {}
  local function date(raw) return setmetatable({raw = raw}, date_mt) end
  local data = toml.parse(profile, {type_conversion = {
    ['datetime'] = date, ['datetime-local'] = date,
    ['date-local'] = date, ['time-local'] = date,
  }})
  local function is_array(value)
    return type(value) == 'table' and getmetatable(value) == toml.array_mt
  end
  local function is_date(value)
    return type(value) == 'table' and getmetatable(value) == date_mt
  end
  local function dictionary(value)
    return type(value) == 'table' and not is_array(value) and not is_date(value)
  end
  local function keys(value)
    local result = {}
    for key in pairs(value) do result[#result + 1] = key end
    table.sort(result)
    return result
  end
  local function quote(value)
    return '"' .. value:gsub('[%z\1-\31\127\\"]', function(c)
      if c == '\\' then return '\\\\' end
      if c == '"' then return '\\"' end
      return string.format('\\u%04X', c:byte())
    end) .. '"'
  end
  local function encode(value)
    local kind = type(value)
    if kind == 'string' then return quote(value) end
    if kind == 'boolean' then return tostring(value) end
    if kind == 'number' then
      if value ~= value then return 'nan' end
      if value == math.huge then return 'inf' end
      if value == -math.huge then return '-inf' end
      if math.type(value) == 'integer' then return tostring(value) end
      local encoded = string.format('%.17g', value)
      if not encoded:find('[.eE]') then encoded = encoded .. '.0' end
      return encoded
    end
    if is_date(value) then return value.raw end
    if is_array(value) then
      local parts = {}
      for _, item in ipairs(value) do parts[#parts + 1] = encode(item) end
      return '[' .. table.concat(parts, ', ') .. ']'
    end
    if dictionary(value) then
      local parts = {}
      for _, key in ipairs(keys(value)) do parts[#parts + 1] = quote(key) .. ' = ' .. encode(value[key]) end
      return '{ ' .. table.concat(parts, ', ') .. ' }'
    end
    error('unsupported TOML value: ' .. kind)
  end
  -- Only discovery-related settings are needed. Avoid exposing unrelated
  -- profile contents in the app-server command line.
  local allowed = {
    model = true, model_provider = true, model_catalog_json = true,
    model_reasoning_effort = true, model_providers = true, features = true,
    openai_base_url = true, chatgpt_base_url = true,
    forced_login_method = true, forced_chatgpt_workspace_id = true,
  }
  local provider_fields = {
    name = true, base_url = true, env_key = true, wire_api = true,
    request_max_retries = true, stream_max_retries = true,
    stream_idle_timeout_ms = true, requires_openai_auth = true,
    env_http_headers = true,
  }
  local function safe_url(value)
    if type(value) ~= 'string' then return false end
    local authority = value:match('^%a[%w+.-]*://([^/]+)')
    return not value:find('[?#]') and (not authority or not authority:find('@', 1, true))
  end
  for _, key in ipairs({'openai_base_url', 'chatgpt_base_url'}) do
    if data[key] ~= nil and not safe_url(data[key]) then
      error('profile URL may contain credentials; configure it in config.toml instead', 0)
    end
  end
  if data.features ~= nil then
    if not dictionary(data.features) then error('profile features must be a table', 0) end
    for _, value in pairs(data.features) do
      if type(value) ~= 'boolean' then error('profile features must be boolean', 0) end
    end
  end
  if data.model_providers ~= nil then
    if not dictionary(data.model_providers) then error('profile model_providers must be a table', 0) end
    for _, provider in pairs(data.model_providers) do
      if not dictionary(provider) then error('profile model provider must be a table', 0) end
      for field, value in pairs(provider) do
        if not provider_fields[field] then
          error('profile provider contains unsupported or potentially sensitive fields; move its definition to config.toml', 0)
        end
        if field == 'env_key' and (type(value) ~= 'string' or not value:match('^[A-Za-z_][A-Za-z0-9_]*$')) then
          error('profile provider env_key must name an environment variable', 0)
        end
        if field == 'base_url' and not safe_url(value) then
          error('profile provider URL may contain credentials; move its definition to config.toml', 0)
        end
        if field == 'env_http_headers' then
          if not dictionary(value) then error('profile env_http_headers must be a table', 0) end
          for _, env_name in pairs(value) do
            if type(env_name) ~= 'string' or not env_name:match('^[A-Za-z_][A-Za-z0-9_]*$') then
              error('profile env_http_headers must reference environment variable names', 0)
            end
          end
        end
      end
    end
  end
  local function emit(node, prefix)
    for _, key in ipairs(keys(node)) do
      local path = prefix == '' and quote(key) or prefix .. '.' .. quote(key)
      if dictionary(node[key]) then emit(node[key], path)
      else io.write(path, '=', encode(node[key]), '\n') end
    end
  end
  for _, key in ipairs(keys(data)) do
    if allowed[key] then
      if dictionary(data[key]) then emit(data[key], quote(key))
      else io.write(quote(key), '=', encode(data[key]), '\n') end
    end
  end
end)
if not ok then
  io.stderr:write('codex pick: cannot read Codex profile: ' .. tostring(err) .. '\n')
  os.exit(1)
end
