# Vendored Lua libraries

- `tinytoml.lua`: FourierTransformer/tinytoml, commit
  `5517aa5d398ae0c992799decc460ec253a62552a`, MIT license. Locally patched to
  tag parsed arrays (including empty arrays) so the installer preserves their
  type. The installer supplies a datetime conversion and its own encoder.
- `json.lua`: rxi/json.lua, commit `dbf4b2dd2eb7c23be2773c89eb059dadd6436f94`,
  MIT license. Locally patched to tag decoded JSON containers and null for
  strict state validation. Used for compatibility with the previous installer.
