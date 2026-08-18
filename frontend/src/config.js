let _config = null;

export async function loadConfig() {
  if (_config) return _config;
  const res = await fetch('/config.json');
  if (!res.ok) throw new Error('Failed to load config.json. Run terraform apply first.');
  _config = await res.json();
  return _config;
}

export function getConfig() {
  if (!_config) throw new Error('Config not loaded. Call loadConfig() first.');
  return _config;
}
